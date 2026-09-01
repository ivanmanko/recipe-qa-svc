"""LLM generation with structured output (SPEC §4 stage 6).

One call per question. The output schema is derived from `LLMAnswer` and
enforced via the OpenAI-compatible `response_format` json_schema mechanism;
the pipeline still applies the deterministic grounding guard on top.
"""

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from recipe_qa.models import Recipe

SYSTEM_PROMPT = """You answer questions about recipes using ONLY the recipes provided below. Rules:

1. Ground every statement in the provided recipes. Never use outside knowledge, even for well-known dishes.
2. If the provided recipes do not actually answer the question, set refused=true with refusal_reason="out_of_corpus".
3. If the question is not about food, cooking, or recipes, set refused=true with refusal_reason="out_of_domain".
4. citation_ids must list the recipe_id of every recipe you used — only ids from the provided recipes.
5. If several provided recipes are variants of the same dish and they differ, describe both versions and what differs, citing each one. Do not silently pick one.
6. Respect any constraint in the question (time, diet, excluded ingredients): only use recipes that satisfy it.
7. If the question asks whether a dish is safe for an allergy, intolerance, pregnancy or similar, set refused=true with refusal_reason="out_of_corpus" — safety judgments are handled elsewhere and must not be answered here.
8. When refused=true: answer=null and citation_ids=[].
9. Keep answers concise and practical; plain text, no markdown.

Respond with a single json object in exactly this format:
{"answer": "the answer text, or null when refusing", "citation_ids": ["recipe-id-1"], "refused": false, "refusal_reason": null}
"refusal_reason" must be "out_of_corpus", "out_of_domain", or null. No other keys."""


class LLMAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str | None
    citation_ids: list[str]
    refused: bool
    refusal_reason: Literal["out_of_corpus", "out_of_domain"] | None


def response_format(supports_json_schema: bool) -> dict:
    """Strict schema where the provider supports it (OpenAI); plain JSON mode
    otherwise (DeepSeek) — the prompt carries the format example required by
    json_object mode, and parse_answer validates either way."""
    if supports_json_schema:
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "recipe_answer",
                "strict": True,
                "schema": LLMAnswer.model_json_schema(),
            },
        }
    return {"type": "json_object"}


def _format_recipe(recipe: Recipe) -> str:
    lines = [
        f"### recipe_id: {recipe.id}",
        f"Title: {recipe.title}",
        f"Total time: {f'{recipe.time_minutes} minutes' if recipe.time_minutes else 'unknown'}",
        f"Diet: {', '.join(recipe.diet_tags) if recipe.diet_tags else 'unspecified'}",
        "Ingredients:",
        *(f"- {item}" for item in recipe.ingredients),
        "Steps:",
        *(f"{n}. {step}" for n, step in enumerate(recipe.steps, start=1)),
    ]
    return "\n".join(lines)


def build_messages(question: str, recipes: list[Recipe]) -> list[dict[str, str]]:
    context = "\n\n".join(_format_recipe(r) for r in recipes)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Recipes:\n\n{context}\n\nQuestion: {question}"},
    ]


def parse_answer(raw: str) -> LLMAnswer:
    """Raises ValueError on output that violates the schema (SPEC §7.12)."""
    try:
        return LLMAnswer.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(f"LLM output does not match schema: {exc}") from exc
