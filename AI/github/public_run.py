"""Run a verified local mirror or explicitly configured WebHDFS public input."""

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from github.artifact_reader import ReadOnlyWebHdfsReader
from github.contracts import GitHubRepoSnapshotBatch
from github.public_analysis import LocalMirrorArtifactReader
from github.public_pipeline import (
    PipelineBusyError,
    PipelineCheckpointError,
    PipelineExecutionError,
    plan_public_pipeline,
    run_public_pipeline,
)
from github.snapshot_input import (
    MAX_JSON_BYTES,
    SnapshotInputError,
    load_published_snapshot,
)
from registry.contracts import TechnologyRegistry, load_registry
from registry.mapper import RegistryMapper


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("invalid public pipeline arguments")


def _local_bytes(path: Path) -> bytes:
    with path.open("rb") as stream:
        body = stream.read(MAX_JSON_BYTES + 1)
    if len(body) > MAX_JSON_BYTES:
        raise ValueError("local input exceeds byte bound")
    return body


def main(argv: Sequence[str] | None = None) -> int:
    parser = _Parser(description="Deterministic public Snapshot partition pipeline")
    parser.add_argument("--mode", choices=["mirror", "hdfs"], default="mirror")
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument(
        "--registry-root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument("--checkpoint-dir", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--artifact-uri-prefix")
    parser.add_argument("--root-uri")
    parser.add_argument("--namenode-base-url")
    parser.add_argument("--hdfs-user", default="hadoop")
    parser.add_argument("--timeout-seconds", type=float, default=15)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--max-requests", type=int, default=50_000)
    parser.add_argument("--include-partial", action="store_true")
    parser.add_argument("--max-records", type=int, default=500)
    parser.add_argument("--max-declared-bytes", type=int, default=50_000_000)
    parser.add_argument("--max-new-partitions", type=int)
    parser.add_argument("--plan-only", action="store_true")
    try:
        args = parser.parse_args(argv)
        if not args.plan_only and args.checkpoint_dir is None:
            raise ValueError("checkpoint directory required for execution")
        registry_source = _local_bytes(args.registry)
        registry = load_registry(args.registry, repository_root=args.registry_root)
        if registry != TechnologyRegistry.model_validate_json(registry_source):
            raise ValueError("Registry changed while loading")
        mapper = RegistryMapper(registry)
        quality = None
        manifest_hash = None
        reader = None
        if args.mode == "mirror":
            if args.snapshot is None or args.root_uri or args.namenode_base_url:
                raise ValueError("mirror mode requires a local Snapshot only")
            source = _local_bytes(args.snapshot)
            batch = GitHubRepoSnapshotBatch.model_validate_json(source)
            source_hash = hashlib.sha256(source).hexdigest()
            if not args.plan_only:
                if args.artifact_root is None or not args.artifact_uri_prefix:
                    raise ValueError("fixed artifact mirror required")
                reader = LocalMirrorArtifactReader(
                    args.artifact_root, args.artifact_uri_prefix
                )
        else:
            if (
                not args.root_uri
                or not args.namenode_base_url
                or args.snapshot
                or args.artifact_root
                or args.artifact_uri_prefix
            ):
                raise ValueError("HDFS mode requires fixed root and NameNode only")
            routes = json.loads(os.getenv("C_PUBLIC_DATANODE_ROUTES_JSON", "{}"))
            if not isinstance(routes, dict) or any(
                not isinstance(k, str) or not isinstance(v, str)
                for k, v in routes.items()
            ):
                raise ValueError("DataNode routes must be an origin mapping")
            reader = ReadOnlyWebHdfsReader(
                args.namenode_base_url,
                args.root_uri,
                datanode_routes=routes,
                user=args.hdfs_user,
                timeout=args.timeout_seconds,
                max_attempts=args.max_attempts,
                max_requests=args.max_requests,
            )
            published = load_published_snapshot(args.root_uri, reader)
            batch, source_hash = published.batch, published.source_sha256
            manifest_hash, quality = published.manifest_sha256, published.quality
        options = {
            "include_partial": args.include_partial,
            "max_records": args.max_records,
            "max_declared_bytes": args.max_declared_bytes,
            "source_sha256": source_hash,
            "manifest_sha256": manifest_hash,
            "registry_sha256": hashlib.sha256(registry_source).hexdigest(),
        }
        if args.plan_only:
            plan = plan_public_pipeline(batch, mapper, **options)
            output = {
                "status": "PLANNED",
                "pipeline_id": plan.pipeline_id,
                "plan": plan.model_dump(mode="json"),
            }
        else:
            progress = run_public_pipeline(
                batch,
                reader,
                mapper,
                args.checkpoint_dir,
                max_new_partitions=args.max_new_partitions,
                **options,
            )
            output = progress.model_dump(mode="json", exclude={"result"})
            if progress.result is not None:
                output["result_quality_status"] = progress.result.status.value
                output["total_repo_count"] = progress.result.total_repo_count
                output["analyzed_repo_count"] = progress.result.analyzed_repo_count
        if quality is not None:
            output["input_quality"] = quality.model_dump(mode="json")
            output["reader_stats"] = reader.stats
    except PipelineBusyError:
        code, exit_code = "PIPELINE_BUSY", 3
    except (PipelineCheckpointError, SnapshotInputError, ValueError, OSError):
        code, exit_code = "INVALID_PUBLIC_INPUT_OR_CHECKPOINT", 2
    except PipelineExecutionError:
        code, exit_code = "PARTITION_EXECUTION_INCOMPLETE", 1
    except Exception:  # noqa: BLE001 - do not print upstream payloads or credentials.
        code, exit_code = "PUBLIC_PIPELINE_FAILED", 1
    else:
        print(json.dumps(output, ensure_ascii=False))
        return 0
    print(json.dumps({"status": "NOT_COMPLETED", "code": code}), file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
