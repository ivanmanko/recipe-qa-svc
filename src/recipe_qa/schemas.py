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
