"""게임잡 collector tests.

The fixture markup mirrors the live listing and detail structure verified on
2026-09-08: one `tr` per posting with the id in the title link's `GI_No`
parameter and 모집분야 only inside the link's tracking call, a detail page of
`dl.recruit-data-item` label rows, and the posting body behind iframes.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from GameJob_Collector_V1.crawler import (
    LIST_PATH,
    SOURCE_SITE,
    CrawlConfig,
    Cursor,
    GameJobCrawler,
    _duty_tokens,
    write_outputs,
)
from GameJob_Collector_V1.dates import (
    is_open_ended_deadline,
    parse_deadline,
    parse_detail_timestamps,
    parse_listing_posted_on,
)
from GameJob_Collector_V1.duties import (
    DUTY_PRESETS,
    matches_preset,
    normalize_duty_text,
    resolve_duty_preset,
)
from GameJob_Collector_V1.parser import (
    body_iframe_refs,
    detail_path,
    parse_body_fragment,
    parse_detail,
    parse_job_list,
)
from job.collector.http import BlockedError, HttpError
from job.contracts import BodyStatus, JobAnalysisInputBatch, PostingStatus

BASE_URL = "https://www.gamejob.co.kr"
SEOUL = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 9, 8, 15, 0, tzinfo=SEOUL)
TODAY = date(2026, 9, 8)


def _row(
    posting_id: str,
    title: str,
    company: str,
    *,
    duty: str = "게임개발(클라이언트), 시스템&#183;DB",
    career: str = "경력무관",
    region: str = "경기 &gt; 성남시",
    deadline: str = "채용시",
    registered: str = "09/08(화) 등록",
) -> str:
    return f"""
    <tr>
      <td>
        <div class="company noLogo">
          <a href="/Company/Detail?tabcode=1&amp;M=11525476" target="_blank">
            <strong>{company}</strong>
          </a>
        </div>
      </td>
      <td>
        <div class="tit">
          <a href="/Recruit/GI_Read/View?GI_No={posting_id}" onclick="GA_Application_Prdt('02_공고클릭', 'N', '{title}', '{posting_id}', '{company}', '없음', IsNullOrWhiteSpace('{duty}'), IsNullOrWhiteSpace('온라인PC게임'), '없음', IsNullOrWhiteSpace('{region}'));" target="_blank"><strong>{title}</strong></a>
          <button type="button" class="btnScrap btnScrap_{posting_id}" title="채용공고 스크랩">채용공고 스크랩</button>
          <p class="info">
            <span>{career}</span>
            <span>학력무관</span>
            <span>{region}</span>
            <span>온라인PC게임, 모바일게임</span>
            <span>정규직, 계약직</span>
          </p>
        </div>
      </td>
      <td><span class="date">{deadline}</span><span class="modifyDate">{registered}</span></td>
    </tr>
    """


def _list_html(*rows: str) -> str:
    return f"""
    <html><body>
      <table class="tblList">
        <thead><tr><th>기업명</th><th>채용공고</th><th>마감일</th></tr></thead>
        <tbody>{"".join(rows)}</tbody>
      </table>
      <div class="pagination"><div class="inner">
        <span class="btn now">1</span>
        <a href="/recruit/_GI_Job_List?Page=2" data-page="2" class="btn">2</a>
      </div></div>
    </body></html>
    """


LIST_HTML = _list_html(
    _row("282335", "Unity 클라이언트 개발자", "(주)웹젠"),
    _row(
        "284727",
        "게임 서버 개발자",
        "㈜컨트롤나인",
        duty="게임개발(모바일), 서버",
        career="경력 3년↑",
        deadline="~11/08",
        registered="3시간 전 등록",
    ),
    _row(
        "284478",
        "배경 컨셉 아티스트",
        "㈜매드엔진",
        duty="원화, 애니메이션",
        registered="6일 전 등록",
    ),
    _row("284100", "예전 공고", "오래된회사", registered="07/28(화) 등록"),
    _row("284101", "날짜없는 공고", "무날짜회사", registered=""),
    _row("284102", "수정일만 있는 공고", "수정회사", registered="09/08(화) 수정"),
    _row(
        "284103",
        "모집분야 없는 공고",
        "미표기회사",
        duty="없음",
    ),
)


def _detail_html(
    posting_id: str = "282335",
    *,
    duty: str = "게임개발(클라이언트), 시스템&#183;DB",
    deadline: str = "채용시 마감",
    registered: str = "2026-09-08 17:07 등록",
    updated: str = "2026-09-08 14:02 수정",
) -> str:
    return f"""
    <html><body>
      <div class="summary-box">
        <article class="recruit-data flex item-center flex-wrap">
          <dl class="recruit-data-item flex align-item">
            <dt class="recruit-data-title">모집분야</dt>
            <dd class="recruit-data-text">{duty}</dd>
            <div class="tooltip-content-box">
              <button type="button" class="tooltip-trigger">툴팁기능</button>
              <div class="tooltip-content hide">{duty}
                <button type="button" class="tooltip-close">툴팁닫기</button>
              </div>
            </div>
          </dl>
          <dl class="recruit-data-item flex align-item">
            <dt class="recruit-data-title">키워드</dt>
            <dd class="recruit-data-text">서버, Unity, MS-SQL, 게임프로그래밍</dd>
          </dl>
          <dl class="recruit-data-item flex align-item">
            <dt class="recruit-data-title">경력</dt>
            <dd class="recruit-data-text">경력 3년↑</dd>
          </dl>
          <dl class="recruit-data-item flex align-item">
            <dt class="recruit-data-title">학력</dt>
            <dd class="recruit-data-text">학력무관</dd>
          </dl>
          <dl class="recruit-data-item flex align-item">
            <dt class="recruit-data-title">고용형태</dt>
            <dd class="recruit-data-text">정규직</dd>
          </dl>
          <dl class="recruit-data-item flex align-item">
            <dt class="recruit-data-title">마감일</dt>
            <dd class="recruit-data-text">{deadline}</dd>
          </dl>
          <div class="recruit-data-ddyytt flex align-item">
            <p class="date">{registered}</p><p class="date">{updated}</p>
          </div>
        </article>
      </div>
      <section id="gj-tab01">
        <article class="section-inner flex direction-col">
          <div class="job-sub-section">
            <div class="job-sub-section__title">담당업무</div>
            <div class="job-sub-section__body"><div class="render-section">
              <iframe src="/Recruit/GI_Read_Comt_Ifrm?gno={posting_id}&amp;v1" title="담당업무"></iframe>
            </div></div>
          </div>
        </article>
        <article class="section-inner flex direction-col">
          <div class="job-sub-section">
            <div class="job-sub-section__title">자격조건</div>
            <div class="job-sub-section__body"><div class="render-section">
              <iframe src="/Recruit/GI_Read_GI_Comment_Ifrm?gno={posting_id}&amp;v1" title="자격요건"></iframe>
            </div></div>
          </div>
        </article>
        <article class="section-inner flex direction-col">
          <div class="job-sub-section">
            <div class="job-sub-section__title">근무지역</div>
            <div class="job-sub-section__body">서울 강남구 테헤란로 1</div>
          </div>
        </article>
        <article class="section-inner flex direction-col">
          <div class="job-sub-section">
            <div class="job-sub-section__title">기업정보 기업정보 상세보기</div>
            <div class="job-sub-section__body"><div class="render-section">
              <iframe src="/Corp/Profile_Ifrm?m=11525476" title="기업정보"></iframe>
            </div></div>
          </div>
        </article>
      </section>
    </body></html>
    """


DETAIL_HTML = _detail_html()

WORK_FRAGMENT = """
<html><head><title>채용공고 상세페이지</title>
<style>body,html { font-size: 16px; line-height: 28px; }</style></head>
<body class="giworkTable">
  <div class="recruit-wrap">
    <p>Unity 클라이언트 개발 및 유지보수</p>
    <p>사내 도구 개발</p>
  </div>
</body></html>
"""

REQUIREMENT_FRAGMENT = """
<html><head><style>body { font-size: 16px; }</style></head>
<body>
  <div class="recruit-wrap">
    <p>C# 3년 이상 필수</p>
    <p>Kafka, Spark 경험자 우대</p>
  </div>
</body></html>
"""

IMAGE_ONLY_FRAGMENT = """
<html><head><style>body { font-size: 16px; }</style></head>
<body>
  <div class="recruit-wrap">
    <img src="/pc/images/blank.gif">
    <img src="https://file.gamejob.co.kr/net/Help/NoticeImg/View?FN=Tong_1.jpg">
    <img src="https://file.gamejob.co.kr/net/Help/NoticeImg/View?FN=Tong_2.jpg">
  </div>
</body></html>
"""

EMPTY_FRAGMENT = """
<html><head><style>body { font-size: 16px; }</style></head><body></body></html>
"""


class FakeClient:
    """Records every path requested, so the robots rule can be asserted."""

    def __init__(
        self,
        list_pages: list[str],
        detail_html: str = DETAIL_HTML,
        *,
        work_fragment: str = WORK_FRAGMENT,
        requirement_fragment: str = REQUIREMENT_FRAGMENT,
        detail_error: Exception | None = None,
        list_error: Exception | None = None,
        list_error_on_page: int | None = None,
        fragment_error: Exception | None = None,
    ) -> None:
        self.list_pages = list_pages
        self.detail_html = detail_html
        self.work_fragment = work_fragment
        self.requirement_fragment = requirement_fragment
        self.detail_error = detail_error
        self.list_error = list_error
        self.list_error_on_page = list_error_on_page
        self.fragment_error = fragment_error
        self.requests: list[str] = []

    def absolute(self, url_or_path: str) -> str:
        if url_or_path.startswith(("http://", "https://")):
            return url_or_path
        return f"{BASE_URL}{url_or_path}"

    def get(self, url_or_path, params=None, *, referer=None, delay_seconds=0.0):
        self.requests.append(url_or_path)
        if url_or_path == LIST_PATH:
            page = 1
            for key, value in params or ():
                if key == "Page":
                    page = int(value)
            if self.list_error_on_page == page and self.list_error is not None:
                raise self.list_error
            index = page - 1
            return self.list_pages[index] if index < len(self.list_pages) else ""
        if "GI_Read_Comt_Ifrm" in url_or_path:
            if self.fragment_error is not None:
                raise self.fragment_error
            return self.work_fragment
        if "GI_Read_GI_Comment_Ifrm" in url_or_path:
            if self.fragment_error is not None:
                raise self.fragment_error
            return self.requirement_fragment
        if self.detail_error is not None:
            raise self.detail_error
        return self.detail_html


def _config(**overrides) -> CrawlConfig:
    values: dict = {
        "start_date": TODAY,
        "end_date": TODAY,
        "max_pages": 1,
        "request_delay": 0.0,
        "base_url": BASE_URL,
        "now": NOW,
    }
    values.update(overrides)
    return CrawlConfig(**values)


# --- listing -----------------------------------------------------------------


def test_parse_job_list_reads_every_row():
    rows = parse_job_list(LIST_HTML, now=NOW)

    assert [row.source_posting_id for row in rows] == [
        "282335",
        "284727",
        "284478",
        "284100",
        "284101",
        "284102",
        "284103",
    ]
    first = rows[0]
    assert first.title == "Unity 클라이언트 개발자"
    assert first.company_name == "(주)웹젠"
    assert first.career_level == "경력무관"
    assert first.region == "경기 > 성남시"
    assert first.posted_on == date(2026, 9, 8)
    assert first.deadline_label == "채용시"
    assert first.detail_ref == "/Recruit/GI_Read/View?GI_No=282335"


def test_listing_reads_the_job_category_only_from_the_tracking_call():
    """`p.info` never prints 모집분야; the GA call is the only source."""

    rows = {row.source_posting_id: row for row in parse_job_list(LIST_HTML, now=NOW)}

    assert rows["282335"].raw_job_category == "게임개발(클라이언트), 시스템·DB"
    assert rows["284478"].raw_job_category == "원화, 애니메이션"
    # `없음` is the site's own placeholder and must not become a category.
    assert rows["284103"].raw_job_category is None


def test_relative_registration_dates_resolve_against_now():
    rows = {row.source_posting_id: row for row in parse_job_list(LIST_HTML, now=NOW)}

    assert rows["284727"].posted_on == date(2026, 9, 8)  # 3시간 전
    assert rows["284478"].posted_on == date(2026, 9, 2)  # 6일 전


def test_row_with_no_date_column_has_no_posted_on():
    rows = {row.source_posting_id: row for row in parse_job_list(LIST_HTML, now=NOW)}
    assert rows["284101"].posted_on is None


def test_banner_links_outside_a_row_are_not_collected():
    """The same posting is linked from promos; only `div.tit` is a row."""

    html = LIST_HTML.replace(
        "</tbody>",
        '</tbody><div class="banner">'
        '<a href="/Recruit/GI_Read/View?GI_No=999999">배너</a></div>',
    )
    assert "999999" not in {
        row.source_posting_id for row in parse_job_list(html, now=NOW)
    }


# --- dates -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected", "label"),
    [
        ("09/08(화) 등록", date(2026, 9, 8), "등록"),
        ("09/08(화) 수정", date(2026, 9, 8), "수정"),
        ("38분 전 등록", date(2026, 9, 8), "등록"),
        ("3시간 전 등록", date(2026, 9, 8), "등록"),
        ("6일 전 등록", date(2026, 9, 2), "등록"),
    ],
)
def test_parse_listing_posted_on(text, expected, label):
    assert parse_listing_posted_on(text, now=NOW) == (expected, label)


def test_registration_date_never_lands_in_the_future():
    """`12/28` seen in January is last December, not eleven months ahead."""

    january = datetime(2026, 1, 5, 9, 0, tzinfo=SEOUL)
    parsed = parse_listing_posted_on("12/28(일) 등록", now=january)

    assert parsed is not None
    assert parsed[0] == date(2025, 12, 28)


def test_deadline_infers_the_year_in_the_opposite_direction():
    """A deadline is generally ahead: `01/15` seen in December is next year."""

    assert parse_deadline("~01/15", today=date(2026, 12, 20)) == date(2027, 1, 15)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("~11/08", date(2026, 11, 8)),
        ("2026.07.15", date(2026, 7, 15)),
        ("채용시", None),
        ("채용시 마감", None),
        ("상시채용", None),
        ("진행예정", None),
        ("", None),
    ],
)
def test_parse_deadline(text, expected):
    assert parse_deadline(text, today=TODAY) == expected


def test_is_open_ended_deadline():
    assert is_open_ended_deadline("채용시 마감")
    assert not is_open_ended_deadline("~11/08")


def test_parse_detail_timestamps_keeps_both_labels():
    stamps = parse_detail_timestamps("2026-09-08 17:07 등록 2026-09-08 14:02 수정")

    assert stamps["등록"] == datetime(2026, 9, 8, 17, 7, tzinfo=SEOUL)
    assert stamps["수정"] == datetime(2026, 9, 8, 14, 2, tzinfo=SEOUL)


# --- detail ------------------------------------------------------------------


def test_parse_detail_reads_the_label_rows_once():
    detail = parse_detail(DETAIL_HTML)

    # The tooltip repeats every value; reading the whole `dl` would double it.
    assert detail.raw_job_category == "게임개발(클라이언트), 시스템·DB"
    assert detail.career_level == "경력 3년↑"
    assert detail.employment_type == "정규직"
    assert detail.education == "학력무관"
    assert detail.deadline_label == "채용시 마감"
    assert detail.region == "서울 강남구 테헤란로 1"


def test_parse_detail_uses_the_exact_registration_stamp():
    detail = parse_detail(DETAIL_HTML)

    assert detail.posted_at == datetime(2026, 9, 8, 17, 7, tzinfo=SEOUL)
    assert detail.updated_at == datetime(2026, 9, 8, 14, 2, tzinfo=SEOUL)


def test_parse_detail_returns_no_body_because_it_lives_in_iframes():
    assert parse_detail(DETAIL_HTML).description_text is None


def test_section_names_exclude_the_employer_sections():
    names = parse_detail(DETAIL_HTML).section_names

    assert "담당업무" in names
    assert "자격조건" in names
    assert not any("기업정보" in name for name in names)


def test_body_iframe_refs_skip_the_employer_iframe():
    refs = body_iframe_refs(DETAIL_HTML)

    assert [name for name, _ in refs] == ["담당업무", "자격조건"]
    assert all("Corp/Profile" not in src for _, src in refs)


def test_parse_body_fragment_drops_the_inline_stylesheet():
    """`html_tree` ignores `style`, which is why the shared tree is used."""

    text, images = parse_body_fragment(WORK_FRAGMENT)

    assert "Unity 클라이언트 개발" in text
    assert "font-size" not in text
    assert images == ()


def test_parse_body_fragment_skips_site_chrome_images():
    _, images = parse_body_fragment(IMAGE_ONLY_FRAGMENT)

    assert images == (
        "https://file.gamejob.co.kr/net/Help/NoticeImg/View?FN=Tong_1.jpg",
        "https://file.gamejob.co.kr/net/Help/NoticeImg/View?FN=Tong_2.jpg",
    )


# --- crawl -------------------------------------------------------------------


def test_run_collects_in_range_rows_and_stitches_the_body():
    client = FakeClient([LIST_HTML])
    result = GameJobCrawler(_config(), client).run()

    by_id = {record.source_posting_id: record for record in result.batch.records}
    assert "282335" in by_id
    record = by_id["282335"]
    assert record.source_record_id == "GAMEJOB:282335"
    assert record.source_site == SOURCE_SITE
    assert record.body_status is BodyStatus.TEXT_AVAILABLE
    # Both iframes, each labelled by its own heading.
    assert "담당업무" in record.description_text
    assert "Unity 클라이언트 개발" in record.description_text
    assert "자격조건" in record.description_text
    assert "C# 3년 이상 필수" in record.description_text


def test_out_of_range_rows_are_skipped_and_counted():
    result = GameJobCrawler(_config(), FakeClient([LIST_HTML])).run()

    collected = {record.source_posting_id for record in result.batch.records}
    assert "284478" not in collected  # 6일 전
    assert "284100" not in collected  # 07/28
    assert result.manifest["counts"]["skipped_out_of_range"] >= 2
    assert result.manifest["counts"]["skipped_undated"] == 1


def test_technology_mentions_come_from_the_body():
    result = GameJobCrawler(_config(), FakeClient([LIST_HTML])).run()
    record = next(r for r in result.batch.records if r.source_posting_id == "282335")

    mentions = {mention.source_technology_id for mention in record.technology_mentions}
    assert "kafka" in mentions


def test_site_keywords_are_counted_but_never_stored():
    """`SourceSurface` has no site-tag value, so 키워드 stops at the parser."""

    result = GameJobCrawler(_config(), FakeClient([LIST_HTML])).run()
    record = next(r for r in result.batch.records if r.source_posting_id == "282335")

    extraction = result.manifest["technology_extraction"]
    assert extraction["site_keyword_count"] > 0
    assert extraction["site_keywords_stored"] is False
    # `MS-SQL` is in the site's 키워드 row and in no posting body here.
    assert "MS-SQL" not in (record.description_text or "")


def test_image_only_body_is_recorded_with_an_absolute_artifact_uri():
    client = FakeClient(
        [LIST_HTML],
        work_fragment=IMAGE_ONLY_FRAGMENT,
        requirement_fragment=EMPTY_FRAGMENT,
    )
    result = GameJobCrawler(_config(), client).run()
    record = next(r for r in result.batch.records if r.source_posting_id == "282335")

    assert record.body_status is BodyStatus.IMAGE_ONLY
    assert record.raw_artifact_uri is not None
    assert record.raw_artifact_uri.startswith("https://file.gamejob.co.kr/")


def test_open_ended_deadline_is_active_not_closed():
    result = GameJobCrawler(_config(), FakeClient([LIST_HTML])).run()
    record = next(r for r in result.batch.records if r.source_posting_id == "282335")

    assert record.deadline is None
    assert record.posting_status is PostingStatus.ACTIVE


def test_posted_at_prefers_the_detail_stamp_over_the_listing_column():
    result = GameJobCrawler(_config(), FakeClient([LIST_HTML])).run()
    record = next(r for r in result.batch.records if r.source_posting_id == "282335")

    assert record.posted_at == datetime(2026, 9, 8, 17, 7, tzinfo=SEOUL)


def test_list_only_run_records_missing_body_and_asks_for_no_detail():
    client = FakeClient([LIST_HTML])
    result = GameJobCrawler(_config(fetch_detail=False), client).run()

    assert all(
        record.body_status is BodyStatus.MISSING for record in result.batch.records
    )
    assert all("GI_Read" not in request for request in client.requests)


def test_paging_does_not_stop_on_a_page_with_nothing_in_range():
    """The listing is not ordered by date, so an early stop would drop rows."""

    stale = _list_html(
        _row("284200", "오래된 공고", "옛회사", registered="07/28(화) 등록")
    )
    fresh = _list_html(_row("284201", "새 공고", "새회사"))
    client = FakeClient([stale, fresh])

    result = GameJobCrawler(_config(max_pages=2), client).run()

    assert result.manifest["counts"]["pages_read"] == 2
    assert "284201" in {r.source_posting_id for r in result.batch.records}


def test_paging_stops_when_the_listing_is_exhausted():
    client = FakeClient([LIST_HTML])
    result = GameJobCrawler(_config(max_pages=5), client).run()

    assert result.manifest["counts"]["pages_read"] == 2
    assert client.requests.count(LIST_PATH) == 2


def test_manifest_states_that_the_site_has_no_server_side_filtering():
    manifest = GameJobCrawler(_config(), FakeClient([LIST_HTML])).run().manifest
    assert manifest["request"]["server_side_filtering"] is False


# --- duty preset -------------------------------------------------------------


def test_duty_preset_skips_out_of_preset_rows_before_the_detail_fetch():
    client = FakeClient([LIST_HTML])
    config = _config(
        start_date=date(2026, 9, 2),
        duty_tokens=resolve_duty_preset("software"),
        duty_preset="software",
    )
    result = GameJobCrawler(config, client).run()

    collected = {record.source_posting_id for record in result.batch.records}
    # 원화·애니메이션 is art, not engineering.
    assert "284478" not in collected
    assert "282335" in collected
    assert result.manifest["counts"]["skipped_out_of_preset"] >= 1
    assert not any("GI_No=284478" in request for request in client.requests)


def test_row_with_unreadable_category_is_kept_not_dropped():
    """A dropped posting can never be collected again; a fetch only costs one."""

    client = FakeClient([LIST_HTML])
    config = _config(
        duty_tokens=resolve_duty_preset("software"),
        duty_preset="software",
    )
    result = GameJobCrawler(config, client).run()

    assert "284103" in {r.source_posting_id for r in result.batch.records}
    assert result.manifest["counts"]["kept_unknown_category"] >= 1


def test_no_preset_collects_every_duty():
    config = _config(start_date=date(2026, 9, 2))
    result = GameJobCrawler(config, FakeClient([LIST_HTML])).run()

    assert "284478" in {r.source_posting_id for r in result.batch.records}


def test_matches_preset_returns_none_when_the_row_says_nothing():
    assert matches_preset(None, ("게임개발",)) is None
    assert matches_preset("", ("게임개발",)) is None


def test_matches_preset_folds_the_middle_dot_variants():
    assert matches_preset("시스템ㆍDB", ("시스템·DB",)) is True
    assert normalize_duty_text("플랫폼 개발") == normalize_duty_text("플랫폼개발")


def test_resolve_duty_preset_rejects_an_unknown_name():
    with pytest.raises(ValueError, match="unknown duty preset"):
        resolve_duty_preset("nope")


def test_presets_are_nested_widest_last():
    assert set(DUTY_PRESETS["software"]) <= set(DUTY_PRESETS["dev"])
    assert set(DUTY_PRESETS["dev"]) <= set(DUTY_PRESETS["dev-extended"])


def test_duty_tokens_merges_preset_and_explicit_without_duplicates():
    tokens = _duty_tokens("서버,게임운영", "software")

    assert tokens.count("서버") == 1
    assert "게임운영" in tokens


# --- robots ------------------------------------------------------------------


@pytest.mark.parametrize(
    "disallowed",
    [
        "/List_GG/",
        "/Login/",
        "/User/",
        "/Text_User/",
        "/Text_Co/",
        "/Project/",
        "/Help/",
    ],
)
def test_no_disallowed_path_is_ever_requested(disallowed: str):
    client = FakeClient([LIST_HTML])
    GameJobCrawler(_config(), client).run()

    assert all(disallowed not in request for request in client.requests)


def test_the_listing_path_is_the_allowed_one():
    """`/List_Gi/` is allowed; `/List_GG/` is a one-letter-different Disallow."""

    assert LIST_PATH.startswith("/List_Gi/")
    assert detail_path("1").startswith("/Recruit/")


def test_manifest_records_the_robots_decision():
    manifest = GameJobCrawler(_config(), FakeClient([LIST_HTML])).run().manifest

    assert manifest["robots"]["list_path"] == LIST_PATH
    assert "/List_GG/" in manifest["robots"]["note"]


# --- failure handling --------------------------------------------------------


def test_a_block_on_the_listing_stops_the_site_and_is_reported():
    client = FakeClient(
        [LIST_HTML],
        list_error=BlockedError("block page served"),
        list_error_on_page=1,
    )
    result = GameJobCrawler(_config(), client).run()

    assert result.batch.records == ()
    assert "blocked" in result.manifest["stopped_reason"]


def test_a_detail_http_failure_becomes_a_blocked_body_not_a_lost_row():
    client = FakeClient([LIST_HTML], detail_error=HttpError("HTTP 500"))
    result = GameJobCrawler(_config(), client).run()

    record = next(r for r in result.batch.records if r.source_posting_id == "282335")
    assert record.body_status is BodyStatus.BLOCKED
    assert result.manifest["counts"]["detail_errors"] >= 1


def test_a_fragment_failure_with_no_text_is_reported():
    client = FakeClient([LIST_HTML], fragment_error=HttpError("HTTP 503"))
    result = GameJobCrawler(_config(), client).run()

    record = next(r for r in result.batch.records if r.source_posting_id == "282335")
    assert record.body_status is BodyStatus.BLOCKED
    assert result.manifest["counts"]["detail_errors"] >= 1


def test_a_parser_that_finds_nothing_yields_parse_failed():
    client = FakeClient(
        [LIST_HTML],
        detail_html="<html><body><p>완전히 다른 구조</p></body></html>",
    )
    result = GameJobCrawler(_config(), client).run()

    record = next(r for r in result.batch.records if r.source_posting_id == "282335")
    assert record.body_status is BodyStatus.PARSE_FAILED


def test_max_body_sections_caps_the_fragment_requests():
    client = FakeClient([LIST_HTML])
    GameJobCrawler(_config(max_body_sections=1), client).run()

    assert not any("GI_Read_GI_Comment_Ifrm" in r for r in client.requests)


# --- resume ------------------------------------------------------------------


def test_cursor_skips_ids_already_collected(tmp_path: Path):
    cursor_path = tmp_path / "cursor.json"
    config = _config(cursor_path=cursor_path)

    first = GameJobCrawler(config, FakeClient([LIST_HTML])).run()
    assert first.batch.records
    # `write_outputs` persists the cursor, not `run` (S15P21E102-174).
    write_outputs(first, tmp_path / "out")

    second_client = FakeClient([LIST_HTML])
    second = GameJobCrawler(config, second_client).run()

    assert second.batch.records == ()
    assert second.manifest["counts"]["skipped_already_collected"] >= 1
    assert not any("GI_No=282335" in r for r in second_client.requests)


def test_cursor_is_discarded_when_the_date_range_changes(tmp_path: Path):
    cursor_path = tmp_path / "cursor.json"
    cursor_path.write_text(
        json.dumps(
            {
                "start_date": "2020-01-01",
                "end_date": "2020-01-01",
                "collected_ids": ["282335"],
            }
        ),
        encoding="utf-8",
    )

    cursor = Cursor.load(cursor_path, _config(cursor_path=cursor_path))
    assert cursor.collected_ids == []


def test_unreadable_cursor_does_not_stop_a_run(tmp_path: Path):
    cursor_path = tmp_path / "cursor.json"
    cursor_path.write_text("{ not json", encoding="utf-8")

    assert (
        Cursor.load(cursor_path, _config(cursor_path=cursor_path)).collected_ids == []
    )


# --- outputs -----------------------------------------------------------------


def test_write_outputs_emits_a_valid_batch_and_manifest(tmp_path: Path):
    result = GameJobCrawler(_config(), FakeClient([LIST_HTML])).run()
    paths = write_outputs(result, tmp_path)

    batch = JobAnalysisInputBatch.model_validate_json(
        paths["json"].read_text(encoding="utf-8")
    )
    assert batch.collector_version == "gamejob-collector/v2"
    assert batch.pipeline_run_id.startswith("GAMEJOB-")

    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    assert manifest["source_site"] == SOURCE_SITE
    assert manifest["outputs"]["postings.csv"] == "postings.csv"

    header = paths["csv"].read_text(encoding="utf-8").splitlines()[0]
    assert header.startswith("source_record_id,source_site")


def test_listing_date_labels_are_reported():
    manifest = GameJobCrawler(_config(), FakeClient([LIST_HTML])).run().manifest
    labels = manifest["listing_date_labels"]

    assert labels["등록"] >= 1
    assert labels["수정"] == 1


# --- publishing is the scheduler's job, not this collector's -----------------
#
# S15P21E102-103 publishes `jobs.collected` from `job/collector/__main__.py`
# once a round's Raw upload succeeded, and the event is a Claim Check pointing
# at HDFS rather than carrying the postings. So this package has no Kafka code
# at all — but it does have to produce a run directory that the publisher can
# read. These pin that contract from the 게임잡 side.


def test_this_package_imports_no_publisher():
    """A per-crawler producer would duplicate S15P21E102-103's.

    Checked against imports and calls rather than the word "Kafka", which the
    crawler docstring uses to explain why publishing lives in the scheduler.
    """

    package = Path(__file__).resolve().parents[1] / "GameJob_Collector_V1"
    forbidden = (
        "import kafka",
        "from kafka",
        "event_sink",
        "publisher_from_env",
        "KafkaProducer",
        "CollectionEventPublisher",
    )
    for source in package.glob("*.py"):
        body = source.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in body, f"{source.name} references {token}"


def test_a_run_directory_can_be_published_by_the_scheduler(tmp_path: Path):
    """The publisher reads only what the run already wrote."""

    from job.collector.events import JOBS_TOPIC, build_collection_event
    from job.collector.schedule import RunOutcome, RunRecord

    result = GameJobCrawler(_config(), FakeClient([LIST_HTML])).run()
    paths = write_outputs(result, tmp_path)
    run_dir = paths["manifest"].parent

    # Stand in for the Raw sink: the publisher skips a round with no upload
    # record, which is what keeps an unarchived round off the topic.
    (run_dir / "raw_upload.json").write_text(
        json.dumps(
            {
                "run_path": f"/gitjob/raw/gamejob/dt=2026-09-08/{result.batch.pipeline_run_id}",
                "uploaded": [
                    "hdfs:///gitjob/raw/gamejob/dt=2026-09-08/x/manifest.json"
                ],
                "unchanged": [],
                "failed": [],
            }
        ),
        encoding="utf-8",
    )

    record = RunRecord(
        run_name="gamejob-morning",
        site=SOURCE_SITE,
        started_at="2026-09-08T06:00:00+00:00",
        finished_at="2026-09-08T06:05:00+00:00",
        status=RunOutcome.SUCCESS_WITH_DATA,
        records=len(result.batch.records),
        exit_code=0,
        pipeline_run_id=result.batch.pipeline_run_id,
        manifest_path=str(paths["manifest"]),
    )

    envelope, reason = build_collection_event(record, run_dir=run_dir)

    assert reason is None
    assert envelope is not None
    assert JOBS_TOPIC == "jobs.collected"
    assert envelope.source == "gamejob"
    assert envelope.payload["site"] == SOURCE_SITE
    assert envelope.payload["collector_version"] == "gamejob-collector/v2"
    assert envelope.payload["record_count"] == len(result.batch.records)
    assert envelope.payload["dataset_snapshot_id"].startswith("GAMEJOB-")


def test_an_unarchived_run_is_not_published(tmp_path: Path):
    """No `raw_upload.json` means the archive the event points at is absent."""

    from job.collector.events import build_collection_event
    from job.collector.schedule import RunOutcome, RunRecord

    result = GameJobCrawler(_config(), FakeClient([LIST_HTML])).run()
    paths = write_outputs(result, tmp_path)

    envelope, reason = build_collection_event(
        RunRecord(
            run_name="gamejob-morning",
            site=SOURCE_SITE,
            started_at="2026-09-08T06:00:00+00:00",
            finished_at="2026-09-08T06:05:00+00:00",
            status=RunOutcome.SUCCESS_WITH_DATA,
            records=len(result.batch.records),
            exit_code=0,
            pipeline_run_id=result.batch.pipeline_run_id,
            manifest_path=str(paths["manifest"]),
        ),
        run_dir=paths["manifest"].parent,
    )

    assert envelope is None
    assert "Raw" in reason


# --- paging that does not advance --------------------------------------------
#
# `GI_Total_List.asp` ignores `Page` along with every other query parameter:
# 80 pages returned 3,200 rows holding 40 distinct postings (2026-09-08). The
# run has to notice that and stop, or `--max-pages 10` spends nine requests a
# round on a site this collector is trying not to be blocked by.


def test_run_stops_once_a_page_adds_no_new_posting():
    """Rows keep arriving, but they are the same rows."""

    client = FakeClient([LIST_HTML] * 10)
    result = GameJobCrawler(_config(max_pages=10), client).run()

    # Page 1 collects, page 2 proves paging is inert, nothing further.
    assert result.manifest["counts"]["pages_read"] == 2
    assert client.requests.count(LIST_PATH) == 2


def test_an_inert_page_is_not_recorded_as_a_stop_reason():
    """Every 게임잡 run ends this way, so it must not look abnormal.

    `stopped_reason` travels into the run history and the `jobs.collected`
    payload, and `main` prints it to stderr. Marking a normal round as
    stopped would make the alerting signal useless.
    """

    result = GameJobCrawler(_config(max_pages=10), FakeClient([LIST_HTML] * 10)).run()

    assert result.manifest["stopped_reason"] is None
    assert result.manifest["request"]["paging_advances"] is False


def test_paging_continues_while_pages_bring_new_postings():
    """A real second page must not be mistaken for a repeat."""

    second = _list_html(
        _row("290001", "새 공고 A", "회사A"),
        _row("290002", "새 공고 B", "회사B"),
    )
    client = FakeClient([LIST_HTML, second, LIST_HTML])
    result = GameJobCrawler(_config(max_pages=5), client).run()

    assert result.manifest["counts"]["pages_read"] == 3
    collected = {r.source_posting_id for r in result.batch.records}
    assert {"290001", "290002"} <= collected


def test_a_page_of_new_but_filtered_rows_does_not_end_the_run():
    """The trap: new postings that every filter rejects are still progress.

    Keying the stop on collected records — or on the cursor's `already` set —
    would end the run here with pages still unread, silently dropping the
    postings on page 3. That is the failure S15P21E102-107 exists to prevent.
    """

    # Page 2 is all out of range, so it collects nothing at all.
    stale = _list_html(
        _row("291001", "오래된 A", "회사A", registered="07/28(화) 등록"),
        _row("291002", "오래된 B", "회사B", registered="07/28(화) 등록"),
    )
    fresh = _list_html(_row("292001", "새 공고", "회사C"))
    client = FakeClient([LIST_HTML, stale, fresh, LIST_HTML])

    result = GameJobCrawler(_config(max_pages=6), client).run()

    assert result.manifest["counts"]["pages_read"] == 4
    assert "292001" in {r.source_posting_id for r in result.batch.records}


def test_manifest_separates_rows_from_distinct_postings():
    """`rows_seen` overstates coverage by the page count on this site."""

    result = GameJobCrawler(_config(max_pages=10), FakeClient([LIST_HTML] * 10)).run()
    counts = result.manifest["counts"]

    assert counts["rows_seen"] == 14  # 7 rows x 2 pages
    assert counts["distinct_postings_seen"] == 7
    assert counts["duplicate_rows"] == 7
