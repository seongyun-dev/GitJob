"""Local-only Kafka/PostgreSQL lease recovery with real Git and tree-sitter.

The broker and database must be selected explicitly. The test refuses non-loopback
endpoints and creates a unique topic/group. Topic deletion is opt-in because the
native Windows Kafka validation runtime cannot safely rename deleted log dirs.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import psycopg
import pytest
from kafka import KafkaAdminClient, KafkaProducer
from kafka.admin import NewTopic

from analysis.claim import ClaimStatus, ClaimStore
from analysis.clone import RepositoryCloner
from analysis.consumer import AnalysisConsumer, ClaimBusyError
from analysis.parse import RepositoryParser
from common.kafka import KafkaPythonConsumer

TEST_DSN = os.getenv("ANALYSIS_TEST_POSTGRES_DSN")
TEST_BROKER = os.getenv("ANALYSIS_TEST_KAFKA_BOOTSTRAP")
DELETE_TOPIC = os.getenv("ANALYSIS_TEST_KAFKA_DELETE_TOPIC") == "1"


def _loopback_only() -> bool:
    if not TEST_DSN or not TEST_BROKER:
        return False
    database_host = urlparse(TEST_DSN).hostname
    broker_host = TEST_BROKER.rsplit(":", 1)[0]
    return database_host in {"127.0.0.1", "localhost"} and broker_host in {
        "127.0.0.1",
        "localhost",
    }


pytestmark = pytest.mark.skipif(
    not _loopback_only(),
    reason=(
        "ANALYSIS_TEST_POSTGRES_DSN and ANALYSIS_TEST_KAFKA_BOOTSTRAP must select "
        "explicit loopback test services"
    ),
)


def _git(*args: str, cwd: Path) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _origin(tmp_path: Path) -> tuple[Path, str]:
    base = tmp_path / "remotes"
    origin = base / "owner" / "repo.git"
    origin.mkdir(parents=True)
    _git("init", "--quiet", "--initial-branch=main", ".", cwd=origin)
    _git("config", "user.email", "test@example.com", cwd=origin)
    _git("config", "user.name", "Test", cwd=origin)
    (origin / "app.ts").write_text(
        "import express = require('express');\n", encoding="utf-8"
    )
    _git("add", ".", cwd=origin)
    _git("commit", "--quiet", "-m", "fixture", cwd=origin)
    return base, _git("rev-parse", "HEAD", cwd=origin)


def _event(event_id: str, analysis_id: str, commit_sha: str) -> bytes:
    return json.dumps(
        {
            "event_id": event_id,
            "schema_version": "repository-analysis-request/v1",
            "event_type": "repository.analysis.requested",
            "occurred_at": "2026-09-09T00:00:00Z",
            "trace_id": f"tr_{event_id}",
            "payload": {
                "analysis_id": analysis_id,
                "analysis_repository_id": f"ar_{analysis_id}",
                "github_repository_id": 1,
                "repository_full_name": "owner/repo",
                "branch_name": "main",
                "commit_sha": commit_sha,
                "analysis_mode": "SNAPSHOT",
                "registry_version": "technology-registry/v1",
            },
        }
    ).encode("utf-8")


class CountingCloner(RepositoryCloner):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.calls: list[str] = []

    def fetch(self, full_name: str, commit_sha: str, into: str):
        self.calls.append(into)
        return super().fetch(full_name, commit_sha, into)


class BoundedConsumerTransport:
    """Delegate to Kafka, stopping only after the requested durable commits."""

    def __init__(
        self, inner: KafkaPythonConsumer, stop_after_commits: int | None = None
    ):
        self.inner = inner
        self.stop_after_commits = stop_after_commits
        self.owner: AnalysisConsumer | None = None
        self.commits = 0
        self.empty_polls = 0

    def poll(self, timeout_ms: int):
        messages = self.inner.poll(timeout_ms)
        if messages:
            self.empty_polls = 0
        else:
            self.empty_polls += 1
            if self.empty_polls >= 20:
                raise AssertionError("timed out waiting for the test topic")
        return messages

    def commit(self) -> None:
        self.inner.commit()
        self.commits += 1
        if self.stop_after_commits == self.commits:
            assert self.owner is not None
            self.owner.stop()

    def close(self) -> None:
        self.inner.close()


def _consumer(
    topic: str,
    group: str,
    claims: ClaimStore,
    cloner: CountingCloner,
    *,
    stop_after_commits: int | None = None,
) -> tuple[AnalysisConsumer, BoundedConsumerTransport]:
    real = KafkaPythonConsumer(
        bootstrap_servers=(TEST_BROKER,),
        topic=topic,
        group_id=group,
        max_poll_interval_ms=60_000,
        session_timeout_ms=6_000,
    )
    transport = BoundedConsumerTransport(real, stop_after_commits)
    consumer = AnalysisConsumer(
        transport=transport,
        claims=claims,
        cloner=cloner,
        parser=RepositoryParser(),
        poll_timeout_ms=500,
    )
    transport.owner = consumer
    return consumer, transport


def _poll_claim_and_wait_for_kill(
    topic: str,
    group: str,
    dsn: str,
    broker: str,
    ready,
    blocker,
) -> None:
    """Child process: take both Kafka delivery and SQL lease, but commit neither."""

    transport = KafkaPythonConsumer(
        bootstrap_servers=(broker,),
        topic=topic,
        group_id=group,
        max_poll_interval_ms=60_000,
        session_timeout_ms=6_000,
    )
    claims = ClaimStore(dsn, lease_seconds=60)
    for _ in range(20):
        messages = transport.poll(500)
        if not messages:
            continue
        request = json.loads(messages[0].value)
        claim = claims.claim(request["event_id"], request["payload"]["analysis_id"])
        if claim.status is not ClaimStatus.ACQUIRED:
            raise AssertionError(f"child could not acquire initial lease: {claim}")
        ready.set()
        # The parent uses Process.kill(), modeling SIGKILL/forced container
        # termination. This wait must never complete normally.
        blocker.wait(60)
        raise AssertionError("child was not force-killed")
    raise AssertionError("child timed out waiting for the first Kafka record")


def test_busy_redelivery_survives_until_lease_takeover_and_preserves_order(tmp_path):
    suffix = uuid4().hex
    topic = f"mr46-review-{suffix}"
    group = f"mr46-review-{suffix}"
    event_one = f"ev_{suffix}_1"
    event_two = f"ev_{suffix}_2"
    analysis_one = f"an_{suffix}_1"
    analysis_two = f"an_{suffix}_2"
    claims = ClaimStore(TEST_DSN, lease_seconds=60)
    base, commit_sha = _origin(tmp_path)
    cloner = CountingCloner(
        work_root=tmp_path / "work",
        github_base_url=str(base),
    )
    cloner.work_root.mkdir()
    admin = KafkaAdminClient(
        bootstrap_servers=TEST_BROKER,
        client_id=f"{group}-admin",
    )
    killed_process = None

    try:
        admin.create_topics([NewTopic(topic, num_partitions=1, replication_factor=1)])
        producer = KafkaProducer(bootstrap_servers=TEST_BROKER, acks="all")
        first_message = _event(event_one, analysis_one, commit_sha)
        second_message = _event(event_two, analysis_two, commit_sha)
        for value in (first_message, second_message, first_message):
            producer.send(topic, key=analysis_one.encode(), value=value).get(timeout=10)
        producer.close(timeout=10)

        # A separate process consumes and commits the SQL claim, then is killed
        # before clone or Kafka commit. No Python finally/close path runs.
        process_context = multiprocessing.get_context("spawn")
        ready = process_context.Event()
        blocker = process_context.Event()
        killed_process = process_context.Process(
            target=_poll_claim_and_wait_for_kill,
            args=(topic, group, TEST_DSN, TEST_BROKER, ready, blocker),
        )
        killed_process.start()
        assert ready.wait(15), "child did not consume and claim the first event"
        killed_process.kill()
        killed_process.join(timeout=10)
        assert not killed_process.is_alive()
        assert killed_process.exitcode != 0

        before_expiry, first_transport = _consumer(topic, group, claims, cloner)
        with pytest.raises(ClaimBusyError):
            before_expiry.run()
        assert first_transport.commits == 0
        assert cloner.calls == []

        redelivered, second_transport = _consumer(topic, group, claims, cloner)
        with pytest.raises(ClaimBusyError):
            redelivered.run()
        assert second_transport.commits == 0
        assert cloner.calls == []

        with psycopg.connect(TEST_DSN) as connection:
            connection.execute(
                """
                UPDATE repo_analysis.event_claim
                SET claimed_at = clock_timestamp() - interval '61 seconds'
                WHERE event_id = %s
                """,
                (event_one,),
            )

        recovered, recovered_transport = _consumer(
            topic,
            group,
            claims,
            cloner,
            stop_after_commits=3,
        )
        recovered.run()

        assert recovered_transport.commits == 3
        assert len(cloner.calls) == 2
        assert claims.claim(event_one, analysis_one).status is ClaimStatus.TERMINAL
        assert claims.claim(event_two, analysis_two).status is ClaimStatus.TERMINAL
    finally:
        if killed_process is not None and killed_process.is_alive():
            killed_process.kill()
            killed_process.join(timeout=10)
        with psycopg.connect(TEST_DSN) as connection:
            connection.execute(
                "DELETE FROM repo_analysis.event_claim WHERE event_id IN (%s, %s)",
                (event_one, event_two),
            )
        try:
            if DELETE_TOPIC:
                admin.delete_topics([topic], timeout_ms=10_000)
        finally:
            admin.close()
