import json
from datetime import date, datetime
from pathlib import Path

from JobKorea_Collector_V1 import crawler as crawler_module
from JobKorea_Collector_V1.crawler import CrawlConfig, JobKoreaCrawler, write_outputs
from JobKorea_Collector_V1.dates import SEOUL, parse_deadline, parse_posted_at
from JobKorea_Collector_V1.ocr import OcrLine, OcrResult, _extract_lines, image_suffix
from JobKorea_Collector_V1.parser import parse_detail, parse_job_list
from JobKorea_Collector_V1.technology import extract_technology_mentions

LIST_HTML = """
<div id="dev-gi-list">
  <div class="tplList tplJobList">
    <table>
      <tbody>
        <tr class="devloopArea" data-gno="49872974" data-info="49872974|x|y">
          <td class="tplCo">
            <a href="/Recruit/Co_Read/C/32492233" class="normalLog">㈜그린플로우</a>
          </td>
          <td class="tplTit">
            <div class="titBx">
              <strong>
                <a href="/Recruit/GI_Read/49872974?rPageCode=PL"
                   title="[경력] 웹 개발자 모집">[경력] 웹 개발자 모집</a>
              </strong>
              <p class="etc">
                <span class="cell">경력5년↑</span>
                <span class="cell">학력무관</span>
                <span class="cell">경기 군포시 외</span>
                <span class="cell">정규직</span>
              </p>
              <p class="dsc">서버관리, SI개발, 웹개발</p>
            </div>
          </td>
          <td class="odd">
            <span class="time"><span>08/25</span>(화) 등록</span>
            <span class="date"><span>~08/31</span>(월)</span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</div>
"""


def test_parse_jobkorea_category_row() -> None:
    [row] = parse_job_list(LIST_HTML)

    assert row.posting_id == "49872974"
    assert row.company_name == "㈜그린플로우"
    assert row.title == "[경력] 웹 개발자 모집"
    assert row.raw_job_category == "서버관리, SI개발, 웹개발"
    assert row.career_level == "경력5년↑"
    assert row.region == "경기 군포시 외"
    assert row.posted_label == "08/25(화) 등록"
    assert row.deadline_label == "~08/31(월)"


def test_parse_human_readable_dates() -> None:
    now = datetime(2026, 9, 3, 12, 0, tzinfo=SEOUL)

    assert parse_posted_at("08/25(화) 등록", now=now, default_year=2026) == datetime(
        2026,
        8,
        25,
        tzinfo=SEOUL,
    )
    assert parse_posted_at("3일 전 등록", now=now, default_year=2026) == datetime(
        2026,
        8,
        31,
        12,
        tzinfo=SEOUL,
    )
    assert parse_deadline("~08/31(월)", default_year=2026) == datetime(
        2026,
        8,
        31,
        23,
        59,
        59,
        tzinfo=SEOUL,
    )
    assert parse_deadline("상시채용", default_year=2026) is None


def test_parse_detail_body_and_deadline() -> None:
    detail = parse_detail(
        """
        <html><body>
          <h1>백엔드 개발자</h1>
          <p>Java/Spring 기반 API 개발</p>
          <div>접수방법</div>
          <div>2026.09.10(목) 까지 (채용시마감)</div>
          <script>ignore this value</script>
        </body></html>
        """
    )

    assert detail.body_status == "TEXT_AVAILABLE"
    assert "Java/Spring 기반 API 개발" in (detail.description_text or "")
    assert "ignore this value" not in (detail.description_text or "")
    assert detail.deadline_label == "2026.09.10(목)"


def test_image_only_detail_is_observable() -> None:
    detail = parse_detail(
        '<html><body><img src="recruit.png" alt="모집요강" /></body></html>'
    )

    assert detail.body_status == "IMAGE_ONLY"
    assert detail.description_text is None
    assert detail.has_images is True
    assert detail.image_sources == ("recruit.png",)


def test_detail_collects_lazy_and_css_image_sources() -> None:
    detail = parse_detail(
        """
        <html><body style="background-image: url('/assets/guide.webp')">
          <img src="/assets/guide.webp"
               srcset="/assets/guide-2.png 1x, /assets/guide-2@2x.png 2x"
               data-src="/assets/guide-2.png" />
          <img data-original="/assets/guide-3.jpg" />
        </body></html>
        """
    )

    assert detail.image_sources == (
        "/assets/guide.webp",
        "/assets/guide-2.png",
        "/assets/guide-2@2x.png",
        "/assets/guide-3.jpg",
    )


def test_technology_mentions_keep_requirement_evidence() -> None:
    mentions = extract_technology_mentions(
        "백엔드 개발자 (Spring Boot)",
        """
        자격요건
        Java, Spring Boot, PostgreSQL 사용 경험
        우대사항
        Docker 및 Kubernetes 운영 경험
        """,
    )

    by_key = {
        (mention.source_technology_id, mention.source_surface.value): mention
        for mention in mentions
    }
    assert by_key[("spring-boot", "TITLE")].requirement_type.value == "MENTIONED"
    assert by_key[("java", "BODY")].requirement_type.value == "REQUIRED"
    assert by_key[("docker", "BODY")].requirement_type.value == "PREFERRED"
    assert by_key[("java", "BODY")].evidence_section == "자격요건"
    assert by_key[("docker", "BODY")].extraction_method == "RULE_BASED_V1"


def test_ocr_result_shapes_are_normalized_without_paddle_runtime() -> None:
    class ArrayLike:
        def __init__(self, values: list[object]) -> None:
            self.values = values

        def tolist(self) -> list[object]:
            return self.values

    current_lines = tuple(
        _extract_lines(
            [
                {
                    "res": {
                        "rec_texts": ["Spring Boot", "낮은 신뢰도"],
                        "rec_scores": ArrayLike([0.98, 0.1]),
                        "rec_boxes": ArrayLike(
                            [
                                [[0, 0], [100, 0], [100, 20], [0, 20]],
                                [[0, 30], [100, 30], [100, 50], [0, 50]],
                            ]
                        ),
                    }
                }
            ],
            0.35,
        )
    )
    legacy_lines = tuple(
        _extract_lines(
            [
                [
                    [[[0, 0], [100, 0], [100, 20], [0, 20]], ("Java", 0.91)],
                ]
            ],
            0.35,
        )
    )

    assert [line.text for line in current_lines] == ["Spring Boot"]
    assert [line.text for line in legacy_lines] == ["Java"]
    assert image_suffix("https://cdn.example.com/image.png?size=large") == ".png"
    assert image_suffix("https://cdn.example.com/image") == ".jpg"


class FakeJobKoreaClient:
    def post(self, *_args: object, **_kwargs: object) -> str:
        return LIST_HTML

    def get(self, *_args: object, **_kwargs: object) -> str:
        raise AssertionError("detail request should be disabled in this test")


class FakeImageJobKoreaClient:
    def post(self, *_args: object, **_kwargs: object) -> str:
        return LIST_HTML

    def get(self, *_args: object, **_kwargs: object) -> str:
        return '<html><body><img src="recruit.png" alt="모집요강" /></body></html>'

    def get_bytes(self, *_args: object, **_kwargs: object) -> bytes:
        return b"fake-image"


def test_image_detail_runs_ocr_and_extracts_technologies(monkeypatch: object) -> None:
    class StubOcrEngine:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def recognize_bytes(
            self,
            _image_bytes: bytes,
            *,
            suffix: str,
        ) -> OcrResult:
            assert suffix == ".png"
            return OcrResult(
                text="자격요건\nPython, FastAPI 개발",
                lines=(
                    OcrLine(text="자격요건"),
                    OcrLine(text="Python, FastAPI 개발", confidence=0.97),
                ),
                average_confidence=0.97,
            )

    monkeypatch.setattr(
        "JobKorea_Collector_V1.crawler.PaddleOcrEngine",
        StubOcrEngine,
    )
    config = CrawlConfig(
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 31),
        request_delay=0,
        detail_delay=0,
        now=datetime(2026, 9, 3, 12, 0, tzinfo=SEOUL),
    )
    crawler = JobKoreaCrawler(config, client=FakeImageJobKoreaClient())
    result = crawler.run()

    assert len(result.batch.records) == 1
    record = result.batch.records[0]
    assert record.body_status.value == "IMAGE_ONLY"
    assert "[OCR 이미지]" in (record.description_text or "")
    assert {mention.source_technology_id for mention in record.technology_mentions} == {
        "python",
        "fastapi",
    }
    assert all(
        mention.extraction_method == "OCR_RULE_BASED_V1"
        for mention in record.technology_mentions
    )
    assert result.manifest["ocr"]["stats"]["postings_completed"] == 1
    assert result.manifest["ocr"]["postings"][0]["status"] == "COMPLETED"


def test_no_detail_run_writes_contract_outputs(tmp_path: Path) -> None:
    config = CrawlConfig(
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 31),
        request_delay=0,
        detail_delay=0,
        fetch_details=False,
        now=datetime(2026, 9, 3, 12, 0, tzinfo=SEOUL),
    )
    result = JobKoreaCrawler(config, client=FakeJobKoreaClient()).run()
    paths = write_outputs(result, tmp_path)

    assert len(result.batch.records) == 1
    assert result.batch.records[0].body_status.value == "MISSING"
    assert result.batch.records[0].raw_job_category == "백엔드개발자"
    assert str(result.batch.records[0].source_url) == (
        "https://www.jobkorea.co.kr/Recruit/GI_Read/49872974"
    )
    assert paths["json"].exists()
    assert paths["csv"].exists()
    assert paths["manifest"].exists()
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    assert manifest["ocr"]["enabled"] is False
    assert manifest["technology_extraction"]["mention_count"] == 0
    assert (
        json.loads(paths["json"].read_text(encoding="utf-8"))["records"][0][
            "source_posting_id"
        ]
        == "49872974"
    )


def test_same_run_replay_replaces_outputs_without_duplicate_records(
    tmp_path: Path,
) -> None:
    config = CrawlConfig(
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 31),
        request_delay=0,
        detail_delay=0,
        fetch_details=False,
        now=datetime(2026, 9, 3, 12, 0, tzinfo=SEOUL),
    )
    result = JobKoreaCrawler(config, client=FakeJobKoreaClient()).run()

    first_paths = write_outputs(result, tmp_path)
    first_payloads = {
        name: path.read_bytes() for name, path in first_paths.items()
    }
    replay_paths = write_outputs(result, tmp_path)
    replay_batch = json.loads(replay_paths["json"].read_text(encoding="utf-8"))

    assert replay_paths == first_paths
    assert {
        name: path.read_bytes() for name, path in replay_paths.items()
    } == first_payloads
    assert [
        (record["source_site"], record["source_posting_id"])
        for record in replay_batch["records"]
    ] == [("JOBKOREA", "49872974")]


# --- resume state (S15P21E102-196) ------------------------------------------
#
# This collector was a one-shot August backfill until `-196` put it on a
# twice-daily schedule. Without a cursor every round re-fetches the same
# postings, which on this site is the cost that matters — see the
# `source_admission` block in the manifest.


def _daily_config(tmp_path: Path, **overrides: object) -> CrawlConfig:
    base = {
        "start_date": date(2026, 8, 1),
        "end_date": date(2026, 8, 31),
        "request_delay": 0,
        "detail_delay": 0,
        "fetch_details": False,
        "now": datetime(2026, 9, 3, 12, 0, tzinfo=SEOUL),
        "cursor_path": tmp_path / "cursor.json",
    }
    base.update(overrides)
    return CrawlConfig(**base)  # type: ignore[arg-type]


def test_a_second_round_skips_postings_the_first_round_wrote(tmp_path: Path) -> None:
    config = _daily_config(tmp_path)

    first = JobKoreaCrawler(config, client=FakeJobKoreaClient()).run()
    write_outputs(first, tmp_path / "run-1")

    second = JobKoreaCrawler(config, client=FakeJobKoreaClient()).run()

    assert [r.source_posting_id for r in first.batch.records] == ["49872974"]
    assert second.batch.records == ()
    assert second.manifest["stats"]["skipped_already_collected"] == 1
    assert second.manifest["resume"]["known_ids_before"] == 1


def test_the_cursor_is_written_after_the_batch_and_the_manifest(
    tmp_path: Path,
) -> None:
    """S15P21E102-174: a cursor saved first can claim postings never stored."""

    config = _daily_config(tmp_path)
    result = JobKoreaCrawler(config, client=FakeJobKoreaClient()).run()
    cursor_path = tmp_path / "cursor.json"
    order: list[str] = []

    real_write = crawler_module._atomic_write

    def record_order(path: Path, content: str) -> None:
        order.append(path.name)
        real_write(path, content)

    original = crawler_module._atomic_write
    crawler_module._atomic_write = record_order
    try:
        write_outputs(result, tmp_path / "run-1")
    finally:
        crawler_module._atomic_write = original

    assert cursor_path.exists()
    assert order[-1] == "cursor.json"
    assert "manifest.json" in order[: order.index("cursor.json")]


def test_no_cursor_path_collects_without_resume_state(tmp_path: Path) -> None:
    """Omitting `--cursor` must not start writing state somewhere by itself."""

    config = _daily_config(tmp_path, cursor_path=None)

    first = JobKoreaCrawler(config, client=FakeJobKoreaClient()).run()
    write_outputs(first, tmp_path / "run-1")
    second = JobKoreaCrawler(config, client=FakeJobKoreaClient()).run()

    assert first.cursor_path is None
    assert not list(tmp_path.glob("cursor.json"))
    assert [r.source_posting_id for r in second.batch.records] == ["49872974"]


def test_a_moved_date_range_resets_the_cursor(tmp_path: Path) -> None:
    """Ids gathered under other bounds must not be trusted for a new range."""

    first = JobKoreaCrawler(
        _daily_config(tmp_path), client=FakeJobKoreaClient()
    ).run()
    write_outputs(first, tmp_path / "run-1")

    widened = _daily_config(tmp_path, start_date=date(2026, 7, 1))
    second = JobKoreaCrawler(widened, client=FakeJobKoreaClient()).run()

    assert second.manifest["resume"]["known_ids_before"] == 0
    assert [r.source_posting_id for r in second.batch.records] == ["49872974"]


def test_days_back_widens_the_range_from_the_end_date() -> None:
    parser = crawler_module.build_arg_parser()
    args = parser.parse_args(["--end-date", "2026-09-10", "--days-back", "1"])

    assert args.end_date == date(2026, 9, 10)
    assert args.days_back == 1


def test_the_request_interval_matches_the_other_sites() -> None:
    """2.0s, not the 0.8/0.5 this collector used as a hand-run backfill.

    `-94` §3.1 makes this the site with an adjudicated case against crawling
    it; being the project's fastest requester here is indefensible.
    """

    config = CrawlConfig(start_date=date(2026, 8, 1), end_date=date(2026, 8, 31))

    assert config.request_delay == 2.0
    assert config.detail_delay == 2.0

    defaults = crawler_module.build_arg_parser().parse_args([])
    assert defaults.request_delay == 2.0
    assert defaults.detail_delay == 2.0


def test_the_manifest_records_that_criterion_a_failed() -> None:
    """The decision travels with the data, not only in a doc."""

    config = _daily_config(Path("."), cursor_path=None)
    result = JobKoreaCrawler(config, client=FakeJobKoreaClient()).run()
    admission = result.manifest["source_admission"]

    assert admission["criterion_a"] == "FAIL"
    assert "서울고등법원" in admission["basis"]
    assert admission["admitted_by"] == "project owner decision, 2026-09-10"
