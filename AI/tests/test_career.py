"""커리어 collector tests.

The fixture markup mirrors the live structure verified on 2026-09-09: a
listing table of five `td` columns whose last three hold two same-class
`span.itx` values each, a detail page of `span.lb` label rows, and a body in
`div.jp_content` with template classes nested inside it.

Three of these cases exist because the site actively invites the wrong
reading — see `test_ad_slot_links_outside_a_row_are_not_postings`,
`test_body_is_not_duplicated_by_the_nested_template_classes` and
`test_application_start_is_not_stored_as_the_registration_date`.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from Career_Collector_V1.crawler import (
    CATEGORY_PRESETS,
    JOB_CATEGORIES,
    LIST_PATH,
    SOURCE_SITE,
    CareerCrawler,
    CrawlConfig,
    Cursor,
    _categories,
    write_outputs,
)
from Career_Collector_V1.dates import (
    is_open_ended_deadline,
    parse_deadline,
    parse_listing_posted_on,
)
from Career_Collector_V1.parser import (
    listing_date_labels,
    parse_detail,
    parse_job_list,
    posting_id_from_ref,
)

SEOUL = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 9, 9, 12, 0, tzinfo=SEOUL)


def _row(
    posting_id: str,
    *,
    company: str = "(주)테스트",
    title: str = "백엔드 개발자",
    categories: tuple[str, ...] = ("#응용프로그래머", "#서버.보안.네트워크.DB"),
    career: str = "경력 3년",
    education: str = "학력무관",
    employment: str = "정규직",
    region: str = "서울 강남구",
    deadline: str = "상시채용",
    registration: str = "(2026-09-08 등록)",
) -> str:
    tags = "".join(f'<span class="otNm">{tag}</span>' for tag in categories)
    return f"""
    <tr>
      <td><div class="cttCkNm txsArea"><div class="txtBx"><div class="tpNm">
        <div class="tx">{company}</div>
      </div></div></div></td>
      <td><div class="cttCntArea"><div class="txtBx"><div class="tpNm">
        <a href="/recruit/view/{posting_id}" class="tx">{title}</a>
      </div><div class="otNmArea">{tags}</div></div></div></td>
      <td>
        <div class="txsArea"><span class="itx">{career}</span></div>
        <div class="txsArea"><span class="itx">{education}</span></div>
      </td>
      <td>
        <div class="txsArea"><span class="itx">{employment}</span></div>
        <div class="txsArea"><span class="itx">{region}</span></div>
      </td>
      <td>
        <a class="cttBtns">홈페이지 지원</a>
        <div class="MT05 txsArea"><span class="itx">{deadline}</span></div>
        <div class="txsArea"><span class="cgray itx">{registration}</span></div>
      </td>
    </tr>
    """


def _list_page(*rows: str, banners: str = "") -> str:
    return f"""
    <html><body>
      {banners}
      <table><thead><tr>
        <th>회사명</th><th>채용제목</th><th>지원자격</th>
        <th>근무조건</th><th>마감일/등록일</th>
      </tr></thead><tbody>{"".join(rows)}</tbody></table>
    </body></html>
    """


# The shape of page 9 of H0: rotating banner links and no table rows.
BANNER_ONLY_PAGE = _list_page(
    banners="""
    <div class="bnrArea">
      <a href="/recruit/view/99990001">추천 공고</a>
      <a href="/recruit/view/99990002">프리미엄 공고</a>
    </div>
    """
)

DETAIL_HTML = """
<html><body>
  <div class="rcInfCont"><div class="ricInner"><div class="lsts">
    <div class="pls tps"><span class="lb">경력</span>
      <span class="vl"><div class="rdd">경력(3년 이상)</div></span></div>
    <div class="tps"><span class="lb">근무형태</span>
      <span class="vl"><div class="rdd">정규직</div></span></div>
    <div class="pls tps"><span class="lb">학력</span>
      <span class="vl"><div class="rdd">학력무관</div></span></div>
    <div class="tps"><span class="lb">근무지역</span>
      <span class="vl">서울 관악구 <a class="lcbtn map"><span class="lbtx">지도보기</span></a></span></div>
  </div></div></div>
  <div class="clst">
    <div class="tps"><span class="lb">시작일</span>
      <div class="po tx">2026.07.02 13:00</div></div>
    <div class="tps"><span class="lb">마감일</span>
      <div class="po tx">상시채용</div></div>
  </div>
  <div class="jp_content">
    <div class="org_desc">회사 소개 문단입니다.</div>
    <div class="role_desc">담당업무는 Django 서버 개발입니다.</div>
    <div class="role_desc">자격요건: PostgreSQL 경험</div>
    <div class="etc_desc">우대사항: Kubernetes</div>
  </div>
</body></html>
"""


class FakeClient:
    """Records every requested path, so the run's request shape is assertable."""

    def __init__(
        self,
        pages_by_category: dict[str, list[str]],
        detail_html: str = DETAIL_HTML,
        *,
        base_url: str = "https://job.career.co.kr",
    ) -> None:
        self.pages_by_category = pages_by_category
        self.detail_html = detail_html
        self.base_url = base_url
        self.requests: list[str] = []

    def absolute(self, url_or_path: str) -> str:
        return f"{self.base_url}{url_or_path}"

    def get(self, url_or_path, params=None, *, referer=None, delay_seconds=0.0):
        self.requests.append(url_or_path)
        if url_or_path == LIST_PATH:
            category, page = "", 1
            for key, value in params or ():
                if key == "i_jc1":
                    category = value
                elif key == "page":
                    page = int(value)
            pages = self.pages_by_category.get(category, [])
            index = page - 1
            return pages[index] if index < len(pages) else BANNER_ONLY_PAGE
        return self.detail_html


def _config(tmp_path: Path | None = None, **overrides) -> CrawlConfig:
    values: dict = {
        "start_date": date(2026, 9, 1),
        "end_date": date(2026, 9, 9),
        "categories": ("H0",),
        "max_pages": 5,
        "request_delay": 0.0,
        "now": NOW,
    }
    if tmp_path is not None:
        values["cursor_path"] = tmp_path / "cursor.json"
    values.update(overrides)
    return CrawlConfig(**values)


# --- the listing traps -------------------------------------------------------


def test_ad_slot_links_outside_a_row_are_not_postings():
    """Banner links must not be read as postings, or a run never ends.

    Measured 2026-09-09: page 1 of H0 carried 68 `/recruit/view/` links against
    30 real rows, and pages 9 through 12 carried two each against none. The
    banner ids rotate, so a run that counted links kept finding "new" postings
    forever and the listing had no end.
    """

    assert parse_job_list(BANNER_ONLY_PAGE, now=NOW) == []


def test_a_page_of_rows_ends_the_run_when_the_next_one_is_banners_only():
    client = FakeClient({"H0": [_list_page(_row("111"), _row("222"))]})
    result = CareerCrawler(_config(), client=client).run()

    assert result.manifest["counts"]["records"] == 2
    # Page 2 falls through to the banner-only page, so exactly two list
    # requests happen and the third page is never asked for.
    assert client.requests.count(LIST_PATH) == 2
    assert result.manifest["stopped_reason"] is None


def test_compound_employment_type_is_not_stored_as_the_region():
    """"정규직, 프리랜서, 계약직" is not a place.

    근무조건 holds an employment type and a region in two `span.itx` with no
    class between them, so each is identified by content. The comma-separated
    form arrives with a space after each separator; before the parts were
    stripped, none matched the employment list and the whole value was stored
    as the region. Caught on a live run, 2026-09-09.
    """

    rows = parse_job_list(
        _list_page(_row("1", employment="정규직", region="정규직, 프리랜서, 계약직")),
        now=NOW,
    )

    assert rows[0].region is None


@pytest.mark.parametrize(
    ("career", "education", "expected"),
    [
        ("경력 3년", "학력무관", "경력 3년"),
        ("경력무관", "대졸(4년)↑", "경력무관"),
        ("신입", "학력무관", "신입"),
        # The site's own wording for "경력구분 무관, 년수 무관".
        ("무관 년수무관", "고졸↑", "무관 년수무관"),
    ],
)
def test_career_level_is_taken_over_the_education_column(career, education, expected):
    rows = parse_job_list(
        _list_page(_row("1", career=career, education=education)), now=NOW
    )

    assert rows[0].career_level == expected


def test_site_category_tags_are_kept_as_the_site_wrote_them():
    """Employer-chosen tags, broad and multiple, so they are text not a filter.

    One measured Product Owner posting carried 웹프로그래머, 응용프로그래머 and
    서버.보안.네트워크.DB. The server-side `i_jc1` 대분류 does the narrowing.
    """

    rows = parse_job_list(
        _list_page(_row("1", categories=("#웹프로그래머", "#응용프로그래머"))),
        now=NOW,
    )

    assert rows[0].raw_job_category == "#웹프로그래머 #응용프로그래머"


def test_posting_id_comes_from_the_detail_href():
    assert posting_id_from_ref("/recruit/view/22039272") == "22039272"
    assert posting_id_from_ref("/jobs/jobpart") is None
    assert posting_id_from_ref("") is None


# --- dates -------------------------------------------------------------------


def test_absolute_registration_carries_its_own_year():
    parsed = parse_listing_posted_on("(2026-07-02 등록)", now=NOW)

    assert parsed == (date(2026, 7, 2), "등록")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # NOW is 12:00, so 13 hours back crosses midnight into the 8th.
        ("(13시간 전 등록)", date(2026, 9, 8)),
        ("(6일 전 등록)", date(2026, 9, 3)),
        ("(30분 전 등록)", date(2026, 9, 9)),
    ],
)
def test_relative_registration_resolves_against_now(text, expected):
    parsed = parse_listing_posted_on(text, now=NOW)

    assert parsed is not None
    assert parsed[0] == expected


def test_modification_label_is_reported_not_disguised():
    parsed = parse_listing_posted_on("(2026-07-02 수정)", now=NOW)

    assert parsed == (date(2026, 7, 2), "수정")
    labels = listing_date_labels(
        _list_page(_row("1", registration="(2026-07-02 수정)")), now=NOW
    )
    assert labels == ["수정"]


def test_open_ended_deadline_never_becomes_a_date():
    """상시채용 was 24 of 30 rows on a measured page.

    Parsing it as a date would mark an open posting CLOSED.
    """

    assert is_open_ended_deadline("상시채용")
    assert parse_deadline("상시채용", today=date(2026, 9, 9)) is None


def test_short_deadline_infers_the_year_forward():
    assert parse_deadline("~10/01(목)", today=date(2026, 9, 9)) == date(2026, 10, 1)
    # A live listing showing 01/15 in December means next January.
    assert parse_deadline("~01/15", today=date(2026, 12, 20)) == date(2027, 1, 15)


def test_undated_rows_are_skipped_not_guessed():
    """No server-side date filter, so an undated row cannot be assumed in range."""

    client = FakeClient({"H0": [_list_page(_row("1", registration="등록일 미표기"))]})
    result = CareerCrawler(_config(), client=client).run()

    assert result.manifest["counts"]["records"] == 0
    assert result.manifest["counts"]["skipped_undated"] == 1


def test_out_of_range_rows_do_not_end_the_run():
    """The listing is not ordered by registration date.

    Measured 2026-09-09: page 2 of H0 held postings from 2026-06-15 while
    page 1 held newer ones. An early stop on an out-of-range page would drop
    everything behind it.
    """

    page = _list_page(
        _row("1001", registration="(2026-06-15 등록)"),
        _row("1002", registration="(2026-09-08 등록)"),
    )
    client = FakeClient({"H0": [page]})
    result = CareerCrawler(_config(), client=client).run()

    assert result.manifest["counts"]["records"] == 1
    assert result.manifest["counts"]["skipped_out_of_range"] == 1
    assert result.batch.records[0].source_posting_id == "1002"


# --- the detail page ---------------------------------------------------------


def test_body_is_not_duplicated_by_the_nested_template_classes():
    """`role_desc` and friends nest inside `jp_content` and repeat.

    They look like section containers and are not: one measured `role_desc`
    held "보상 연봉 : ...". Reading them as sections would double the body and
    label it wrongly, so only `jp_content` is read.
    """

    detail = parse_detail(DETAIL_HTML)

    assert detail.description_text is not None
    assert detail.description_text.count("Django") == 1
    assert detail.description_text.count("회사 소개 문단입니다.") == 1


def test_application_start_is_not_stored_as_the_registration_date():
    """시작일 is the application window opening, not 등록일.

    `normalize._posted_at_for` prefers a detail timestamp over the listing
    column, so promoting 시작일 would store an application date as a
    registration date for every posting scheduled ahead of time — the failure
    S15P21E102-148 recorded.
    """

    detail = parse_detail(DETAIL_HTML)

    assert detail.posted_at is None
    assert "시작일" in detail.section_names


def test_detail_labels_are_read_across_both_value_shapes():
    """`rcInfCont` wraps values in `span.vl`; `clst` uses `div.po`."""

    detail = parse_detail(DETAIL_HTML)

    assert detail.career_level == "경력(3년 이상)"
    assert detail.deadline_label == "상시채용"


def test_map_button_is_stripped_from_the_region():
    detail = parse_detail(DETAIL_HTML)

    assert detail.region == "서울 관악구"


def test_unexpected_markup_does_not_raise():
    """A parser that raises loses the row entirely (interface docstring)."""

    detail = parse_detail("<html><body><div>nothing familiar</div></body></html>")

    assert detail.description_text is None
    assert detail.career_level is None


# --- the run -----------------------------------------------------------------


def test_records_reach_the_contract_with_the_detail_body():
    client = FakeClient({"H0": [_list_page(_row("22039272"))]})
    result = CareerCrawler(_config(), client=client).run()

    assert len(result.batch.records) == 1
    record = result.batch.records[0]
    assert record.source_site == SOURCE_SITE
    assert record.source_posting_id == "22039272"
    assert str(record.source_url).endswith("/recruit/view/22039272")
    assert record.body_status.value == "TEXT_AVAILABLE"
    # The detail body carries them; the site's 직종 tags do not become
    # technology mentions.
    mentions = {mention.source_technology_id for mention in record.technology_mentions}
    assert "django" in {value.lower() for value in mentions if value}


def test_a_posting_in_two_categories_is_fetched_once():
    """A posting tagged into both 대분류 appears in both listings."""

    shared = _list_page(_row("2001"))
    client = FakeClient({"H0": [shared], "N0": [shared]})
    result = CareerCrawler(_config(categories=("H0", "N0")), client=client).run()

    assert result.manifest["counts"]["records"] == 1
    assert result.manifest["counts"]["distinct_postings_seen"] == 1
    assert result.manifest["counts"]["duplicate_rows"] == 1
    assert client.requests.count("/recruit/view/2001") == 1


def test_manifest_records_why_the_source_was_admitted():
    """기준 A 미통과 must travel with every batch, not only in a doc."""

    client = FakeClient({"H0": [_list_page(_row("1"))]})
    result = CareerCrawler(_config(), client=client).run()

    admission = result.manifest["source_admission"]
    assert admission["criterion_a"] == "FAIL"
    assert "제14조" in admission["terms_clause"]
    assert admission["admitted_by"]


def test_rows_seen_and_distinct_postings_are_both_reported():
    """`rows_seen` counts rows; reading it as postings overstates coverage."""

    client = FakeClient({"H0": [_list_page(_row("1"), _row("2"))]})
    result = CareerCrawler(_config(), client=client).run()

    counts = result.manifest["counts"]
    assert counts["rows_seen"] == 2
    assert counts["distinct_postings_seen"] == 2
    assert counts["pages_by_category"] == {"H0": 2}


# --- resume ------------------------------------------------------------------


def test_run_alone_does_not_persist_the_cursor(tmp_path: Path):
    """S15P21E102-174: the cursor must not claim unwritten postings.

    A cursor saved during the crawl marks postings collected while the batch
    is still in memory. An interrupted run then loses them permanently,
    because a resume trusts the cursor and skips them silently.
    """

    client = FakeClient({"H0": [_list_page(_row("1"))]})
    config = _config(tmp_path)
    result = CareerCrawler(config, client=client).run()

    assert result.manifest["counts"]["records"] == 1
    assert not config.cursor_path.exists()

    write_outputs(result, tmp_path / "out")
    assert config.cursor_path.exists()
    saved = json.loads(config.cursor_path.read_text(encoding="utf-8"))
    assert saved["collected_ids"] == ["1"]


def test_a_resumed_id_is_skipped(tmp_path: Path):
    config = _config(tmp_path)
    Cursor(
        start_date=config.start_date.isoformat(),
        end_date=config.end_date.isoformat(),
        collected_ids=["1"],
    ).save(config.cursor_path)

    client = FakeClient({"H0": [_list_page(_row("1"), _row("2"))]})
    result = CareerCrawler(config, client=client).run()

    assert result.manifest["counts"]["skipped_already_collected"] == 1
    assert [r.source_posting_id for r in result.batch.records] == ["2"]


def test_a_cursor_for_a_different_range_is_discarded(tmp_path: Path):
    config = _config(tmp_path)
    Cursor(start_date="2020-01-01", end_date="2020-01-02", collected_ids=["1"]).save(
        config.cursor_path
    )

    loaded = Cursor.load(config.cursor_path, config)

    assert loaded.collected_ids == []


# --- configuration -----------------------------------------------------------


def test_dev_preset_covers_both_developer_categories():
    """R&D and embedded roles sit under 연구개발.엔지니어, not IT.인터넷."""

    assert CATEGORY_PRESETS["dev"] == ("H0", "N0")
    assert _categories(None, "dev") == ("H0", "N0")
    assert _categories("H0", "dev") == ("H0", "N0")
    assert _categories("i0", None) == ("I0",)


def test_an_unknown_category_is_refused():
    with pytest.raises(ValueError, match="unknown 직종 대분류"):
        _config(categories=("ZZ",))


def test_every_declared_category_has_a_name():
    for preset in CATEGORY_PRESETS.values():
        for code in preset:
            assert code in JOB_CATEGORIES


def test_a_reversed_date_range_is_refused():
    with pytest.raises(ValueError, match="end_date must not precede"):
        _config(start_date=date(2026, 9, 9), end_date=date(2026, 9, 1))
