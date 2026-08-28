#!/usr/bin/env bash

set -Eeuo pipefail

secret_file=/run/secrets/jenkins_agent_secret
[[ -r "$secret_file" ]] || {
  echo "Jenkins agent secret file is missing: $secret_file" >&2
  exit 1
}

JENKINS_SECRET="$(<"$secret_file")"
[[ -n "$JENKINS_SECRET" ]] || {
  echo "Jenkins agent secret file is empty: $secret_file" >&2
  exit 1
}
export JENKINS_SECRET

exec /usr/local/bin/jenkins-agent "$@"
