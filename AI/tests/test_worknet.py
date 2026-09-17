"""Worknet collector tests.

The fixture markup mirrors the live listing and detail structure verified on
2026-09-07: postings are reached through a `wantedAuthNo` detail link, and
fields are carried as labelled Korean text rather than stable class names.
"""

import csv
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin

import pytest

from job.collector import ListingRow, PostingDetail, content_hash_for
from job.contracts import (
    JOB_ANALYSIS_INPUT_SCHEMA_VERSION,
    BodyStatus,
    JobAnalysisInputBatch,
    PostingStatus,
    RequirementType,
    SourceSurface,
)
from Worknet_Collector_V1.client import looks_blocked
from Worknet_Collector_V1.crawler import (
    COLLECTOR_VERSION,
    CSV_FIELDS,
    LIST_PATH,
    SOURCE_SITE,
    CrawlConfig,
    Cursor,
    WorknetCrawler,
    write_outputs,
)
from Worknet_Collector_V1.dates import (
    is_open_ended_deadline,
    parse_date,
    parse_datetime,
)
from Worknet_Collector_V1.parser import parse_detail, parse_job_list

BASE_URL = "https://www.work24.go.kr"


def _detail_href(posting_id: str) -> str:
    return (
        f"/wk/a/b/1500/empDetailAuthView.do?wantedAuthNo={posting_id}"
        "&infoTypeCd=VALIDATION&infoTypeGroup=tb_workinfoworknet"
    )


def _list_row(
    posting_id: str,
    company: str,
    title: str,
    career: str,
    region: str,
    reg_date: str,
    deadline: str,
) -> str:
    return f"""
    <tr>
      <td>
        <a href="/wk/a/c/1000/coInfoView.do?coNo={posting_id}">[{company}]</a>
        <a href="{_detail_href(posting_id)}">{title}</a>
        <img src="/wk/static/images/logo/work24.png" alt="work24" />
      </td>
      <td>
        <span>{career}</span>
        <span>{region}</span>
        <span>등록일: {reg_date}</span>
        <span>마감일: {deadline}</span>
      </td>
    </tr>
    """


LIST_HTML = f"""
<html><body>
<table>
  <thead><tr><th>회사명 / 채용공고명 / 정보제공처</th><th>지원자격 / 근무조건</th></tr></thead>
  <tbody>
    {
    _list_row(
        "K120032609070005",
        "씨앤피건축사사무소",
        "건축가(건축설계 포함)",
        "신입",
        "서울특별시 강남구",
        "2026-09-07",
        "2026-11-05",
    )
}
    {
    _list_row(
        "K131132609070013",
        "테스트주식회사",
        "백엔드 개발자 채용",
        "경력무관",
        "경기도 성남시",
        "2026-09-07",
        "채용시까지",
    )
}
    {
    _list_row(
        "K999992608010001",
        "오래된회사",
        "예전 공고",
        "경력",
        "부산광역시 해운대구",
        "2026-08-01",
        "2026-08-20",
    )
}
  </tbody>
</table>
</body></html>
"""

DETAIL_HTML = """
<html><body>
  <h2>백엔드 개발자 채용</h2>
  <section>
    <h3>모집요강</h3>
    <p>[모집직무] 백엔드 개발</p>
    <p>[주요업무] API 설계 및 구현, 데이터 파이프라인 운영</p>
  </section>
  <section>
    <h3>근무조건</h3>
    <p>경력무관 / 대졸(4년) / 기간의 정함이 없는 근로계약</p>
    <p>서울특별시 강남구 개포로25길 3-4</p>
  </section>
  <section>
    <h3>우대사항</h3>
    <p>Kafka, Spark 경험자 우대</p>
  </section>
  <section>
    <h3>전형방법</h3>
    <p>서류 후 면접</p>
  </section>
  <p>등록일: 2026.09.07 10:15:57</p>
  <p>마감일: 2026-09-30</p>
  <script>var tracking = "무시되어야 한다";</script>
</body></html>
"""

IMAGE_ONLY_DETAIL_HTML = """
<html><body>
  <div><img src="/upload/posting/9999/body.png" alt="공고 이미지" /></div>
  <img src="/wk/static/images/logo/work24.png" alt="logo" />
</body></html>
"""


class FakeClient:
    """Duck-typed stand-in for WorknetHttpClient."""

    def __init__(
        self,
        list_pages: list[str],
        detail_html: str = DETAIL_HTML,
        *,
        detail_error: Exception | None = None,
        list_error_on_page: int | None = None,
        list_error: Exception | None = None,
    ) -> None:
        self.list_pages = list_pages
        self.detail_html = detail_html
        self.detail_error = detail_error
        self.list_error_on_page = list_error_on_page
        self.list_error = list_error
        self.requests: list[str] = []

    def absolute(self, url_or_path: str) -> str:
        return urljoin(BASE_URL + "/", url_or_path)

    def get(self, url_or_path, params=None, *, referer=None, delay_seconds=0.0):
        self.requests.append(url_or_path)
        if url_or_path == LIST_PATH:
            page = 1
            for key, value in params or ():
                if key == "currntPageNo":
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
        "start_date": date(2026, 9, 7),
        "end_date": date(2026, 9, 7),
        "request_delay": 0.0,
        "max_pages": 3,
        "base_url": BASE_URL,
    }
    params.update(overrides)
    return CrawlConfig(**params)  # type: ignore[arg-type]


# --- dates -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("등록일: 2026-09-07", date(2026, 9, 7)),
        ("2026.09.07 10:15:57", date(2026, 9, 7)),
        ("2026/09/07", date(2026, 9, 7)),
        ("채용시까지", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_date(text, expected):
    assert parse_date(text) == expected


def test_parse_datetime_keeps_timezone_and_clock():
    parsed = parse_datetime("등록일: 2026.09.07 10:15:57")
    assert parsed == datetime(2026, 9, 7, 10, 15, 57, tzinfo=parsed.tzinfo)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() is not None


def test_parse_datetime_anchors_bare_date_to_midnight_with_timezone():
    parsed = parse_datetime("2026-09-07")
    assert parsed.hour == 0 and parsed.minute == 0
    assert parsed.tzinfo is not None


def test_parse_datetime_rejects_impossible_clock():
    parsed = parse_datetime("2026-09-07 99:99:99")
    assert parsed is not None
    assert parsed.hour == 0


@pytest.mark.parametrize(
    "label", ["채용시까지", "상시채용", "채 용 시 까 지", "수시채용"]
)
def test_open_ended_deadline_labels(label):
    assert is_open_ended_deadline(label)


def test_dated_deadline_is_not_open_ended():
    assert not is_open_ended_deadline("2026-09-30")


def test_config_rejects_reversed_range():
    with pytest.raises(ValueError):
        _config(start_date=date(2026, 9, 8), end_date=date(2026, 9, 7))


# --- list parsing ----------------------------------------------------------


def test_parse_job_list_extracts_all_rows():
    items = parse_job_list(LIST_HTML)
    assert [item.source_posting_id for item in items] == [
        "K120032609070005",
        "K131132609070013",
        "K999992608010001",
    ]


def test_parse_job_list_field_extraction():
    first = parse_job_list(LIST_HTML)[0]
    assert first.title == "건축가(건축설계 포함)"
    assert first.company_name == "씨앤피건축사사무소"
    assert first.career_level == "신입"
    assert first.region == "서울특별시 강남구"
    assert first.posted_on == date(2026, 9, 7)
    assert first.deadline_label == "2026-11-05"
    assert "wantedAuthNo=K120032609070005" in first.detail_ref


def test_parse_job_list_keeps_open_ended_deadline_label():
    second = parse_job_list(LIST_HTML)[1]
    assert second.deadline_label == "채용시까지"
    assert second.region == "경기도 성남시"


def test_parse_job_list_ignores_non_detail_links():
    items = parse_job_list(
        '<a href="/wk/a/c/1000/coInfoView.do?coNo=1">회사</a>'
        '<a href="/some/other/page.do">기타</a>'
    )
    assert items == []


def test_parse_job_list_deduplicates_repeated_posting_links():
    duplicated = LIST_HTML + LIST_HTML
    items = parse_job_list(duplicated)
    assert len(items) == 3


# --- detail parsing --------------------------------------------------------


def test_parse_detail_reads_sections_and_drops_scripts():
    detail = parse_detail(DETAIL_HTML)
    assert detail.section_names == (
        "모집요강",
        "근무조건",
        "우대사항",
        "전형방법",
    )
    assert "API 설계 및 구현" in detail.description_text
    assert "무시되어야 한다" not in detail.description_text


def test_parse_detail_reads_condition_fields():
    detail = parse_detail(DETAIL_HTML)
    assert detail.career_level == "경력무관"
    assert detail.education == "대졸(4년)"
    assert detail.employment_type == "기간의 정함이 없는 근로계약"
    assert detail.region == "서울특별시 강남구"
    assert detail.posted_at is not None
    assert detail.posted_at.hour == 10


@pytest.mark.parametrize(
    "value", ["신입", "신입<br>,<br>경력<br>(최소 3년 이상)", "관계없음"]
)
def test_detail_filter_fields_ignore_caption_and_company_address(value):
    # Minimal markup from the labelled text in the preserved Worknet sample;
    # this is not a downloaded original HTML fixture.
    detail = parse_detail(f"""
        <h3>모집요강</h3>
        <p>모집 직종, 경력, 학력, 근무 예정지를 제공하는 표</p>
        <dl><dt>경력</dt><dd>{value}</dd><dt>학력</dt><dd>학력무관</dd>
        <dt>근무 예정지</dt><dd>대구 동구</dd><dt>임금조건</dt><dd>협의</dd></dl>
        <h3>기업정보</h3><p>경력 개발자를 우대합니다</p>
        <p>주소</p><p>경기도 성남시 분당구</p>
    """)
    expected = value.replace("<br>", " ")
    assert detail.career_level == ("경력무관" if value == "관계없음" else expected)
    assert detail.region == "대구 동구"


def test_detail_missing_workplace_does_not_use_company_address_or_caption_career():
    detail = parse_detail("""
        <h3>모집요강</h3><p>경력, 학력, 근무 예정지를 제공하는 표</p>
        <dl><dt>경력</dt><dd>-</dd><dt>학력</dt><dd>학력무관</dd>
        <dt>근무 예정지</dt><dd>-</dd><dt>임금조건</dt><dd>협의</dd></dl>
        <h3>기업정보</h3><p>경력 개발자</p><p>주소</p><p>서울특별시 강남구</p>
    """)
    assert detail.career_level is None
    assert detail.region is None


def test_detail_absent_workplace_does_not_read_company_region_label():
    detail = parse_detail(
        "<h3>모집요강</h3><dl><dt>경력</dt><dd>신입</dd></dl>"
        "<h3>기업정보</h3><dl><dt>지역</dt><dd>서울특별시 강남구</dd></dl>"
    )
    assert detail.region is None


def test_detail_navigation_company_tab_does_not_hide_workplace_field():
    detail = parse_detail(
        "<h3>근무조건</h3><p>기타 조건</p>"
        "<p>모집요강</p><p>근무조건</p><p>우대사항</p><p>복리후생</p>"
        "<p>전형방법</p><p>기업정보</p><p>추천정보</p><p>모집요강</p>"
        "<dl><dt>근무 예정지</dt><dd>대구 동구</dd><dt>임금조건</dt><dd>협의</dd></dl>"
    )
    assert detail.region == "대구 동구"


def test_parse_detail_separates_posting_images_from_site_chrome():
    detail = parse_detail(IMAGE_ONLY_DETAIL_HTML)
    assert detail.image_sources == ("/upload/posting/9999/body.png",)
    assert detail.description_text.strip() == ""


# --- crawl: contract conformance -------------------------------------------


def test_run_emits_contract_valid_batch():
    crawler = WorknetCrawler(_config(), FakeClient([LIST_HTML]))
    result = crawler.run()

    assert result.batch.schema_version == JOB_ANALYSIS_INPUT_SCHEMA_VERSION
    assert result.batch.collector_version == "worknet-collector/v2"
    # Re-validating the serialized batch proves the output is contract-clean,
    # not just that our in-memory objects happened to construct.
    JobAnalysisInputBatch.model_validate_json(
        result.batch.model_dump_json(by_alias=True)
    )


def test_run_skips_rows_outside_registration_range():
    crawler = WorknetCrawler(_config(), FakeClient([LIST_HTML]))
    result = crawler.run()

    ids = [record.source_posting_id for record in result.batch.records]
    assert "K999992608010001" not in ids
    assert result.manifest["counts"]["skipped_out_of_range"] == 1


def test_run_populates_required_contract_fields():
    crawler = WorknetCrawler(_config(), FakeClient([LIST_HTML]))
    record = crawler.run().batch.records[0]

    assert record.source_site == SOURCE_SITE
    assert record.source_record_id == f"{SOURCE_SITE}:K120032609070005"
    assert str(record.source_url).startswith(f"{BASE_URL}/wk/a/b/1500/")
    assert len(record.content_hash) == 64
    assert record.collected_at.tzinfo is not None
    assert record.body_status is BodyStatus.TEXT_AVAILABLE
    assert record.description_text


def test_content_hash_is_stable_for_identical_input():
    first = WorknetCrawler(_config(), FakeClient([LIST_HTML])).run()
    second = WorknetCrawler(_config(), FakeClient([LIST_HTML])).run()
    assert [r.content_hash for r in first.batch.records] == [
        r.content_hash for r in second.batch.records
    ]


def test_source_url_is_absolute_for_every_record():
    result = WorknetCrawler(_config(), FakeClient([LIST_HTML])).run()
    assert result.batch.records
    for record in result.batch.records:
        assert str(record.source_url).startswith("https://")


# --- crawl: body status ----------------------------------------------------


def test_no_detail_run_marks_body_missing():
    crawler = WorknetCrawler(_config(fetch_detail=False), FakeClient([LIST_HTML]))
    result = crawler.run()
    assert all(
        record.body_status is BodyStatus.MISSING for record in result.batch.records
    )
    assert result.manifest["body_status_counts"] == {"MISSING": 2}


def test_image_only_detail_sets_raw_artifact_uri():
    client = FakeClient([LIST_HTML], detail_html=IMAGE_ONLY_DETAIL_HTML)
    record = WorknetCrawler(_config(), client).run().batch.records[0]

    assert record.body_status is BodyStatus.IMAGE_ONLY
    assert record.raw_artifact_uri == f"{BASE_URL}/upload/posting/9999/body.png"
    assert record.description_text is None


def test_detail_failure_marks_blocked_and_keeps_record():
    from Worknet_Collector_V1.client import WorknetHttpError

    client = FakeClient([LIST_HTML], detail_error=WorknetHttpError("boom"))
    result = WorknetCrawler(_config(), client).run()

    assert len(result.batch.records) == 2
    assert all(
        record.body_status is BodyStatus.BLOCKED for record in result.batch.records
    )
    assert result.manifest["counts"]["detail_errors"] == 2


# --- crawl: posting status -------------------------------------------------


def test_open_ended_deadline_is_active():
    client = FakeClient([LIST_HTML], detail_html="<html><body></body></html>")
    result = WorknetCrawler(_config(fetch_detail=False), client).run()
    by_id = {r.source_posting_id: r for r in result.batch.records}
    assert by_id["K131132609070013"].posting_status is PostingStatus.ACTIVE
    assert by_id["K131132609070013"].deadline is None


def test_future_deadline_is_active():
    result = WorknetCrawler(_config(fetch_detail=False), FakeClient([LIST_HTML])).run()
    by_id = {r.source_posting_id: r for r in result.batch.records}
    assert by_id["K120032609070005"].posting_status is PostingStatus.ACTIVE


# --- crawl: blocking stops this site --------------------------------------


def test_block_on_list_stops_run_and_records_reason():
    from Worknet_Collector_V1.client import WorknetBlockedError

    client = FakeClient(
        [LIST_HTML, LIST_HTML],
        list_error_on_page=1,
        list_error=WorknetBlockedError("refused"),
    )
    result = WorknetCrawler(_config(), client).run()

    assert result.batch.records == ()
    assert "blocked" in result.manifest["stopped_reason"]


def test_block_on_later_page_keeps_earlier_records():
    from Worknet_Collector_V1.client import WorknetBlockedError

    client = FakeClient(
        [LIST_HTML, LIST_HTML],
        list_error_on_page=2,
        list_error=WorknetBlockedError("refused"),
    )
    result = WorknetCrawler(_config(), client).run()

    assert len(result.batch.records) == 2
    assert "blocked" in result.manifest["stopped_reason"]


@pytest.mark.parametrize(
    "body",
    [
        "<html>자동입력 방지 문자를 입력하세요</html>",
        "<html>비정상적인 접근이 감지되었습니다</html>",
        "<html>Too Many Requests</html>",
        "<html>CAPTCHA required</html>",
    ],
)
def test_looks_blocked_detects_block_pages(body):
    assert looks_blocked(body)


def test_looks_blocked_passes_normal_listing():
    assert not looks_blocked(LIST_HTML)


# --- cursor: resume --------------------------------------------------------


def test_cursor_round_trip(tmp_path: Path):
    config = _config(cursor_path=tmp_path / "worknet.cursor.json")
    cursor = Cursor.load(config.cursor_path, config)
    cursor.collected_ids.append("K1")
    cursor.last_page = 2
    cursor.save(config.cursor_path)

    reloaded = Cursor.load(config.cursor_path, config)
    assert reloaded.collected_ids == ["K1"]
    assert reloaded.last_page == 2
    assert reloaded.updated_at is not None


def test_cursor_is_discarded_for_a_different_date_range(tmp_path: Path):
    path = tmp_path / "worknet.cursor.json"
    first = _config(cursor_path=path)
    saved = Cursor.load(path, first)
    saved.collected_ids.append("K1")
    saved.save(path)

    other = _config(
        cursor_path=path,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 2),
    )
    assert Cursor.load(path, other).collected_ids == []


def test_cursor_survives_corrupt_file(tmp_path: Path):
    path = tmp_path / "worknet.cursor.json"
    path.write_text("{ not json", encoding="utf-8")
    assert Cursor.load(path, _config(cursor_path=path)).collected_ids == []


def test_rerun_with_cursor_skips_already_collected_postings(tmp_path: Path):
    config = _config(cursor_path=tmp_path / "worknet.cursor.json")

    first = WorknetCrawler(config, FakeClient([LIST_HTML])).run()
    assert len(first.batch.records) == 2
    # `write_outputs` persists the cursor, not `run` (S15P21E102-174).
    write_outputs(first, tmp_path / "out")

    second = WorknetCrawler(config, FakeClient([LIST_HTML])).run()
    assert second.batch.records == ()
    assert second.manifest["counts"]["skipped_already_collected"] == 2
    assert second.manifest["resume"]["ids_known_before_run"] == 2


def test_run_without_cursor_path_does_not_write_state(tmp_path: Path):
    result = WorknetCrawler(_config(), FakeClient([LIST_HTML])).run()
    assert result.manifest["resume"]["cursor_path"] is None
    assert list(tmp_path.iterdir()) == []


# --- paging ----------------------------------------------------------------


def test_paging_stops_when_page_has_no_rows_in_range():
    older_only = f"<html><body><table><tbody>{
        _list_row(
            'K888882607010001',
            '옛회사',
            '옛공고',
            '경력',
            '대구광역시',
            '2026-07-01',
            '2026-07-20',
        )
    }</tbody></table></body></html>"
    client = FakeClient([LIST_HTML, older_only, LIST_HTML])
    result = WorknetCrawler(_config(), client).run()

    assert result.manifest["counts"]["pages_read"] == 2
    assert len(result.batch.records) == 2


def test_paging_stops_on_empty_page():
    client = FakeClient([LIST_HTML])
    result = WorknetCrawler(_config(), client).run()
    assert result.manifest["counts"]["pages_read"] == 2


def test_page_params_advance_page_number():
    client = FakeClient([LIST_HTML, LIST_HTML, LIST_HTML])
    crawler = WorknetCrawler(_config(max_pages=2), client)
    crawler.run()
    assert client.requests.count(LIST_PATH) == 2


# --- outputs ---------------------------------------------------------------


def test_write_outputs_creates_json_csv_and_manifest(tmp_path: Path):
    result = WorknetCrawler(_config(), FakeClient([LIST_HTML])).run()
    paths = write_outputs(result, tmp_path)

    run_dir = tmp_path / result.batch.pipeline_run_id
    assert run_dir.is_dir()
    for key in ("json", "csv", "manifest"):
        assert paths[key].exists()

    reloaded = JobAnalysisInputBatch.model_validate_json(
        paths["json"].read_text(encoding="utf-8")
    )
    assert len(reloaded.records) == len(result.batch.records)

    with paths["csv"].open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == CSV_FIELDS
    assert len(rows) == len(result.batch.records) + 1

    assert not list(run_dir.glob("*.tmp")), "temp files must not survive a write"


def test_write_outputs_is_rerunnable_into_the_same_directory(tmp_path: Path):
    result = WorknetCrawler(_config(), FakeClient([LIST_HTML])).run()
    write_outputs(result, tmp_path)
    paths = write_outputs(result, tmp_path)
    assert paths["json"].exists()


def test_manifest_records_request_and_resume_context():
    result = WorknetCrawler(_config(), FakeClient([LIST_HTML])).run()
    manifest = result.manifest

    assert manifest["source_site"] == SOURCE_SITE
    assert manifest["request"]["start_date"] == "2026-09-07"
    assert manifest["request"]["list_path"] == LIST_PATH
    assert manifest["schema_version"] == JOB_ANALYSIS_INPUT_SCHEMA_VERSION
    assert manifest["counts"]["records"] == 2
    assert manifest["stopped_reason"] is None


# --- detail scope: real pages are mostly site chrome ----------------------

CHROME_WRAPPED_DETAIL_HTML = """
<html><body>
  <header class="new">
    <div class="gnb_wrap">홈 채용정보 일자리 찾기 상세검색 AI 일자리추천</div>
  </header>
  <section id="container">
    <div id="contents">
      <div class="cont_wrap">
        <div class="cont_wrap_area">
          <h2>백엔드 개발자</h2>
          <section><h3>모집요강</h3><p>Kafka 파이프라인 운영</p></section>
          <p>등록일: 2026.09.07 10:15:57</p>
        </div>
      </div>
    </div>
  </section>
  <footer class="footer">
    <p>고용노동부 시스템 점검 안내 (2026년 9월12일 00:00~18:00)</p>
  </footer>
</body></html>
"""


def test_detail_scope_excludes_header_and_footer():
    detail = parse_detail(CHROME_WRAPPED_DETAIL_HTML)

    assert "Kafka 파이프라인 운영" in detail.description_text
    assert "일자리추천" not in detail.description_text
    assert "시스템 점검 안내" not in detail.description_text


def test_detail_scope_falls_back_to_body_when_container_is_absent():
    detail = parse_detail(DETAIL_HTML)
    assert "API 설계 및 구현" in detail.description_text


def test_no_detail_run_reports_no_detail_errors():
    """--no-detail is a deliberate list-only run, not ten failures."""

    result = WorknetCrawler(_config(fetch_detail=False), FakeClient([LIST_HTML])).run()

    assert result.manifest["counts"]["detail_errors"] == 0
    assert result.manifest["detail_error_samples"] == []
    assert all(
        record.body_status is BodyStatus.MISSING for record in result.batch.records
    )


# --- registration date: labelled value only -------------------------------

DETAIL_WITH_REG_DATETIME_LABEL = """
<html><body><div class="cont_wrap_area">
  <h2>백엔드 개발자</h2>
  <p>마감일 2026.10.30 (금) 24:00 고용24 입사지원 가능 기업</p>
  <p>채용공고 등록일시 2026.09.07 10:53:54</p>
</div></body></html>
"""

DETAIL_WITHOUT_REG_LABEL = """
<html><body><div class="cont_wrap_area">
  <h2>백엔드 개발자</h2>
  <p>설립일 2014. 01. 24</p>
  <p>접수 마감 2026.10.30 (금) 24:00</p>
</div></body></html>
"""


def test_detail_reads_the_reg_datetime_label_used_by_the_detail_page():
    """The listing says 등록일, the detail page says 등록일시."""

    detail = parse_detail(DETAIL_WITH_REG_DATETIME_LABEL)

    assert detail.posted_at is not None
    assert detail.posted_at.date() == date(2026, 9, 7)
    assert (detail.posted_at.hour, detail.posted_at.minute) == (10, 53)


def test_detail_does_not_invent_a_registration_date_from_body_text():
    """No label means no value — the deadline must not become the post date.

    A live posting reported 등록일 2026-10-30 because an unlabelled fallback
    took the first date in the body, which was the deadline.
    """

    detail = parse_detail(DETAIL_WITHOUT_REG_LABEL)
    assert detail.posted_at is None


def test_record_falls_back_to_the_listing_registration_date():
    """The listing column is labelled, so it wins when the detail has none."""

    client = FakeClient([LIST_HTML], detail_html=DETAIL_WITHOUT_REG_LABEL)
    record = WorknetCrawler(_config(), client).run().batch.records[0]

    assert record.posted_at is not None
    assert record.posted_at.date() == date(2026, 9, 7)


def test_deadline_label_is_bounded_on_collapsed_text():
    """Detail text is one long line; the label must not eat the document."""

    detail = parse_detail(DETAIL_WITH_REG_DATETIME_LABEL)

    assert detail.deadline_label is not None
    assert len(detail.deadline_label) <= 40
    assert parse_date(detail.deadline_label) == date(2026, 10, 30)


# --- job filters -----------------------------------------------------------


def _params(**overrides) -> dict[str, str]:
    crawler = WorknetCrawler(_config(**overrides), FakeClient([LIST_HTML]))
    return dict(crawler._page_params(1))


def test_no_filter_params_when_unset():
    params = _params()
    for key in ("keyword", "srcKeyword", "occupation", "codeDepth1Info"):
        assert key not in params


def test_keyword_is_sent_to_both_search_fields():
    params = _params(keyword="개발자")
    assert params["keyword"] == "개발자"
    assert params["srcKeyword"] == "개발자"


def test_occupation_codes_are_comma_joined():
    """The site's own script submits picker selections as one joined value."""

    params = _params(occupation_codes=("133", "134"))
    assert params["occupation"] == "133,134"


def test_region_code_sets_both_depth_fields():
    params = _params(region_code="11000")
    assert params["codeDepth1Info"] == "11000"
    assert params["codeDepth2Info"] == "11000"


def test_manifest_records_the_active_filter():
    """A run must be reproducible from its own manifest."""

    config = _config(keyword="개발자", occupation_codes=("133",))
    result = WorknetCrawler(config, FakeClient([LIST_HTML])).run()

    assert result.manifest["request"]["keyword"] == "개발자"
    assert result.manifest["request"]["occupation_codes"] == ["133"]


# --- S15P21E102-99 shared normalizer adoption ------------------------------


def test_records_now_carry_technology_mentions():
    """Before adoption Worknet emitted an empty tuple for every record.

    The extractor was never Worknet-specific — it only lived in the JobKorea
    package, so every Worknet run stored zero technologies while the whole
    point of the collection is technology demand.
    """

    record = WorknetCrawler(_config(), FakeClient([LIST_HTML])).run().batch.records[0]

    mentions = {
        mention.source_technology_id: mention for mention in record.technology_mentions
    }
    assert "kafka" in mentions
    assert mentions["kafka"].requirement_type is RequirementType.PREFERRED
    assert mentions["kafka"].source_surface is SourceSurface.BODY
    assert mentions["kafka"].evidence_text.strip()


def test_manifest_reports_the_extraction_count():
    """Parity with the JobKorea manifest, so a run's yield is visible."""

    result = WorknetCrawler(_config(), FakeClient([LIST_HTML])).run()

    extraction = result.manifest["technology_extraction"]
    assert extraction["method"] == "RULE_BASED_V1"
    assert extraction["mention_count"] == sum(
        len(record.technology_mentions) for record in result.batch.records
    )
    assert extraction["mention_count"] > 0


def test_list_only_run_extracts_nothing_rather_than_guessing():
    result = WorknetCrawler(_config(fetch_detail=False), FakeClient([LIST_HTML])).run()

    assert all(record.technology_mentions == () for record in result.batch.records)
    assert result.manifest["technology_extraction"]["mention_count"] == 0


def test_content_hash_matches_the_shared_helper():
    """The hash is the shared one, so it now has field separators.

    The hand-written copy concatenated fields with no separator despite a
    comment claiming otherwise, which let two different field splits collide.
    """

    record = WorknetCrawler(_config(), FakeClient([LIST_HTML])).run().batch.records[0]

    assert record.content_hash == content_hash_for(
        source_site=SOURCE_SITE,
        source_posting_id=record.source_posting_id,
        title=record.title,
        company_name=record.company_name,
        description_text=record.description_text,
    )


def test_parser_returns_the_shared_listing_shape():
    """S15P21E102-99 fixed the shape; Worknet uses it rather than its own."""

    row = parse_job_list(LIST_HTML)[0]
    assert isinstance(row, ListingRow)


def test_parsed_detail_is_the_shared_detail_shape():
    detail = parse_detail(DETAIL_HTML)
    assert isinstance(detail, PostingDetail)
    # Worknet still reads these; they stop at the parser by S15P21E102-99.
    assert detail.education == "대졸(4년)"


def test_crawler_satisfies_the_site_collector_protocol_surface():
    """The pieces the protocol names are all present on the Worknet modules."""

    assert SOURCE_SITE == "WORKNET"
    assert COLLECTOR_VERSION == "worknet-collector/v2"
    assert callable(parse_job_list)
    assert callable(parse_detail)


# --- deadline: the two forms Worknet actually uses -------------------------

PERIOD_DETAIL_HTML = """
<html><body>
  <div class="cont_wrap_area">
    <p>채용정보 상세(민간연계)</p>
    <p>채용정보</p>
    <p>기업정보</p>
    <p>위쉬정보기술㈜</p>
    <p>일반기업</p>
    <p>java 웹스퀘어 개발자 모집</p>
    <p>정보제공처</p>
    <p>조회수 21</p>
    <p>채용정보 제공 사이트 바로가기</p>
    <p>모집요강</p>
    <p>근무조건</p>
    <p>복리후생</p>
    <p>전형방법</p>
    <p>기업정보</p>
    <p>모집요강</p>
    <p>[모집직무] 백엔드 개발</p>
    <p>자격요건</p>
    <p>Kafka 경험 필수</p>
    <p>전형방법</p>
    <p>접수 기간 2026.09.07 (월) ~ 2026.09.13 (일) 마감일까지</p>
    <p>채용사이트 바로가기</p>
    <p>등록일시 2026.09.07 09:10:11</p>
  </div>
</body></html>
"""


def test_deadline_is_read_from_an_application_period():
    """ "접수 기간 A ~ B 마감일까지" — the end of the period is the deadline.

    The label regex used to match the trailing "마감일까지" and capture
    "까지 채용사이트 바로가기 ...", which parsed to no date at all. Five of
    eight postings in a live run were stored with no deadline because of it.
    """

    detail = parse_detail(PERIOD_DETAIL_HTML)
    assert detail.deadline_label == "2026.09.13"
    assert parse_date(detail.deadline_label) == date(2026, 9, 13)


def test_labelled_deadline_still_wins_over_a_period():
    detail = parse_detail(DETAIL_HTML)
    assert parse_date(detail.deadline_label) == date(2026, 9, 30)


def test_trailing_deadline_word_without_a_date_yields_no_label():
    """A bare "마감일까지" must not become a label of its own."""

    from Worknet_Collector_V1.parser import _deadline_label_from_row

    assert _deadline_label_from_row("마감일까지 채용사이트 바로가기 접수 방법") is None


def test_period_deadline_makes_the_posting_active():
    client = FakeClient([LIST_HTML], detail_html=PERIOD_DETAIL_HTML)
    collected_at = parse_datetime("2026-09-13 12:00:00")
    assert collected_at is not None
    record = (
        WorknetCrawler(_config(), client, collected_at=collected_at)
        .run()
        .batch.records[0]
    )

    assert record.collected_at == collected_at
    assert record.deadline is not None
    assert record.deadline.isoformat() == "2026-09-14T00:00:00+09:00"
    assert record.posting_status is PostingStatus.ACTIVE


# --- in-page header trim ---------------------------------------------------


def test_detail_drops_the_in_page_header_block():
    """The header survives container narrowing; the view counter closes it."""

    detail = parse_detail(PERIOD_DETAIL_HTML)
    lines = [
        line.strip() for line in detail.description_text.split("\n") if line.strip()
    ]

    assert lines[0] == "모집요강"
    for furniture in ("조회수 21", "위쉬정보기술㈜", "일반기업", "정보제공처"):
        assert furniture not in detail.description_text


def test_header_trim_removes_the_repeated_section_tab_strip():
    """The tab strip lists every section before the content repeats them."""

    detail = parse_detail(PERIOD_DETAIL_HTML)

    assert detail.description_text.count("모집요강") == 1
    assert "채용정보 제공 사이트 바로가기" not in detail.description_text


def test_header_trim_keeps_a_company_name_out_of_the_evidence_section():
    """A company name containing "기술" was reported as a mention's section.

    `위쉬정보기술㈜` came from the header block and was picked up by the
    section look-back, displacing the real heading.
    """

    from job.collector import extract_technology_mentions

    detail = parse_detail(PERIOD_DETAIL_HTML)
    mentions = extract_technology_mentions(
        "java 웹스퀘어 개발자 모집", detail.description_text
    )
    sections = {mention.evidence_section for mention in mentions}

    assert "위쉬정보기술㈜" not in sections


def test_header_trim_keeps_both_blocks_when_a_section_repeats_with_content():
    """Two 모집요강 blocks with content between them are not a tab strip."""

    from Worknet_Collector_V1.parser import _strip_page_header

    text = "조회수 3\n모집요강\n[모집직무] 백엔드\n모집요강\n[모집직무] 프론트엔드"
    assert _strip_page_header(text).count("모집요강") == 2


def test_header_trim_is_a_no_op_without_a_view_counter():
    """A template without the counter degrades to the previous behaviour."""

    from Worknet_Collector_V1.parser import _strip_page_header

    text = "모집요강\n[모집직무] 백엔드 개발"
    assert _strip_page_header(text) == text


def test_header_trim_never_empties_a_body():
    from Worknet_Collector_V1.parser import _strip_page_header

    text = "조회수 12"
    assert _strip_page_header(text) == text


# --- 직종 preset -----------------------------------------------------------


def test_dev_preset_resolves_to_the_development_groups():
    from Worknet_Collector_V1.occupations import resolve_occupation_preset

    assert resolve_occupation_preset("dev") == ("024", "025", "026", "023")
    assert resolve_occupation_preset("software") == ("024",)


def test_dev_extended_adds_hardware_and_telecom():
    from Worknet_Collector_V1.occupations import resolve_occupation_preset

    assert "022" in resolve_occupation_preset("dev-extended")
    assert "022" not in resolve_occupation_preset("dev")


def test_unknown_preset_raises_instead_of_collecting_everything():
    """A typo must not quietly become a full-occupation crawl."""

    from Worknet_Collector_V1.occupations import resolve_occupation_preset

    with pytest.raises(ValueError, match="unknown occupation preset"):
        resolve_occupation_preset("developer")


def test_preset_and_explicit_codes_combine_without_duplicates():
    from Worknet_Collector_V1.crawler import _occupation_codes

    assert _occupation_codes("133202", "software") == ("024", "133202")
    assert _occupation_codes("024", "software") == ("024",)
    assert _occupation_codes(None, None) == ()


def test_preset_reaches_the_request_and_the_manifest():
    config = _config(occupation_codes=("024", "025", "026", "023"))
    result = WorknetCrawler(config, FakeClient([LIST_HTML])).run()

    assert result.manifest["request"]["occupation_codes"] == [
        "024",
        "025",
        "026",
        "023",
    ]


def test_every_preset_code_is_a_documented_group():
    """A preset must not name a code the module cannot explain."""

    from Worknet_Collector_V1.occupations import (
        OCCUPATION_GROUPS,
        OCCUPATION_PRESETS,
    )

    for codes in OCCUPATION_PRESETS.values():
        for code in codes:
            assert code in OCCUPATION_GROUPS


# --- 모집직종 -> raw_job_category ------------------------------------------
#
# Every other collector fills the shared `raw_job_category` slot and
# `job.cohort._matches_role` reads it before falling back to the title regex.
# Worknet left it empty, so a Worknet posting could only ever match a role by
# its title. The label was already known to the parser as a field boundary; it
# just was not read as a value.

JOB_CATEGORY_DETAIL_HTML = """
<html><body>
  <h2>펌웨어 개발</h2>
  <section>
    <h3>모집요강</h3>
    <p>모집 직종,모집 인원,경력,학력,고용형태를 제공하는 표</p>
    <dl>
      <dt>모집 직종</dt><dd>펌웨어(Firmware),회로설계</dd>
      <dt>모집 인원</dt><dd>1명</dd>
      <dt>경력</dt><dd>경력무관</dd>
      <dt>학력</dt><dd>대졸(2~3년)</dd>
    </dl>
  </section>
  <h3>기업정보</h3><p>모집 직종</p><p>영업</p>
</body></html>
"""

# The exact text the live 2026-09-13 posting (wantedAuthNo 2609120000064)
# carried, so the assertion is anchored to production bytes rather than to a
# fixture written to pass.
LIVE_CONDITION_TEXT = (
    "모집 직종,모집 인원,경력,학력,고용형태,근무 예정지,임금조건,채용 직급,"
    "우대조건을(를) 제공하는 표\n\n"
    "모집 직종\n\n펌웨어(Firmware),회로설계\n\n모집 인원\n\n1명\n\n"
    "경력\n\n경력\n\n(최소 7년\n\n이상)\n\n학력\n\n대졸(2~3년)\n"
)


def test_detail_reads_the_job_category_label():
    detail = parse_detail(JOB_CATEGORY_DETAIL_HTML)
    assert detail.raw_job_category == "펌웨어(Firmware),회로설계"


def test_job_category_is_read_from_the_live_posting_text():
    from Worknet_Collector_V1.parser import _detail_job_category

    assert _detail_job_category(LIVE_CONDITION_TEXT) == "펌웨어(Firmware),회로설계"


def test_job_category_value_splits_into_role_tokens():
    # `_matches_role` splits on [,;|]; the value has to survive that tokenizer
    # the same way Saramin's "백엔드/서버개발, API, Java" does.
    import re

    detail = parse_detail(JOB_CATEGORY_DETAIL_HTML)
    tokens = [t.strip() for t in re.split(r"[,;|]", detail.raw_job_category)]
    assert tokens == ["펌웨어(Firmware)", "회로설계"]


def test_job_category_ignores_the_table_caption_and_company_section():
    # The caption repeats every label on one line and the company block reuses
    # the label; neither may become the value.
    detail = parse_detail(JOB_CATEGORY_DETAIL_HTML)
    assert "제공하는 표" not in detail.raw_job_category
    assert detail.raw_job_category != "영업"


def test_detail_without_the_label_reports_no_job_category():
    # Regression guard: the existing fixture has no 모집직종, and the parser must
    # leave the slot empty rather than invent one from nearby prose.
    assert parse_detail(DETAIL_HTML).raw_job_category is None


def test_job_category_reaches_the_emitted_record_and_csv(tmp_path):
    crawler = WorknetCrawler(
        _config(), FakeClient([LIST_HTML], detail_html=JOB_CATEGORY_DETAIL_HTML)
    )
    result = crawler.run()
    assert result.batch.records, "fixture crawl produced no record"
    assert result.batch.records[0].raw_job_category == "펌웨어(Firmware),회로설계"

    paths = write_outputs(result, tmp_path)
    with paths["csv"].open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert "raw_job_category" in CSV_FIELDS
    assert rows[0]["raw_job_category"] == "펌웨어(Firmware),회로설계"
