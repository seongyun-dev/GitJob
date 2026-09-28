"""A stored recommendation carries metadata the model never declared.

S15P21E102-368. The writer puts `cohort_snapshot_id`, `explanation`,
`job_matching`/`job_matching_ref` and `projection_version_id` beside the model
fields, but `RecommendationSnapshot` is `extra="forbid"`. The What-if detail
route used to drop those keys by name and missed `projection_version_id`, so
every recommendation written after the projection rollout raised a pydantic
`ValidationError` on read. That is a `ValueError`, which C reports as
`INVALID_INPUT` 422 and B shows as "지원하지 않는 직무 또는 필터입니다."

Reading by the model's own field list removes the whole class of failure: the
next additive key cannot break the detail page either.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from recommendation.engine import (
    RecommendationSnapshot,
    list_related_jobs,
    snapshot_from_stored_payload,
)

FIXTURE = Path(__file__).parent / "fixtures/recommendation-legacy-v1.json"


def stored(**metadata: Any) -> dict[str, Any]:
    """The model fields as persisted, plus metadata stored beside them."""

    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload.update(metadata)
    return payload


def test_projection_version_id_no_longer_breaks_the_read():
    """The exact production payload shape that returned 422."""

    result = snapshot_from_stored_payload(
        stored(projection_version_id="jp-" + "0" * 64)
    )
    assert [item.tech_id for item in result.candidates] == ["docker", "redis"]


@pytest.mark.parametrize(
    "metadata",
    [
        {"cohort_snapshot_id": "c-" + "1" * 64},
        {"explanation": {"snapshot_id": "c-x"}},
        {"job_matching": {"schema_version": "job-matching-storage/v2"}},
        {"job_matching_ref": {"schema_version": "job-matching-storage/v2"}},
        {"projection_version_id": "jp-" + "2" * 64},
    ],
)
def test_every_known_metadata_key_is_ignored(metadata: dict[str, Any]):
    assert snapshot_from_stored_payload(stored(**metadata)).user_id == "user-1"


def test_all_known_metadata_keys_together_are_ignored():
    result = snapshot_from_stored_payload(
        stored(
            cohort_snapshot_id="c-" + "3" * 64,
            explanation={"snapshot_id": "c-x"},
            job_matching_ref={"schema_version": "job-matching-storage/v2"},
            projection_version_id="jp-" + "4" * 64,
        )
    )
    assert (
        result.snapshot_id
        == json.loads(FIXTURE.read_text(encoding="utf-8"))["snapshot_id"]
    )


def test_a_metadata_key_nobody_has_added_yet_is_also_ignored():
    """The point of the change: the next additive field must not break reads."""

    result = snapshot_from_stored_payload(
        stored(some_future_sidecar_id="whatever-we-add-next")
    )
    assert result.user_id == "user-1"


def test_reading_does_not_change_the_model_values():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    restored = snapshot_from_stored_payload(stored(projection_version_id="jp-x"))
    assert restored.model_dump(mode="json") == payload


def test_what_if_detail_still_lists_the_same_jobs():
    """What the detail page asks for, on a payload that used to 422."""

    result = snapshot_from_stored_payload(stored(projection_version_id="jp-y"))
    for tech_id, expected in (("docker", 2), ("redis", 2)):
        page = list_related_jobs(
            result, user_id="user-1", view="WHAT_IF", tech_id=tech_id
        )
        assert page.total_count == expected


def test_an_unknown_candidate_is_still_rejected():
    """Narrowing the payload must not weaken the What-if contract."""

    result = snapshot_from_stored_payload(stored(projection_version_id="jp-z"))
    with pytest.raises(ValueError, match="candidate"):
        list_related_jobs(
            result, user_id="user-1", view="WHAT_IF", tech_id="not-a-candidate"
        )


def test_a_missing_model_field_is_still_a_validation_error():
    """This drops unknown keys; it does not make the model permissive."""

    payload = stored(projection_version_id="jp-w")
    payload.pop("candidates")
    with pytest.raises(ValidationError):
        snapshot_from_stored_payload(payload)


def test_direct_model_validate_still_forbids_extras():
    """The model keeps its guarantee; only the read path narrows the input."""

    with pytest.raises(ValidationError):
        RecommendationSnapshot.model_validate(stored(projection_version_id="jp-v"))
