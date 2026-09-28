"""JobKorea v3 active-scope producer regressions (S15P21E102-335).

The v3 run that produced `JOBKOREA-ACTIVE-2026-09-15-50b4a6593c62` only existed
as an operational patch outside the repository. These tests pin the three
defects that audit found in that patch, so the official producer cannot ship
with them:

1. ``posted_at`` was widened to ``datetime | None`` while ``posted_at.date()``
   stayed unguarded.
2. An empty first page was recorded as the terminal ``empty_page`` reason, so a
   blocked scope counted as complete and the snapshot still claimed
   ``all_scopes_complete``.
3. ``COLLECTOR_VERSION`` was a single constant, so a legacy ``date_range`` run
   also stamped ``jobkorea-crawler/v3``.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime

import pytest

from job.contracts import BodyStatus
from job.jobkorea_contract import _TERMINAL_SCOPE_REASONS as contract_terminal_reasons
from job.jobkorea_contract import JOBKOREA_V3_DUTY_ROLE_PAIRS, active_snapshot_metadata
from JobKorea_Collector_V1.adapter import (
    listing_row_from_jobkorea,
    normalize_jobkorea_posting,
)
from JobKorea_Collector_V1.crawler import (
    TERMINAL_SCOPE_REASONS,
    CollectionMode,
    CrawlConfig,
    JobKoreaCrawler,
    build_arg_parser,
    collector_version_for,
    config_from_args,
)
from JobKorea_Collector_V1.dates import SEOUL
from JobKorea_Collector_V1.duties import resolve_duty_preset
from JobKorea_Collector_V1.parser import DetailContent, JobListItem


def listing_item(**overrides: object) -> JobListItem:
    """One listing row; overrides keep each test's intent on one line."""

    fields: dict[str, object] = {
        "posting_id": "49872974",
        "source_url": "https://www.jobkorea.co.kr/Recruit/GI_Read/49872974",
        "company_name": "㈜그린플로우",
        "title": "[경력] 웹 개발자 모집",
        "raw_job_category": "서버관리, SI개발",
        "career_level": "경력5년↑",
        "region": "경기 군포시",
        "posted_label": "08/25(화) 등록",
        "deadline_label": "~08/31(월)",
    }
    fields.update(overrides)
    return JobListItem(**fields)  # type: ignore[arg-type]


def test_an_unparsed_registration_label_keeps_posted_on_empty() -> None:
    """An active listing whose label did not parse must not crash the adapter.

    ``ListingRow.posted_on`` is ``date | None`` and the shared normalizer maps
    ``None`` through to ``posted_at=None``, so the honest value is absent --
    never a guessed date.
    """

    row = listing_row_from_jobkorea(listing_item(posted_label=None), posted_at=None)

    assert row.posted_on is None


def test_a_parsed_registration_label_still_becomes_posted_on() -> None:
    posted_at = datetime(2026, 8, 25, 9, 30, tzinfo=SEOUL)

    row = listing_row_from_jobkorea(listing_item(), posted_at=posted_at)

    assert row.posted_on == posted_at.date()


def test_normalizing_an_undated_active_posting_reports_no_posted_at() -> None:
    """The whole adapter path, not just the listing row, tolerates ``None``.

    This is the production shape: v3 selects the posting, the detail page has
    no registration label either, and the record must still normalize with an
    absent ``posted_at`` rather than a fabricated one.
    """

    record = normalize_jobkorea_posting(
        item=listing_item(posted_label=None),
        detail=DetailContent(
            description_text="Python 백엔드 개발",
            body_status=BodyStatus.TEXT_AVAILABLE.value,
            has_images=False,
            deadline_label=None,
        ),
        description_text="Python 백엔드 개발",
        image_sources=(),
        posted_at=None,
        deadline=None,
        collected_at=datetime(2026, 9, 15, 7, 33, tzinfo=SEOUL),
        detail_fetched=True,
        detail_error=None,
    )

    assert record.posted_at is None


def test_a_date_range_run_is_stamped_v2() -> None:
    """The legacy mode keeps its own version. A v3 stamp here is a lie.

    `job.collector.analysis_input` and `job.jobkorea_contract` both admit a
    snapshot as v3 only when the version says so, so a legacy run wearing the
    v3 stamp is a legacy batch presented for v3 validation.
    """

    assert collector_version_for(CollectionMode.DATE_RANGE) == "jobkorea-crawler/v2"


def test_an_active_listing_run_is_stamped_v3() -> None:
    assert (
        collector_version_for(CollectionMode.ACTIVE_LISTING) == "jobkorea-crawler/v3"
    )


def test_the_service_roles_preset_is_sixteen_duties_over_five_roles() -> None:
    """The v3 population is a fixed list, so its size is part of the contract.

    `JOBKOREA-ACTIVE-2026-09-15-50b4a6593c62` was collected over these 16 duty
    codes. A scope added or dropped silently would change the population while
    the snapshot still called itself the same thing.
    """

    scopes = resolve_duty_preset("service-roles")

    assert len(scopes) == 16
    assert len({scope.code for scope in scopes}) == 16
    assert {scope.target_role for scope in scopes} == {
        "BACKEND",
        "FRONTEND",
        "AI_DATA",
        "INFRASTRUCTURE",
        "MOBILE",
    }


def test_each_target_role_keeps_its_measured_duty_count() -> None:
    counts = Counter(scope.target_role for scope in resolve_duty_preset("service-roles"))

    assert counts == Counter(
        {
            "AI_DATA": 8,
            "INFRASTRUCTURE": 5,
            "BACKEND": 1,
            "FRONTEND": 1,
            "MOBILE": 1,
        }
    )


def test_an_unknown_preset_is_refused_rather_than_silently_empty() -> None:
    with pytest.raises(ValueError, match="unknown duty preset"):
        resolve_duty_preset("no-such-preset")


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

EMPTY_LIST_HTML = """
<div id="dev-gi-list">
  <div class="tplList tplJobList"><table><tbody></tbody></table></div>
</div>
"""


class ScopedListClient:
    """A list-only client that answers per duty code.

    ``pages`` maps a duty code to the HTML for page 1, 2, ... Any page past
    the end of a code's list answers empty, which is how the real site ends a
    scope. A code missing from the map answers empty on page 1, which is how a
    blocked or re-skinned scope looks.
    """

    def __init__(self, pages: dict[str, list[str]]) -> None:
        self.pages = pages
        self.requested: list[tuple[str, int]] = []

    def post(
        self,
        _path: str,
        data: list[tuple[str, str]],
        **_kwargs: object,
    ) -> str:
        fields = dict(data)
        duty = fields["condition[duty]"]
        page = int(fields["page"])
        self.requested.append((duty, page))
        pages = self.pages.get(duty, [])
        if page - 1 < len(pages):
            return pages[page - 1]
        return EMPTY_LIST_HTML

    def get(self, *_args: object, **_kwargs: object) -> str:  # pragma: no cover
        raise AssertionError("a list-only run must not fetch details")


def active_config(**overrides: object) -> CrawlConfig:
    fields: dict[str, object] = {
        "start_date": date(2026, 9, 15),
        "end_date": date(2026, 9, 15),
        "collection_mode": CollectionMode.ACTIVE_LISTING,
        "duty_scopes": resolve_duty_preset("service-roles")[:2],
        "fetch_details": False,
        "ocr_images": False,
        "request_delay": 0,
        "detail_delay": 0,
        "max_pages": 5,
        "now": datetime(2026, 9, 15, 7, 33, tzinfo=SEOUL),
    }
    fields.update(overrides)
    return CrawlConfig(**fields)  # type: ignore[arg-type]


def test_a_scope_whose_first_page_is_empty_cannot_report_all_scopes_complete() -> None:
    """The defect that would have shipped: a blocked scope counting as done.

    `job.jobkorea_contract` treats ``short_page`` and ``empty_page`` as
    terminal, so recording an empty *first* page as ``empty_page`` would let a
    scope that returned nothing pass as complete and the run still claim the
    full 16-duty population. An empty first page is not an exhausted list --
    it is a scope that never answered.
    """

    config = active_config()
    backend, frontend = config.duty_scopes
    client = ScopedListClient({backend.code: [LIST_HTML]})

    result = JobKoreaCrawler(config, client=client).run()

    stats = result.manifest["stats"]
    assert stats["scan_stop_reason"] != "all_scopes_complete"
    reasons = {
        scope["code"]: scope["scan_stop_reason"]
        for scope in result.manifest["source"]["duty_scopes"]
    }
    assert reasons[frontend.code] == "first_page_empty"
    assert reasons[backend.code] in {"short_page", "empty_page"}


def test_a_scope_that_runs_out_on_a_later_page_is_a_normal_ending() -> None:
    """``empty_page`` stays terminal from page 2 on -- that is an exhausted list.

    The fix for the first page must not make every empty page suspicious, or a
    scope whose posting count is an exact multiple of the page size could never
    report complete.
    """

    config = active_config(page_size=1, max_pages=5)
    backend, frontend = config.duty_scopes
    client = ScopedListClient(
        {backend.code: [LIST_HTML], frontend.code: [LIST_HTML]}
    )

    result = JobKoreaCrawler(config, client=client).run()

    reasons = {
        scope["code"]: scope["scan_stop_reason"]
        for scope in result.manifest["source"]["duty_scopes"]
    }
    assert reasons == {backend.code: "empty_page", frontend.code: "empty_page"}
    assert result.manifest["stats"]["scan_stop_reason"] == "all_scopes_complete"


def test_a_completed_scoped_run_satisfies_the_v3_consumer_contract() -> None:
    """The producer's manifest must pass `active_snapshot_metadata` unchanged.

    This is the whole point of the Jira: the consumer half already shipped in
    S15P21E102-289, so the producer is correct only if that validator admits
    its output without being modified.
    """

    scopes = resolve_duty_preset("service-roles")
    config = active_config(duty_scopes=scopes, page_size=1, max_pages=5)
    client = ScopedListClient({scope.code: [LIST_HTML] for scope in scopes})

    result = JobKoreaCrawler(config, client=client).run()
    metadata = active_snapshot_metadata(result.manifest)

    assert metadata is not None
    assert metadata.complete is True
    assert metadata.scope_key is not None


def test_the_producer_duty_pairs_are_the_pairs_the_consumer_expects() -> None:
    """`active_snapshot_metadata` admits a snapshot only on the exact 16 pairs.

    So the producer's duty table is not merely similar to the consumer's --
    it has to be the same set, or a fully collected run is still refused.
    """

    produced = frozenset(
        (scope.code, scope.target_role)
        for scope in resolve_duty_preset("service-roles")
    )

    assert produced == JOBKOREA_V3_DUTY_ROLE_PAIRS


def test_a_blocked_scope_is_refused_by_the_v3_consumer_contract() -> None:
    config = active_config()
    backend, _frontend = config.duty_scopes
    client = ScopedListClient({backend.code: [LIST_HTML]})

    result = JobKoreaCrawler(config, client=client).run()
    metadata = active_snapshot_metadata(result.manifest)

    assert metadata is None or metadata.complete is False


def test_a_posting_listed_under_two_scopes_is_collected_once() -> None:
    """9,128 raw rows became 5,859 distinct postings by this rule.

    Both scopes return the same posting id, so the raw row count sees it twice
    and the record count must see it once.
    """

    config = active_config(page_size=1, max_pages=5)
    backend, frontend = config.duty_scopes
    client = ScopedListClient(
        {backend.code: [LIST_HTML], frontend.code: [LIST_HTML]}
    )

    result = JobKoreaCrawler(config, client=client).run()

    stats = result.manifest["stats"]
    assert stats["raw_rows_seen"] == 2
    assert stats["unique_rows_seen"] == 1
    assert stats["cross_scope_duplicates"] == 1
    assert len(result.batch.records) == 1


def test_a_scoped_run_stamps_v3_in_the_manifest_and_the_batch() -> None:
    config = active_config(page_size=1, max_pages=5)
    backend, frontend = config.duty_scopes
    client = ScopedListClient(
        {backend.code: [LIST_HTML], frontend.code: [LIST_HTML]}
    )

    result = JobKoreaCrawler(config, client=client).run()

    assert result.manifest["collector_version"] == "jobkorea-crawler/v3"
    assert result.batch.collector_version == "jobkorea-crawler/v3"
    assert result.manifest["source"]["mode"] == "active_listing"


def test_a_legacy_run_keeps_the_category_mode_and_v2_stamp() -> None:
    """The legacy manifest shape is unchanged: no duty_scopes block, v2, category."""

    config = CrawlConfig(
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 31),
        page_size=1,
        max_pages=5,
        fetch_details=False,
        ocr_images=False,
        request_delay=0,
        detail_delay=0,
        now=datetime(2026, 9, 3, 12, 0, tzinfo=SEOUL),
    )
    client = ScopedListClient({config.duty_code: [LIST_HTML]})

    result = JobKoreaCrawler(config, client=client).run()

    assert result.manifest["collector_version"] == "jobkorea-crawler/v2"
    assert result.manifest["source"]["mode"] == "category"
    assert "duty_scopes" not in result.manifest["source"]
    assert active_snapshot_metadata(result.manifest) is None


def test_the_producer_and_consumer_agree_on_which_reasons_are_terminal() -> None:
    """A drift here silently changes what "complete" means for a snapshot."""

    assert TERMINAL_SCOPE_REASONS == contract_terminal_reasons


def test_the_duty_preset_flag_configures_a_v3_run() -> None:
    """The v3 producer has to be startable from the official CLI.

    Without this the only way to run it is the ad-hoc script the operational
    patch used, which is the reproducibility gap this Jira closes.
    """

    args = build_arg_parser().parse_args(["--duty-preset", "service-roles"])
    config = config_from_args(args)

    assert config.collection_mode is CollectionMode.ACTIVE_LISTING
    assert len(config.duty_scopes) == 16
    assert config.collector_version == "jobkorea-crawler/v3"


def test_the_legacy_cli_stays_a_date_range_run() -> None:
    args = build_arg_parser().parse_args(["--duty-code", "1000229", "--days-back", "1"])
    config = config_from_args(args)

    assert config.collection_mode is CollectionMode.DATE_RANGE
    assert config.duty_scopes == ()
    assert config.collector_version == "jobkorea-crawler/v2"


def test_an_unknown_cli_preset_fails_before_any_request() -> None:
    args = build_arg_parser().parse_args(["--duty-preset", "no-such-preset"])

    with pytest.raises(ValueError, match="unknown duty preset"):
        config_from_args(args)
