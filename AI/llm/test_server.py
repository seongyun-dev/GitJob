"""Temporary FastAPI smoke-test server for the local Ollama model."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field


OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip(
    "/"
)
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3.5:4b")
OLLAMA_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "300"))

app = FastAPI(
    title="GitJob Local LLM Test Server",
    description="Temporary test wrapper for the local Ollama qwen3.5:4b model.",
)


class ChatRequest(BaseModel):
    """Input accepted by the test-only chat endpoint."""

    prompt: str = Field(min_length=1, max_length=32_000)
    num_ctx: int = Field(default=8_192, ge=256, le=32_768)
    num_predict: int = Field(default=5_500, ge=64, le=5_500)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)


class ChatResponse(BaseModel):
    """Small, stable response shape for manual smoke tests."""

    model: str
    content: str
    total_duration_ms: int | None = None
    load_duration_ms: int | None = None
    prompt_eval_count: int | None = None
    eval_count: int | None = None


def _duration_ms(value: Any) -> int | None:
    """Convert Ollama's nanosecond duration fields to milliseconds."""
    if not isinstance(value, (int, float)):
        return None
    return round(value / 1_000_000)


@app.get("/health")
def health() -> dict[str, str]:
    """Report that the test HTTP process is alive."""
    return {
        "status": "alive",
        "service": "llm-test-server",
        "model": LLM_MODEL,
        "ollama_base_url": OLLAMA_BASE_URL,
    }


def _ollama_payload(request: ChatRequest, *, stream: bool) -> dict[str, Any]:
    """Build a bounded request for the local model."""
    return {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": request.prompt}],
        "stream": stream,
        "think": False,
        "keep_alive": -1,
        "options": {
            "num_ctx": request.num_ctx,
            "num_predict": request.num_predict,
            "temperature": request.temperature,
        },
    }


def _ollama_request(payload: dict[str, Any]) -> Request:
    """Create an HTTP request for Ollama."""
    return Request(
        f"{OLLAMA_BASE_URL}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    """Forward one prompt to Ollama and return the generated content."""
    ollama_request = _ollama_request(_ollama_payload(request, stream=False))

    try:
        with urlopen(ollama_request, timeout=OLLAMA_TIMEOUT_SECONDS) as response:
            result = json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise HTTPException(
            status_code=502,
            detail=f"Ollama returned HTTP {exc.code}: {detail}",
        ) from exc
    except TimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail=(
                "Ollama inference timed out after "
                f"{OLLAMA_TIMEOUT_SECONDS:g} seconds"
            ),
        ) from exc
    except URLError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Cannot reach Ollama at {OLLAMA_BASE_URL}: {exc}",
        ) from exc

    message = result.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise HTTPException(
            status_code=502,
            detail="Ollama response did not contain message.content",
        )

    return ChatResponse(
        model=result.get("model", LLM_MODEL),
        content=content,
        total_duration_ms=_duration_ms(result.get("total_duration")),
        load_duration_ms=_duration_ms(result.get("load_duration")),
        prompt_eval_count=result.get("prompt_eval_count"),
        eval_count=result.get("eval_count"),
    )


def _stream_ollama(request: ChatRequest) -> Iterator[bytes]:
    """Yield Ollama's newline-delimited streaming response."""
    ollama_request = _ollama_request(_ollama_payload(request, stream=True))

    try:
        with urlopen(ollama_request, timeout=OLLAMA_TIMEOUT_SECONDS) as response:
            for line in response:
                if line.strip():
                    yield line
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        yield json.dumps(
            {"error": f"Ollama returned HTTP {exc.code}: {detail}"},
            ensure_ascii=False,
        ).encode("utf-8") + b"\n"
    except TimeoutError:
        yield json.dumps(
            {
                "error": (
                    "Ollama inference timed out after "
                    f"{OLLAMA_TIMEOUT_SECONDS:g} seconds"
                )
            },
            ensure_ascii=False,
        ).encode("utf-8") + b"\n"
    except URLError as exc:
        yield json.dumps(
            {"error": f"Cannot reach Ollama at {OLLAMA_BASE_URL}: {exc}"},
            ensure_ascii=False,
        ).encode("utf-8") + b"\n"


@app.post("/chat/stream")
def chat_stream(request: ChatRequest) -> StreamingResponse:
    """Stream Ollama NDJSON chunks for faster first-token feedback."""
    return StreamingResponse(
        _stream_ollama(request),
        media_type="application/x-ndjson",
    )
