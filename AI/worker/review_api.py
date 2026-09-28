"""Service-authenticated review operations; end-user admin authorization belongs to B."""

from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from registry.mapper import RegistryMapper
from registry.review import ReviewStatus
from worker.reviews import (
    ReviewIdempotencyConflict,
    ReviewNotFound,
    ReviewStateConflict,
    ReviewVersionConflict,
)

NonBlank = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
]


class ReviewAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    actor: NonBlank
    note: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]
    idempotency_key: NonBlank
    expected_version: int = Field(strict=True, ge=1)


class ResolveReview(ReviewAction):
    tech_id: Annotated[
        str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)
    ]


def install_review_routes(
    app: FastAPI, *, prefix: str, auth: list, database, mapper: RegistryMapper | None
):
    def invoke(operation):
        try:
            return {
                "message": "C Registry review",
                "data": operation().model_dump(mode="json"),
            }
        except ReviewNotFound as exc:
            raise HTTPException(404, "REVIEW_NOT_FOUND") from exc
        except ReviewVersionConflict as exc:
            raise HTTPException(409, "REVIEW_VERSION_CONFLICT") from exc
        except ReviewIdempotencyConflict as exc:
            raise HTTPException(409, "REVIEW_IDEMPOTENCY_CONFLICT") from exc
        except ReviewStateConflict as exc:
            raise HTTPException(409, "REVIEW_STATE_CONFLICT") from exc

    @app.get(prefix + "/registry/reviews", dependencies=auth)
    def list_reviews(
        status: ReviewStatus | None = None,
        after: Annotated[str | None, Query(max_length=128)] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ):
        return invoke(
            lambda: database().query_reviews(status=status, after=after, limit=limit)
        )

    @app.get(prefix + "/registry/reviews/{review_id}", dependencies=auth)
    def get_review(review_id: NonBlank):
        return invoke(lambda: database().get_review(review_id))

    @app.post(prefix + "/registry/reviews/{review_id}/resolve", dependencies=auth)
    def resolve_review(review_id: NonBlank, action: ResolveReview):
        return invoke(
            lambda: database().resolve_review(
                review_id=review_id, mapper=mapper, **action.model_dump()
            )
        )

    @app.post(prefix + "/registry/reviews/{review_id}/reprocess", dependencies=auth)
    def reprocess_review(review_id: NonBlank, action: ReviewAction):
        return invoke(
            lambda: database().reprocess_review(
                review_id=review_id, mapper=mapper, **action.model_dump()
            )
        )
