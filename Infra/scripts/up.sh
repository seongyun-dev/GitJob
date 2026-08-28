#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_lib.sh"

require_core_tools

echo "Validating Compose configuration..."
compose config --quiet

echo "Starting GitJob selected services..."
if profile_enabled ci; then
  # Start non-CI services first. The agent secret does not exist until the
  # controller has created the permanent node, so bootstrap CI in two phases.
  original_profile_set="$PROFILE_SET"
  PROFILE_SET="${PROFILE_SET//,ci/}"
  PROFILE_SET="${PROFILE_SET#ci,}"
  PROFILE_SET="${PROFILE_SET%,ci}"
  if [[ -n "$PROFILE_SET" ]]; then
    compose up -d
  fi
  PROFILE_SET="$original_profile_set"
  "$SCRIPT_DIR/bootstrap-jenkins-agent.sh"
else
  compose up -d
fi

"$SCRIPT_DIR/healthcheck.sh"
