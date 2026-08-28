#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_lib.sh"

require_core_tools

if [[ "${1:-}" == "--volumes" || "${1:-}" == "-v" ]]; then
  [[ "${CONFIRM:-}" == "yes" ]] || die "Removing volumes is destructive; rerun with CONFIRM=yes"
  echo "Stopping selected services and removing GitJob volumes..."
  compose down --volumes
  exit 0
fi

[[ $# -eq 0 ]] || die "usage: $0 [--volumes] (use CONFIRM=yes with --volumes)"
echo "Stopping selected services; named volumes are preserved."
compose down
