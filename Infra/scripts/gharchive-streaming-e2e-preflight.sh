#!/usr/bin/env bash
#
# Verify one GH Archive streaming canary from already-captured artifacts.
#
# This wrapper is deliberately offline: it does not call compose, Kafka,
# Spark, HDFS, cron, or GH Archive.  Every input is supplied to the Python
# checker as a read-only artifact.

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"

export PYTHONPATH="$REPO_ROOT/AI${PYTHONPATH:+:$PYTHONPATH}"
exec python -m collector.gharchive.e2e "$@"
