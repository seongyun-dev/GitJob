#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env.wsl}"
if [[ "$ENV_FILE" != /* ]]; then
  ENV_FILE="$REPO_ROOT/$ENV_FILE"
fi

if [[ -e "$ENV_FILE" ]]; then
  echo "Already exists: $ENV_FILE"
  echo "Delete it only if you intentionally want to recreate the local settings."
  exit 0
fi

cp "$REPO_ROOT/.env.example" "$ENV_FILE"

if command -v openssl >/dev/null 2>&1; then
  replace_value() {
    local key="$1"
    local value="$2"
    sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
  }

  replace_value POSTGRES_PASSWORD "$(openssl rand -hex 24)"
  # The Debezium replication role is separate from the application DB user;
  # BE/src/main/resources/db/cdc/cdc_prerequisites.sql needs this value.
  replace_value CDC_DATABASE_PASSWORD "$(openssl rand -hex 24)"
  replace_value REDIS_PASSWORD "$(openssl rand -hex 24)"
  replace_value JWT_SECRET "$(openssl rand -hex 32)"
  # GitHub Access Token 을 저장할 때 쓰는 키다. 이것을 채우지 않으면 .env.example 의
  # placeholder 가 그대로 실제 암호화 키가 되는데, 그 값은 저장소에 커밋돼 있어서
  # 누구나 복호화할 수 있다. compose 의 ${AES_SYMMETRIC_KEY:?...} 는 비어 있지만
  # 않으면 통과하므로 그 검사에 걸리지도 않는다.
  #
  # AesBytesEncryptor 가 salt 를 Hex.decode 하므로 둘 다 16진수여야 한다.
  # 키는 PBKDF2 로 256비트를 유도하고, salt 는 16바이트다.
  replace_value AES_SYMMETRIC_KEY "$(openssl rand -hex 32)"
  replace_value AES_SALT "$(openssl rand -hex 16)"
  replace_value JENKINS_ADMIN_PASSWORD "$(openssl rand -hex 24)"
else
  echo "warning: openssl is unavailable; replace all change-me values manually" >&2
fi

chmod 600 "$ENV_FILE"
echo "Created $ENV_FILE"
echo "Review the values, then run ./Infra/scripts/up.sh"
echo "When the ci profile is enabled, Jenkins issues the inbound agent secret after the controller starts."
