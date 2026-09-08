#!/usr/bin/env bash

# Cross-check an env file against the mandatory ${VAR:?...} variables declared
# in the given Compose files.
#
# `docker compose config` already fails on a missing one, but it stops at the
# first variable and reports it as an interpolation error deep inside a service
# definition, which reads like a YAML problem rather than a missing setting.
# This lists every missing key at once, before Compose runs.
#
# Note that Compose interpolates the whole file before it filters by profile, so
# a mandatory variable is required even when its service belongs to a profile
# that is not enabled.

set -Eeuo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: $0 <env-file> <compose-file>..." >&2
  exit 2
fi

env_file="$1"
shift

[[ -f "$env_file" ]] || {
  echo "env file not found: $env_file" >&2
  exit 1
}
for compose_file in "$@"; do
  [[ -f "$compose_file" ]] || {
    echo "compose file not found: $compose_file" >&2
    exit 1
  }
done

# Whole-line comments are dropped so that a documented example such as the
# ${env:CDC_DATABASE_PASSWORD} note in compose.yaml is not mistaken for a
# declaration.
required=()
mapfile -t required < <(
  grep -hv '^[[:space:]]*#' "$@" \
    | grep -ohE '\$\{[A-Za-z_][A-Za-z0-9_]*:\?' \
    | sed -E 's/^\$\{//; s/:\?$//' \
    | sort -u
)

if [[ ${#required[@]} -eq 0 ]]; then
  echo "check-required-env: no mandatory variables declared in: $*"
  exit 0
fi

missing=()
for key in "${required[@]}"; do
  grep -qE "^[[:space:]]*${key}[[:space:]]*=[[:space:]]*[^[:space:]]" "$env_file" \
    || missing+=("$key")
done

if [[ ${#missing[@]} -gt 0 ]]; then
  echo "$env_file is missing ${#missing[@]} mandatory variable(s):" >&2
  printf '  %s\n' "${missing[@]}" >&2
  echo "Declared as \${VAR:?...} in: $*" >&2
  exit 1
fi

echo "check-required-env: all ${#required[@]} mandatory variables present in $env_file"
