"""Cross-site canonical identity for Current Market (S15P21E102-352).

The same job is posted to both JobKorea and Saramin under different
`source_posting_id`s, so Current Market counted it twice. There is no business
number, company id, employment type or canonical URL in
`job-analysis-input/v1`, so a hard identity key cannot be built. What is left
is a deterministic rule over the fields that do exist, tuned on the published
2026-09-19 population and kept deliberately narrow: it merges only when every
condition holds, and leaves everything else as two postings.

Fuzzy title similarity is **not** a merge condition. In the measured data the
0.80-0.90 band mixed different roles at the same company, so only an exact
match after normalisation counts.
"""

from __future__ import annotations

from datetime import UTC, datetime

from job.cross_site_identity import (
    canonical_identities,
    normalize_company,
    normalize_title,
    region_compatible,
)


class Row:
    """Minimal stand-in for CohortJob/CohortExclusion: only what the rule reads."""

    def __init__(self, site, pid, company, title, region, deadline):
        self.source_site = site
        self.source_posting_id = pid
        self.company_name = company
        self.title = title
        self.region = region
        self.deadline = deadline


def day(text):
    if text is None:
        return None
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def jk(
    pid,
    company="세스코",
    title="AI Engineer 채용",
    region="서울 강동구",
    deadline="2026-09-30T00:00:00",
):
    return Row("JOBKOREA", pid, company, title, region, day(deadline))


def sa(
    pid,
    company="세스코",
    title="AI Engineer 채용",
    region="서울 강동구",
    deadline="2026-10-01T00:00:00",
):
    return Row("SARAMIN", pid, company, title, region, day(deadline))


# --- normalisation ------------------------------------------------------------


def test_company_normalisation_strips_legal_form_and_spacing():
    assert normalize_company("(주)세스코") == normalize_company("주식회사 세스코")
    assert normalize_company("㈜세스코") == normalize_company("세스코")
    assert normalize_company("Hecto Inc.") == normalize_company("HECTO")


def test_company_normalisation_keeps_distinct_companies_distinct():
    assert normalize_company("삼성전자") != normalize_company("삼성물산")


def test_title_normalisation_drops_measured_noise_but_keeps_the_role():
    assert normalize_title("[11번가] 데이터 엔지니어 (계약직)") == normalize_title(
        "데이터 엔지니어"
    )
    assert normalize_title("2026년 백엔드 개발자 채용") == normalize_title(
        "백엔드 개발자"
    )
    assert "백엔드" in normalize_title("백엔드 개발자 모집")


def test_title_normalisation_keeps_different_roles_apart():
    assert normalize_title("백엔드 개발자") != normalize_title("프론트엔드 개발자")


def test_region_prefix_compatibility():
    assert region_compatible("경기 성남시", "경기 성남시 분당구")
    assert region_compatible("경기 평택시 외", "경기 평택시")
    assert not region_compatible("서울 강남구", "부산 해운대구")
    assert region_compatible("서울 강남구", None) is False


# --- the merge rule -----------------------------------------------------------


def canonical_of(rows):
    return canonical_identities(rows)


def test_high_confidence_pair_merges():
    rows = [jk("A"), sa("B")]

    mapping = canonical_of(rows)

    assert mapping[("JOBKOREA", "A")] == mapping[("SARAMIN", "B")]


def test_pair_identity_is_unambiguous_when_posting_ids_contain_delimiters():
    rows = [
        jk("a|SARAMIN:b", company="회사 가"),
        sa("c", company="회사 가"),
        jk("a", company="회사 나"),
        sa("b|SARAMIN:c", company="회사 나"),
    ]

    mapping = canonical_of(rows)

    assert mapping[("JOBKOREA", "a|SARAMIN:b")] == mapping[("SARAMIN", "c")]
    assert mapping[("JOBKOREA", "a")] == mapping[
        ("SARAMIN", "b|SARAMIN:c")
    ]
    assert mapping[("JOBKOREA", "a|SARAMIN:b")] != mapping[("JOBKOREA", "a")]


def test_different_company_same_title_does_not_merge():
    rows = [jk("A", company="회사가"), sa("B", company="회사나")]

    assert canonical_of(rows) == {}


def test_same_company_different_role_does_not_merge():
    rows = [jk("A", title="백엔드 개발자"), sa("B", title="프론트엔드 개발자")]

    assert canonical_of(rows) == {}


def test_similar_but_not_exact_title_does_not_merge():
    """0.8-0.9 similarity was measured to mix different roles; exact only."""

    rows = [jk("A", title="백엔드 개발자"), sa("B", title="백엔드 개발자 리드")]

    assert canonical_of(rows) == {}


def test_deadline_more_than_three_days_apart_does_not_merge():
    rows = [
        jk("A", deadline="2026-09-30T00:00:00"),
        sa("B", deadline="2026-10-14T00:00:00"),
    ]

    assert canonical_of(rows) == {}


def test_deadline_pairing_is_stable_after_postgres_utc_round_trip():
    original = [
        Row(
            "JOBKOREA",
            "A",
            "씨엔씨네트웍스",
            "2026년 하반기 개발자 채용",
            "서울 금천구",
            datetime.fromisoformat("2026-10-18T23:59:59+09:00"),
        ),
        Row(
            "SARAMIN",
            "B",
            "(주)씨엔씨네트웍스",
            "2026년 하반기 개발자 채용",
            "서울 금천구",
            datetime.fromisoformat("2026-10-15T00:00:00+09:00"),
        ),
        Row(
            "SARAMIN",
            "C",
            "(주)씨엔씨네트웍스",
            "2026년 하반기 개발자 채용",
            "서울 금천구",
            datetime.fromisoformat("2026-10-16T00:00:00+09:00"),
        ),
    ]
    restored = [
        Row(
            row.source_site,
            row.source_posting_id,
            row.company_name,
            row.title,
            row.region,
            row.deadline.astimezone(UTC),
        )
        for row in original
    ]

    # Both Saramin rows remain candidates, so the ambiguous one-to-many group
    # is never merged before or after a PostgreSQL timestamptz round trip.
    assert canonical_of(original) == {}
    assert canonical_of(restored) == canonical_of(original)


def test_incompatible_region_does_not_merge():
    rows = [jk("A", region="서울 강동구"), sa("B", region="부산 해운대구")]

    assert canonical_of(rows) == {}


def test_many_to_one_does_not_merge():
    """Two JobKorea reposts against one Saramin posting: which one is it?"""

    rows = [
        jk("A", deadline="2026-09-30T00:00:00"),
        jk("A2", deadline="2026-09-29T00:00:00"),
        sa("B"),
    ]

    assert canonical_of(rows) == {}


def test_missing_deadline_does_not_merge():
    rows = [jk("A", deadline=None), sa("B")]

    assert canonical_of(rows) == {}


def test_missing_region_does_not_merge():
    rows = [jk("A", region=None), sa("B")]

    assert canonical_of(rows) == {}


def test_same_site_pairs_are_never_merged_here():
    """Same-source identity stays `input_union`'s job, not this module's."""

    rows = [jk("A"), jk("A2")]

    assert canonical_of(rows) == {}


def test_canonical_id_is_deterministic_and_order_independent():
    forward = canonical_of([jk("A"), sa("B")])
    backward = canonical_of([sa("B"), jk("A")])

    assert forward == backward
    assert set(forward.values()) == set(backward.values())


def test_three_sites_never_collapse_beyond_the_matched_pair():
    """An unmatched third posting keeps its own identity."""

    rows = [jk("A"), sa("B"), jk("C", title="플랫폼 엔지니어")]

    mapping = canonical_of(rows)

    assert ("JOBKOREA", "C") not in mapping
