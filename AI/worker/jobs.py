"""Shared job completion behavior for HTTP events and the local input monitor."""

from job.cohort import build_cohort
from job.demand import aggregate_demand
from worker.store import Artifact, digest


def job_stream(criteria, versions):
    return digest({"criteria": criteria.model_dump(mode="json"), "versions": versions})


def job_artifacts(batch, criteria, mapper, versions):
    cohort = build_cohort(batch, criteria, mapper)
    demand = aggregate_demand(cohort)
    stream = job_stream(criteria, versions)
    return [
        Artifact("COHORT", None, cohort.model_dump(mode="json"), stream),
        Artifact("DEMAND", None, demand.model_dump(mode="json"), stream),
    ]
