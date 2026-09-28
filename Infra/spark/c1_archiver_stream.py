"""C1 Archiver — Kafka envelopes to a columnar archive (S15P21E102-112).

C1 is the first of the two consumers `-102` §2.3 defines. It subscribes to
`github.events` and `so.raw`, and it does exactly one thing: it lands what
arrived, without interpreting it. Technology and requirement judgement is C2's,
and aggregation is C3's.

### Three decisions this file encodes, and why

**One streaming query per topic, each with its own checkpoint.** `-108`'s
completion condition was written as "the three groups hold independent
offsets", which cannot be checked with `--describe` once offsets live in a
Spark checkpoint (`-102` §5). Separate checkpoint directories are what makes
the property true *and* observable: `so.raw` keeps its position while
`github.events` is replayed, and each directory can be inspected on its own.

**No `kafka.group.id`.** `-102` §5 offers two ways to own an offset and
recommends the first: the checkpoint is the single source of truth. Setting a
group id as well would leave two records of progress and no rule for which one
a restart believes. Consequently `kafka-consumer-groups.sh --describe` shows
nothing for C1, and that is the intended state, not a defect.

**The payload stays opaque.** The envelope's own fields are promoted to
columns because they are the contract (`-103` §4.1); `payload` is carried
through as the JSON text that arrived. `repo_activity_topn.py` keeps the same
line — an archiver that parses payloads acquires a second schema to maintain
and a reason to fail on data it was only supposed to store.

### The cutoff guard, and why it does not silently drop

GH Archive reaches HDFS two ways: history goes straight to Raw as untouched
hourly files, and anything after `HISTORICAL_CUTOFF` comes through Kafka
(`-102` §2.4). `-144`'s completion condition is that no hour arrives on both
paths — an overlap is duplication, a gap is missing data.

So this job checks the boundary, but a record that fails the check is written
to a rejected path with its reason rather than discarded. Dropping would make
a producer whose boundary disagrees with ours look identical to a quiet
success, which is the failure mode `docs/data/README.md` §14.1 already cost
this project once.

### Where the output goes

`-112` did not name a path, so this one is a skeleton decision to confirm with
the `-110` Sink owner. The archive is written under `PARQUET_ROOT`, not under
`/gitjob/raw/`: Raw holds untouched source bytes — gzip hours and collector
run directories — and `-190`'s verification counts files there. Mixing
micro-batch Parquet into it would break that accounting for no gain.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

UTC = timezone.utc

# `-102` §2.3. C1 does not subscribe to `jobs.collected`: that event is
# published *after* the collector already wrote the run to Raw, so archiving it
# again would write the same files twice.
C1_TOPICS: tuple[str, ...] = ("github.events", "so.raw")

# `-102` §2.4. The boundary between GH Archive's batch path and its Kafka path.
HISTORICAL_CUTOFF = "2026-09-01T00:00:00Z"

# Only GH Archive has a batch path to collide with. Stack Overflow's dump
# (`-113`) is a separate ingest that does not publish to `so.raw`.
CUTOFF_SOURCES: tuple[str, ...] = ("gharchive",)

# `-103` §4.1. `event_id` and `trace_id` are recommended, not required, so a
# message without them is archived rather than rejected.
REQUIRED_ENVELOPE_FIELDS: tuple[str, ...] = (
    "schema_version",
    "source",
    "source_id",
    "event_type",
    "occurred_at",
    "ingested_at",
    "payload",
)

# The archive's columns, in order. Declared rather than inferred: see
# `_write_batch`. `dt` is last because it is the partition column.
ARCHIVE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("schema_version", "string"),
    ("source", "string"),
    ("source_id", "string"),
    ("event_type", "string"),
    ("event_id", "string"),
    ("trace_id", "string"),
    ("occurred_at", "string"),
    ("ingested_at", "string"),
    ("payload", "string"),
    ("kafka_topic", "string"),
    ("kafka_partition", "int"),
    ("kafka_offset", "long"),
    ("kafka_timestamp", "string"),
    ("raw_value", "string"),
    ("dt", "string"),
)

# A rejected record keeps its position and the reason, so the boundary that
# rejected it can be argued about without re-running anything.
REJECTED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("kafka_topic", "string"),
    ("kafka_partition", "int"),
    ("kafka_offset", "long"),
    ("reject_reason", "string"),
    ("raw_value", "string"),
    ("batch_id", "long"),
)

DEFAULT_PARQUET_ROOT = "hdfs:///gitjob/parquet"
DEFAULT_CHECKPOINT_ROOT = "hdfs:///gitjob/checkpoints"
ARCHIVE_PREFIX = "stream"
REJECTED_PREFIX = "_rejected"
CONSUMER = "c1"

__all__ = [
    "ARCHIVE_COLUMNS",
    "ARCHIVE_PREFIX",
    "C1_TOPICS",
    "CONSUMER",
    "CUTOFF_SOURCES",
    "DEFAULT_CHECKPOINT_ROOT",
    "DEFAULT_PARQUET_ROOT",
    "HISTORICAL_CUTOFF",
    "REJECTED_COLUMNS",
    "REJECTED_PREFIX",
    "REQUIRED_ENVELOPE_FIELDS",
    "archive_location",
    "build_parser",
    "checkpoint_location",
    "envelope_rejection",
    "main",
    "normalize_location",
    "parse_utc",
    "partition_date",
    "rejected_location",
]


def parse_utc(value: str) -> datetime:
    """Parse an RFC3339 instant, requiring a timezone.

    A naive timestamp is rejected rather than assumed to be UTC. `-103` §4.5
    separates `occurred_at` from `ingested_at` so replay lag can be measured,
    and a guessed offset makes that measurement quietly wrong.
    """

    text = str(value).strip()
    if not text:
        raise ValueError("timestamp must not be blank")
    if text.endswith(("Z", "z")):
        text = f"{text[:-1]}+00:00"
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        raise ValueError(f"timestamp must carry a timezone: {value!r}")
    return moment.astimezone(UTC)


def partition_date(occurred_at: str) -> str:
    """`dt=` for one event, from when it happened at the source.

    Partitioning by `occurred_at` rather than by arrival keeps a replay landing
    where the original did. Using arrival would scatter one source day across
    every day we happened to re-read it.
    """

    return f"{parse_utc(occurred_at):%Y-%m-%d}"


def normalize_location(uri: str) -> str:
    """Drop an authority-less scheme, leaving a path `fs.defaultFS` resolves.

    The project writes roots as `hdfs:///gitjob/...` — `.env.example`'s
    `PARQUET_ROOT` and `RAW_ROOT`, and `raw_sink.py`'s `DEFAULT_RAW_ROOT`, all
    take that shape. Most Spark and Hadoop APIs accept it, but Structured
    Streaming's checkpoint resolver does not:

        IllegalArgumentException: Uri without authority:
        hdfs:/gitjob/checkpoints/c1/github.events

    Rewriting the NameNode host in here would be worse — it would put the
    cluster address in two places and let them disagree. Handing Spark the
    bare path instead defers to `spark.hadoop.fs.defaultFS`, which the submit
    already sets and which is the one place that address belongs.

    A URI that names an authority (`hdfs://hdfs-namenode:8020/x`) is left
    alone, and so is a path that never had a scheme.
    """

    text = uri.strip()
    for scheme in ("hdfs:", "file:"):
        if text.startswith(f"{scheme}///"):
            return text[len(scheme) + 2 :]
    return text


def _location(root: str, prefix: str, topic: str) -> str:
    if not topic.strip():
        raise ValueError("topic must not be blank")
    return f"{normalize_location(root).rstrip('/')}/{prefix}/{topic.strip()}"


def archive_location(topic: str, *, parquet_root: str = DEFAULT_PARQUET_ROOT) -> str:
    return _location(parquet_root, ARCHIVE_PREFIX, topic)


def rejected_location(topic: str, *, parquet_root: str = DEFAULT_PARQUET_ROOT) -> str:
    return _location(parquet_root, f"{ARCHIVE_PREFIX}/{REJECTED_PREFIX}", topic)


def checkpoint_location(
    topic: str,
    *,
    checkpoint_root: str = DEFAULT_CHECKPOINT_ROOT,
    consumer: str = CONSUMER,
) -> str:
    """One directory per (consumer, topic).

    The consumer segment is what keeps C1 and C2 from sharing progress while
    reading the same topic — the property `-108` calls independent offsets.
    """

    if not consumer.strip():
        raise ValueError("consumer must not be blank")
    return _location(checkpoint_root, consumer.strip(), topic)


def envelope_rejection(
    envelope: Any,
    *,
    cutoff: str = HISTORICAL_CUTOFF,
    cutoff_sources: Sequence[str] = CUTOFF_SOURCES,
) -> str | None:
    """Why this message must not join the archive, or `None` to accept it.

    Returning a reason instead of a boolean is deliberate: the reason is
    written beside the message, so a rejected batch can be explained without
    re-deriving the check from the code that made it.
    """

    if not isinstance(envelope, Mapping):
        return "envelope is not a JSON object"

    missing = [f for f in REQUIRED_ENVELOPE_FIELDS if envelope.get(f) in (None, "")]
    if missing:
        return f"envelope is missing required fields: {', '.join(missing)}"

    try:
        occurred_at = parse_utc(str(envelope["occurred_at"]))
    except ValueError as error:
        return f"occurred_at is unusable: {error}"
    try:
        parse_utc(str(envelope["ingested_at"]))
    except ValueError as error:
        return f"ingested_at is unusable: {error}"

    source = str(envelope["source"]).strip().lower()
    if source in {s.lower() for s in cutoff_sources} and occurred_at < parse_utc(
        cutoff
    ):
        # `-144`: history is the batch path's. Archiving it here would be the
        # double ingestion that ticket forbids.
        return (
            f"occurred_at {occurred_at.isoformat()} precedes the historical "
            f"cutoff {cutoff}; that range belongs to the batch path"
        )
    return None


def _decode(value: bytes | str | None) -> tuple[Any, str | None]:
    """Return the parsed envelope, or `(None, reason)` when it will not parse."""

    if value is None:
        return None, "message value is empty"
    text = value.decode("utf-8", "replace") if isinstance(value, bytes) else value
    try:
        return json.loads(text), None
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return None, f"message value is not JSON: {error}"


def _row(
    envelope: Mapping[str, Any],
    *,
    topic: str,
    partition: int,
    offset: int,
    kafka_timestamp: Any,
    raw_value: str,
) -> dict[str, Any]:
    """One archive row.

    `kafka_partition` and `kafka_offset` travel with the data because `-102`
    §2.2 makes the event offset C1's deduplication key. A replay that lands the
    same event twice is then removable by a query rather than by guesswork.
    """

    return {
        "schema_version": str(envelope["schema_version"]),
        "source": str(envelope["source"]),
        "source_id": str(envelope["source_id"]),
        "event_type": str(envelope["event_type"]),
        "event_id": _optional(envelope.get("event_id")),
        "trace_id": _optional(envelope.get("trace_id")),
        "occurred_at": str(envelope["occurred_at"]),
        "ingested_at": str(envelope["ingested_at"]),
        "payload": json.dumps(envelope["payload"], ensure_ascii=False),
        "kafka_topic": topic,
        "kafka_partition": int(partition),
        "kafka_offset": int(offset),
        "kafka_timestamp": None if kafka_timestamp is None else str(kafka_timestamp),
        "raw_value": raw_value,
        "dt": partition_date(str(envelope["occurred_at"])),
    }


def _optional(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="c1_archiver_stream",
        description="Archive Kafka envelopes to Parquet, one query per topic.",
    )
    parser.add_argument(
        "--bootstrap-servers",
        required=True,
        help="Kafka bootstrap servers, for example kafka:9092",
    )
    parser.add_argument(
        "--topics",
        default=",".join(C1_TOPICS),
        help=f"comma-separated topics (default: {','.join(C1_TOPICS)})",
    )
    parser.add_argument("--parquet-root", default=DEFAULT_PARQUET_ROOT)
    parser.add_argument("--checkpoint-root", default=DEFAULT_CHECKPOINT_ROOT)
    parser.add_argument(
        "--starting-offsets",
        default="earliest",
        help=(
            "only consulted the first time a checkpoint directory is created; "
            "afterwards the checkpoint decides (default: earliest)"
        ),
    )
    parser.add_argument(
        "--max-offsets-per-trigger",
        type=int,
        default=None,
        help=(
            "cap the events one micro-batch reads. github.events holds 8.8M "
            "messages, and an uncapped first batch tries to land them at once"
        ),
    )
    parser.add_argument(
        "--trigger-seconds",
        type=float,
        default=30.0,
        help="processing-time trigger interval (default: 30)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help=(
            "run a single micro-batch and stop. This is how the skeleton is "
            "verified without leaving a stream running"
        ),
    )
    parser.add_argument("--cutoff", default=HISTORICAL_CUTOFF)
    return parser


def _spark_schema(columns: Sequence[tuple[str, str]]) -> Any:
    from pyspark.sql.types import (
        IntegerType,
        LongType,
        StringType,
        StructField,
        StructType,
    )

    kinds = {"string": StringType(), "int": IntegerType(), "long": LongType()}
    return StructType([StructField(name, kinds[kind], True) for name, kind in columns])


def _write_batch(
    batch_rows: list[dict[str, Any]],
    rejects: list[dict[str, Any]],
    *,
    spark: Any,
    topic: str,
    parquet_root: str,
) -> None:
    """Land one micro-batch: accepted rows, then the rejected ones.

    Accepted goes first. A reader that sees a rejection can then rely on the
    accepted part of the same batch already being there, which mirrors the rule
    `raw_sink.py` follows when it uploads a run's batch before its manifest.

    The schema is declared, never inferred. Inference fails outright on a batch
    where every `event_id` happens to be absent — `CANNOT_DETERMINE_TYPE`, seen
    on the first real run against `github.events` — and even when it succeeds it
    would let the archive's columns drift with whatever one batch contained.
    """

    if batch_rows:
        spark.createDataFrame(
            batch_rows, schema=_spark_schema(ARCHIVE_COLUMNS)
        ).write.mode("append").partitionBy("dt").parquet(
            archive_location(topic, parquet_root=parquet_root)
        )
    if rejects:
        spark.createDataFrame(
            rejects, schema=_spark_schema(REJECTED_COLUMNS)
        ).write.mode("append").parquet(
            rejected_location(topic, parquet_root=parquet_root)
        )


def _foreach_batch(spark: Any, topic: str, parquet_root: str, cutoff: str):
    def handler(frame: Any, batch_id: int) -> None:
        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for record in frame.collect():
            raw = record["value"]
            envelope, reason = _decode(raw)
            text = (
                raw if isinstance(raw, str) else (raw or b"").decode("utf-8", "replace")
            )
            if reason is None:
                reason = envelope_rejection(envelope, cutoff=cutoff)
            if reason is None:
                accepted.append(
                    _row(
                        envelope,
                        topic=topic,
                        partition=record["partition"],
                        offset=record["offset"],
                        kafka_timestamp=record["timestamp"],
                        raw_value=text,
                    )
                )
            else:
                rejected.append(
                    {
                        "kafka_topic": topic,
                        "kafka_partition": int(record["partition"]),
                        "kafka_offset": int(record["offset"]),
                        "reject_reason": reason,
                        "raw_value": text,
                        "batch_id": int(batch_id),
                    }
                )
        _write_batch(
            accepted, rejected, spark=spark, topic=topic, parquet_root=parquet_root
        )
        print(
            json.dumps(
                {
                    "topic": topic,
                    "batch_id": batch_id,
                    "accepted": len(accepted),
                    "rejected": len(rejected),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    return handler


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    topics = [t.strip() for t in arguments.topics.split(",") if t.strip()]
    if not topics:
        raise SystemExit("at least one topic is required")

    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F

    spark = SparkSession.builder.appName("gitjob-c1-archiver").getOrCreate()

    queries = []
    for topic in topics:
        reader = (
            spark.readStream.format("kafka")
            .option("kafka.bootstrap.servers", arguments.bootstrap_servers)
            .option("subscribe", topic)
            .option("startingOffsets", arguments.starting_offsets)
            # A message we cannot keep up with must not end the stream. It is
            # already durable in the topic; `retention.ms=-1` (`-108`) means
            # rewinding stays possible.
            .option("failOnDataLoss", "false")
        )
        if arguments.max_offsets_per_trigger:
            reader = reader.option(
                "maxOffsetsPerTrigger", str(arguments.max_offsets_per_trigger)
            )
        frame = reader.load().select(
            F.col("value").cast("string").alias("value"),
            F.col("partition"),
            F.col("offset"),
            F.col("timestamp"),
        )

        writer = (
            frame.writeStream.foreachBatch(
                _foreach_batch(spark, topic, arguments.parquet_root, arguments.cutoff)
            )
            .option(
                "checkpointLocation",
                checkpoint_location(topic, checkpoint_root=arguments.checkpoint_root),
            )
            .outputMode("append")
        )
        if arguments.once:
            # Drain what is already in the topic, then stop. Unlike `once=True`
            # this still honours `maxOffsetsPerTrigger`, so the 8.8M message
            # backlog is read in bounded batches rather than one.
            writer = writer.trigger(availableNow=True)
        else:
            writer = writer.trigger(
                processingTime=f"{int(arguments.trigger_seconds)} seconds"
            )
        queries.append(writer.start())

    for query in queries:
        query.awaitTermination()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
