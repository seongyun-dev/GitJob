#!/usr/bin/env bash
# Historical chain health probe. READ-ONLY.
#
# Self-match is the failure this avoids: `pgrep -f monthly-top10k-chain.sh`
# typed on a command line matches that very command line, so a dead chain
# reports alive. The pattern therefore lives inside this file (the invoking
# command line is only `bash chain-probe.sh`) and the bracket form keeps the
# probe's own `ps` pipeline out of the result.
#
# Health needs agreement from more than one signal, so three are reported:
# exact-command PID, tmux session, and chain-state heartbeat age.
set -uo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
CR="$ROOT/.local/gharchive-monthly-artifact"
SESSION=s15p21e102-194-historical-chain

PIDS=$(ps -eo pid,args --no-headers 2>/dev/null \
  | grep -E '[b]ash .*[r]epo-snapshot-monthly-top10k-chain\.sh' \
  | awk '{print $1}' | tr '\n' ' ')
PIDS="${PIDS% }"
NPROC=$(printf '%s' "$PIDS" | wc -w | tr -d ' ')
TMUXOK=$(tmux has-session -t "$SESSION" 2>/dev/null && echo yes || echo no)
HB=$(python3 - "$CR/chain-state.json" <<'PY' 2>/dev/null
import json,sys,datetime
try:
    d=json.load(open(sys.argv[1]))
except Exception:
    print("na|na|na|na"); raise SystemExit
t=d.get("last_heartbeat_at")
age="na"
if t:
    dt=datetime.datetime.fromisoformat(t.replace("Z","+00:00"))
    age=int((datetime.datetime.now(datetime.timezone.utc)-dt).total_seconds())
print(f"{d.get('month')}|{d.get('phase')}|{d.get('status')}|{age}")
PY
)
[ -z "$HB" ] && HB="na|na|na|na"
IFS='|' read -r M P S AGE <<< "$HB"
# 두 신호 이상이 살아 있어야 ALIVE. 단독 신호는 판정 근거로 쓰지 않는다.
ALIVE=0
[ "$NPROC" -gt 0 ] && ALIVE=$((ALIVE+1))
[ "$TMUXOK" = "yes" ] && ALIVE=$((ALIVE+1))
if [ "$AGE" != "na" ] && [ "$AGE" -lt 900 ] && [ "$S" != "STOPPED" ]; then ALIVE=$((ALIVE+1)); fi
if [ "$ALIVE" -ge 2 ]; then VERDICT=ALIVE; else VERDICT=DEAD; fi
echo "VERDICT=$VERDICT signals=$ALIVE/3 pids=[${PIDS:-none}] nproc=$NPROC tmux=$TMUXOK month=$M phase=$P status=$S hb_age=${AGE}s"
