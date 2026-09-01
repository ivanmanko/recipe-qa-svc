"""API contract (SPEC §3.1). `AskResponse` is the single source of truth:
OpenAPI, the LLM structured-output schema and the eval harness derive from it.
"""

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class RefusalReason(StrEnum):
    out_of_corpus = "out_of_corpus"
    out_of_domain = "out_of_domain"
    safety = "safety"


class AskRequest(BaseModel):
    # 1–500 chars after trimming (SPEC §3.1); violations → HTTP 422
    question: str = Field(min_length=1, max_length=500)

    @field_validator("question", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class Citation(BaseModel):
    title: str
    url: str
    recipe_id: str


class AskResponse(BaseModel):
    answer: str | None
    citations: list[Citation]
    refused: bool
    refusal_reason: RefusalReason | None
    request_id: str


class RecipeDetail(BaseModel):
    """One corpus recipe, served so a client can render a cited source in
    place (SPEC §3.3). Kept separate from AskResponse on purpose: /ask is the
    graded contract, and this is a presentation concern. `url` is mandatory —
    CC BY-SA attribution is impossible without it."""

    id: str
    title: str
    url: str
    time_minutes: int | None
    diet_tags: list[str]
    ingredients: list[str]
    steps: list[str]
