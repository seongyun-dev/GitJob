#!/usr/bin/env bash

# Phase 5 gate: prove that one HDFS path is replicated across both EC2 failure
# domains. Read-only by design. This script never runs setrep, never writes to
# HDFS and never stops a DataNode, so it is safe to re-run on a live cluster.
#
# Run it on the data server, where the NameNode container is reachable:
#   ./Infra/scripts/verify-hdfs-cross-host-replication.sh
#   CANARY_PATH=/gitjob/demo/other ./Infra/scripts/verify-hdfs-cross-host-replication.sh

set -Eeuo pipefail

NAMENODE_CONTAINER="${NAMENODE_CONTAINER:-gitjob-data-hdfs-namenode-1}"
CANARY_PATH="${CANARY_PATH:-/gitjob/demo/distributed-proof}"
EXPECTED_LIVE_DATANODES="${EXPECTED_LIVE_DATANODES:-4}"
EXPECTED_REPLICATION="${EXPECTED_REPLICATION:-2}"
DATA_RACK="${DATA_RACK:-/rack-a}"
SERVICE_RACK="${SERVICE_RACK:-/rack-b}"

failures=0

die() {
  echo "error: $*" >&2
  exit 1
}

pass() { printf '  PASS  %s\n' "$*"; }

fail() {
  printf '  FAIL  %s\n' "$*"
  failures=$((failures + 1))
}

nn() {
  docker exec "$NAMENODE_CONTAINER" "$@" 2>/dev/null
}

command -v docker >/dev/null 2>&1 || die "Docker is not installed or is not on PATH"
docker inspect "$NAMENODE_CONTAINER" >/dev/null 2>&1 \
  || die "NameNode container not found: $NAMENODE_CONTAINER"

echo "cross-host replication gate: $CANARY_PATH"

# 1. Cluster membership. A dead DataNode invalidates every placement claim
#    below, so check it before looking at any block.
report="$(nn hdfs dfsadmin -report || true)"
[[ -n "$report" ]] || die "dfsadmin -report returned nothing"

live="$(sed -n 's/^Live datanodes (\([0-9]*\)).*/\1/p' <<< "$report" | head -n 1)"
dead="$(sed -n 's/^Dead datanodes (\([0-9]*\)).*/\1/p' <<< "$report" | head -n 1)"
live="${live:-0}"
dead="${dead:-0}"

[[ "$live" == "$EXPECTED_LIVE_DATANODES" ]] \
  && pass "live datanodes = $live" \
  || fail "live datanodes = $live, expected $EXPECTED_LIVE_DATANODES"
[[ "$dead" == "0" ]] \
  && pass "dead datanodes = 0" \
  || fail "dead datanodes = $dead, expected 0"

# 2. Both failure domains must exist. Without two racks HDFS cannot place a
#    cross-host replica at all.
topology="$(nn hdfs dfsadmin -printTopology || true)"
for rack in "$DATA_RACK" "$SERVICE_RACK"; do
  grep -q "^Rack: ${rack}\$" <<< "$topology" \
    && pass "topology has $rack" \
    || fail "topology is missing $rack"
done

# 3. Per-block placement for the canary path. `-racks` prefixes each replica
#    location with its rack, which is the only output that proves the replica
#    sits on the other host rather than merely on another DataNode.
fsck="$(nn hdfs fsck "$CANARY_PATH" -files -blocks -locations -racks || true)"
[[ -n "$fsck" ]] || die "fsck returned nothing for $CANARY_PATH"

block_lines="$(grep -c 'Live_repl=' <<< "$fsck" || true)"
[[ "${block_lines:-0}" -gt 0 ]] \
  || die "no blocks found under $CANARY_PATH; create the canary first"
pass "blocks under canary path = $block_lines"

under_replicated_blocks=0
single_rack_blocks=0
while IFS= read -r line; do
  [[ "$line" == *Live_repl=* ]] || continue

  repl="$(sed -n 's/.*Live_repl=\([0-9]\+\).*/\1/p' <<< "$line")"
  if [[ -z "$repl" || "$repl" -lt "$EXPECTED_REPLICATION" ]]; then
    under_replicated_blocks=$((under_replicated_blocks + 1))
    continue
  fi

  # The bracketed location list is the authoritative placement record. Extract
  # it with sed: a `[` inside a shell glob pattern opens a bracket expression,
  # so `${line##*[}` is not a portable way to reach it.
  locations="$(sed -n 's/.*\[\(.*\)\].*/\1/p' <<< "$line")"
  if [[ "$locations" != *"$DATA_RACK/"* || "$locations" != *"$SERVICE_RACK/"* ]]; then
    single_rack_blocks=$((single_rack_blocks + 1))
  fi
done <<< "$fsck"

[[ "$under_replicated_blocks" == "0" ]] \
  && pass "every canary block has >= $EXPECTED_REPLICATION live replicas" \
  || fail "$under_replicated_blocks canary block(s) below replication $EXPECTED_REPLICATION"

[[ "$single_rack_blocks" == "0" ]] \
  && pass "every canary block spans $DATA_RACK and $SERVICE_RACK" \
  || fail "$single_rack_blocks canary block(s) do not span both racks"

# 4. Canary integrity must not be asserted from a byte stream piped out of the
#    container: `docker exec` applies newline translation and silently inflates
#    binary output, so a sha256 taken that way is meaningless. Ask HDFS for its
#    own block checksum instead. `tail -n 1` guards against a Java stack trace
#    being printed ahead of the result, and $NF avoids depending on how many
#    whitespace-separated fields the path contributes.
canary_files="$(nn hdfs dfs -ls "$CANARY_PATH" | awk '/^-/ {print $NF}' || true)"
[[ -n "$canary_files" ]] || die "no files found under $CANARY_PATH"

checksum_failures=0
while IFS= read -r file; do
  [[ -n "$file" ]] || continue
  digest="$(nn hdfs dfs -checksum "$file" | tail -n 1 | awk '{print $NF}' || true)"
  [[ "$digest" =~ ^[0-9a-f]+$ ]] || checksum_failures=$((checksum_failures + 1))
done <<< "$canary_files"

[[ "$checksum_failures" == "0" ]] \
  && pass "every canary file reports an HDFS block checksum" \
  || fail "$checksum_failures canary file(s) returned no usable checksum"

# 5. Whole-filesystem health. The canary must not have been bought with damage
#    somewhere else.
whole="$(nn hdfs fsck /gitjob || true)"
for metric in 'Missing blocks' 'Corrupt blocks' 'Under-replicated blocks' 'Mis-replicated blocks'; do
  value="$(sed -n "s/^ *${metric}:[[:space:]]*\([0-9]*\).*/\1/p" <<< "$whole" | head -n 1)"
  [[ "${value:-1}" == "0" ]] \
    && pass "$metric = 0" \
    || fail "$metric = ${value:-unknown}, expected 0"
done

grep -q "is HEALTHY" <<< "$whole" \
  && pass "/gitjob fsck HEALTHY" \
  || fail "/gitjob fsck is not HEALTHY"

if [[ "$failures" -gt 0 ]]; then
  echo "cross-host replication gate: FAIL ($failures check(s))"
  exit 1
fi

echo "cross-host replication gate: PASS"
