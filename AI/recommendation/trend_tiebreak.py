"""Order an already-chosen Top3 when the job gain cannot really separate it.

<h2>왜 집합이 아니라 순서만 다루는가</h2>

후보 자격과 Top3 집합은 `increased_count` 가 정한다(S15P21E102-354). 이 모듈은 그
결과를 **입력으로 받아** 순서만 바꾸며, 후보를 넣거나 빼지 않는다. 출력이 입력의
순열이 아니면 예외다 -- Trend 가 후보 선정으로 역류하는 것을 규약이 아니라 코드로
막는다. 4위 후보의 Trend 가 아무리 높아도 이 모듈은 그 후보를 볼 일이 없다.

<h2>왜 near-tie 인가</h2>

`+31` 과 `+30` 은 "공고 한 건"이다. 그 한 건으로 학습 순서를 정하는 것은 측정이
말해 주지 않는 것을 말하는 것이다. 차이가 작을 때는 gain 대신 시장에서 실제로
관측된 저장소 수(`active_repo_count`)를 쓴다. 차이가 크면 gain 이 그대로 이긴다 --
Trend 는 gain 을 뒤집는 힘이 아니라 gain 이 침묵할 때 답하는 지표다.

<h2>왜 leader 기준으로 묶는가</h2>

near-tie 는 추이적이지 않다. `31~29`, `29~27` 이 각각 10% 안이어도 `31~27` 은
12.9% 다. 인접한 쌍을 이어 붙이면(transitive chaining) 세 후보가 한 무리가 되고,
1위와 10% 넘게 벌어진 후보가 Trend 만으로 1위에 올라갈 수 있다. 그래서 각 무리는
**그 무리의 첫 후보(leader)** 와만 비교한다. 이러면 순위 이동 폭이 언제나 leader
기준 10% 안으로 묶인다.

<h2>왜 무리 전체에 Trend 가 있어야 하는가</h2>

한 후보만 Trend 를 가진 무리에서 그 후보를 올리면, 그것은 "Trend 가 더 높다"가
아니라 "Trend 를 측정한 쪽이 이긴다"가 된다. 값이 없는 것은 낮은 값이 아니다.
무리 안에 하나라도 값이 없으면 그 무리는 기존 순서를 그대로 유지한다.
"""

from collections.abc import Mapping, Sequence
from typing import Any, NamedTuple, Protocol

#: 더 큰 `increased_count` 대비 몇 %까지를 "사실상 같은 증가"로 볼 것인가.
#: 백분율 정수로 두는 것은 비교를 정수 연산으로 하기 위해서다 -- `3/30 <= 0.10`
#: 같은 경계값을 부동소수에 맡기면 같은 입력이 환경에 따라 다른 순서를 낼 수 있다.
NEAR_TIE_THRESHOLD_PERCENT = 10

#: 주간 저장소 활동이 저장되는 **payload** source 다.
#:
#: TREND 는 이름 공간이 둘이고 여기서 쓰는 쪽은 payload 다. 선택자(selector) 쪽
#: 이름은 `WEEKLY_REPO_ACTIVITY` 이며 `POST /trends/resolve` 는 **그 이름으로만**
#: 찾는다 -- resolve enum 에 `GITHUB_GH_ARCHIVE` 는 없으므로 그쪽을 이 값으로
#: 바꾸면 깨진다. 반대로 payload 를 훑는 집계(순위·여기)는 selector 이름으로 물으면
#: 0건이 나온다. 주간 head 도 payload 에는 `GITHUB_GH_ARCHIVE` / `granularity=WEEK`
#: 로 적히기 때문이다(`AI/worker/trend_streams.py`).
TREND_SOURCE = "GITHUB_GH_ARCHIVE"

#: 주간 point 만 쓴다. 월별과 섞으면 분모가 다른 값이 한 축에 들어간다.
TREND_GRANULARITY = "WEEK"

#: 순위에 쓰는 필드. 같은 point 의 `event_count` 는 쓰지 않는다 -- 그것은 기술의
#: 이벤트가 아니라 그 기술을 쓰는 저장소들의 전체 활동 합이라 한 저장소가 여러
#: 기술을 쓰면 기술마다 통째로 다시 더해진다(`AI/worker/store.py`).
TREND_METRIC = "active_repo_count"

#: 한 번의 조회가 감당할 후보 수. 추천은 최대 3개를 넘기지 않는다.
MAX_TIEBREAK_TECH_IDS = 3


class TieBreakCandidate(NamedTuple):
    """Top3 한 자리. `rest_key` 는 기존 비교 키에서 gain 을 뺀 나머지다.

    gain 을 따로 받는 것은 이 모듈이 무리 안에서 gain 을 **Trend 로 대체**하기
    때문이다. `rest_key` 는 그대로 이어 붙으므로 선행기술 준비 여부부터
    `tech_id` 까지 S15P21E102-202 가 정한 순서가 유지된다.
    """

    tech_id: str
    increased_count: int
    rest_key: tuple[Any, ...]


class TrendBasis(NamedTuple):
    """어떤 주차의 어떤 값으로 순서를 바꿨는지. 결과에 그대로 남긴다.

    값만 남기면 같은 입력이 다른 순서를 낸 이유를 나중에 설명할 수 없다. 기간과
    출처까지 함께 남겨야 저장된 결과를 다시 계산해 검증할 수 있다.
    """

    source: str
    granularity: str
    period: str
    values: Mapping[str, int]


class TrendValueStore(Protocol):
    """`AI/worker/store.py` 의 ComputeStore 중 이 모듈이 쓰는 부분만."""

    def get_trend_periods(self, *, source: str, granularity: str) -> list[str]: ...

    def get_trend_values(
        self,
        *,
        source: str,
        granularity: str,
        period: str,
        tech_ids: tuple[str, ...],
    ) -> dict[str, int]: ...


def near_tie(left: int, right: int) -> bool:
    """두 증가량이 더 큰 쪽 기준 임계치 안인가.

    둘 다 0이면 정확히 같으므로 near-tie 다. `0` 과 `1` 은 분모가 1이라 100% 차이,
    즉 near-tie 가 아니다 -- "한 건도 안 늘어남"과 "한 건 늘어남"은 다른 사실이다.
    """
    if left < 0 or right < 0:
        raise ValueError("increased_count must not be negative")
    larger = max(left, right)
    if larger == 0:
        return True
    return abs(left - right) * 100 <= larger * NEAR_TIE_THRESHOLD_PERCENT


def cluster_near_ties(
    candidates: Sequence[TieBreakCandidate],
) -> tuple[tuple[int, ...], ...]:
    """이미 gain 내림차순인 후보를 leader 기준 무리로 묶어 인덱스로 돌려준다.

    각 후보는 **직전 후보가 아니라 무리의 첫 후보** 와 비교한다. 인접 비교로
    이어 붙이면 `31 / 29 / 27` 이 한 무리가 되지만, leader 기준이면
    `31~27` 이 12.9% 라 `{31, 29}` 와 `{27}` 로 갈린다.
    """
    clusters: list[list[int]] = []
    leader_gain: int | None = None
    for index, candidate in enumerate(candidates):
        if leader_gain is not None and near_tie(leader_gain, candidate.increased_count):
            clusters[-1].append(index)
            continue
        clusters.append([index])
        leader_gain = candidate.increased_count
    return tuple(tuple(cluster) for cluster in clusters)


def apply_trend_tiebreak(
    candidates: Sequence[TieBreakCandidate],
    trend_values: Mapping[str, int] | None,
) -> tuple[TieBreakCandidate, ...]:
    """Reorder within near-tie clusters only; never add, drop or re-select.

    `candidates` 는 기존 비교 키로 이미 정렬되고 Top3 로 잘린 결과여야 한다.
    돌려주는 것은 언제나 그 입력의 순열이다.

    무리 안에서는 gain 자리에 `-active_repo_count` 가 들어가고 `rest_key` 는
    그대로다. 값이 하나라도 빠진 무리는 손대지 않는다.
    """
    ordered = tuple(candidates)
    if not trend_values or len(ordered) < 2:
        return ordered
    result: list[TieBreakCandidate] = []
    for cluster in cluster_near_ties(ordered):
        members = [ordered[index] for index in cluster]
        values = [trend_values.get(member.tech_id) for member in members]
        if len(members) < 2 or any(value is None for value in values):
            # 값이 없는 것은 낮은 값이 아니다. 비교할 수 없으면 기존 순서를 둔다.
            result.extend(members)
            continue
        result.extend(
            sorted(
                members, key=lambda item: (-trend_values[item.tech_id], *item.rest_key)
            )
        )
    if len(result) != len(ordered) or {item.tech_id for item in result} != {
        item.tech_id for item in ordered
    }:  # pragma: no cover - 방어적 불변식
        raise ValueError("trend tie-break must permute the given candidates")
    return tuple(result)


def resolve_trend_basis(
    store: TrendValueStore,
    tech_ids: Sequence[str],
    *,
    period: str | None = None,
) -> TrendBasis | None:
    """최신 게시 주차의 후보 Trend 값을 **한 번의 조회**로 가져온다.

    기간을 달력으로 계산하지 않고 저장된 목록의 마지막을 쓰는 것은 기존 순위
    endpoint 와 같은 규칙이다(`AI/worker/api.py`). 게시되지 않은 주를 물으면 값이
    있는데도 빈 결과가 온다.

    후보마다 조회하지 않는다 -- 후보 수만큼 질의가 늘면 추천 한 건이 네트워크를
    세 번 왕복한다. 세 `tech_id` 를 한 질의로 묻는다.
    """
    unique = tuple(dict.fromkeys(tech_ids))
    if not unique:
        return None
    if len(unique) > MAX_TIEBREAK_TECH_IDS:
        raise ValueError("trend tie-break reads at most three technologies")
    if period is None:
        available = store.get_trend_periods(
            source=TREND_SOURCE, granularity=TREND_GRANULARITY
        )
        if not available:
            return None
        period = available[-1]
    values = store.get_trend_values(
        source=TREND_SOURCE,
        granularity=TREND_GRANULARITY,
        period=period,
        tech_ids=unique,
    )
    if not values:
        return None
    return TrendBasis(
        source=TREND_SOURCE,
        granularity=TREND_GRANULARITY,
        period=period,
        values=dict(sorted(values.items())),
    )
