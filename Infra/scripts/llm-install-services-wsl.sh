#!/usr/bin/env bash
#
# Install the AI host's two services as systemd *user* units.
#
# User units rather than the system units under Infra/systemd used on EC2: this
# host has no passwordless sudo, and Ollama lives under the user's home because
# installing it needed no root either. Nothing here requires elevation.
#
# Idempotent. Re-run after moving the repository or recreating the venv.

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
PYTHON="${PYTHON:-$REPO_ROOT/.venv/bin/python}"
UNIT_DIR="$HOME/.config/systemd/user"
UNITS=(gitjob-ollama.service gitjob-llm-summary.service)

[[ -x "$HOME/.local/ollama/bin/ollama" ]] || {
  echo "error: Ollama is not installed. Run bash Infra/scripts/llm-install-wsl.sh first" >&2
  exit 1
}
[[ -x "$PYTHON" ]] || { echo "error: $PYTHON not found" >&2; exit 1; }
systemctl --user show-environment >/dev/null 2>&1 || {
  echo "error: no systemd user session. Check that /etc/wsl.conf has systemd=true" >&2
  exit 1
}

mkdir -p "$UNIT_DIR"
for unit in "${UNITS[@]}"; do
  sed -e "s|@REPO_ROOT@|$REPO_ROOT|g" -e "s|@PYTHON@|$PYTHON|g" \
    "$REPO_ROOT/Infra/systemd/$unit" >"$UNIT_DIR/$unit"
done

systemctl --user daemon-reload
systemctl --user enable --now "${UNITS[@]}"

# Without lingering, the units only run while a login session for this user is
# open -- so the GPU host would go quiet the moment the last WSL shell closed,
# and the EC2 backend's calls would start failing with nothing in any log to say
# why. Needs root, so it is attempted and reported rather than required.
if [[ "$(loginctl show-user "$USER" --property=Linger --value 2>/dev/null)" != "yes" ]]; then
  if sudo -n loginctl enable-linger "$USER" 2>/dev/null; then
    echo "lingering enabled: services now survive logout"
  else
    echo "WARNING: lingering is off. The services stop when the last WSL session"
    echo "         closes. Enable it once with:  sudo loginctl enable-linger $USER"
  fi
fi

echo
systemctl --user --no-pager --lines=0 status "${UNITS[@]}" 2>/dev/null \
  | grep -E "^●|Active:" || true
