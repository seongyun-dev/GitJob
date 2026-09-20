"""Trend orders a settled Top3; it never chooses one (S15P21E102-355).

앞부분은 순수 정렬 규칙과 bounded 조회 경로를, 뒷부분은 `build_recommendations`
배선과 snapshot identity 를 검증한다.

함수 안에서 import 하지 않는 것은 ruff isort 가 `recommendation` 을 first-party 로
볼지가 **실행 디렉터리에 따라 달라지기** 때문이다. `AI/` 에서 돌리면 통과하고
저장소 루트에서 돌리면 I001 이 난다. 모듈 상단으로 올리면 그 차이가 사라진다.
"""

import inspect
from pathlib import Path

import pytest
from evidence_fixtures import proof_payload
from pydantic import ValidationError
from test_evidence_consumption import legacy_analysis_payload
from test_job_cohort import batch, criteria, posting
from test_recommendation_engine import make_cohort, make_job, recommend

from job.cohort import build_cohort
from recommendation.engine import (
    LEGACY_TIE_BREAK_RULE,
    RECOMMENDATION_ALGORITHM_VERSION,
    TIE_BREAK_RULE,
    TREND_TIE_BREAK_RULE,
    RecommendationSnapshot,
    TrendTieBreakBasis,
    _snapshot_id,
    build_recommendations,
)
from recommendation.evidence import EvidenceAnalysis
from recommendation.trend_tiebreak import (
    MAX_TIEBREAK_TECH_IDS,
    NEAR_TIE_THRESHOLD_PERCENT,
    TREND_GRANULARITY,
    TREND_METRIC,
    TREND_SOURCE,
    TieBreakCandidate,
    apply_trend_tiebreak,
    cluster_near_ties,
    near_tie,
    resolve_trend_basis,
)


def candidate(
    tech_id: str,
    gain: int,
    *,
    prerequisites_ready: bool = True,
    required: int = 0,
    uncertainty: int = 0,
    total: int = 0,
) -> TieBreakCandidate:
    """`engine.py` 비교 키에서 gain 을 뺀 나머지를 그대로 흉내 낸다."""
    return TieBreakCandidate(
        tech_id=tech_id,
        increased_count=gain,
        rest_key=(not prerequisites_ready, -required, uncertainty, -total, tech_id),
    )


def rank(candidates, trend_values=None, *, top=3):
    """engine.py 의 `sorted(ranked, key=...)[:3]` 뒤에 tie-break 를 붙인 모양."""
    base = sorted(candidates, key=lambda item: (-item.increased_count, *item.rest_key))
    return [item.tech_id for item in apply_trend_tiebreak(base[:top], trend_values)]


class FakeTrendStore:
    """호출을 기록하는 읽기 전용 대역. 실제 SQL 은 여기서 돌지 않는다."""

    def __init__(self, periods, values):
        self._periods = periods
        self._values = values
        self.period_calls: list[dict] = []
        self.value_calls: list[dict] = []

    def get_trend_periods(self, *, source, granularity):
        self.period_calls.append({"source": source, "granularity": granularity})
        return list(self._periods.get((source, granularity), []))

    def get_trend_values(self, *, source, granularity, period, tech_ids):
        self.value_calls.append(
            {
                "source": source,
                "granularity": granularity,
                "period": period,
                "tech_ids": tech_ids,
            }
        )
        stored = self._values.get((source, granularity, period), {})
        return {tech: stored[tech] for tech in tech_ids if tech in stored}


# --- A. Top3 집합은 increased_count 가 정한다 ---------------------------------


def test_a_trend_cannot_pull_a_fourth_candidate_into_the_top_three():
    candidates = [
        candidate("a", 40),
        candidate("b", 30),
        candidate("c", 20),
        candidate("d", 19),
    ]
    # d 는 Trend 최고이고 c 와 near-tie(1/20 = 5%)이기도 하다. 그래도 Top3 밖이다.
    assert near_tie(20, 19)
    trend = {"a": 1, "b": 2, "c": 3, "d": 100_000}
    assert rank(candidates, trend) == ["a", "b", "c"]


def test_a_tiebreak_only_ever_permutes_what_it_is_given():
    given = (candidate("a", 30), candidate("b", 30))
    result = apply_trend_tiebreak(given, {"a": 1, "b": 2, "zzz": 99_999})
    assert sorted(item.tech_id for item in result) == ["a", "b"]
    assert len(result) == len(given)


# --- B. near-tie 안에서는 Trend 가 앞선다 -------------------------------------


def test_b_a_one_job_difference_is_settled_by_the_repository_count():
    docker = candidate("docker", 31)
    redis = candidate("redis", 30)
    assert near_tie(31, 30)
    assert rank([docker, redis], {"docker": 100, "redis": 300}) == ["redis", "docker"]
    # Trend 가 같은 방향이면 순서는 그대로다.
    assert rank([docker, redis], {"docker": 300, "redis": 100}) == ["docker", "redis"]


# --- C. near-tie 가 아니면 Trend 는 순서를 뒤집지 못한다 ----------------------


def test_c_a_large_gain_gap_is_not_overturned_by_trend():
    assert not near_tie(40, 25)
    docker = candidate("docker", 40)
    redis = candidate("redis", 25)
    assert rank([docker, redis], {"docker": 100, "redis": 300}) == ["docker", "redis"]


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        (31, 30, True),
        (40, 25, False),
        (30, 27, True),  # 정확히 10% -- "이내"는 포함이다
        (30, 26, False),  # 13.3%
        (1, 1, True),
        (1, 0, False),  # 분모가 1이라 100% 차이
        (100, 90, True),
        (100, 89, False),
    ],
)
def test_c_threshold_boundaries_are_exact_integer_comparisons(left, right, expected):
    assert near_tie(left, right) is expected
    assert near_tie(right, left) is expected
    assert NEAR_TIE_THRESHOLD_PERCENT == 10


# --- D. 0 vs 0 경계 ----------------------------------------------------------


def test_d_two_zero_gain_candidates_are_an_exact_tie_and_stay_deterministic():
    assert near_tie(0, 0)
    zero_a = candidate("alpha", 0)
    zero_b = candidate("beta", 0)
    # Trend 가 있으면 그것이 답한다.
    assert rank([zero_a, zero_b], {"alpha": 5, "beta": 50}) == ["beta", "alpha"]
    # 없으면 기존 키의 마지막 결정자인 tech_id 로 고정된다.
    assert rank([zero_a, zero_b], None) == ["alpha", "beta"]
    assert rank([zero_b, zero_a], None) == ["alpha", "beta"]


def test_d_zero_gain_never_ties_with_a_real_gain():
    assert not near_tie(0, 1)
    assert rank([candidate("z", 0), candidate("a", 1)], {"z": 999, "a": 1}) == [
        "a",
        "z",
    ]


# --- E. Trend 가 없으면 기존 comparator 로 떨어진다 ---------------------------


@pytest.mark.parametrize(
    "trend",
    [
        None,
        {},
        {"docker": 100},  # redis 만 값이 없다
        {"redis": 300},  # docker 만 값이 없다 -- 없는 값을 0으로 읽으면 뒤집힌다
        {"kotlin": 7},  # 무리 밖 기술만 있다
    ],
)
def test_e_absent_or_partial_trend_leaves_the_existing_order_untouched(trend):
    docker = candidate("docker", 31)
    redis = candidate("redis", 30)
    # 값이 하나라도 빠지면 무리 전체가 기존 순서를 유지한다. 측정하지 않은 것을
    # 0으로 읽으면 "Trend 가 더 높다"가 아니라 "측정된 쪽이 이긴다"가 된다.
    assert rank([docker, redis], trend) == ["docker", "redis"]


def test_e_existing_comparator_keys_still_decide_inside_a_cluster_without_trend():
    # gain 이 같고 선행기술 준비만 다른 경우 -- S15P21E102-202 의 2순위 규칙.
    ready = candidate("zzz-ready", 30, prerequisites_ready=True)
    blocked = candidate("aaa-blocked", 30, prerequisites_ready=False)
    assert rank([blocked, ready], None) == ["zzz-ready", "aaa-blocked"]


def test_e_rest_key_breaks_a_trend_tie_inside_a_cluster():
    ready = candidate("zzz-ready", 30, prerequisites_ready=True)
    blocked = candidate("aaa-blocked", 30, prerequisites_ready=False)
    order = rank([blocked, ready], {"zzz-ready": 7, "aaa-blocked": 7})
    assert order == ["zzz-ready", "aaa-blocked"]


# --- F. event_count 는 쓰지 않는다 -------------------------------------------


def test_f_the_ranked_metric_is_the_repository_count():
    assert TREND_METRIC == "active_repo_count"


def test_f_a_huge_event_count_cannot_move_a_low_repository_count():
    docker = candidate("docker", 31)
    redis = candidate("redis", 30)
    # 같은 point 에서 읽을 수 있었을 값들. 순위는 active_repo_count 만 본다.
    active_repo_count = {"docker": 300, "redis": 100}
    event_count = {"docker": 1, "redis": 1_191_450}
    assert rank([docker, redis], active_repo_count) == ["docker", "redis"]
    assert rank([docker, redis], event_count) != ["docker", "redis"]


def test_f_the_bounded_query_binds_the_ranking_field_and_never_event_count():
    from worker.store import TREND_VALUE_KEYS, ComputeStore

    assert TREND_VALUE_KEYS[TREND_SOURCE] == TREND_METRIC
    sql = inspect.getsource(ComputeStore.get_trend_values)
    statement = sql.split('"""', 2)[-1]
    assert "event_count" not in statement
    assert "%(value_key)s" in statement
    assert "TREND_VALUE_KEYS[source]" in statement


def test_f_the_shipped_module_does_not_mention_event_count_as_a_metric():
    module = Path(__file__).resolve().parents[1] / "recommendation/trend_tiebreak.py"
    body = module.read_text(encoding="utf-8")
    # 주석으로 금지 사유를 적는 것은 허용하되, 상수로 쓰지는 않는다.
    assert 'TREND_METRIC = "active_repo_count"' in body
    assert 'TREND_METRIC = "event_count"' not in body


# --- G. WEEK/MONTH 혼입 금지 -------------------------------------------------


def test_g_the_lookup_always_asks_for_the_week_granularity():
    assert TREND_GRANULARITY == "WEEK"
    store = FakeTrendStore(
        periods={
            (TREND_SOURCE, "WEEK"): ["2026-08-31", "2026-09-07"],
            (TREND_SOURCE, "MONTH"): ["2026-08", "2026-09"],
        },
        values={
            (TREND_SOURCE, "WEEK", "2026-09-07"): {"docker": 100, "redis": 300},
            (TREND_SOURCE, "MONTH", "2026-09"): {"docker": 9_999, "redis": 1},
        },
    )
    basis = resolve_trend_basis(store, ["docker", "redis"])
    assert basis is not None
    assert basis.granularity == "WEEK"
    assert basis.period == "2026-09-07"
    assert basis.values == {"docker": 100, "redis": 300}
    assert {call["granularity"] for call in store.period_calls} == {"WEEK"}
    assert {call["granularity"] for call in store.value_calls} == {"WEEK"}


def test_g_the_source_is_the_payload_namespace_not_the_stream_selector():
    # payload 를 훑는 집계는 payload 이름으로 물어야 한다. selector 이름
    # (`WEEKLY_REPO_ACTIVITY`)은 resolve 전용이고, payload 에는 그 이름이 0건이라
    # 값이 있어도 빈 결과가 온다 -- docs/be/c-compute-public-api.md.
    assert TREND_SOURCE == "GITHUB_GH_ARCHIVE"
    store = FakeTrendStore(
        periods={("WEEKLY_REPO_ACTIVITY", "WEEK"): ["2026-09-07"]},
        values={("WEEKLY_REPO_ACTIVITY", "WEEK", "2026-09-07"): {"docker": 1}},
    )
    assert resolve_trend_basis(store, ["docker"]) is None


def test_g_the_bounded_query_filters_the_granularity_and_the_period():
    from worker.store import ComputeStore

    statement = inspect.getsource(ComputeStore.get_trend_values).split('"""', 2)[-1]
    assert "p->>'granularity' = %(granularity)s" in statement
    assert "p->>'period' = %(period)s" in statement


# --- H. 같은 입력은 같은 결과 ------------------------------------------------


def test_h_repeated_and_reordered_input_produces_one_stable_order():
    candidates = [candidate("a", 31), candidate("b", 30), candidate("c", 30)]
    trend = {"a": 100, "b": 300, "c": 300}
    expected = rank(candidates, trend)
    for permutation in (
        candidates,
        list(reversed(candidates)),
        [candidates[1], candidates[0], candidates[2]],
    ):
        for _ in range(5):
            assert rank(permutation, trend) == expected
    # b 와 c 는 Trend 까지 같으므로 tech_id 가 마지막 결정자다.
    assert expected == ["b", "c", "a"]


# --- near-tie 무리 규칙 -------------------------------------------------------


def test_clusters_anchor_on_their_leader_and_never_chain_transitively():
    # 31~29 = 6.5%, 29~27 = 6.9% 지만 31~27 = 12.9% 다.
    assert near_tie(31, 29) and near_tie(29, 27) and not near_tie(31, 27)
    candidates = [candidate("a", 31), candidate("b", 29), candidate("c", 27)]
    assert cluster_near_ties(candidates) == ((0, 1), (2,))
    # 따라서 c 는 Trend 가 아무리 높아도 a 를 넘지 못한다.
    assert rank(candidates, {"a": 1, "b": 2, "c": 100_000}) == ["b", "a", "c"]


def test_a_single_cluster_reorders_all_three_when_every_gain_is_near():
    candidates = [candidate("a", 31), candidate("b", 30), candidate("c", 29)]
    assert cluster_near_ties(candidates) == ((0, 1, 2),)
    assert rank(candidates, {"a": 1, "b": 2, "c": 3}) == ["c", "b", "a"]


# --- bounded 조회 경로 --------------------------------------------------------


def test_the_lookup_reads_every_candidate_in_one_query():
    store = FakeTrendStore(
        periods={(TREND_SOURCE, "WEEK"): ["2026-08-31", "2026-09-07"]},
        values={
            (TREND_SOURCE, "WEEK", "2026-09-07"): {
                "docker": 100,
                "redis": 300,
                "python": 200,
            }
        },
    )
    basis = resolve_trend_basis(store, ["docker", "redis", "python"])
    assert basis is not None
    assert len(store.value_calls) == 1
    assert len(store.period_calls) == 1
    assert store.value_calls[0]["tech_ids"] == ("docker", "redis", "python")
    assert basis.values == {"docker": 100, "python": 200, "redis": 300}


def test_the_lookup_uses_the_newest_published_week_and_not_a_calendar_guess():
    store = FakeTrendStore(
        periods={(TREND_SOURCE, "WEEK"): ["2026-08-31", "2026-09-07"]},
        values={(TREND_SOURCE, "WEEK", "2026-09-07"): {"docker": 4}},
    )
    assert resolve_trend_basis(store, ["docker"]).period == "2026-09-07"


def test_an_unpublished_source_yields_no_basis_instead_of_an_empty_week():
    store = FakeTrendStore(periods={}, values={})
    assert resolve_trend_basis(store, ["docker"]) is None
    assert store.value_calls == []


def test_a_week_with_no_matching_technology_yields_no_basis():
    store = FakeTrendStore(
        periods={(TREND_SOURCE, "WEEK"): ["2026-09-07"]},
        values={(TREND_SOURCE, "WEEK", "2026-09-07"): {"kotlin": 3}},
    )
    assert resolve_trend_basis(store, ["docker", "redis"]) is None


def test_the_lookup_refuses_more_technologies_than_a_top_three():
    store = FakeTrendStore(periods={}, values={})
    assert MAX_TIEBREAK_TECH_IDS == 3
    with pytest.raises(ValueError, match="at most three"):
        resolve_trend_basis(store, ["a", "b", "c", "d"])


def test_duplicate_candidates_are_asked_once_and_keep_their_order():
    store = FakeTrendStore(
        periods={(TREND_SOURCE, "WEEK"): ["2026-09-07"]},
        values={(TREND_SOURCE, "WEEK", "2026-09-07"): {"docker": 1, "redis": 2}},
    )
    resolve_trend_basis(store, ["docker", "redis", "docker"])
    assert store.value_calls[0]["tech_ids"] == ("docker", "redis")


def test_the_store_refuses_an_unbounded_or_duplicated_selection():
    from worker.store import ComputeStore

    store = ComputeStore.__new__(ComputeStore)
    assert (
        store.get_trend_values(
            source=TREND_SOURCE, granularity="WEEK", period="2026-09-07", tech_ids=()
        )
        == {}
    )
    for selection in (tuple(f"t{n}" for n in range(11)), ("docker", "docker")):
        with pytest.raises(ValueError, match="invalid trend value selection"):
            store.get_trend_values(
                source=TREND_SOURCE,
                granularity="WEEK",
                period="2026-09-07",
                tech_ids=selection,
            )


def test_a_negative_gain_is_rejected_rather_than_silently_ordered():
    with pytest.raises(ValueError, match="must not be negative"):
        near_tie(-1, 3)


# --- build_recommendations 배선 (Phase B) -------------------------------------


def make_basis(values, *, period="2026-09-07"):
    return TrendTieBreakBasis(
        source=TREND_SOURCE,
        granularity=TREND_GRANULARITY,
        period=period,
        metric=TREND_METRIC,
        values=values,
    )


def lookup_of(values, *, period="2026-09-07", calls=None):
    """Top3 tech_id 로만 불리는지 기록하는 조회 대역."""

    def lookup(tech_ids):
        if calls is not None:
            calls.append(tech_ids)
        observed = {tech: values[tech] for tech in tech_ids if tech in values}
        return make_basis(observed, period=period) if observed else None

    return lookup


def rebuilt_with(payload: dict, **overrides) -> dict:
    changed = {**payload, **overrides}
    changed.pop("snapshot_id", None)
    changed["snapshot_id"] = _snapshot_id(changed)
    return changed


def wide_gap_cohort():
    """docker 는 2건, react 는 1건 늘어난다 -- 차이 50%, near-tie 가 아니다."""
    return make_cohort(
        (
            make_job("docker-1", (("docker",),)),
            make_job("docker-2", (("docker",),)),
            make_job("react-1", (("react",),)),
        )
    )


def exact_tie_cohort():
    return make_cohort(
        (make_job("react", (("react",),)), make_job("docker", (("docker",),)))
    )


def tech_order(result):
    return [item.tech_id for item in result.candidates]


def test_wiring_keeps_the_base_order_when_no_lookup_is_supplied():
    plain = recommend(wide_gap_cohort())
    assert plain.tie_break_rule == TIE_BREAK_RULE
    assert plain.trend_tiebreak is None
    assert "trend_tiebreak" not in plain.model_dump(mode="json")


def test_wiring_asks_only_for_the_settled_top3_exactly_once():
    calls: list[tuple[str, ...]] = []
    result = recommend(
        wide_gap_cohort(),
        trend_lookup=lookup_of({"docker": 10, "react": 20}, calls=calls),
    )
    assert len(calls) == 1
    assert set(calls[0]) == set(tech_order(result))
    assert len(calls[0]) <= 3


def test_wiring_does_not_reorder_when_the_gain_gap_is_wide():
    plain = tech_order(recommend(wide_gap_cohort()))
    result = recommend(
        wide_gap_cohort(), trend_lookup=lookup_of({"docker": 1, "react": 9_999})
    )
    assert tech_order(result) == plain
    assert result.tie_break_rule == TREND_TIE_BREAK_RULE


def test_wiring_reorders_an_exact_tie_by_the_repository_count():
    cohort = exact_tie_cohort()
    assert tech_order(recommend(cohort)) == ["docker", "react"]
    swapped = recommend(cohort, trend_lookup=lookup_of({"docker": 10, "react": 900}))
    assert tech_order(swapped) == ["react", "docker"]
    assert swapped.trend_tiebreak.metric == "active_repo_count"
    assert swapped.trend_tiebreak.granularity == "WEEK"
    assert swapped.trend_tiebreak.source == "GITHUB_GH_ARCHIVE"


def test_wiring_keeps_the_v7_calculation_untouched():
    """순서만 바뀐다 -- 후보 집합도 What-if 숫자도 그대로여야 한다."""
    cohort = exact_tie_cohort()
    plain = recommend(cohort)
    trended = recommend(cohort, trend_lookup=lookup_of({"docker": 10, "react": 900}))
    assert plain.algorithm_version == trended.algorithm_version
    assert set(tech_order(plain)) == set(tech_order(trended))
    assert plain.current_count == trended.current_count
    gains = {item.tech_id: item.what_if.increased_count for item in plain.candidates}
    assert {
        item.tech_id: item.what_if.increased_count for item in trended.candidates
    } == gains
    assert [item.rank for item in trended.candidates] == [1, 2]


def test_wiring_survives_a_week_that_published_nothing():
    result = recommend(wide_gap_cohort(), trend_lookup=lambda tech_ids: None)
    plain = recommend(wide_gap_cohort())
    assert result.tie_break_rule == TIE_BREAK_RULE
    assert result.trend_tiebreak is None
    # Trend 는 순서 보정이지 추천 생성의 전제가 아니다.
    assert result.snapshot_id == plain.snapshot_id


def test_wiring_refuses_a_basis_about_technologies_it_did_not_ask_for():
    with pytest.raises(ValueError, match="only the Top3"):
        recommend(
            wide_gap_cohort(),
            trend_lookup=lambda tech_ids: make_basis({"kotlin": 5}),
        )


# --- snapshot identity (Codex S15P21E102-358 감사 항목) -----------------------


def test_identity_a_a_different_trend_period_is_a_different_snapshot():
    cohort = wide_gap_cohort()
    values = {"docker": 10, "react": 20}
    first = recommend(cohort, trend_lookup=lookup_of(values, period="2026-08-31"))
    second = recommend(cohort, trend_lookup=lookup_of(values, period="2026-09-07"))
    assert tech_order(first) == tech_order(second)
    assert first.tie_break_rule == second.tie_break_rule
    assert first.snapshot_id != second.snapshot_id


def test_identity_b_a_different_basis_that_changes_order_changes_identity():
    cohort = exact_tie_cohort()
    low = recommend(cohort, trend_lookup=lookup_of({"docker": 900, "react": 10}))
    high = recommend(cohort, trend_lookup=lookup_of({"docker": 10, "react": 900}))
    assert tech_order(low) == ["docker", "react"]
    assert tech_order(high) == ["react", "docker"]
    assert low.snapshot_id != high.snapshot_id


def test_identity_c_trend_absent_is_distinguishable_from_trend_applied():
    cohort = wide_gap_cohort()
    plain = recommend(cohort)
    trended = recommend(cohort, trend_lookup=lookup_of({"docker": 10, "react": 20}))
    assert plain.tie_break_rule != trended.tie_break_rule
    assert plain.trend_tiebreak is None
    assert trended.trend_tiebreak is not None
    assert plain.snapshot_id != trended.snapshot_id


def test_identity_d_legacy_snapshots_still_read_back_unchanged():
    payload = recommend(wide_gap_cohort()).model_dump(mode="json")
    old = rebuilt_with(
        payload,
        algorithm_version="c-recommendation/lexicographic/v2",
        tie_break_rule=LEGACY_TIE_BREAK_RULE,
    )
    restored = RecommendationSnapshot.model_validate(old)
    assert restored.model_dump(mode="json") == old
    assert restored.trend_tiebreak is None


def test_identity_e_a_current_version_snapshot_without_trend_still_reads_back():
    """현재 운영 알고리즘이 Trend 없이 낸 결과가 새 코드에서 그대로 읽힌다.

    버전 문자열을 적어 넣지 않고 상수와 비교하는 것은, 추천 계산 버전이 -355 의
    소관이 아니기 때문이다. 계산이 올라가도 이 테스트가 묻는 것은 같다.
    """
    stored = current_recommend(("Docker", 3), ("Redis", 2)).model_dump(mode="json")
    assert stored["algorithm_version"] == RECOMMENDATION_ALGORITHM_VERSION
    assert "trend_tiebreak" not in stored
    restored = RecommendationSnapshot.model_validate(stored)
    assert restored.model_dump(mode="json") == stored
    assert restored.tie_break_rule == TIE_BREAK_RULE


# --- 실제 v7 계산 위에서의 near-tie -------------------------------------------


def held_java(registry_version: str) -> EvidenceAnalysis:
    """java 하나만 보유한 분석. 후보가 되는 기술과는 겹치지 않는다.

    이 helper 를 S15P21E102-354 의 테스트 파일에서 가져오지 않고 직접 들고 있는
    것은, 그쪽 fixture 가 "personal level 이 L1 이상이면 후보에서 뺀다"는 **정책을
    전제**하기 때문이다. 그 정책은 바뀌는 중이다(공고 requiredLevel 과 비교하는
    방향). 여기서 필요한 것은 그 정책이 아니라 "증거가 전혀 없는 기술 몇 개가
    후보가 되는 코호트"뿐이므로, 어느 정책에서도 같은 후보가 나오도록 보유 기술을
    후보와 분리해 둔다. -355 는 그 후보들의 **순서**만 본다.
    """
    proofs = [
        proof_payload(kind, tech_id="java", suffix="java")
        for kind in ("DIRECT_DEPENDENCY", "PARTICIPATION", "IMPLEMENTATION")
    ]
    payload = legacy_analysis_payload()
    payload["schema_version"] = "evidence-consumption-input/v3"
    payload["registry_version"] = registry_version
    repository = payload["repositories"][0]
    repository["technologies"] = [
        {
            "tech_id": "java",
            "fact_ids": [proof["fact_id"] for proof in proofs],
            "evidence_level": "L2",
            "direct_dependency": True,
            "implementation_present": True,
            "user_participation": True,
            "implemented_by": "SELF",
            "attribution_status": "COMPLETE",
            "source_refs": ["https://github.com/example/repo/blob/aaa/java"],
            "proofs": proofs,
            "personal_level": "L2",
        }
    ]
    repository["evaluated_tech_ids"] = ["java"]
    repository["coverage_complete"] = True
    return EvidenceAnalysis.model_validate(payload)


def current_recommend(*counts, trend_lookup=None):
    """현재 운영 알고리즘 경로로 계산한 뒤 Trend 순서만 다르게 한다.

    `counts` 는 (표시명, 공고 수) 쌍이거나 docker/redis 두 정수다.
    """
    if counts and isinstance(counts[0], int):
        counts = tuple(zip(("Docker", "Redis"), counts, strict=True))
    postings = [
        posting(f"{name}-{index}", required=(name,))
        for name, jobs in counts
        for index in range(jobs)
    ]
    cohort = build_cohort(batch(*postings), criteria())
    return build_recommendations(
        cohort,
        held_java(cohort.registry_version),
        user_id="user-1",
        analysis_id="analysis-1",
        trend_lookup=trend_lookup,
    )


def test_current_near_tie_is_reordered_by_the_weekly_repository_count():
    # 31 vs 30 -- 차이 1/31 = 3.2%.
    plain = current_recommend(31, 30)
    assert plain.algorithm_version == RECOMMENDATION_ALGORITHM_VERSION
    assert tech_order(plain) == ["docker", "redis"]
    assert [item.what_if.increased_count for item in plain.candidates] == [31, 30]

    trended = current_recommend(
        31, 30, trend_lookup=lookup_of({"docker": 100, "redis": 300})
    )
    assert tech_order(trended) == ["redis", "docker"]
    # 순서만 바뀐다 -- 증가 공고 수는 후보를 따라간다.
    gains = {item.tech_id: item.what_if.increased_count for item in trended.candidates}
    assert gains == {"docker": 31, "redis": 30}
    assert [item.rank for item in trended.candidates] == [1, 2]
    assert trended.trend_tiebreak.values == {"docker": 100, "redis": 300}


def test_current_a_fourth_candidate_never_enters_the_top3_through_trend():
    """배선 회귀 감지용 -- Trend 를 자르기 **전에** 적용하면 여기서 깨진다.

    postgresql(+20) 과 nginx(+19) 는 서로 near-tie(5%) 다. nginx 의 Trend 가
    가장 높아도 4위는 4위다. 순수 규칙 테스트와 달리 이것은 engine.py 의 연결
    순서를 직접 검증한다.
    """
    counts = (("Docker", 40), ("Redis", 30), ("PostgreSQL", 20), ("Nginx", 19))
    plain = current_recommend(*counts)
    assert tech_order(plain) == ["docker", "redis", "postgresql"]
    assert near_tie(20, 19)

    asked: list[tuple[str, ...]] = []
    trended = current_recommend(
        *counts,
        trend_lookup=lookup_of(
            {"docker": 1, "redis": 2, "postgresql": 3, "nginx": 100_000},
            calls=asked,
        ),
    )
    assert tech_order(trended) == ["docker", "redis", "postgresql"]
    # 4위는 조회 대상조차 아니다 -- 묻지 않으므로 값이 있어도 쓰일 수 없다.
    assert asked == [("docker", "redis", "postgresql")]
    assert "nginx" not in trended.trend_tiebreak.values


def test_current_wide_gap_is_not_reordered_even_by_a_much_larger_trend():
    # 40 vs 25 -- 차이 15/40 = 37.5%.
    trended = current_recommend(
        40, 25, trend_lookup=lookup_of({"docker": 100, "redis": 300})
    )
    assert tech_order(trended) == ["docker", "redis"]
    assert [item.what_if.increased_count for item in trended.candidates] == [40, 25]


def test_identity_f_the_same_basis_replays_to_the_same_snapshot_and_order():
    cohort = exact_tie_cohort()
    runs = [
        recommend(cohort, trend_lookup=lookup_of({"docker": 10, "react": 900}))
        for _ in range(5)
    ]
    assert len({run.snapshot_id for run in runs}) == 1
    assert {tuple(tech_order(run)) for run in runs} == {("react", "docker")}


def test_a_trended_snapshot_round_trips_through_json():
    result = recommend(
        wide_gap_cohort(), trend_lookup=lookup_of({"docker": 10, "react": 20})
    )
    stored = result.model_dump(mode="json")
    assert stored["trend_tiebreak"] == {
        "source": "GITHUB_GH_ARCHIVE",
        "granularity": "WEEK",
        "period": "2026-09-07",
        "metric": "active_repo_count",
        "values": {"docker": 10, "react": 20},
    }
    restored = RecommendationSnapshot.model_validate(stored)
    assert restored.model_dump(mode="json") == stored


# --- validator 가 순서 의미를 섞이지 않게 막는가 -----------------------------


def test_a_stored_basis_cannot_claim_the_old_rank_policy():
    stored = recommend(
        wide_gap_cohort(), trend_lookup=lookup_of({"docker": 10, "react": 20})
    ).model_dump(mode="json")
    forged = rebuilt_with(stored, tie_break_rule=TIE_BREAK_RULE)
    with pytest.raises(ValidationError, match="trend basis requires"):
        RecommendationSnapshot.model_validate(forged)


def test_an_unknown_rank_policy_is_still_refused():
    stored = recommend(wide_gap_cohort()).model_dump(mode="json")
    forged = rebuilt_with(stored, tie_break_rule="trend-first,whatever")
    with pytest.raises(ValidationError):
        RecommendationSnapshot.model_validate(forged)


def test_a_tampered_trend_value_breaks_the_snapshot_identity():
    result = recommend(
        wide_gap_cohort(), trend_lookup=lookup_of({"docker": 10, "react": 20})
    )
    tampered = result.model_dump(mode="json")
    tampered["trend_tiebreak"]["values"]["docker"] = 999
    with pytest.raises(ValidationError):
        RecommendationSnapshot.model_validate(tampered)


def test_the_basis_refuses_an_event_count_metric_and_a_month_granularity():
    with pytest.raises(ValidationError):
        TrendTieBreakBasis(
            source=TREND_SOURCE,
            granularity="WEEK",
            period="2026-09-07",
            metric="event_count",
            values={"docker": 1},
        )
    with pytest.raises(ValidationError):
        TrendTieBreakBasis(
            source=TREND_SOURCE,
            granularity="MONTH",
            period="2026-09",
            metric=TREND_METRIC,
            values={"docker": 1},
        )
    with pytest.raises(ValidationError, match="bounded to the Top3"):
        TrendTieBreakBasis(
            source=TREND_SOURCE,
            granularity="WEEK",
            period="2026-09-07",
            metric=TREND_METRIC,
            values={"a": 1, "b": 2, "c": 3, "d": 4},
        )
