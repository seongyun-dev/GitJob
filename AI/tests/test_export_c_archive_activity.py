import hashlib
import json
import os
import stat
import sys
from types import ModuleType, SimpleNamespace

import pytest
from jobs import export_c_archive_activity as exporter
from jobs.export_c_archive_activity import (
    build_export_metadata,
    load_repo_ids,
    validate_period,
    validate_source_period_binding,
    write_bounded_export,
)


def _candidate_payload() -> dict[str, object]:
    return {
        "schema_version": "repo-fetch-candidates/v1",
        "input_root": "hdfs:///gitjob/repo_activity/period=2026-03",
        "candidates": [
            {"repo_id": 2, "repo_name": "o/two", "activity_count": 3, "rank": 2},
            {"repo_id": 1, "repo_name": "o/one", "activity_count": 5, "rank": 1},
        ],
    }


def test_candidate_ids_are_strict_bounded_and_sorted(tmp_path):
    path = tmp_path / "candidates.json"
    path.write_text(json.dumps(_candidate_payload()), encoding="utf-8")

    assert load_repo_ids(path, max_rows=2) == (1, 2)

    payload = _candidate_payload()
    payload["candidates"][1]["repo_id"] = 2  # type: ignore[index]
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate repo_id"):
        load_repo_ids(path, max_rows=2)


@pytest.mark.parametrize("bad_id", [None, True, "1", 0])
def test_candidate_ids_reject_null_and_coercion(tmp_path, bad_id):
    payload = _candidate_payload()
    payload["candidates"][0]["repo_id"] = bad_id  # type: ignore[index]
    path = tmp_path / "candidates.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="repo_id"):
        load_repo_ids(path, max_rows=2)


def test_public_snapshot_records_are_an_allowed_id_source(tmp_path):
    path = tmp_path / "public.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "c-public-repo-analysis/v1",
                "records": [
                    {"github_repo_id": 4, "included_in_denominator": True},
                    {"github_repo_id": 3, "included_in_denominator": True},
                ],
            }
        ),
        encoding="utf-8",
    )
    assert load_repo_ids(path, max_rows=10) == (3, 4)


@pytest.mark.parametrize("wrapped", [False, True])
def test_current_public_result_exports_only_denominator_ids(tmp_path, wrapped):
    result = {
        "schema_version": "c-public-repo-analysis/v2",
        "records": [
            {"github_repo_id": 4, "included_in_denominator": True},
            {"github_repo_id": 3, "included_in_denominator": False},
            {"github_repo_id": 2, "included_in_denominator": True},
        ],
    }
    payload = (
        {
            "schema_version": "c-public-published-result/v1",
            "publication": {"status": "published"},
            "result": result,
        }
        if wrapped
        else result
    )
    path = tmp_path / "public.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_repo_ids(path, max_rows=10) == (2, 4)


def test_public_result_requires_explicit_denominator_decision(tmp_path):
    path = tmp_path / "public.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "c-public-repo-analysis/v2",
                "records": [{"github_repo_id": 4}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(TypeError, match="included_in_denominator"):
        load_repo_ids(path, max_rows=10)


def test_weekly_public_denominator_allows_repos_without_activity():
    exporter._validate_selected_repository_coverage(
        selected_repo_count=1,
        requested_repo_count=2,
        public_source=True,
    )
    with pytest.raises(RuntimeError, match="missing from Repo Activity"):
        exporter._validate_selected_repository_coverage(
            selected_repo_count=1,
            requested_repo_count=2,
            public_source=False,
        )


def test_period_contract_supports_month_and_monday_week_only():
    validate_period("2026-03", "MONTH")
    validate_period("2026-03-02", "WEEK")
    with pytest.raises(ValueError, match="Monday"):
        validate_period("2026-03-03", "WEEK")
    with pytest.raises(ValueError, match="MONTH"):
        validate_period("2026-03-02", "MONTH")


def test_six_month_aggregate_cannot_be_relabelled_as_one_month():
    validate_source_period_binding(
        "2026-03",
        "MONTH",
        observed_intervals=(("2026-03-01T00:00:00Z", "2026-04-01T00:00:00Z"),),
    )
    with pytest.raises(ValueError, match="requested month"):
        validate_source_period_binding(
            "2026-03",
            "MONTH",
            observed_intervals=(
                (
                    "2026-03-01T00:00:00Z",
                    "2026-09-01T00:00:00Z",
                ),
            ),
        )


@pytest.mark.parametrize(
    "summary,expected_error,expected_result",
    [
        (
            {
                "repo_count": 2,
                "distinct_repo_count": 1,
                "event_count": 5,
                "null_count": 1,
                "invalid_value_count": 0,
            },
            "null required fields",
            None,
        ),
        (
            {
                "repo_count": 2,
                "distinct_repo_count": 1,
                "event_count": 5,
                "null_count": 0,
                "invalid_value_count": 0,
            },
            "duplicate repo_id",
            None,
        ),
        (
            {
                "repo_count": 2,
                "distinct_repo_count": 2,
                "event_count": 5,
                "null_count": 0,
                "invalid_value_count": 0,
            },
            None,
            (2, 5),
        ),
    ],
)
def test_activity_quality_distinguishes_null_duplicate_and_valid_summaries(
    monkeypatch,
    summary,
    expected_error,
    expected_result,
):
    class FakeExpression:
        def alias(self, *_args):
            return self

        def isNull(self):
            return self

        def otherwise(self, *_args):
            return self

        def __eq__(self, _other):
            return self

        def __lt__(self, _other):
            return self

        def __or__(self, _other):
            return self

    functions = SimpleNamespace(
        col=lambda *_args: FakeExpression(),
        count=lambda *_args: FakeExpression(),
        countDistinct=lambda *_args: FakeExpression(),
        length=lambda *_args: FakeExpression(),
        lit=lambda *_args: FakeExpression(),
        sum=lambda *_args: FakeExpression(),
        trim=lambda *_args: FakeExpression(),
        when=lambda *_args: FakeExpression(),
    )
    spark_sql = ModuleType("pyspark.sql")
    spark_sql.functions = functions
    pyspark = ModuleType("pyspark")
    pyspark.sql = spark_sql
    monkeypatch.setitem(sys.modules, "pyspark", pyspark)
    monkeypatch.setitem(sys.modules, "pyspark.sql", spark_sql)

    class FakeRow(dict):
        def asDict(self):
            return dict(self)

    summary = FakeRow(summary)
    activity = SimpleNamespace(
        agg=lambda *_args: SimpleNamespace(first=lambda: summary)
    )

    if expected_error:
        with pytest.raises(RuntimeError, match=expected_error):
            exporter._activity_quality(activity, "event_count")
    else:
        assert exporter._activity_quality(activity, "event_count") == expected_result


def test_metadata_reconciles_sample_and_source_denominators():
    metadata = build_export_metadata(
        source_schema_version="repo-activity/v1",
        source_version="spark-repo-activity/v2",
        dataset_snapshot_id="activity-2026-03",
        source_uri="hdfs:///gitjob/repo_activity/period=2026-03",
        source_hash="a" * 64,
        period="2026-03",
        granularity="MONTH",
        top_n_limit=10_000,
        selected_repo_count=2,
        selected_event_count=8,
        valid_event_count=20,
        total_active_repo_count=100,
    )

    assert metadata["selection_event_coverage"] == 0.4
    with pytest.raises(ValueError, match="selected_event_count"):
        build_export_metadata(
            **{**metadata, "selected_event_count": 21}  # type: ignore[arg-type]
        )


def test_export_is_bounded_hashed_and_refuses_overwrite(tmp_path):
    output = tmp_path / "period-2026-03"
    metadata = build_export_metadata(
        source_schema_version="repo-activity/v1",
        source_version="spark-repo-activity/v2",
        dataset_snapshot_id="activity-2026-03",
        source_uri="hdfs:///gitjob/repo_activity/period=2026-03",
        source_hash="a" * 64,
        period="2026-03",
        granularity="MONTH",
        top_n_limit=2,
        selected_repo_count=2,
        selected_event_count=8,
        valid_event_count=20,
        total_active_repo_count=100,
    )
    rows = (
        {"repo_id": 1, "repo_name": "o/one", "event_count": 5},
        {"repo_id": 2, "repo_name": "o/two", "event_count": 3},
    )

    result = write_bounded_export(output, rows, metadata, output_format="ndjson")
    manifest = result["manifest"]

    data_path = output / "activity.ndjson"
    metadata_path = output / "metadata.json"
    stored_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert data_path.read_text(encoding="utf-8").splitlines()[0] == (
        '{"event_count":5,"period":"2026-03","repo_id":1,"repo_name":"o/one"}'
    )
    assert manifest["data_sha256"] == hashlib.sha256(data_path.read_bytes()).hexdigest()
    assert stored_metadata["source_hash"] == manifest["data_sha256"]
    assert stored_metadata["upstream_source_hash"] == "a" * 64
    assert stored_metadata["upstream_source_uri"] == metadata["source_uri"]
    assert result["metadata"] == stored_metadata
    assert (
        manifest["metadata_sha256"]
        == hashlib.sha256(metadata_path.read_bytes()).hexdigest()
    )
    assert (
        json.loads((output / "manifest.json").read_text(encoding="utf-8")) == manifest
    )
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        write_bounded_export(output, rows, metadata, output_format="ndjson")


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits require Linux")
def test_published_export_has_cross_uid_read_mode(tmp_path):
    output = tmp_path / "period-2026-03"
    metadata = build_export_metadata(
        source_schema_version="repo-activity/v1",
        source_version="spark-repo-activity/v2",
        dataset_snapshot_id="activity-2026-03",
        source_uri="hdfs:///gitjob/repo_activity/period=2026-03",
        source_hash="a" * 64,
        period="2026-03",
        granularity="MONTH",
        top_n_limit=1,
        selected_repo_count=1,
        selected_event_count=5,
        valid_event_count=20,
        total_active_repo_count=100,
    )

    write_bounded_export(
        output,
        ({"repo_id": 1, "repo_name": "o/one", "event_count": 5},),
        metadata,
        output_format="ndjson",
    )

    assert stat.S_IMODE(output.stat().st_mode) == 0o555
    for name in ("activity.ndjson", "metadata.json", "manifest.json"):
        assert stat.S_IMODE((output / name).stat().st_mode) == 0o444


@pytest.mark.parametrize("public_source", [False, True])
def test_cli_stdout_uses_the_final_export_metadata(
    tmp_path, monkeypatch, capsys, public_source
):
    class FakeExpression:
        def cast(self, *_args):
            return self

        def alias(self, *_args):
            return self

    class FakeRow(dict):
        def asDict(self):
            return dict(self)

    class FakeSelected:
        def __init__(self, rows):
            self.rows = rows

        def select(self, *_args):
            return self

        def orderBy(self, *_args):
            return self

        def agg(self, *_args):
            summary = FakeRow(
                repo_count=len(self.rows),
                event_count=sum(row["event_count"] for row in self.rows),
            )
            return SimpleNamespace(first=lambda: summary)

        def toLocalIterator(self):
            return iter(self.rows)

    selected_rows = (FakeRow(repo_id=1, repo_name="o/one", event_count=5),)
    if not public_source:
        selected_rows += (FakeRow(repo_id=2, repo_name="o/two", event_count=3),)
    selected = FakeSelected(selected_rows)

    class FakeActivity:
        columns = ("repo_id", "repo_name", "event_count", "period")

        def join(self, *_args):
            return selected

    class FakeSpark:
        read = SimpleNamespace(parquet=lambda _path: FakeActivity())

        def createDataFrame(self, *_args):
            return object()

        def stop(self):
            return None

    class FakeBuilder:
        def appName(self, *_args):
            return self

        def getOrCreate(self):
            return FakeSpark()

    functions = SimpleNamespace(
        broadcast=lambda value: value,
        col=lambda *_args: FakeExpression(),
        count=lambda *_args: FakeExpression(),
        lit=lambda *_args: FakeExpression(),
        sum=lambda *_args: FakeExpression(),
    )
    spark_sql = ModuleType("pyspark.sql")
    spark_sql.SparkSession = SimpleNamespace(builder=FakeBuilder())
    spark_sql.functions = functions
    spark_types = ModuleType("pyspark.sql.types")
    spark_types.LongType = lambda: object()
    spark_types.StructField = lambda *_args: object()
    spark_types.StructType = lambda *_args: object()
    pyspark = ModuleType("pyspark")
    pyspark.sql = spark_sql
    monkeypatch.setitem(sys.modules, "pyspark", pyspark)
    monkeypatch.setitem(sys.modules, "pyspark.sql", spark_sql)
    monkeypatch.setitem(sys.modules, "pyspark.sql.types", spark_types)
    monkeypatch.setattr(exporter, "_validate_activity_period", lambda *_args: None)
    monkeypatch.setattr(exporter, "_activity_quality", lambda *_args: (2, 20))

    repo_ids = tmp_path / "repo-ids.json"
    id_payload = _candidate_payload()
    if public_source:
        id_payload = {
            "schema_version": "c-public-published-result/v1",
            "publication": {"status": "published"},
            "result": {
                "schema_version": "c-public-repo-analysis/v2",
                "records": [
                    {"github_repo_id": 1, "included_in_denominator": True},
                    {"github_repo_id": 2, "included_in_denominator": True},
                ],
            },
        }
    repo_ids.write_text(json.dumps(id_payload), encoding="utf-8")
    output = tmp_path / "export"
    assert (
        exporter.main(
            [
                "--input",
                "hdfs:///repo-activity",
                "--repo-ids",
                str(repo_ids),
                "--output",
                str(output),
                "--period",
                "2026-03",
                "--granularity",
                "MONTH",
                "--top-n-limit",
                "2",
                "--source-version",
                "spark-repo-activity/v2",
                "--dataset-snapshot-id",
                "activity-2026-03",
                "--source-hash",
                "a" * 64,
            ]
        )
        == 0
    )

    stdout = json.loads(capsys.readouterr().out)
    stored_metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    assert stdout["metadata"] == stored_metadata
    assert stdout["metadata"]["selected_repo_count"] == (1 if public_source else 2)
    assert stdout["metadata"]["source_hash"] == stdout["manifest"]["data_sha256"]
    assert stdout["metadata"]["upstream_source_hash"] == "a" * 64


def test_export_rejects_more_rows_than_declared_top_n(tmp_path):
    metadata = build_export_metadata(
        source_schema_version="repo-activity/v1",
        source_version="spark-repo-activity/v2",
        dataset_snapshot_id="activity-2026-03",
        source_uri="hdfs:///gitjob/repo_activity/period=2026-03",
        source_hash="a" * 64,
        period="2026-03",
        granularity="MONTH",
        top_n_limit=1,
        selected_repo_count=1,
        selected_event_count=5,
        valid_event_count=20,
        total_active_repo_count=100,
    )
    rows = (
        {"repo_id": 1, "repo_name": "o/one", "event_count": 5},
        {"repo_id": 2, "repo_name": "o/two", "event_count": 3},
    )
    with pytest.raises(ValueError, match="top_n_limit"):
        write_bounded_export(tmp_path / "too-many", rows, metadata, output_format="csv")


def test_week_export_uses_the_week_start_contract_field(tmp_path):
    metadata = build_export_metadata(
        source_schema_version="repo-activity/v1",
        source_version="spark-repo-activity/v2",
        dataset_snapshot_id="activity-week",
        source_uri="hdfs:///gitjob/repo_activity/week=2026-03-02",
        source_hash="a" * 64,
        period="2026-03-02",
        granularity="WEEK",
        top_n_limit=1,
        selected_repo_count=1,
        selected_event_count=5,
        valid_event_count=10,
        total_active_repo_count=5,
    )
    output = tmp_path / "week"
    write_bounded_export(
        output,
        ({"repo_id": 1, "repo_name": "o/one", "event_count": 5},),
        metadata,
        output_format="csv",
    )
    header, row = (output / "activity.csv").read_text(encoding="utf-8").splitlines()
    assert header == "week_start,repo_id,repo_name,event_count"
    assert row == "2026-03-02,1,o/one,5"
