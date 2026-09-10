"""Run C2 against a topic, or inspect what one message resolves to.

`--dry-run` is the mode that makes this skeleton verifiable before AI팀's
judgement and BE's table exist: it resolves messages for real — including the
Claim Check read from HDFS — and reports the fan-out instead of storing
anything. That covers the part A조 owns.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Sequence

from common.kafka import consumer_from_env
from common.webhdfs import WebHdfsClient, parse_datanode_hosts

from extractor.consumer import ExtractorConsumer, Outcome
from extractor.contracts import C2_TOPICS, FactRecord, ResolvedRecord
from extractor.resolve import RecordResolver

DEFAULT_GROUP = "gitjob-extractor"


class CountingSeam:
    """Stands in for AI팀's judgement: one fact per record, no opinion.

    Enough to exercise the fan-out and the upsert key without pretending to
    decide anything about technology.
    """

    dict_version: str = "dry-run"

    def extract(self, record: ResolvedRecord) -> Sequence[FactRecord]:
        return [
            FactRecord(
                source=record.source,
                source_id=record.source_id,
                dict_version=self.dict_version,
                payload={"resolved": True},
                origin=record.origin,
            )
        ]


class InMemoryStore:
    """Keeps the last write per key, which is what an upsert means."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, str], FactRecord] = {}

    def upsert(self, facts: Sequence[FactRecord]) -> int:
        for fact in facts:
            self.rows[fact.key] = fact
        return len(facts)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m extractor",
        description="C2 Extractor: consume, resolve, extract, upsert.",
    )
    parser.add_argument(
        "--topic",
        required=True,
        choices=C2_TOPICS,
        help="one topic per process; `-102` §2.3 lists the three",
    )
    parser.add_argument("--group-id", default=DEFAULT_GROUP)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "resolve and count without storing, and without committing. Use "
            "this to check the Claim Check fan-out against real messages"
        ),
    )
    parser.add_argument(
        "--max-polls",
        type=int,
        default=1,
        help="stop after this many polls (default: 1)",
    )
    parser.add_argument("--poll-timeout-ms", type=int, default=5_000)
    parser.add_argument(
        "--dlq-topic", default=os.environ.get("KAFKA_TOPIC_EXTRACTOR_DLQ")
    )
    return parser


def webhdfs_from_env() -> WebHdfsClient | None:
    """The same switch the Raw sink uses: no URL means no HDFS."""

    base_url = (os.environ.get("WEBHDFS_URL") or "").strip()
    if not base_url:
        return None
    return WebHdfsClient(
        base_url=base_url,
        user=(os.environ.get("WEBHDFS_USER") or "hadoop").strip() or "hadoop",
        datanode_hosts=parse_datanode_hosts(os.environ.get("WEBHDFS_DATANODE_HOSTS")),
    )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    arguments = build_parser().parse_args(argv)

    transport = consumer_from_env(arguments.topic, arguments.group_id)
    if transport is None:
        print(
            json.dumps(
                {"topic": arguments.topic, "reason": "KAFKA_BOOTSTRAP_SERVERS 미설정"}
            ),
            file=sys.stderr,
        )
        return 0

    store = InMemoryStore()
    consumer = ExtractorConsumer(
        transport=transport,
        resolver=RecordResolver(client=webhdfs_from_env()),
        seam=CountingSeam(),
        store=store,
        dlq_topic=None if arguments.dry_run else arguments.dlq_topic,
        poll_timeout_ms=arguments.poll_timeout_ms,
    )

    try:
        polls = 0
        while polls < arguments.max_polls:
            messages = transport.poll(arguments.poll_timeout_ms)
            polls += 1
            if not messages:
                continue
            for message in messages:
                consumer.handle(message)
            # A dry run must not move the group's position: it is an
            # inspection, and inspecting a topic should not consume it.
            if not arguments.dry_run and Outcome.RETRY.value not in consumer.tally:
                transport.commit()
    finally:
        transport.close()

    print(
        json.dumps(
            {
                "topic": arguments.topic,
                "dry_run": arguments.dry_run,
                "outcomes": consumer.tally,
                "distinct_fact_keys": len(store.rows),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
