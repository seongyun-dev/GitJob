"""One-use credential exchange for private repository checkout.

The Kafka request remains secret-free. Only after an anonymous GitHub fetch
proves that authorised access is needed does the worker call the backend's
private endpoint. The returned token is passed straight to the Git subprocess
environment and is never cached here.
"""

from __future__ import annotations

import json
import urllib.error
from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from analysis.clone import PermanentCloneError, TransientCloneError

__all__ = ["HttpCredentialBroker"]


@dataclass(frozen=True)
class HttpCredentialBroker:
    endpoint: str
    service_token: str
    timeout_seconds: int = 5

    def __post_init__(self) -> None:
        endpoint = urlsplit(self.endpoint)
        if (
            endpoint.scheme not in {"http", "https"}
            or endpoint.hostname is None
            or endpoint.username is not None
            or endpoint.password is not None
            or endpoint.fragment
        ):
            raise ValueError(
                "credential broker endpoint must be an HTTP(S) URL without embedded credentials"
            )
        if not self.service_token.strip():
            raise ValueError("credential broker service token must not be blank")
        if self.timeout_seconds < 1:
            raise ValueError("credential broker timeout must be at least 1 second")

    def access_token_for(
        self,
        *,
        analysis_id: str,
        analysis_repository_id: str,
        github_repository_id: int,
        repository_full_name: str,
        commit_sha: str,
    ) -> str:
        body = json.dumps(
            {
                "schema_version": "repository-analysis-credential-request/v1",
                "analysis_id": analysis_id,
                "analysis_repository_id": analysis_repository_id,
                "github_repository_id": github_repository_id,
                "repository_full_name": repository_full_name,
                "commit_sha": commit_sha,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        request = Request(
            self.endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.service_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read())
        except urllib.error.HTTPError as error:
            self._raise_status(error.code)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise TransientCloneError(
                "CREDENTIAL_BROKER_UNAVAILABLE",
                "credential broker is temporarily unavailable",
            ) from error
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as error:
            raise TransientCloneError(
                "CREDENTIAL_BROKER_INVALID_RESPONSE",
                "credential broker returned an invalid response",
            ) from error

        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            raise TransientCloneError(
                "CREDENTIAL_BROKER_INVALID_RESPONSE",
                "credential broker returned an invalid response",
            )
        data = payload["data"]
        if (
            data.get("schema_version")
            != "repository-analysis-credential-response/v1"
            or data.get("credential_type") != "GITHUB_OAUTH_ACCESS_TOKEN"
        ):
            raise TransientCloneError(
                "CREDENTIAL_BROKER_INVALID_RESPONSE",
                "credential broker returned an unsupported credential contract",
            )
        token = data.get("access_token")
        if not isinstance(token, str) or not token.strip():
            raise TransientCloneError(
                "CREDENTIAL_BROKER_INVALID_RESPONSE",
                "credential broker response did not contain a credential",
            )
        return token

    @staticmethod
    def _raise_status(status: int) -> None:
        if status == 401 or status == 403:
            raise PermanentCloneError(
                "CREDENTIAL_BROKER_UNAUTHORIZED",
                "worker is not authorised to request repository credentials",
            )
        if status == 404:
            raise PermanentCloneError(
                "REPOSITORY_CREDENTIAL_NOT_FOUND",
                "analysis repository credential was not found",
            )
        if status == 409:
            raise PermanentCloneError(
                "ANALYSIS_NOT_ACTIVE", "analysis is no longer active"
            )
        if status == 424:
            raise PermanentCloneError(
                "GITHUB_RECONNECT_REQUIRED",
                "GitHub connection must be renewed",
            )
        if status == 429 or status >= 500:
            raise TransientCloneError(
                "CREDENTIAL_BROKER_UNAVAILABLE",
                "credential broker is temporarily unavailable",
            )
        raise PermanentCloneError(
            "CREDENTIAL_BROKER_REQUEST_REJECTED",
            "credential broker rejected the analysis request",
        )
