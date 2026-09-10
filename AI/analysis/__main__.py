"""`python -m analysis` — the repository analysis consumer process.

Kept out of `worker/`, which runs an HTTP compute API. A consumer and a web
service fail, restart and scale differently, so they are separate Compose
services on the same image, the way `collector` and `worker` already are.

Refuses to start when Kafka, the database or the claim table is missing. A
consumer that silently idles because one environment variable is unset looks
identical to a quiet topic, and that is discovered days later.
"""

from __future__ import annotations

import logging
import os
import sys

from analysis.claim import ClaimStore, connect, dsn_from_env
from analysis.clone import RepositoryCloner
from analysis.consumer import AnalysisConsumer, work_root_from_env
from analysis.manifests import ManifestScanner
from analysis.parse import RepositoryParser, verify_grammars
from analysis.publish import ResultPublisher
from analysis.rules import RegistryStore
from common.kafka import consumer_from_env, transport_from_env

DEFAULT_TOPIC = "gitjob.repository-analysis.requests.v1"
DEFAULT_GROUP = "gitjob-repository-analysis"
# Its own dead letter topic. C's worker publishes a different payload shape to
# KAFKA_TOPIC_ANALYSIS_DLQ, and mixing the two leaves whoever drains it guessing.
DEFAULT_DLQ_TOPIC = "gitjob.repository-analysis.dlq.v1"
# The only path by which an analysis finishes. Without it analysis_job stays
# at QUEUED however well the worker did its job.
DEFAULT_RESULTS_TOPIC = "gitjob.repository-analysis.results.v1"


def build() -> AnalysisConsumer:
    topic = (
        os.getenv("KAFKA_TOPIC_REPOSITORY_ANALYSIS_REQUESTS") or DEFAULT_TOPIC
    ).strip()
    group = (os.getenv("ANALYSIS_CONSUMER_GROUP") or DEFAULT_GROUP).strip()

    transport = consumer_from_env(topic, group)
    if transport is None:
        raise SystemExit("KAFKA_BOOTSTRAP_SERVERS is not set; nothing to consume")

    dsn = dsn_from_env()
    if dsn is None:
        raise SystemExit("POSTGRES_* is not fully set; the claim store is required")
    claims = ClaimStore(dsn, lease_seconds=_int("ANALYSIS_CLAIM_LEASE_SECONDS", 900))
    if not claims.ready():
        raise SystemExit(
            "repo_analysis.event_claim is missing; apply "
            "BE/src/main/resources/db/migrations/002_repo_analysis.sql first"
        )

    # Grammars are loaded here rather than on first use. A missing wheel would otherwise
    # raise inside _parse_file, which catches per file: every source becomes a
    # parse_error, the run reports zero imports, and that is indistinguishable from a
    # repository with nothing to parse.
    try:
        verify_grammars()
    except Exception as missing:
        raise SystemExit(f"tree-sitter grammars are not loadable: {missing}") from missing

    work_root = work_root_from_env()
    work_root.mkdir(parents=True, exist_ok=True)
    cloner = RepositoryCloner(
        work_root=work_root,
        github_base_url=os.getenv("GITHUB_CLONE_BASE_URL", "https://github.com"),
        timeout_seconds=_int("ANALYSIS_CLONE_TIMEOUT_SECONDS", 600),
        max_bytes=_int("ANALYSIS_MAX_REPOSITORY_BYTES", 2 * 1024 * 1024 * 1024),
    )

    dlq_topic = (
        os.getenv("KAFKA_TOPIC_REPOSITORY_ANALYSIS_DLQ") or DEFAULT_DLQ_TOPIC
    ).strip() or None
    parser = RepositoryParser(
        max_file_bytes=_int("ANALYSIS_MAX_FILE_BYTES", 1024 * 1024),
        max_files=_int("ANALYSIS_MAX_FILES", 50_000),
    )
    scanner = ManifestScanner(
        max_file_bytes=_int("ANALYSIS_MAX_MANIFEST_BYTES", 512 * 1024),
        max_manifests=_int("ANALYSIS_MAX_MANIFESTS", 500),
    )
    # The worker reads the registry; it never writes it. The version comes from
    # each event, so a deployment that overlaps two versions serves both.
    registry = RegistryStore(connect=lambda: connect(dsn))

    results_topic = (
        os.getenv("KAFKA_TOPIC_REPOSITORY_ANALYSIS_RESULTS") or DEFAULT_RESULTS_TOPIC
    ).strip()
    results_transport = transport_from_env(default_client_id="gitjob-analysis-results")
    if results_transport is None:
        raise SystemExit("KAFKA_BOOTSTRAP_SERVERS is not set; results cannot be published")
    results = ResultPublisher(results_transport, results_topic)

    return AnalysisConsumer(
        transport=transport,
        claims=claims,
        cloner=cloner,
        parser=parser,
        scanner=scanner,
        registry=registry,
        results=results,
        dlq_topic=dlq_topic,
        max_attempts=_int("ANALYSIS_MAX_ATTEMPTS", 5),
        dlq_transport=(
            transport_from_env(default_client_id="gitjob-analysis-dlq")
            if dlq_topic
            else None
        ),
    )


def _int(name: str, default: int) -> int:
    try:
        value = int((os.getenv(name) or "").strip())
    except ValueError:
        return default
    return value if value > 0 else default


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    consumer = build()
    consumer.install_signal_handlers()
    consumer.run()


if __name__ == "__main__":
    main()
