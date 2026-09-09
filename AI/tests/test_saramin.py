"""Saramin collector tests (S15P21E102-148).

The fixture markup mirrors the live search and detail-popup structure verified
on 2026-09-07: one `div.item_recruit` per posting carrying the id in its own
`value` attribute, and a `div.user_content` body inside the popup.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from job.collector import ListingRow, PostingDetail
from job.contracts import BodyStatus, JobAnalysisInputBatch, PostingStatus
from Saramin_Collector_V1.categories import (
    CATEGORY_PRESETS,
    ROLE_CATEGORIES,
    STACK_CATEGORIES,
    resolve_category_preset,
)
from Saramin_Collector_V1.crawler import (
    LIST_PATH,
    SOURCE_SITE,
    CrawlConfig,
    Cursor,
    SaraminCrawler,
    _category_codes,
    write_outputs,
)
from Saramin_Collector_V1.dates import (
    is_open_ended_deadline,
    parse_deadline,
    parse_listing_date,
)
from Saramin_Collector_V1.parser import detail_path, parse_detail, parse_job_list

BASE_URL = "https://www.saramin.co.kr"
TODAY = date(2026, 9, 7)
SEOUL = ZoneInfo("Asia/Seoul")


def _item(
    posting_id: str,
    title: str,
    company: str,
    *,
    region: str = "서울",
    district: str = "강남구",
    career: str = "신입·경력",
    date_label: str = "등록일",
    day: str = "26/09/07",
    deadline: str = "~ 10/07(수)",
) -> str:
    return f"""
    <div class="item_recruit" value="{posting_id}">
      <div class="area_job">
        <h2 class="job_tit">
          <a title="{title}" href="/zf_user/jobs/relay/view?view_type=search&amp;rec_idx={posting_id}&amp;search_uuid=abc"><span>{title}</span></a>
        </h2>
        <div class="job_date"><span class="date">{deadline}</span></div>
        <div class="job_condition">
          <span><a href="/zf_user/area-recruit/area-list/area/101000">{region}</a> <a href="/zf_user/area-recruit/area-list/area/101010">{district}</a></span>
          <span>{career}</span> <span>대졸↑</span> <span>정규직</span>
        </div>
        <div class="job_sector">
          <a href="/zf_user/jobs/list/job-category?cat_kewd=84">백엔드/서버개발</a>,
          <a href="/zf_user/jobs/list/job-category?cat_kewd=235">Java</a>
          <span class="job_day">{date_label} {day}</span>
        </div>
      </div>
      <div class="area_corp">
        <strong class="corp_name"><a href="/zf_user/company-info/view?csn=x">{company}</a></strong>
      </div>
    </div>
    """


LIST_HTML = f"""
<html><body>
<div id="recruit_info_list">
  {_item("54962457", "AI 에이전트 주니어 개발자", "(주)라이너스")}
  {_item("54962450", "백엔드 개발자 채용", "미스터마인드(주)", region="경기", district="성남시 분당구", career="경력5년↑", deadline="채용시")}
  {_item("54900001", "예전 공고", "오래된회사", day="26/08/01", deadline="~ 09/01(화)")}
  {_item("54900002", "날짜없는 공고", "무날짜회사", date_label="", day="")}
  {_item("54900003", "수정일만 있는 공고", "수정회사", date_label="수정일")}
</div>
</body></html>
"""

DETAIL_HTML = """
<html><body>
  <section class="jview">
    <div class="wrap_jv_cont">
      <div class="jv_cont jv_summary">
        <div class="cont">
          <dl><dt>경력</dt><dd><strong>신입·경력 4년 ↓</strong></dd></dl>
          <dl><dt>학력</dt><dd><strong>대졸(4년제) 이상</strong></dd></dl>
          <dl><dt>근무형태</dt><dd><strong>정규직</strong> 수습기간 3개월</dd></dl>
        </div>
      </div>
      <div class="jv_cont jv_detail">
        <h2 class="jv_title blind">상세요강</h2>
        <div class="cont">
          <div class="user_content">
            <p>모집분야</p>
            <p>자격요건</p>
            <p>- Python, FastAPI 개발 경험 필수</p>
            <p>우대사항</p>
            <p>- Kubernetes 운영 경험 우대</p>
          </div>
        </div>
      </div>
      <div class="jv_cont jv_benefit">
        <p>관련 공고: Java 개발자 모집</p>
      </div>
    </div>
  </section>
</body></html>
"""

IMAGE_ONLY_DETAIL_HTML = """
<html><body>
  <div class="user_content">
    <img src="/upload/posting/1234/body.png" alt="공고 이미지" />
    <img src="//www.saraminimage.co.kr/common/bul_sri_star.png" alt="star" />
  </div>
</body></html>
"""

NO_BODY_DETAIL_HTML = """
<html><body>
  <section class="jview"><div class="wrap_jv_cont"><p>공고가 마감되었습니다</p></div></section>
</body></html>
"""


class FakeClient:
    """Duck-typed stand-in for PoliteHttpClient."""

    def __init__(
        self,
        list_pages: list[str],
        detail_html: str = DETAIL_HTML,
        *,
        detail_error: Exception | None = None,
        list_error: Exception | None = None,
        list_error_on_page: int | None = None,
    ) -> None:
        self.list_pages = list_pages
        self.detail_html = detail_html
        self.detail_error = detail_error
        self.list_error = list_error
        self.list_error_on_page = list_error_on_page
        self.requests: list[str] = []

    def absolute(self, url_or_path: str) -> str:
        return BASE_URL + url_or_path if url_or_path.startswith("/") else url_or_path

    def get(self, url_or_path, params=None, *, referer=None, delay_seconds=0.0):
        self.requests.append(url_or_path)
        if url_or_path == LIST_PATH:
            page = 1
            for key, value in params or ():
                if key == "recruitPage":
                    page = int(value)
            if self.list_error_on_page == page and self.list_error is not None:
                raise self.list_error
            index = page - 1
            return self.list_pages[index] if index < len(self.list_pages) else ""
        if self.detail_error is not None:
            raise self.detail_error
        return self.detail_html


def _config(**overrides) -> CrawlConfig:
    params: dict[str, object] = {
        "start_date": TODAY,
        "end_date": TODAY,
        "request_delay": 0.0,
        "max_pages": 3,
        "base_url": BASE_URL,
    }
    params.update(overrides)
    return CrawlConfig(**params)  # type: ignore[arg-type]


# --- robots.txt compliance -------------------------------------------------


def test_detail_path_is_the_robots_allowed_popup():
    """robots.txt Disallows the ordinary detail paths and Allows this one."""

    path = detail_path("54962457")
    assert path.startswith("/zf_user/jobs/view/popup")
    assert "rec_idx=54962457" in path


@pytest.mark.parametrize(
    "disallowed",
    [
        "/zf_user/recruit/view/",
        "/zf_user/recruit/recruit-posting/",
        "/recruit/recruit_view.php",
        "/zf_user/company/",
    ],
)
def test_no_disallowed_path_is_ever_requested(disallowed: str):
    client = FakeClient([LIST_HTML])
    SaraminCrawler(_config(), client).run()

    assert all(disallowed not in request for request in client.requests)


def test_source_url_drops_the_listing_tracking_parameters():
    """The listing href carries a per-search uuid that must not be stored."""

    record = SaraminCrawler(_config(), FakeClient([LIST_HTML])).run().batch.records[0]

    assert "search_uuid" not in str(record.source_url)
    assert "/zf_user/jobs/view/popup" in str(record.source_url)


def test_manifest_records_which_detail_path_was_used():
    manifest = SaraminCrawler(_config(), FakeClient([LIST_HTML])).run().manifest
    assert manifest["robots"]["detail_path"] == "/zf_user/jobs/view/popup"


# --- dates -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("등록일 26/09/07", (date(2026, 9, 7), "등록일")),
        ("수정일 26/09/07", (date(2026, 9, 7), "수정일")),
        ("등록일 26/13/40", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_listing_date(text, expected):
    assert parse_listing_date(text) == expected


def test_listing_date_keeps_the_label_that_produced_it():
    """수정일 is not 등록일; a run has to be able to say how many it used."""

    parsed = parse_listing_date("수정일 26/09/07")
    assert parsed is not None and parsed[1] == "수정일"


def test_deadline_infers_the_current_year():
    assert parse_deadline("~ 10/07(수)", today=TODAY) == date(2026, 10, 7)


def test_deadline_rolls_into_next_year_when_far_behind():
    """A live listing showing ~ 01/15 in December means next January."""

    assert parse_deadline("~ 01/15(목)", today=date(2026, 12, 20)) == date(2027, 1, 15)


def test_a_just_expired_deadline_stays_in_the_current_year():
    assert parse_deadline("~ 09/01(화)", today=TODAY) == date(2026, 9, 1)


@pytest.mark.parametrize("label", ["채용시", "상시채용", "수시채용", "채용시까지"])
def test_open_ended_deadlines(label: str):
    assert is_open_ended_deadline(label)
    assert parse_deadline(label, today=TODAY) is None


def test_not_started_posting_has_no_deadline():
    assert parse_deadline("진행예정", today=TODAY) is None


# --- list parsing ----------------------------------------------------------


def test_parse_job_list_extracts_every_row():
    rows = parse_job_list(LIST_HTML, today=TODAY)
    assert [row.source_posting_id for row in rows] == [
        "54962457",
        "54962450",
        "54900001",
        "54900002",
        "54900003",
    ]


def test_parse_job_list_field_extraction():
    first = parse_job_list(LIST_HTML, today=TODAY)[0]

    assert first.title == "AI 에이전트 주니어 개발자"
    assert first.company_name == "(주)라이너스"
    assert first.region == "서울 강남구"
    assert first.career_level == "신입·경력"
    assert first.posted_on == date(2026, 9, 7)
    assert first.deadline_label == "~ 10/07(수)"
    assert first.raw_job_category is not None
    assert "백엔드/서버개발" in first.raw_job_category


def test_region_is_the_span_holding_links_not_a_fixed_index():
    second = parse_job_list(LIST_HTML, today=TODAY)[1]
    assert second.region == "경기 성남시 분당구"
    assert second.career_level == "경력5년↑"


def test_rows_returned_as_the_shared_listing_shape():
    assert isinstance(parse_job_list(LIST_HTML, today=TODAY)[0], ListingRow)


# --- detail parsing --------------------------------------------------------


def test_detail_body_is_narrowed_to_user_content():
    """The popup is ~10x the body; a neighbouring block must not leak in."""

    detail = parse_detail(DETAIL_HTML, today=TODAY)

    assert detail.description_text is not None
    assert "FastAPI" in detail.description_text
    assert "관련 공고" not in detail.description_text


def test_detail_reads_the_labelled_summary_fields():
    detail = parse_detail(DETAIL_HTML, today=TODAY)

    assert detail.career_level == "신입·경력 4년 ↓"
    assert detail.education == "대졸(4년제) 이상"
    assert detail.employment_type is not None
    assert "정규직" in detail.employment_type


def test_detail_is_the_shared_detail_shape():
    assert isinstance(parse_detail(DETAIL_HTML, today=TODAY), PostingDetail)


def test_a_popup_without_a_body_yields_no_description():
    """Returning the whole document would store navigation as a posting."""

    detail = parse_detail(NO_BODY_DETAIL_HTML, today=TODAY)
    assert detail.description_text is None


def test_site_asset_images_are_not_treated_as_posting_images():
    detail = parse_detail(IMAGE_ONLY_DETAIL_HTML, today=TODAY)
    assert detail.image_sources == ("/upload/posting/1234/body.png",)


# --- crawl -----------------------------------------------------------------


def test_run_emits_a_contract_valid_batch():
    result = SaraminCrawler(_config(), FakeClient([LIST_HTML])).run()

    JobAnalysisInputBatch.model_validate(result.batch.model_dump(by_alias=True))
    assert result.batch.collector_version == "saramin-collector/v2"
    assert all(record.source_site == SOURCE_SITE for record in result.batch.records)


def test_rows_outside_the_range_are_skipped():
    result = SaraminCrawler(_config(), FakeClient([LIST_HTML])).run()

    ids = {record.source_posting_id for record in result.batch.records}
    assert "54900001" not in ids
    assert result.manifest["counts"]["skipped_out_of_range"] >= 1


def test_undated_rows_are_skipped_and_counted():
    """There is no server-side range filter, so an undated row is not in range."""

    result = SaraminCrawler(_config(), FakeClient([LIST_HTML])).run()

    ids = {record.source_posting_id for record in result.batch.records}
    assert "54900002" not in ids
    assert result.manifest["counts"]["skipped_undated"] == 1


def test_manifest_reports_the_date_label_mix():
    result = SaraminCrawler(_config(), FakeClient([LIST_HTML])).run()
    labels = result.manifest["listing_date_labels"]

    assert labels["등록일"] >= 1
    assert labels["수정일"] == 1


def test_technology_mentions_are_extracted_per_record():
    record = SaraminCrawler(_config(), FakeClient([LIST_HTML])).run().batch.records[0]
    ids = {mention.source_technology_id for mention in record.technology_mentions}

    assert "python" in ids
    assert "fastapi" in ids


def test_open_ended_deadline_is_active_without_a_date():
    result = SaraminCrawler(_config(), FakeClient([LIST_HTML])).run()
    record = next(
        item for item in result.batch.records if item.source_posting_id == "54962450"
    )

    assert record.deadline is None
    assert record.posting_status is PostingStatus.ACTIVE


def test_no_detail_run_marks_body_missing():
    result = SaraminCrawler(_config(fetch_detail=False), FakeClient([LIST_HTML])).run()

    assert all(
        record.body_status is BodyStatus.MISSING for record in result.batch.records
    )
    assert result.manifest["counts"]["detail_errors"] == 0


def test_no_detail_run_requests_no_detail_pages():
    client = FakeClient([LIST_HTML])
    SaraminCrawler(_config(fetch_detail=False), client).run()

    assert all("popup" not in request for request in client.requests)


def test_image_only_detail_sets_an_absolute_raw_artifact_uri():
    client = FakeClient([LIST_HTML], detail_html=IMAGE_ONLY_DETAIL_HTML)
    record = SaraminCrawler(_config(), client).run().batch.records[0]

    assert record.body_status is BodyStatus.IMAGE_ONLY
    assert record.raw_artifact_uri == f"{BASE_URL}/upload/posting/1234/body.png"


def test_detail_failure_keeps_the_record_as_blocked():
    from job.collector.http import HttpError

    client = FakeClient([LIST_HTML], detail_error=HttpError("boom"))
    result = SaraminCrawler(_config(), client).run()

    assert result.batch.records
    assert all(
        record.body_status is BodyStatus.BLOCKED for record in result.batch.records
    )
    assert result.manifest["counts"]["detail_errors"] == len(result.batch.records)


def test_a_block_stops_this_site_and_keeps_earlier_records():
    from job.collector.http import BlockedError

    client = FakeClient(
        [LIST_HTML, LIST_HTML],
        list_error=BlockedError("refused"),
        list_error_on_page=2,
    )
    result = SaraminCrawler(_config(max_pages=3), client).run()

    assert result.manifest["stopped_reason"] is not None
    assert "blocked" in result.manifest["stopped_reason"]
    assert result.batch.records


def test_paging_stops_when_a_page_has_nothing_in_range():
    old_only = f"<html><body>{_item('54900009', '옛 공고', '회사', day='26/07/01')}</body></html>"
    client = FakeClient([LIST_HTML, old_only, LIST_HTML])
    result = SaraminCrawler(_config(max_pages=3), client).run()

    assert result.manifest["counts"]["pages_read"] == 2


def test_page_params_carry_registration_sort_and_categories():
    crawler = SaraminCrawler(_config(category_codes=("84", "87")), FakeClient([]))
    params = dict(crawler._page_params(2))

    assert params["recruitSort"] == "reg_dt"
    assert params["recruitPage"] == "2"
    assert params["cat_kewd"] == "84,87"


# --- resume ----------------------------------------------------------------


def test_cursor_round_trip(tmp_path: Path):
    """`write_outputs` is what persists the cursor (S15P21E102-174)."""

    config = _config(cursor_path=tmp_path / "cursor.json")
    result = SaraminCrawler(config, FakeClient([LIST_HTML])).run()
    write_outputs(result, tmp_path / "out")

    reloaded = Cursor.load(tmp_path / "cursor.json", config)
    assert "54962457" in reloaded.collected_ids


def test_run_alone_does_not_persist_the_cursor(tmp_path: Path):
    """The regression that cost 2,633 postings.

    `run` used to write the cursor inside the page loop, so a crawl killed
    mid-run left it claiming ids whose batch was never stored — and the next
    run skipped them silently, because skipping is exactly what a cursor is
    for. Nothing surfaced the loss.

    Now an interrupted run leaves no cursor at all, which costs a repeated
    request instead of the postings.
    """

    cursor_path = tmp_path / "cursor.json"
    result = SaraminCrawler(
        _config(cursor_path=cursor_path), FakeClient([LIST_HTML])
    ).run()

    assert result.batch.records, "the crawl itself still collected"
    assert not cursor_path.exists()


def test_rerun_with_cursor_skips_already_collected(tmp_path: Path):
    config = _config(cursor_path=tmp_path / "cursor.json")
    first = SaraminCrawler(config, FakeClient([LIST_HTML])).run()
    write_outputs(first, tmp_path / "out")

    second = SaraminCrawler(config, FakeClient([LIST_HTML])).run()

    assert second.batch.records == ()
    assert second.manifest["counts"]["skipped_already_collected"] >= 1


def test_cursor_is_discarded_for_a_different_range(tmp_path: Path):
    first = _config(cursor_path=tmp_path / "cursor.json")
    write_outputs(
        SaraminCrawler(first, FakeClient([LIST_HTML])).run(), tmp_path / "out"
    )

    other = _config(
        cursor_path=tmp_path / "cursor.json",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 2),
    )
    assert Cursor.load(tmp_path / "cursor.json", other).collected_ids == []


def test_config_rejects_a_reversed_range():
    with pytest.raises(ValueError):
        _config(start_date=date(2026, 9, 8), end_date=TODAY)


# --- 직군 preset -----------------------------------------------------------


def test_dev_preset_is_role_codes_only():
    """Filtering by stack tags would make the technology count circular."""

    codes = set(resolve_category_preset("dev"))
    assert codes <= set(ROLE_CATEGORIES)
    assert not codes & set(STACK_CATEGORIES)


def test_software_preset_is_narrower_than_dev():
    assert set(resolve_category_preset("software")) < set(
        resolve_category_preset("dev")
    )


def test_dev_extended_adds_the_support_roles():
    extended = set(resolve_category_preset("dev-extended"))
    assert "104" in extended
    assert "104" not in set(resolve_category_preset("dev"))


def test_unknown_preset_raises_instead_of_collecting_everything():
    with pytest.raises(ValueError, match="unknown category preset"):
        resolve_category_preset("backend")


def test_every_preset_code_is_a_documented_role():
    for codes in CATEGORY_PRESETS.values():
        for code in codes:
            assert code in ROLE_CATEGORIES


def test_preset_and_explicit_codes_combine_without_duplicates():
    assert _category_codes("84", "software")[0] == "84"
    assert len(_category_codes("84", "software")) == len(
        resolve_category_preset("software")
    )


# --- outputs ---------------------------------------------------------------


def test_write_outputs_creates_json_csv_and_manifest(tmp_path: Path):
    result = SaraminCrawler(_config(), FakeClient([LIST_HTML])).run()
    paths = write_outputs(result, tmp_path)

    assert paths["json"].exists()
    assert paths["csv"].exists()
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    assert manifest["outputs"]["postings.csv"] == "postings.csv"


def test_csv_lists_the_technology_ids(tmp_path: Path):
    result = SaraminCrawler(_config(), FakeClient([LIST_HTML])).run()
    paths = write_outputs(result, tmp_path)

    body = paths["csv"].read_text(encoding="utf-8")
    assert "python" in body


def test_write_outputs_is_rerunnable_into_the_same_directory(tmp_path: Path):
    result = SaraminCrawler(_config(), FakeClient([LIST_HTML])).run()
    write_outputs(result, tmp_path)
    write_outputs(result, tmp_path)

    assert not list(tmp_path.rglob("*.tmp"))


def test_run_id_and_snapshot_id_follow_the_shared_helpers():
    result = SaraminCrawler(_config(), FakeClient([LIST_HTML])).run()

    assert result.batch.pipeline_run_id.startswith("SARAMIN-")
    assert result.batch.dataset_snapshot_id == "SARAMIN-2026-09-07-2026-09-07"


def test_collected_at_is_timezone_aware():
    record = SaraminCrawler(_config(), FakeClient([LIST_HTML])).run().batch.records[0]
    assert record.collected_at.tzinfo is not None
    assert isinstance(record.collected_at, datetime)
