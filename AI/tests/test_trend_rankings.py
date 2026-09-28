"""A period's ranking comes from the whole Registry, not from the caller's list.

"이 기간에 많이 관측된 기술"은 모집단 전체를 봐야 나오는 답이다. 부르는 쪽이 기술을
지정하면 그 답은 "내가 고른 것들 중의 순위"가 되고, 그것은 다른 질문이다. 그래서 이
endpoint 는 `tech_id` 를 받지 않는다.

숫자는 이미 저장돼 있다. 여기서 확인하는 것은 계산이 아니라 **어느 head 를 기술의
대표로 고르는가**와 **어떤 행이 순위에 오르는가**다.
"""

from fastapi.testclient import TestClient
from test_compute_api import PREFIX, REGISTRY, TOKEN

from worker.api import create_compute_app

SOURCE = "GITHUB_GH_ARCHIVE"


class RankingStore:
    """읽기 메서드만 노출한다 — 순위 조회가 쓰기를 숨길 수 없게."""

    def __init__(self, rows, periods=("2026-08",)):
        self.rows = rows
        self.periods = list(periods)
        self.calls = []
        self.period_calls = []

    def get_trend_periods(self, *, source, granularity):
        self.period_calls.append({"source": source, "granularity": granularity})
        return self.periods

    def get_trend_rankings(self, *, source, granularity, period, limit):
        self.calls.append(
            {
                "source": source,
                "granularity": granularity,
                "period": period,
                "limit": limit,
            }
        )
        return self.rows


def client(store):
    app = create_compute_app(store=store, token=TOKEN, registry=REGISTRY)
    return TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"})


def rows(*pairs, denominator=4045):
    return [
        {
            "tech_id": tech_id,
            "value": value,
            "denominator": denominator,
            "data_status": status,
        }
        for tech_id, value, status in pairs
    ]


def ranking(store, **params):
    query = {
        "source": SOURCE,
        "granularity": "MONTH",
        "period": "2026-08",
        **params,
    }
    with client(store) as http:
        response = http.get(PREFIX + "/trends/rankings", params=query)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_ranking_needs_no_technology_list_from_the_caller():
    store = RankingStore(rows(("python", 10, "READY")))

    data = ranking(store)

    assert store.calls == [
        {
            "source": SOURCE,
            "granularity": "MONTH",
            "period": "2026-08",
            "limit": 10,
        }
    ]
    assert data["technology_population"] == len(REGISTRY.technologies)


def test_rank_follows_the_stored_value_order():
    store = RankingStore(
        rows(("html", 2402, "INSUFFICIENT_DATA"), ("css", 1732, "READY"))
    )

    data = ranking(store)

    assert [(item["tech_id"], item["rank"]) for item in data["technologies"]] == [
        ("html", 1),
        ("css", 2),
    ]
    assert [item["value"] for item in data["technologies"]] == [2402, 1732]


def test_a_thin_sample_keeps_its_verdict_and_its_place():
    """S15P21E102-327: 값이 있으면 순위에 오르고 상태는 그대로 실려 간다."""
    store = RankingStore(rows(("html", 5, "INSUFFICIENT_DATA")))

    data = ranking(store)

    assert data["technologies"][0]["data_status"] == "INSUFFICIENT_DATA"
    assert data["technologies"][0]["rank"] == 1


def test_display_name_comes_from_the_registry():
    known = REGISTRY.technologies[0]
    store = RankingStore(
        rows((known.tech_id, 1, "READY"), ("not-in-registry", 0, "READY"))
    )

    data = ranking(store)

    assert data["technologies"][0]["display_name"] == known.display_name
    # 모르는 기술의 이름을 지어내지 않는다.
    assert data["technologies"][1]["display_name"] is None


def test_week_is_the_same_endpoint_with_another_granularity():
    store = RankingStore(rows(("javascript", 153_682, "INSUFFICIENT_DATA")))

    store.periods = ["2026-09-07"]
    data = ranking(store, granularity="WEEK", period="2026-09-07")

    assert data["granularity"] == "WEEK"
    assert data["period"] == "2026-09-07"
    assert store.calls[0]["granularity"] == "WEEK"


def test_limit_is_passed_through_and_bounded():
    store = RankingStore(rows(("python", 1, "READY")))

    ranking(store, limit=25)
    assert store.calls[0]["limit"] == 25

    with client(store) as http:
        too_many = http.get(
            PREFIX + "/trends/rankings",
            params={
                "source": SOURCE,
                "granularity": "MONTH",
                "period": "2026-08",
                "limit": 999,
            },
        )
    assert too_many.status_code == 422


def test_an_unknown_source_is_refused_before_any_read():
    store = RankingStore(rows())

    with client(store) as http:
        response = http.get(
            PREFIX + "/trends/rankings",
            params={
                "source": "WEEKLY_REPO_ACTIVITY",
                "granularity": "WEEK",
                "period": "2026-09-07",
            },
        )

    assert response.status_code == 422
    assert store.calls == []


def test_a_period_with_nothing_stored_is_an_empty_ranking_not_an_error():
    """게시되지 않은 기간은 오류가 아니다 — 카드가 사라지면 안 된다."""
    store = RankingStore(rows())

    data = ranking(store, period="2020-01")

    assert data["technologies"] == []
    assert data["sample_repo_count"] is None
    # 갈 수 있는 곳은 그대로 알려 준다. 모르면 화면이 되돌아올 수 없다.
    assert data["available_periods"] == ["2026-08"]
    # 저장되지 않은 기간을 순위로 묻지 않는다.
    assert store.calls == []


def test_a_missing_period_means_the_newest_one_the_source_published():
    """달력으로 최근 주차를 계산하면 게시되지 않은 주를 묻게 된다."""
    store = RankingStore(
        rows(("javascript", 2323, "INSUFFICIENT_DATA")),
        periods=["2026-03-02", "2026-08-31", "2026-09-07"],
    )

    with client(store) as http:
        response = http.get(
            PREFIX + "/trends/rankings",
            params={"source": SOURCE, "granularity": "WEEK"},
        )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["period"] == "2026-09-07"
    assert store.period_calls == [{"source": SOURCE, "granularity": "WEEK"}]
    assert store.calls[0]["period"] == "2026-09-07"


def test_available_periods_are_oldest_first_so_the_card_can_step_back():
    """S15P21E102-329: 카드가 `periods[index - 1]`을 이전으로 읽는다."""
    store = RankingStore(
        rows(("python", 2434, "INSUFFICIENT_DATA")),
        periods=["2026-03-02", "2026-08-31", "2026-09-07"],
    )

    data = ranking(store, granularity="WEEK", period="2026-08-31")

    assert data["available_periods"] == ["2026-03-02", "2026-08-31", "2026-09-07"]
    # 기본 선택이 아니라 물어본 기간을 그대로 읽는다.
    assert data["period"] == "2026-08-31"


def test_the_denominator_rides_along_so_a_count_can_be_read_as_a_share():
    """주차마다 코호트가 달라(4,045 vs 133) raw count 는 기간끼리 비교할 수 없다."""
    store = RankingStore(rows(("python", 2434, "INSUFFICIENT_DATA"), denominator=4045))

    data = ranking(store)

    assert data["sample_repo_count"] == 4045
    assert data["unit"] == "REPOSITORIES"
    # 비율을 서버가 새 metric 으로 만들어 내지 않는다.
    assert "ratio" not in data["technologies"][0]


def test_a_source_that_published_nothing_returns_an_empty_ranking():
    store = RankingStore(rows(), periods=[])

    with client(store) as http:
        response = http.get(
            PREFIX + "/trends/rankings",
            params={"source": SOURCE, "granularity": "WEEK"},
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["period"] is None
    assert data["available_periods"] == []
    assert data["technologies"] == []
    # 기간을 모르면 순위를 묻지 않는다.
    assert store.calls == []
