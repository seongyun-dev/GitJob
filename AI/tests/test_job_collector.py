"""Tests for the shared collector interface and normalizer (S15P21E102-99)."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from job.collector import (
    ListingRow,
    PostingDetail,
    SiteCollector,
    content_hash_for,
    dataset_snapshot_id_for,
    normalize_posting,
    pipeline_run_id_for,
    posting_status_from_deadline,
    resolve_body_status,
    source_record_id_for,
)
from job.contracts import BodyStatus, PostingStatus, RequirementType, SourceSurface

SEOUL = ZoneInfo("Asia/Seoul")
COLLECTED_AT = datetime(2026, 9, 7, 11, 30, tzinfo=SEOUL)


def _row(**overrides: object) -> ListingRow:
    fields: dict[str, object] = {
        "source_posting_id": "KWN-0001",
        "detail_ref": "/wk/a/b/1500/empDetailAuthView.do?wantedAuthNo=KWN0001",
        "title": "백엔드 개발자",
        "company_name": "테스트주식회사",
    }
    fields.update(overrides)
    return ListingRow(**fields)  # type: ignore[arg-type]


def _normalize(**overrides: object):
    kwargs: dict[str, object] = {
        "source_site": "WORKNET",
        "row": _row(),
        "detail": PostingDetail(description_text="Spring Boot 경험 필수"),
        "source_url": "https://www.work24.go.kr/wk/a/b/1500/empDetailAuthView.do",
        "collected_at": COLLECTED_AT,
        "detail_fetched": True,
    }
    kwargs.update(overrides)
    return normalize_posting(**kwargs)  # type: ignore[arg-type]


# --- body_status: absence must stay representable (contract §5) -------------


def test_text_wins_over_images_when_both_present() -> None:
    status = resolve_body_status(
        description_text="모집요강 ...",
        image_sources=("https://example.test/a.png",),
        detail_fetched=True,
        detail_error=None,
    )
    assert status is BodyStatus.TEXT_AVAILABLE


def test_image_only_posting_keeps_image_only_status() -> None:
    status = resolve_body_status(
        description_text=None,
        image_sources=("https://example.test/a.png",),
        detail_fetched=True,
        detail_error=None,
    )
    assert status is BodyStatus.IMAGE_ONLY


def test_whitespace_body_is_not_text_available() -> None:
    status = resolve_body_status(
        description_text="   \n  ",
        image_sources=(),
        detail_fetched=True,
        detail_error=None,
    )
    assert status is BodyStatus.PARSE_FAILED


def test_list_only_run_is_missing_not_an_error() -> None:
    status = resolve_body_status(
        description_text=None,
        image_sources=(),
        detail_fetched=False,
        detail_error=None,
    )
    assert status is BodyStatus.MISSING


def test_list_only_run_stays_missing_even_with_a_recorded_error() -> None:
    """A run that never asked for the body must not be reported as blocked."""

    status = resolve_body_status(
        description_text=None,
        image_sources=(),
        detail_fetched=False,
        detail_error="boom",
    )
    assert status is BodyStatus.MISSING


def test_detail_error_is_blocked() -> None:
    status = resolve_body_status(
        description_text=None,
        image_sources=(),
        detail_fetched=True,
        detail_error="HTTP 403",
    )
    assert status is BodyStatus.BLOCKED


def test_image_only_record_carries_the_image_as_raw_artifact_uri() -> None:
    record = _normalize(
        detail=PostingDetail(
            description_text=None,
            image_sources=("https://example.test/poster.png",),
        )
    )
    assert record.body_status is BodyStatus.IMAGE_ONLY
    assert record.raw_artifact_uri == "https://example.test/poster.png"
    assert record.description_text is None


def test_normalizer_does_not_invent_a_body_for_a_blocked_detail() -> None:
    record = _normalize(detail=None, detail_error="HTTP 403")
    assert record.body_status is BodyStatus.BLOCKED
    assert record.description_text is None
    assert record.raw_artifact_uri is None


# --- content hash ----------------------------------------------------------


def test_content_hash_is_stable_across_two_collections_of_one_posting() -> None:
    first = _normalize(collected_at=COLLECTED_AT)
    second = _normalize(
        collected_at=datetime(2026, 9, 8, 4, 0, tzinfo=SEOUL),
    )
    assert first.content_hash == second.content_hash


def test_content_hash_separates_fields_so_a_different_split_differs() -> None:
    """Without a separator "AB"+"C" and "A"+"BC" would hash identically.

    That is what made the two hand-written copies of this mapping risky: one
    posting could be treated as a duplicate of another.
    """

    shifted_title = content_hash_for(
        source_site="WORKNET",
        source_posting_id="KWN",
        title="0001백엔드",
        company_name="회사",
        description_text=None,
    )
    shifted_id = content_hash_for(
        source_site="WORKNET",
        source_posting_id="KWN0001",
        title="백엔드",
        company_name="회사",
        description_text=None,
    )
    assert shifted_title != shifted_id


def test_content_hash_changes_when_the_body_changes() -> None:
    original = _normalize()
    edited = _normalize(detail=PostingDetail(description_text="Kotlin 경험 필수"))
    assert original.content_hash != edited.content_hash


# --- posting_status --------------------------------------------------------


@pytest.mark.parametrize(
    ("deadline_date", "label", "expected"),
    [
        (date(2026, 9, 6), None, PostingStatus.CLOSED),
        (date(2026, 9, 7), None, PostingStatus.ACTIVE),
        (date(2026, 10, 30), None, PostingStatus.ACTIVE),
        (None, "채용시까지", PostingStatus.ACTIVE),
        (None, "상시채용 (수시)", PostingStatus.ACTIVE),
        (None, None, PostingStatus.UNKNOWN),
        (None, "2026.10.30 (금) 24:00", PostingStatus.UNKNOWN),
    ],
)
def test_posting_status_follows_evidence(
    deadline_date: date | None,
    label: str | None,
    expected: PostingStatus,
) -> None:
    assert (
        posting_status_from_deadline(
            deadline_date=deadline_date,
            deadline_label=label,
            collected_at=COLLECTED_AT,
        )
        is expected
    )


def test_date_only_deadline_is_the_next_seoul_day_exclusive_boundary() -> None:
    record = _normalize(deadline_date=date(2026, 9, 7))

    assert record.deadline == datetime(2026, 9, 8, 0, 0, tzinfo=SEOUL)
    assert record.posting_status is PostingStatus.ACTIVE


def test_precise_deadline_is_preserved_including_a_real_midnight() -> None:
    precise = datetime(2026, 9, 8, 0, 0, tzinfo=SEOUL)

    record = _normalize(deadline_date=precise)

    assert record.deadline == precise


def test_precise_deadline_status_compares_the_actual_clock_time() -> None:
    assert (
        posting_status_from_deadline(
            deadline_date=datetime(2026, 9, 7, 10, 0, tzinfo=SEOUL),
            deadline_label=None,
            collected_at=COLLECTED_AT,
        )
        is PostingStatus.CLOSED
    )


# --- field precedence ------------------------------------------------------


def test_detail_values_win_over_listing_values() -> None:
    record = _normalize(
        row=_row(career_level="경력", region="서울"),
        detail=PostingDetail(
            description_text="Java 필수",
            career_level="경력 3년 이상",
            region="서울 강남구",
        ),
    )
    assert record.career_level == "경력 3년 이상"
    assert record.region == "서울 강남구"


def test_listing_values_fill_in_what_the_detail_omits() -> None:
    record = _normalize(
        row=_row(career_level="신입", region="부산"),
        detail=PostingDetail(description_text="Python 필수"),
    )
    assert record.career_level == "신입"
    assert record.region == "부산"


def test_blank_detail_value_does_not_shadow_the_listing() -> None:
    record = _normalize(
        row=_row(region="대전"),
        detail=PostingDetail(description_text="Go 필수", region="   "),
    )
    assert record.region == "대전"


def test_posted_at_falls_back_to_the_listing_date_column() -> None:
    """The body is never consulted — that stored deadlines as posted dates."""

    record = _normalize(
        row=_row(posted_on=date(2026, 9, 7)),
        detail=PostingDetail(
            description_text="마감일 2026.10.30 (금) 24:00 까지",
            posted_at=None,
        ),
    )
    assert record.posted_at is not None
    assert record.posted_at.date() == date(2026, 9, 7)


def test_detail_timestamp_wins_over_the_listing_date() -> None:
    detail_posted_at = datetime(2026, 9, 7, 10, 53, 54, tzinfo=SEOUL)
    record = _normalize(
        row=_row(posted_on=date(2026, 9, 6)),
        detail=PostingDetail(description_text="Java 필수", posted_at=detail_posted_at),
    )
    assert record.posted_at == detail_posted_at


def test_withheld_company_name_keeps_the_record() -> None:
    record = _normalize(row=_row(company_name=None))
    assert record.company_name == "(회사명 미표기)"


# --- technology mentions: the completion criterion -------------------------


def test_or_combination_is_decomposed_into_individual_rows() -> None:
    """S15P21E102-99 stores each technology as its own row.

    The combination form is not preserved, so "Java 또는 Kotlin" must produce
    two rows, not one row naming both.
    """

    record = _normalize(
        detail=PostingDetail(
            description_text="자격요건\nJava 또는 Kotlin 개발 경험 필수"
        )
    )
    ids = {mention.source_technology_id for mention in record.technology_mentions}
    assert {"java", "kotlin"} <= ids


def test_and_combination_is_decomposed_into_individual_rows() -> None:
    record = _normalize(
        detail=PostingDetail(description_text="자격요건\nJava 와 Spring 모두 필수")
    )
    ids = {mention.source_technology_id for mention in record.technology_mentions}
    assert {"java", "spring"} <= ids


def test_requirement_type_and_surface_are_retained_per_row() -> None:
    record = _normalize(
        row=_row(title="React 프론트엔드 개발자"),
        detail=PostingDetail(
            description_text="자격요건\nJava 필수\n\n우대사항\nKotlin 경험 우대"
        ),
    )
    by_id = {
        mention.source_technology_id: mention for mention in record.technology_mentions
    }
    assert by_id["java"].requirement_type is RequirementType.REQUIRED
    assert by_id["kotlin"].requirement_type is RequirementType.PREFERRED
    assert by_id["react"].source_surface is SourceSurface.TITLE
    assert by_id["java"].source_surface is SourceSurface.BODY


def test_every_mention_carries_evidence_text() -> None:
    record = _normalize(
        detail=PostingDetail(description_text="자격요건\nSpring Boot 경험 필수")
    )
    assert record.technology_mentions
    assert all(mention.evidence_text.strip() for mention in record.technology_mentions)


def test_common_spring_boot_and_postgresql_aliases_are_extracted() -> None:
    record = _normalize(
        detail=PostingDetail(
            description_text="자격요건\nSpringBoot 및 Postgres 운영 경험 필수"
        )
    )

    ids = {mention.source_technology_id for mention in record.technology_mentions}
    assert {"spring-boot", "postgresql"} <= ids


def test_compound_words_do_not_trigger_the_new_technology_aliases() -> None:
    record = _normalize(
        detail=PostingDetail(description_text="SpringBootcamp 및 PostgresSQL")
    )

    ids = {mention.source_technology_id for mention in record.technology_mentions}
    assert "spring-boot" not in ids
    assert "postgresql" not in ids


def test_a_body_less_record_has_no_mentions_rather_than_guessed_ones() -> None:
    record = _normalize(detail=None, detail_fetched=False)
    assert record.body_status is BodyStatus.MISSING
    assert record.technology_mentions == ()


def test_extraction_can_be_switched_off_for_a_list_only_run() -> None:
    record = _normalize(extract_technologies=False)
    assert record.technology_mentions == ()


def test_worknet_now_gets_the_same_extraction_as_jobkorea() -> None:
    """The extractor moved out of the JobKorea package in this ticket.

    Worknet was emitting an empty tuple for every record only because the
    code lived in a site package.
    """

    from job.collector.technology import (
        extract_technology_mentions as via_shared,
    )
    from JobKorea_Collector_V1.technology import (
        extract_technology_mentions as via_jobkorea,
    )

    assert via_jobkorea is via_shared


# --- identifiers -----------------------------------------------------------


def test_source_record_id_is_namespaced_by_site() -> None:
    assert source_record_id_for("WORKNET", "0001") == "WORKNET:0001"
    assert source_record_id_for("JOBKOREA", "0001") == "JOBKOREA:0001"


def test_pipeline_run_id_is_stamped_in_utc() -> None:
    run_id = pipeline_run_id_for(
        "WORKNET", datetime(2026, 9, 7, 11, 11, 7, tzinfo=SEOUL)
    )
    assert run_id == "WORKNET-20260907T021107Z"


def test_dataset_snapshot_id_is_shared_by_two_runs_of_one_range() -> None:
    snapshot_id = dataset_snapshot_id_for(
        "WORKNET",
        date(2026, 9, 7),
        date(2026, 9, 7),
    )
    assert snapshot_id == "WORKNET-2026-09-07-2026-09-07"


# --- contract conformance --------------------------------------------------


def test_normalized_record_never_omits_source_url() -> None:
    record = _normalize()
    assert str(record.source_url).startswith("https://")


def test_naive_collected_at_is_rejected() -> None:
    """The missing tzinfo is the point of the test, hence the noqa."""

    with pytest.raises(ValidationError):
        _normalize(collected_at=datetime(2026, 9, 7, 11, 30))  # noqa: DTZ001


def test_blank_posting_id_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _normalize(row=_row(source_posting_id="  "))


# --- the interface itself --------------------------------------------------


def test_a_site_satisfying_the_protocol_is_recognized() -> None:
    class StubSite:
        source_site = "STUB"
        collector_version = "stub-collector/v1"

        def parse_list(self, html: str) -> list[ListingRow]:
            return [_row()]

        def parse_detail(self, html: str) -> PostingDetail:
            return PostingDetail(description_text=html)

        def absolute_url(self, ref: str) -> str:
            return f"https://stub.test{ref}"

    site = StubSite()
    assert isinstance(site, SiteCollector)


def test_the_interface_carries_no_education_field() -> None:
    """S15P21E102-99 puts education and graduation status out of scope.

    Asserted so a later change has to argue with the ticket rather than
    quietly widen what gets stored.
    """

    assert not hasattr(PostingDetail(), "education")
    assert not hasattr(
        ListingRow(source_posting_id="x", detail_ref="/", title="t"), "education"
    )
