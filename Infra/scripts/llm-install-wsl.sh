#!/usr/bin/env bash
#
# One-time install of Ollama into this WSL distro, under the user's home.
#
# The Docker path (compose.llm.yaml + llm-up.sh) stays the documented option for
# a notebook with Docker Desktop running. This script exists because the AI
# server host has no Docker daemon and no passwordless sudo: everything here
# lands in $OLLAMA_HOME and needs no root.

set -Eeuo pipefail

# Pinned to the same version compose.llm.yaml pins its image digest to, so the
# container path and this path run identical inference.
OLLAMA_VERSION="${OLLAMA_VERSION:-v0.33.2}"
OLLAMA_HOME="${OLLAMA_HOME:-$HOME/.local/ollama}"
ASSET="ollama-linux-amd64.tar.zst"
URL="https://github.com/ollama/ollama/releases/download/${OLLAMA_VERSION}/${ASSET}"

command -v curl >/dev/null 2>&1 || { echo "error: curl is not on PATH" >&2; exit 1; }

if [[ -x "$OLLAMA_HOME/bin/ollama" ]]; then
  echo "Already installed: $("$OLLAMA_HOME/bin/ollama" --version 2>&1 | tail -n 1)"
  echo "Remove $OLLAMA_HOME to reinstall."
  exit 0
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "Downloading Ollama ${OLLAMA_VERSION} (about 1.4 GiB)..."
curl --fail --location --silent --show-error --output "$WORK/$ASSET" "$URL"

mkdir -p "$OLLAMA_HOME"
echo "Extracting to $OLLAMA_HOME..."

# The release asset is zstd-compressed. GNU tar's --zstd shells out to the zstd
# binary, which is not installed here and needs root to install, so fall back to
# Python's zstandard package in a throwaway directory.
if command -v zstd >/dev/null 2>&1; then
  tar --zstd -xf "$WORK/$ASSET" -C "$OLLAMA_HOME"
else
  PYTHON="${PYTHON:-python3}"
  command -v "$PYTHON" >/dev/null 2>&1 || {
    echo "error: neither zstd nor $PYTHON is available to extract the archive" >&2
    exit 1
  }
  "$PYTHON" -m pip install --quiet --target "$WORK/pylibs" zstandard
  PYTHONPATH="$WORK/pylibs" "$PYTHON" - "$WORK/$ASSET" "$OLLAMA_HOME" <<'PY'
import sys
import tarfile

import zstandard

archive_path, destination = sys.argv[1], sys.argv[2]
with open(archive_path, "rb") as raw:
    with zstandard.ZstdDecompressor().stream_reader(raw) as stream:
        with tarfile.open(fileobj=stream, mode="r|") as archive:
            archive.extractall(destination, filter="tar")
PY
fi

"$OLLAMA_HOME/bin/ollama" --version 2>&1 | tail -n 1
echo "Installed. Start it with: bash Infra/scripts/llm-serve-wsl.sh"
