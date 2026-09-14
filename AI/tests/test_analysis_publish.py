"""Building and sending the result event.

The contract itself is checked in `test_analysis_results.py`. What matters here
is that a real judgement fills it in correctly, and that the id is stable — a
takeover re-runs the same request, and a fresh id would make the backend write
the same evidence twice.
"""

from __future__ import annotations

import json

from analysis.contracts import RepositoryAnalysisRequest
from analysis.judge import Candidate, EvidenceFact, Fact, Judgement, Verdict
from analysis.manifests import DependencyOccurrence, DependencyReport
from analysis.parse import ImportOccurrence, ParseReport
from analysis.publish import (
    ResultPublisher,
    completed_result,
    failed_result,
    result_event_id,
)

SHA = "818c4136ea971c21674525f9053de0d9c7ad8cfe"


def request(event_id: str = "ev_1") -> RepositoryAnalysisRequest:
    return RepositoryAnalysisRequest.model_validate({
        "event_id": event_id,
        "schema_version": "repository-analysis-request/v1",
        "event_type": "repository.analysis.requested",
        "occurred_at": "2026-09-10T01:02:03Z",
        "trace_id": "tr_1",
        "payload": {
            "analysis_id": "an_1",
            "analysis_repository_id": "ar_1",
            "github_repository_id": 1,
            "repository_full_name": "octocat/gitjob",
            "branch_name": "main",
            "commit_sha": SHA,
            "analysis_mode": "SNAPSHOT",
            "registry_version": "registry-20260910.1",
        },
    })


def judgement() -> Judgement:
    fact = Fact(
        fact_type="IMPORT",
        fields={"MODULE": "org.springframework.boot.SpringApplication", "LANGUAGE": "java"},
        file="src/main/java/App.java",
        line=3,
        tech_ids=frozenset({"spring-boot"}),
    )
    return Judgement(
        verdicts=(Verdict("spring-boot", "L1", ("spring-boot.l1.import",)),),
        evidence=(EvidenceFact("spring-boot.l1.import", "spring-boot", fact),),
        candidates=(Candidate("MAVEN", "com.h2database:h2", "runtimeOnly", 2),),
    )


def reports() -> tuple[ParseReport, DependencyReport]:
    return (
        ParseReport(
            occurrences=(
                ImportOccurrence(
                    "org.springframework.boot.SpringApplication", "java", "JAVA",
                    "src/main/java/App.java", 3,
                ),
            ),
            files_parsed=50,
            files_skipped=82,
            bytes_parsed=1000,
        ),
        DependencyReport(
            occurrences=(
                DependencyOccurrence("MAVEN", "com.h2database:h2", "runtimeOnly",
                                     "build.gradle", 16),
            ),
            manifests_read=1,
        ),
    )


class FakeTransport:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[tuple[str, bytes | None, bytes]] = []
        self.fail = fail

    def send(self, topic: str, *, key: bytes | None, value: bytes) -> None:
        if self.fail:
            raise RuntimeError("broker is down")
        self.sent.append((topic, key, value))


# -- the event id -----------------------------------------------------------


def test_the_result_id_is_derived_from_the_request_so_a_retry_deduplicates():
    # A takeover re-runs the same request. A random id would make that a second
    # result for one analysis and the backend would write the evidence twice.
    assert result_event_id("ev_1") == result_event_id("ev_1")
    assert result_event_id("ev_1") != result_event_id("ev_2")


def test_a_long_request_id_still_yields_a_valid_identifier():
    # The contract caps identifiers at 80 characters.
    long_id = "ev_" + "a" * 77
    derived = result_event_id(long_id)

    assert len(derived) <= 80
    assert derived == result_event_id(long_id)


# -- a completed result -----------------------------------------------------


def test_a_completed_result_carries_the_verdicts_evidence_and_candidates(tmp_path):
    report, dependencies = reports()

    result = completed_result(request(), judgement(), report, dependencies)

    payload = result.payload
    assert payload.status == "COMPLETED"
    assert payload.analysis_id == "an_1"
    assert payload.request_event_id == "ev_1"
    assert payload.registry_version == "registry-20260910.1"
    assert payload.technologies[0].tech_id == "spring-boot"
    assert payload.evidence[0].file_path == "src/main/java/App.java"
    assert payload.evidence[0].start_line == 3
    assert payload.candidates[0].coordinate == "com.h2database:h2"
    assert result.trace_id == "tr_1"


def test_the_stats_come_from_the_two_extraction_stages():
    report, dependencies = reports()

    stats = completed_result(
        request(), judgement(), report, dependencies, bytes_on_disk=1932742
    ).payload.stats

    assert (stats.files_parsed, stats.files_skipped) == (50, 82)
    assert (stats.import_count, stats.dependency_count) == (1, 1)
    assert stats.bytes_on_disk == 1932742


def test_a_snippet_is_read_from_the_checkout_while_it_still_exists(tmp_path):
    # consumer.py deletes the checkout in its finally, so this is the only
    # chance. A private or rewritten repository cannot be rendered without it.
    source = tmp_path / "src/main/java"
    source.mkdir(parents=True)
    (source / "App.java").write_text(
        "package a;\n\nimport org.springframework.boot.SpringApplication;\n",
        encoding="utf-8",
    )
    report, dependencies = reports()

    result = completed_result(
        request(), judgement(), report, dependencies, checkout=tmp_path
    )

    assert result.payload.evidence[0].code_snippet == (
        "import org.springframework.boot.SpringApplication;"
    )


def test_a_missing_file_costs_the_snippet_and_nothing_else(tmp_path):
    # The permalink needs only the path and the line, which is why the contract
    # makes the snippet optional.
    report, dependencies = reports()

    result = completed_result(
        request(), judgement(), report, dependencies, checkout=tmp_path
    )

    assert result.payload.evidence[0].code_snippet is None
    assert result.payload.evidence[0].file_path == "src/main/java/App.java"


def test_no_checkout_means_no_snippets():
    report, dependencies = reports()

    result = completed_result(request(), judgement(), report, dependencies)

    assert result.payload.evidence[0].code_snippet is None


# -- a failed result --------------------------------------------------------


def test_a_failure_reaches_the_backend_rather_than_only_the_dlq():
    # analysis_job never leaves QUEUED otherwise, and the user waits forever.
    result = failed_result(request(), "REPOSITORY_NOT_FOUND", "git fetch: not found")

    assert result.payload.status == "FAILED"
    assert result.payload.error_code == "REPOSITORY_NOT_FOUND"
    assert result.payload.error_detail == "git fetch: not found"
    assert result.payload.technologies == ()


def test_a_long_error_detail_is_truncated_to_the_contract_limit():
    result = failed_result(request(), "CLONE_FAILED", "x" * 900)

    assert len(result.payload.error_detail) == 500


# -- sending ----------------------------------------------------------------


def test_publishing_sends_valid_json_keyed_by_the_analysis():
    # Keyed like the request topic, so every event for one analysis stays on
    # one partition and keeps its order.
    transport = FakeTransport()
    report, dependencies = reports()

    ResultPublisher(transport, "gitjob.repository-analysis.results.v1").publish(
        completed_result(request(), judgement(), report, dependencies)
    )

    topic, key, value = transport.sent[0]
    assert topic == "gitjob.repository-analysis.results.v1"
    assert key == b"an_1"
    body = json.loads(value)
    assert body["schema_version"] == "repository-analysis-result/v1"
    assert body["payload"]["analysis_id"] == "an_1"


def test_a_broker_failure_is_raised_rather_than_swallowed():
    # Unlike the DLQ, this topic is the only path by which an analysis
    # finishes. Losing a message here strands the job.
    transport = FakeTransport(fail=True)
    report, dependencies = reports()

    try:
        ResultPublisher(transport, "t").publish(
            completed_result(request(), judgement(), report, dependencies)
        )
    except RuntimeError as raised:
        assert "broker is down" in str(raised)
    else:  # pragma: no cover - the point of the test
        raise AssertionError("a failed publish must not be silent")


# -- line authorship --------------------------------------------------------


def test_authorship_rides_on_the_evidence_it_belongs_to():
    # 근거 한 줄과 그 줄을 쓴 커밋이 같은 항목에 있어야 BE 가 둘을 잇는다.
    report, dependencies = reports()
    blamed = {("src/main/java/App.java", 3): "b" * 40}

    result = completed_result(
        request(), judgement(), report, dependencies, authorship=blamed
    )

    assert result.payload.evidence[0].commit_sha == "b" * 40


def test_evidence_without_authorship_carries_none_not_a_guess():
    """얕은 클론이나 blame 실패의 결과다.

    여기서 다른 값을 채우면 BE 는 그것을 기여로 읽는다. 근거가 없다는 사실은
    없음으로 표현해야 한다.
    """
    report, dependencies = reports()

    result = completed_result(request(), judgement(), report, dependencies)

    assert result.payload.evidence[0].commit_sha is None


def test_authorship_for_other_lines_does_not_leak_onto_this_one():
    # (파일, 줄) 이 키다. 파일만 맞고 줄이 다르면 붙으면 안 된다.
    report, dependencies = reports()
    blamed = {("src/main/java/App.java", 99): "c" * 40}

    result = completed_result(
        request(), judgement(), report, dependencies, authorship=blamed
    )

    assert result.payload.evidence[0].commit_sha is None
