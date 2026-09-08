"""Bounded union of verified observations, not a full-market or absence census."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC
from typing import TYPE_CHECKING

from job.cohort import (
    CohortCriteria,
    InputUnionBatch,
    InputUnionObservation,
    InputUnionProvenance,
    JobCohort,
    _stable_hash,
    build_cohort,
)
from job.contracts import JobAnalysisInputBatch
from registry.mapper import RegistryMapper

if TYPE_CHECKING:
    from worker.intake import JobOutput

INPUT_UNION_VERSION = "c-job-input-union/v1"
MAX_INPUT_RECORDS = 50_000
MAX_INPUT_BYTES = 128 * 1024 * 1024


def build_input_union(
    outputs: tuple[JobOutput, ...], criteria: CohortCriteria, mapper: RegistryMapper
) -> JobCohort:
    """Select latest source/posting observations before filtering or classification.

    ``outputs`` must come from the hash-verifying completion loader. Original byte
    hashes remain provenance; this pure function never reads a file or URI.
    Repeated delivery of the same bound batch is one input, not another observation.
    """
    criteria = CohortCriteria.model_validate_json(criteria.model_dump_json())
    inputs = {}
    input_records = input_bytes = 0
    for output in outputs:
        sites = {row.source_site.strip().upper() for row in output.batch.records}
        source = getattr(output, "source_site", None)
        source = source.strip().upper() if source else next(iter(sites), None)
        if not source or sites - {source}:
            raise ValueError("union batch must identify exactly one source")
        if criteria.sources and source not in criteria.sources:
            continue
        if output.collection_issues:
            raise ValueError("incomplete collection cannot publish an observed union")
        if output.mixed_date_semantics and (criteria.posted_from or criteria.posted_to):
            raise ValueError("modified dates cannot be original posting dates")
        size = getattr(output, "batch_size_bytes", 0)
        if type(size) is not int or size <= 0:
            raise ValueError("union requires the verified raw batch byte size")
        input_records += len(output.batch.records)
        input_bytes += size
        if input_records > MAX_INPUT_RECORDS or input_bytes > MAX_INPUT_BYTES:
            raise ValueError("union input record or byte limit exceeded")
        if output.occurred_at.tzinfo is None or output.occurred_at.utcoffset() is None:
            raise ValueError("union input timestamp requires timezone")
        batch = JobAnalysisInputBatch.model_validate_json(
            output.batch.model_dump_json()
        )
        collected_at = output.occurred_at.astimezone(UTC)
        if any(row.collected_at != collected_at for row in batch.records):
            raise ValueError("union batch timestamp differs from source observations")
        metadata = {
            "source_site": source,
            "dataset_snapshot_id": batch.dataset_snapshot_id,
            "pipeline_run_id": batch.pipeline_run_id,
            "collector_version": batch.collector_version,
            "collected_at": collected_at.isoformat(),
            "batch_sha256": output.batch_sha256,
            "manifest_sha256": output.manifest_sha256,
            "record_count": len(batch.records),
            "batch_size_bytes": size,
        }
        input_id = _stable_hash(metadata)
        content_digest = _stable_hash(batch.model_dump(mode="json"))
        reference = InputUnionBatch(
            input_id=input_id, batch_content_sha256=content_digest, **metadata
        )
        if input_id in inputs:
            if inputs[input_id][0] != reference:
                raise ValueError("one bound input has conflicting batch contents")
            continue
        inputs[input_id] = (reference, batch)
    if not inputs:
        raise ValueError("no relevant verified completed inputs")

    references = tuple(inputs[key][0] for key in sorted(inputs))
    observations = []
    groups = defaultdict(list)
    dispositions = {}
    for reference in references:
        for index, record in enumerate(inputs[reference.input_id][1].records):
            item = {
                "input_id": reference.input_id,
                "record_index": index,
                "source_site": reference.source_site,
                "source_posting_id": record.source_posting_id,
                "source_record_id": record.source_record_id,
                "collected_at": record.collected_at.astimezone(UTC),
                "record_sha256": _stable_hash(record.model_dump(mode="json")),
            }
            number = len(observations)
            observations.append(item)
            if record.collected_at > criteria.as_of:
                dispositions[number] = "AFTER_AS_OF"
            else:
                groups[(reference.source_site, record.source_posting_id)].append(
                    (number, record)
                )
    selected = []
    conflicting_keys = set()
    for source_key, group in sorted(groups.items()):
        latest = max(record.collected_at for _, record in group)
        variants = defaultdict(list)
        for number, record in group:
            if record.collected_at < latest:
                dispositions[number] = "SUPERSEDED"
            else:
                variants[observations[number]["record_sha256"]].append((number, record))
        conflicting = len(variants) > 1
        if conflicting:
            conflicting_keys.add(source_key)
        for _, copies in sorted(variants.items()):
            number, record = copies[0]
            dispositions[number] = "CONFLICT" if conflicting else "SELECTED"
            selected.append(record)
            for duplicate_number, _ in copies[1:]:
                dispositions[duplicate_number] = "DUPLICATE"
    items = tuple(
        InputUnionObservation(**value, disposition=dispositions[index])
        for index, value in enumerate(observations)
    )
    counts = Counter(dispositions.values())
    provenance = InputUnionProvenance(
        policy_version=INPUT_UNION_VERSION,
        input_batches=references,
        observations=items,
        input_record_count=len(items),
        input_bytes=sum(item.batch_size_bytes for item in references),
        selected_record_count=counts["SELECTED"],
        conflict_record_count=counts["CONFLICT"],
        duplicate_record_count=counts["DUPLICATE"],
        superseded_record_count=counts["SUPERSEDED"],
        after_as_of_record_count=counts["AFTER_AS_OF"],
        sources_without_as_of_observations=tuple(
            sorted(
                {item.source_site for item in references} - {key[0] for key in groups}
            )
        ),
    )
    identity = _stable_hash(
        {
            "policy_version": INPUT_UNION_VERSION,
            "inputs": [r.model_dump(mode="json") for r in references],
        }
    )
    composite = JobAnalysisInputBatch(
        schema_version="job-analysis-input/v1",
        dataset_snapshot_id="input-union-" + identity,
        pipeline_run_id="input-union-run-" + identity,
        collector_version=INPUT_UNION_VERSION,
        records=tuple(selected),
    )
    cohort = build_cohort(composite, criteria, mapper, qualify_job_ids=True)
    exclusions = tuple(
        item.model_copy(update={"decision": "REVIEW_REQUIRED"})
        if (item.source_site.strip().upper(), item.source_posting_id)
        in conflicting_keys
        else item
        for item in cohort.exclusions
    )
    payload = cohort.model_dump(mode="json")
    payload.update(
        input_union=provenance.model_dump(mode="json"),
        exclusions=[item.model_dump(mode="json") for item in exclusions],
        review_count=sum(item.decision == "REVIEW_REQUIRED" for item in exclusions),
        excluded_count=sum(item.decision == "EXCLUDED" for item in exclusions),
    )
    payload["cohort_id"] = "cohort-" + _stable_hash(payload)
    return JobCohort.model_validate(payload)
