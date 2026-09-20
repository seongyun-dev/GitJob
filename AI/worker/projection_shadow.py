"""Bounded, non-blocking comparison of legacy and projection demand results."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore, Lock

from job.demand import DemandSnapshot
from worker.store import digest

LOGGER = logging.getLogger(__name__)


class ProjectionShadow:
    def __init__(self, *, sample_rate: float = 0.01, queue_size: int = 4):
        if not 0 <= sample_rate <= 1:
            raise ValueError("projection shadow sample rate must be in [0, 1]")
        if queue_size < 1:
            raise ValueError("projection shadow queue size must be positive")
        self.sample_rate = sample_rate
        self._slots = BoundedSemaphore(queue_size)
        self._lock = Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="projection-shadow"
        )
        self._metrics = {
            "projection_shadow_submitted_total": 0,
            "projection_shadow_skipped_total": 0,
            "projection_shadow_compared_total": 0,
            "projection_shadow_mismatch_total": 0,
            "projection_shadow_error_total": 0,
            "projection_shadow_selected_id_mismatch_total": 0,
            "projection_shadow_selected_count_mismatch_total": 0,
            "projection_shadow_technology_id_mismatch_total": 0,
            "projection_shadow_technology_category_mismatch_total": 0,
            "projection_shadow_technology_rank_mismatch_total": 0,
            "projection_shadow_aggregate_mismatch_total": 0,
        }

    def should_sample(self, selector) -> bool:
        bucket = int(digest(selector.model_dump(mode="json"))[:8], 16) / 0xFFFFFFFF
        return bucket < self.sample_rate

    def submit(self, selector, compare) -> bool:
        if not self.should_sample(selector):
            return False
        if not self._slots.acquire(blocking=False):
            self._increment("projection_shadow_skipped_total")
            return False
        self._increment("projection_shadow_submitted_total")

        def run():
            try:
                mismatches = compare()
                self._increment("projection_shadow_compared_total")
                if mismatches:
                    self._increment("projection_shadow_mismatch_total")
                    mismatch_set = set(mismatches)
                    if "job_ids" in mismatch_set:
                        self._increment(
                            "projection_shadow_selected_id_mismatch_total"
                        )
                    if "job_count" in mismatch_set:
                        self._increment(
                            "projection_shadow_selected_count_mismatch_total"
                        )
                    if "technology_ids" in mismatch_set:
                        self._increment(
                            "projection_shadow_technology_id_mismatch_total"
                        )
                    if "technology_categories" in mismatch_set:
                        self._increment(
                            "projection_shadow_technology_category_mismatch_total"
                        )
                    if "technology_ranks" in mismatch_set:
                        self._increment(
                            "projection_shadow_technology_rank_mismatch_total"
                        )
                    if mismatch_set - {
                        "job_ids",
                        "job_count",
                        "technology_ids",
                        "technology_categories",
                        "technology_ranks",
                    }:
                        self._increment(
                            "projection_shadow_aggregate_mismatch_total"
                        )
                    LOGGER.warning(
                        "projection_shadow_mismatch fields=%s",
                        ",".join(mismatches),
                    )
            except Exception as exc:  # noqa: BLE001 - isolated background boundary
                self._increment("projection_shadow_error_total")
                LOGGER.warning(
                    "projection_shadow_failed error_type=%s", type(exc).__name__
                )
            finally:
                self._slots.release()

        self._executor.submit(run)
        return True

    def skip(self, reason: str) -> None:
        """Record a sampled comparison rejected before queue submission."""

        self._increment("projection_shadow_skipped_total")
        LOGGER.info("projection_shadow_skipped reason=%s", reason)

    def _increment(self, name: str) -> None:
        with self._lock:
            self._metrics[name] += 1

    def metrics(self) -> dict[str, int | float]:
        with self._lock:
            return {"sample_rate": self.sample_rate, **self._metrics}

    def close(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=False)


def compare_demands(
    legacy: DemandSnapshot,
    projected: DemandSnapshot,
    *,
    legacy_job_ids: tuple[str, ...] | None = None,
    projected_job_ids: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    mismatches = []
    if legacy.criteria != projected.criteria:
        mismatches.append("criteria")
    if (
        legacy_job_ids is not None
        and projected_job_ids is not None
        and legacy_job_ids != projected_job_ids
    ):
        mismatches.append("job_ids")
        if len(legacy_job_ids) != len(projected_job_ids):
            mismatches.append("job_count")
    for field in (
        "status",
        "denominator",
        "matching_count",
        "input_count",
        "duplicate_count",
        "excluded_count",
        "review_count",
        "cross_site_merged_count",
    ):
        if getattr(legacy, field) != getattr(projected, field):
            mismatches.append(field)
    legacy_tech = {
        row.tech_id: row.model_dump(exclude={"tech_id"}) for row in legacy.technologies
    }
    projected_tech = {
        row.tech_id: row.model_dump(exclude={"tech_id"})
        for row in projected.technologies
    }
    if set(legacy_tech) != set(projected_tech):
        mismatches.append("technology_ids")
    category_fields = {
        "required_count",
        "preferred_count",
        "general_count",
        "total_count",
        "required_ratio",
        "preferred_ratio",
        "general_ratio",
        "total_ratio",
    }
    rank_fields = {
        "rank",
        "required_rank",
        "preferred_rank",
        "general_rank",
        "total_rank",
    }
    common_tech = set(legacy_tech) & set(projected_tech)
    if any(
        any(legacy_tech[tech][field] != projected_tech[tech][field]
            for field in category_fields)
        for tech in common_tech
    ):
        mismatches.append("technology_categories")
    if any(
        any(legacy_tech[tech][field] != projected_tech[tech][field]
            for field in rank_fields)
        for tech in common_tech
    ):
        mismatches.append("technology_ranks")
    return tuple(mismatches)
