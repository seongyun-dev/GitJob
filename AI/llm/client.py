"""HTTP access to the local Ollama model that writes the summaries."""

import json
import os
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from llm.contracts import technology_summary_json_schema

DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen3.5:4b"
#: The model's default context. The whole point of collapsing 82 evidence rows
#: into eight highlights is to stay inside it.
DEFAULT_NUM_CTX = 8_192
#: A summary is a restatement, not an essay. Left open, the model keeps writing
#: after it has finished summarizing.
DEFAULT_NUM_PREDICT = 300


class OllamaError(RuntimeError):
    """The local model could not be reached or did not answer usefully."""


@dataclass(frozen=True)
class OllamaSettings:
    """Where the model lives and how much of it to use."""

    base_url: str = DEFAULT_OLLAMA_BASE_URL
    model: str = DEFAULT_MODEL
    timeout_seconds: float = 300.0
    num_ctx: int = DEFAULT_NUM_CTX
    num_predict: int = DEFAULT_NUM_PREDICT

    @classmethod
    def from_env(cls) -> "OllamaSettings":
        """Read the same variables the LLM test server already uses."""

        return cls(
            base_url=os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL).rstrip("/"),
            model=os.getenv("LLM_MODEL", DEFAULT_MODEL),
            timeout_seconds=float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "300")),
        )


class ChatClient(Protocol):
    """The one call the summary service makes, so tests can stand in for it."""

    model: str

    def chat(self, messages: list[dict[str, str]], *, temperature: float) -> str:
        """Return the model's raw message content for these messages."""


def build_chat_payload(
    messages: list[dict[str, str]],
    *,
    settings: OllamaSettings,
    temperature: float,
) -> dict[str, Any]:
    """Build one bounded, non-streaming chat request.

    ``format`` carries the response JSON Schema, which makes the reply
    syntactically valid JSON. It does not make the reply true -- the content
    checks still run afterwards.

    ``keep_alive`` is -1 so the weights stay resident: a person's screen asks
    for a dozen technologies in a row, and reloading the model between them
    costs more than the generations do.
    """

    return {
        "model": settings.model,
        "stream": False,
        "think": False,
        "keep_alive": -1,
        "messages": messages,
        "format": technology_summary_json_schema(),
        "options": {
            "num_ctx": settings.num_ctx,
            "num_predict": settings.num_predict,
            "temperature": temperature,
        },
    }


class OllamaChatClient:
    """Calls a local Ollama server over plain HTTP."""

    def __init__(self, settings: OllamaSettings | None = None) -> None:
        self._settings = settings or OllamaSettings()

    @property
    def model(self) -> str:
        return self._settings.model

    @property
    def settings(self) -> OllamaSettings:
        return self._settings

    def chat(self, messages: list[dict[str, str]], *, temperature: float) -> str:
        """Send one request and return ``message.content``."""

        payload = build_chat_payload(
            messages,
            settings=self._settings,
            temperature=temperature,
        )
        request = Request(
            f"{self._settings.base_url}/api/chat",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urlopen(request, timeout=self._settings.timeout_seconds) as response:
                result = json.load(response)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise OllamaError(f"Ollama returned HTTP {exc.code}: {detail}") from exc
        except TimeoutError as exc:
            raise OllamaError(
                "Ollama inference timed out after "
                f"{self._settings.timeout_seconds:g} seconds"
            ) from exc
        except URLError as exc:
            raise OllamaError(
                f"Cannot reach Ollama at {self._settings.base_url}: {exc}"
            ) from exc

        message = result.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise OllamaError("Ollama response did not contain message.content")
        return content
