"""Real producer serialization contracts, with offline collector HTTP fixtures."""

import hashlib
import json
from dataclasses import replace
from datetime import date, datetime

import pytest
from test_job_cohort import criteria
from test_jobkorea import FakeJobKoreaClient

from JobKorea_Collector_V1.crawler import CrawlConfig, JobKoreaCrawler, write_outputs
from JobKorea_Collector_V1.dates import SEOUL
from worker.intake import IntakeConfig, IntakeRunner, load_job_output


def assert_manifest_binds_exact_bytes(paths):
    manifest = json.loads(paths["manifest"].read_bytes())
    assert manifest["output_sha256"] == {
        paths["json"].name: hashlib.sha256(paths["json"].read_bytes()).hexdigest()
    }


def test_jobkorea_actual_writer_completion_is_accepted(tmp_path):
    config = CrawlConfig(
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 31),
        request_delay=0,
        detail_delay=0,
        fetch_details=False,
        now=datetime(2026, 9, 3, 12, 0, tzinfo=SEOUL),
    )
    collected = JobKoreaCrawler(config, client=FakeJobKoreaClient()).run()
    paths = write_outputs(collected, tmp_path)

    assert paths["json"].name == "job_analysis_input_v1.json"
    assert_manifest_binds_exact_bytes(paths)
    loaded = load_job_output(paths["manifest"], tmp_path)

    assert loaded.batch == collected.batch
    assert loaded.collection_issues == ()
    assert loaded.occurred_at == collected.batch.records[0].collected_at


@pytest.mark.parametrize("source", ["CAREER", "GAMEJOB"])
def test_actual_career_gamejob_writer_completion_is_accepted_and_tamper_rejected(
    tmp_path, source
):
    if source == "CAREER":
        from test_career import FakeClient, _config, _list_page, _row

        from Career_Collector_V1.crawler import CareerCrawler as Crawler
        from Career_Collector_V1.crawler import write_outputs as write

        collected = Crawler(
            _config(), FakeClient({"H0": [_list_page(_row("1"))]})
        ).run()
    else:
        from test_gamejob import LIST_HTML, FakeClient, _config

        from GameJob_Collector_V1.crawler import GameJobCrawler as Crawler
        from GameJob_Collector_V1.crawler import write_outputs as write

        collected = Crawler(_config(), FakeClient([LIST_HTML])).run()

    paths = write(collected, tmp_path)
    assert_manifest_binds_exact_bytes(paths)
    loaded = load_job_output(paths["manifest"], tmp_path)
    assert loaded.collection_issues == ()
    from test_compute_matching import REGISTRY, MemoryStore

    from registry.mapper import RegistryMapper
    from worker.intake import publish_job_output

    # Execute the real publication guard and calculation, not only watcher dispatch.
    result = publish_job_output(
        loaded,
        criteria(),
        store=MemoryStore(),
        mapper=RegistryMapper(REGISTRY),
        registry=REGISTRY,
    )
    assert result["status"] == "COMPLETED"
    assert {item["kind"] for item in result["results"]} == {"COHORT", "DEMAND"}

    published = []
    runner = IntakeRunner(
        IntakeConfig(
            schema_version="c-intake-config/v1",
            job_roots=(tmp_path,),
            criteria=(criteria(),),
        ),
        job_sink=lambda loaded, criterion: (
            published.append((loaded, criterion)) or {"status": "COMPLETED"}
        ),
    )
    assert runner.poll_once()["completed"] == 1
    assert len(published) == 1

    paths["json"].write_bytes(paths["json"].read_bytes() + b"\n")
    with pytest.raises(ValueError, match="bind.*batch bytes"):
        load_job_output(paths["manifest"], tmp_path)
    assert runner.poll_once()["failed"] == 1


@pytest.mark.parametrize("source", ["SARAMIN", "WORKNET"])
def test_actual_saramin_worknet_writer_completion_is_accepted(tmp_path, source):
    if source == "SARAMIN":
        from test_saramin import LIST_HTML, FakeClient, _config

        from Saramin_Collector_V1.crawler import SaraminCrawler as Crawler
        from Saramin_Collector_V1.crawler import write_outputs as write
    else:
        from test_worknet import LIST_HTML, FakeClient, _config

        from Worknet_Collector_V1.crawler import WorknetCrawler as Crawler
        from Worknet_Collector_V1.crawler import write_outputs as write

    collected = Crawler(_config(), FakeClient([LIST_HTML])).run()
    paths = write(collected, tmp_path)
    assert_manifest_binds_exact_bytes(paths)
    loaded = load_job_output(paths["manifest"], tmp_path)

    assert paths["json"].name == "job_analysis_input.json"
    assert loaded.batch == collected.batch
    assert loaded.collection_issues == ()
    assert all(row.source_site == source for row in loaded.batch.records)


@pytest.mark.parametrize("source", ["SARAMIN", "WORKNET", "JOBKOREA"])
def test_existing_manifest_cannot_complete_new_batch_during_writer_replay(
    tmp_path, monkeypatch, source
):
    from test_job_cohort import criteria

    if source == "SARAMIN":
        from test_saramin import LIST_HTML, FakeClient, _config

        from Saramin_Collector_V1 import crawler

        collected = crawler.SaraminCrawler(_config(), FakeClient([LIST_HTML])).run()
    elif source == "WORKNET":
        from test_worknet import LIST_HTML, FakeClient, _config

        from Worknet_Collector_V1 import crawler

        collected = crawler.WorknetCrawler(_config(), FakeClient([LIST_HTML])).run()
    else:
        from JobKorea_Collector_V1 import crawler

        config = CrawlConfig(
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
            request_delay=0,
            detail_delay=0,
            fetch_details=False,
            now=datetime(2026, 9, 3, 12, 0, tzinfo=SEOUL),
        )
        collected = crawler.JobKoreaCrawler(config, client=FakeJobKoreaClient()).run()
    paths = crawler.write_outputs(collected, tmp_path)
    first = collected.batch.records[0].model_copy(
        update={"title": "New batch awaiting its completion manifest"}
    )
    batch = collected.batch.model_copy(
        update={"records": (first, *collected.batch.records[1:])}
    )
    counter = "stats" if source == "JOBKOREA" else "counts"
    error_field = "detail_failures" if source == "JOBKOREA" else "detail_errors"
    manifest = {
        **collected.manifest,
        counter: {**collected.manifest[counter], error_field: 1},
    }
    replay = replace(collected, batch=batch, manifest=manifest)
    original_write = crawler._atomic_write
    checked = []

    def paused_before_manifest(path, content):
        if path.name == "manifest.json":
            checked.append(True)
            # Stable files can still be from different producer write generations.
            with pytest.raises(ValueError, match="bind.*batch bytes"):
                load_job_output(paths["manifest"], tmp_path)
        original_write(path, content)

    monkeypatch.setattr(crawler, "_atomic_write", paused_before_manifest)
    crawler.write_outputs(replay, tmp_path)
    assert checked == [True]
    assert_manifest_binds_exact_bytes(paths)
    loaded = load_job_output(paths["manifest"], tmp_path)
    assert loaded.batch == batch
    assert loaded.collection_issues == ("DETAIL_COLLECTION_FAILED",)

    def must_not_publish(*args):
        raise AssertionError("collector errors must not reach the database sink")

    runner = IntakeRunner(
        IntakeConfig(
            schema_version="c-intake-config/v1",
            job_roots=(tmp_path,),
            criteria=(criteria(),),
        ),
        job_sink=must_not_publish,
    )
    assert runner.poll_once()["blocked"] == 1
