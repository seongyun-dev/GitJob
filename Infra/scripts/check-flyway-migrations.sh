#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
migration_dir="$repo_root/BE/src/main/resources/db/migration"

die() {
  echo "check-flyway-migrations: $*" >&2
  exit 1
}

mapfile -t migration_files < <(
  find "$migration_dir" -maxdepth 1 -type f -name 'V*__*.sql' -printf '%f\n' | sort -V
)

declare -A version_owner=()
for migration_file in "${migration_files[@]}"; do
  [[ "$migration_file" =~ ^V([0-9]+)__(.+)\.sql$ ]] \
    || die "invalid versioned migration filename: $migration_file"
  version="${BASH_REMATCH[1]}"
  if [[ -n "${version_owner[$version]:-}" ]]; then
    die "duplicate migration version V$version: ${version_owner[$version]} and $migration_file"
  fi
  version_owner[$version]="$migration_file"
done

# V18 was applied to the shared service database on 2026-09-17. It is an
# immutable production identity now: reusing V18 for technology_summary made
# Flyway reject the next backend image before Spring could start.
v18_name="V18__technology_candidate_ecosystem_go_cargo_composer.sql"
v18_sha256="70cbf40d3a5e076a8827f549639f5ba693d233d9f159cf8eadf76b78be79d1a4"
[[ "${version_owner[18]:-}" == "$v18_name" ]] \
  || die "V18 must remain $v18_name; add a new migration instead of reusing V18"

actual_v18_sha256="$(sha256sum "$migration_dir/$v18_name" | awk '{print $1}')"
[[ "$actual_v18_sha256" == "$v18_sha256" ]] \
  || die "V18 content changed; restore it and add a new migration version"

# V20 was already published while resolving the cross-branch number collision.
# Keep it byte-identical to V18: existing databases safely re-apply the same
# constraint, while databases that recorded V20 continue to validate it.
v20_name="V20__technology_candidate_ecosystem_go_cargo_composer.sql"
[[ "${version_owner[20]:-}" == "$v20_name" ]] \
  || die "V20 compatibility migration is missing or renamed"
cmp -s "$migration_dir/$v18_name" "$migration_dir/$v20_name" \
  || die "V20 compatibility migration must remain byte-identical to V18"

[[ "${version_owner[21]:-}" == "V21__technology_summary_cache.sql" ]] \
  || die "technology_summary must use V21; V18 is already applied in production"

echo "check-flyway-migrations: version uniqueness and frozen V18 identity verified"
