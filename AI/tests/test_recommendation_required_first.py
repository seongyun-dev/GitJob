"""Next-skill ordering values confirmed required postings before preferred reach."""

from test_job_cohort import posting
from test_recommendation_new_skill import candidate_ids, scenario, top3_scenario

from recommendation.engine import (
    IMPACT_V8_ALGORITHM_VERSION,
    IMPACT_V8_TIE_BREAK_RULE,
    IMPACT_V8_TREND_TIE_BREAK_RULE,
    RecommendationSnapshot,
    _snapshot_id,
)


def test_required_postings_outrank_larger_preferred_or_overlapping_reach():
    result = scenario(
        postings=[
            posting("spring-required-1", required=("Spring Boot",)),
            posting("spring-required-2", required=("Spring Boot",)),
            posting("spring-required-3", required=("Spring Boot",)),
            *[
                posting(f"docker-preferred-{index}", required=(), preferred=("Docker",))
                for index in range(6)
            ],
            posting("overlap", required=("Spring Boot",), preferred=("Docker",)),
        ],
        technologies=[],
        evaluated=[],
    )

    assert candidate_ids(result)[:2] == ["spring-boot", "docker"]
    assert result.candidates[0].impact.required_count == 4
    assert result.candidates[1].impact.preferred_count == 7
    assert result.algorithm_version == "c-recommendation/condition-impact/v9"


def test_general_mention_alone_is_not_a_recommendation_with_empty_job_list():
    result = scenario(
        postings=[
            posting("general", required=(), general=("Docker",)),
            posting("required", required=("Redis",)),
        ],
        technologies=[],
        evaluated=[],
    )

    assert "docker" not in candidate_ids(result)
    assert "redis" in candidate_ids(result)


def test_preferred_only_candidate_remains_when_no_required_candidate_exists():
    result = scenario(
        postings=[posting("preferred", required=(), preferred=("Docker",))],
        technologies=[],
        evaluated=[],
    )

    assert candidate_ids(result) == ["docker"]
    assert result.candidates[0].impact.required_count == 0
    assert result.candidates[0].impact.preferred_count == 1


def test_prior_v8_snapshot_keeps_its_stored_rank_rule_and_immutable_id():
    # All three candidates occur in required postings only, so this payload
    # also has the exact order emitted by v8. Its persisted hash is not changed
    # by the new v9 defaults or rank policy.
    old = top3_scenario().model_dump(mode="json")
    old["algorithm_version"] = IMPACT_V8_ALGORITHM_VERSION
    old["tie_break_rule"] = IMPACT_V8_TIE_BREAK_RULE
    old["snapshot_id"] = _snapshot_id(
        {key: value for key, value in old.items() if key != "snapshot_id"}
    )

    restored = RecommendationSnapshot.model_validate(old)
    assert restored.model_dump(mode="json") == old
    assert restored.algorithm_version == IMPACT_V8_ALGORITHM_VERSION


def test_prior_v8_trended_snapshot_still_accepts_its_rank_policy():
    from test_recommendation_trend_tiebreak import current_recommend, lookup_of

    old = current_recommend(
        30, 30, trend_lookup=lookup_of({"docker": 10, "redis": 20})
    ).model_dump(mode="json")
    old["algorithm_version"] = IMPACT_V8_ALGORITHM_VERSION
    old["tie_break_rule"] = IMPACT_V8_TREND_TIE_BREAK_RULE
    old["snapshot_id"] = _snapshot_id(
        {key: value for key, value in old.items() if key != "snapshot_id"}
    )

    restored = RecommendationSnapshot.model_validate(old)
    assert restored.model_dump(mode="json") == old
