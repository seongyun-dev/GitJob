#!/usr/bin/env bash

set -Eeuo pipefail

# Hadoop invokes this script with one or more DataNode IP addresses.  Keep the
# mapping environment-driven so the repository never contains an operator's
# Tailscale address. Unknown nodes deliberately fall back to /default-rack.
for node in "$@"; do
  case "$node" in
    "${DATA_TS_IP:-}") printf '%s\n' /rack-a ;;
    "${SERVICE_TS_IP:-}"|"${SERVICE_DN_REGISTRATION_IP:-}")
      printf '%s\n' /rack-b
      ;;
    *) printf '%s\n' /default-rack ;;
  esac
done
