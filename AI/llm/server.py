"""HTTP boundary the backend calls for one technology summary."""

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator

from llm.client import ChatClient, OllamaChatClient, OllamaSettings
from llm.contracts import Confidence, FactPack, TechnologySummary
from llm.prompt import PROMPT_VERSION
from llm.service import GeneratedSummary, SummaryStatus, generate_summary


class SummaryRequest(BaseModel):
    """One Fact Pack, plus the user the cache key has to separate.

    ``user_id`` sits outside ``fact_pack`` because it never reaches the model.
    The summary must not contain a value that points at a person, and the
    simplest way to guarantee that is not to put one in the prompt.
    """

    model_config = ConfigDict(extra="forbid")

    user_id: StrictStr = Field(min_length=1, max_length=200)
    fact_pack: FactPack

    @field_validator("user_id")
    @classmethod
    def require_non_blank_user_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("user_id must not be blank")
        return value


class AttemptReport(BaseModel):
    """Why one generation was not accepted, for the backend's logs."""

    temperature: float
    failure_codes: tuple[str, ...] = ()
    error: str | None = None


class SummaryResponse(BaseModel):
    """What the backend stores against ``cache_key``.

    ``llm_status`` is ``FALLBACK`` when the sentence was assembled from the
    data instead of generated. It is not an error: the card renders either way,
    and the level, evidence and permalinks never depended on the model.
    """

    llm_status: SummaryStatus
    summary: TechnologySummary
    cache_key: str
    model: str
    prompt_version: str
    attempts: tuple[AttemptReport, ...] = ()
    #: Present only when the model's own confidence band disagreed with the one
    #: derived from the Fact Pack. The derived value is the one in ``summary``.
    model_confidence: Confidence | None = None


def _to_response(generated: GeneratedSummary) -> SummaryResponse:
    return SummaryResponse(
        llm_status=generated.status,
        summary=generated.summary,
        cache_key=generated.cache_key,
        model=generated.model,
        prompt_version=generated.prompt_version,
        model_confidence=generated.model_confidence,
        attempts=tuple(
            AttemptReport(
                temperature=attempt.temperature,
                failure_codes=tuple(failure.code for failure in attempt.failures),
                error=attempt.error,
            )
            for attempt in generated.attempts
        ),
    )


def create_app(client: ChatClient | None = None) -> FastAPI:
    """Build the summary application, with an injectable model client."""

    settings = OllamaSettings.from_env()
    chat_client = client or OllamaChatClient(settings)

    app = FastAPI(
        title="GitJob Technology Summary",
        description=(
            "Writes the human sentence for a rule-decided technology level. "
            "It does not decide the level."
        ),
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        """Report that this process is alive, not that Ollama is ready."""

        return {
            "status": "alive",
            "service": "llm-technology-summary",
            "model": chat_client.model,
            "prompt_version": PROMPT_VERSION,
            "ollama_base_url": settings.base_url,
        }

    @app.post("/technology-summary", response_model=SummaryResponse)
    def technology_summary(request: SummaryRequest) -> SummaryResponse:
        """Summarize one technology for one user.

        Always answers 200. A model that is down, slow or wrong produces a
        ``FALLBACK`` summary rather than an error the screen has to handle:
        the caller is rendering a card that is already complete without it.
        """

        return _to_response(
            generate_summary(
                request.fact_pack,
                user_id=request.user_id,
                client=chat_client,
            )
        )

    return app


app = create_app()
