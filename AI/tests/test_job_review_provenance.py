"""Review provenance stays independent from cohort eligibility filters."""

from contextlib import nullcontext

from test_compute_api import REGISTRY
from test_job_cohort import batch, criteria, posting

from job.input_union import prepare_input_union
from registry.mapper import RegistryMapper
from worker.intake import JobOutput, publish_job_input_set
from worker.jobs import job_artifacts
from worker.store import Ticket


def test_single_and_union_publication_keep_review_for_cohort_exclusion(
    monkeypatch,
) -> None:
    source_batch = batch(
        posting(
            "outside-region",
            required=("QuantumDB",),
            region="부산",
        )
    )
    selected_criteria = criteria(regions=("서울",))
    mapper = RegistryMapper(REGISTRY)
    direct = job_artifacts(source_batch, selected_criteria, mapper, {"test": "v1"})

    class Store:
        lease_seconds = 120

        def __init__(self) -> None:
            self.artifacts = ()

        def claim(self, **kwargs):
            return Ticket(
                event_id=kwargs["event_id"],
                kind=kwargs["kind"],
                owner=kwargs["owner"],
                occurred_at=kwargs["occurred_at"],
                status="RUNNING",
                token="owned-token",
                attempt=1,
                results=[],
            )

        def complete(self, _ticket, artifacts):
            self.artifacts = tuple(artifacts)
            return []

        def fail(self, *_args):
            raise AssertionError("the publication should not fail")

    store = Store()
    monkeypatch.setattr("worker.intake.LeaseHeartbeat", lambda *_args: nullcontext())
    output = JobOutput(
        batch=source_batch,
        occurred_at=source_batch.records[0].collected_at,
        batch_sha256="a" * 64,
        manifest_sha256="b" * 64,
        collection_issues=(),
        source_site="SARAMIN",
        batch_size_bytes=len(source_batch.model_dump_json().encode()),
    )

    publish_job_input_set(
        (output,),
        selected_criteria,
        store=store,
        mapper=mapper,
        registry=REGISTRY,
    )

    direct_cohort = direct[0]
    union_cohort = next(item for item in store.artifacts if item.kind == "COHORT")
    assert direct_cohort.payload["exclusions"][0]["reasons"] == [
        "REGION_NOT_MATCHED",
        "TECHNOLOGY_REVIEW_REQUIRED",
    ]
    assert union_cohort.payload["input_union"]["observations"][0]["disposition"] == (
        "SELECTED"
    )
    assert union_cohort.payload["exclusions"][0]["reasons"] == [
        "REGION_NOT_MATCHED",
        "TECHNOLOGY_REVIEW_REQUIRED",
    ]
    assert direct_cohort.review_records == union_cohort.review_records
    assert [record["source_record_id"] for record in union_cohort.review_records] == [
        "outside-region"
    ]


def test_prepared_union_keeps_review_context_without_retaining_it_in_projection():
    source_batch = batch(posting("review-context", required=("QuantumDB",)))
    output = JobOutput(
        batch=source_batch,
        occurred_at=source_batch.records[0].collected_at,
        batch_sha256="a" * 64,
        manifest_sha256="b" * 64,
        collection_issues=(),
        source_site="SARAMIN",
        batch_size_bytes=len(source_batch.model_dump_json().encode()),
    )

    prepared = prepare_input_union((output,), criteria(), RegistryMapper(REGISTRY))

    assert prepared.review_records
    assert "QuantumDB" in prepared.review_records[0]["context"]
    assert all(
        technology.mapping_context == ""
        for record in prepared.cohort.classified.records
        for technology in record.technologies
    )
    assert all(
        technology.mapping_context == ""
        for record in prepared.cohort.records
        for technology in record.classification.technologies
    )
