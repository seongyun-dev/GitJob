"""Build immutable raw inputs for a bounded Weekly recovery run.

The accepted events are selected by the same envelope serialization and byte
limit as the Kafka publisher.  The output keeps the original GH Archive JSON
objects so Spark can reuse its existing raw reader without inventing another
event contract.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from collector.gharchive.events import RejectedEvent, iter_hour_records
from common.kafka import MAX_MESSAGE_BYTES

MANIFEST_SCHEMA_VERSION = "weekly-recovery-source-manifest/v1"
BUILD_SPEC_SCHEMA_VERSION = "weekly-recovery-build-spec/v1"
FIXED_INGESTED_AT = datetime(2026, 9, 18, 0, 0, 0, 123456, tzinfo=UTC)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_hour(value: object) -> datetime:
    if not isinstance(value, str):
        raise TypeError("hour must be an ISO UTC string")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:00:00Z", value):
        raise ValueError(f"recovery hour must use YYYY-MM-DDTHH:00:00Z: {value}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid recovery hour: {value}") from exc
    return parsed


def build_recovery_file(
    source_path: Path,
    output_path: Path,
    *,
    hour: str,
    source_uri: str,
    output_uri: str,
    ingested_at: datetime = FIXED_INGESTED_AT,
) -> dict[str, object]:
    """Filter one gzip by the publisher's exact acceptance decision."""

    source_path = Path(source_path).resolve(strict=True)
    output_path = Path(output_path).resolve(strict=False)
    if source_path == output_path:
        raise ValueError("recovery output must differ from its source")
    if output_path.exists():
        raise FileExistsError(f"recovery output already exists: {output_path}")
    parsed_hour = _parse_hour(hour)
    canonical_hour = parsed_hour.isoformat().replace("+00:00", "Z")

    skipped: list[str] = []
    rejected: list[RejectedEvent] = []
    accepted_lines = {
        line_number
        for line_number, _key, _value in iter_hour_records(
            source_path,
            hour_key=canonical_hour,
            ingested_at=ingested_at,
            skipped=skipped,
            rejected=rejected,
            max_message_bytes=MAX_MESSAGE_BYTES,
        )
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    if temporary.exists():
        raise FileExistsError(f"recovery temporary output already exists: {temporary}")
    source_event_count = 0
    try:
        with (
            gzip.open(source_path, "rt", encoding="utf-8") as source,
            temporary.open("xb") as raw_output,
            gzip.GzipFile(
                filename="", fileobj=raw_output, mode="wb", mtime=0
            ) as compressed,
        ):
            for line_number, line in enumerate(source, start=1):
                if line.strip():
                    source_event_count += 1
                if line_number in accepted_lines:
                    compressed.write(line.rstrip("\r\n").encode("utf-8") + b"\n")
        expected = len(accepted_lines) + len(rejected) + len(skipped)
        if source_event_count != expected:
            raise ValueError(
                "publisher acceptance did not account for every non-blank source line"
            )
        temporary.replace(output_path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise

    return {
        "hour": canonical_hour,
        "source_uri": source_uri,
        "source_sha256": _sha256(source_path),
        "source_event_count": source_event_count,
        "uri": output_uri,
        "sha256": _sha256(output_path),
        "accepted_event_count": len(accepted_lines),
        "rejected_oversized_count": len(rejected),
        "skipped_line_count": len(skipped),
    }


def build_manifest(spec: Mapping[str, object]) -> dict[str, object]:
    """Build all 168 outputs named by one immutable local operator spec."""

    if spec.get("schema_version") != BUILD_SPEC_SCHEMA_VERSION:
        raise ValueError("unsupported recovery build spec")
    period_start = spec.get("period_start")
    period_end = spec.get("period_end")
    start, end = _parse_hour(period_start), _parse_hour(period_end)
    if end - start != timedelta(hours=168):
        raise ValueError("recovery build period must be exactly 168 hours")
    files = spec.get("files")
    if not isinstance(files, list) or len(files) != 168:
        raise ValueError("recovery build spec must contain exactly 168 files")
    if any(not isinstance(entry, Mapping) for entry in files):
        raise TypeError("recovery build file entry must be an object")
    expected_hours = {
        (start + timedelta(hours=index)).isoformat().replace("+00:00", "Z")
        for index in range(168)
    }
    actual_hours = {entry.get("hour") for entry in files if isinstance(entry, Mapping)}
    if len(actual_hours) != 168 or actual_hours != expected_hours:
        raise ValueError("recovery build hours do not exactly cover the period")

    source_paths = [
        Path(str(entry["source_path"])).resolve(strict=True) for entry in files
    ]
    if len(set(source_paths)) != len(source_paths):
        raise ValueError("duplicate recovery source path")

    entries = []
    for raw in sorted(files, key=lambda item: str(item["hour"])):
        entries.append(
            build_recovery_file(
                Path(str(raw["source_path"])),
                Path(str(raw["output_path"])),
                hour=str(raw["hour"]),
                source_uri=str(raw["source_uri"]),
                output_uri=str(raw["uri"]),
            )
        )
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "period_start": str(period_start),
        "period_end": str(period_end),
        "max_message_bytes": MAX_MESSAGE_BYTES,
        "files": entries,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.manifest.exists():
        parser.error(f"manifest already exists: {args.manifest}")
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    manifest = build_manifest(spec)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.manifest.with_suffix(args.manifest.suffix + ".tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(args.manifest)
    print(json.dumps({"manifest": str(args.manifest), "files": 168}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
