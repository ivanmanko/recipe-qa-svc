"""The /ask pipeline: SPEC §4 stages in order, first match wins.

Deterministic branches (safety, relevance gate) never call the LLM.
Every request emits exactly one structured JSON log line (SPEC §8).
"""

import json
import logging
import time
import uuid

from recipe_qa import generation
from recipe_qa.config import Settings
from recipe_qa.constraints import Constraints, extract_constraints
from recipe_qa.llm import LLMClient
from recipe_qa.retrieval import RecipeIndex, RetrievalResult
from recipe_qa.safety import is_safety_question
from recipe_qa.schemas import AskResponse, Citation, RefusalReason

logger = logging.getLogger("recipe_qa.request")

# Fixed polite templates (SPEC §3.1: text carries no contract weight).
REFUSAL_MESSAGES = {
    RefusalReason.out_of_corpus: (
        "Sorry — I can only answer from the recipes in this corpus, "
        "and none of them covers that."
    ),
    RefusalReason.out_of_domain: (
        "Sorry — I can only help with questions about the recipes in this corpus."
    ),
}

SAFETY_DISCLAIMER = (
    "I can't confirm whether a dish is safe for an allergy, intolerance, or any "
    "other condition. This corpus is an open wiki: ingredient lists may be "
    "incomplete and say nothing about traces or cross-contamination — please "
    "verify with a reliable source. What the closest matching recipe(s) list "
    "as ingredients:"
)

SAFETY_CITATIONS_LIMIT = 3  # SPEC §4 stage 2


class GenerationUnavailable(Exception):
    """LLM failed after retries or returned unusable output (SPEC §7.12)."""


class Pipeline:
    def __init__(self, index: RecipeIndex, llm: LLMClient, settings: Settings):
        self._index = index
        self._llm = llm
        self._settings = settings

    @property
    def corpus_size(self) -> int:
        return len(self._index.recipes)

    async def ask(self, question: str) -> AskResponse:
        request_id = str(uuid.uuid4())
        started = time.perf_counter()
        log: dict = {"request_id": request_id, "question": question}

        safety = is_safety_question(question)
        constraints = Constraints() if safety else extract_constraints(question)
        log["safety_triggered"] = safety
        log["extracted_constraints"] = constraints.model_dump()

        retrieval_started = time.perf_counter()
        result = await self._index.retrieve(question, constraints)
        retrieval_ms = round((time.perf_counter() - retrieval_started) * 1000)
        log["retrieved"] = [
            {
                "recipe_id": c.recipe.id,
                "bm25_score": round(c.bm25_score, 4),
                "vector_score": round(c.vector_score, 4),
                "fused_score": round(c.fused_score, 4),
            }
            for c in result.candidates
        ]
        log["threshold_passed"] = result.threshold_passed

        llm_ms = 0
        if safety:
            response = self._safety_response(request_id, result)
        elif not result.threshold_passed:
            response = self._refusal(request_id, RefusalReason.out_of_corpus)
        else:
            llm_started = time.perf_counter()
            try:
                response = await self._generate(request_id, question, result, log)
            finally:
                llm_ms = round((time.perf_counter() - llm_started) * 1000)

        log["model"] = self._settings.llm_model if llm_ms else None
        log["latency_ms"] = {
            "retrieval": retrieval_ms,
            "llm": llm_ms,
            "total": round((time.perf_counter() - started) * 1000),
        }
        log["refused"] = response.refused
        log["refusal_reason"] = response.refusal_reason
        log["citation_ids"] = [c.recipe_id for c in response.citations]
        logger.info(json.dumps(log, ensure_ascii=False, default=str))
        return response

    def _refusal(self, request_id: str, reason: RefusalReason) -> AskResponse:
        return AskResponse(
            answer=REFUSAL_MESSAGES[reason],
            citations=[],
            refused=True,
            refusal_reason=reason,
            request_id=request_id,
        )

    def _safety_response(self, request_id: str, result: RetrievalResult) -> AskResponse:
        cited = result.candidates[:SAFETY_CITATIONS_LIMIT] if result.threshold_passed else []
        parts = [SAFETY_DISCLAIMER] if cited else [
            "I can't make safety judgments, and no recipe in the corpus matches "
            "this question closely enough to show its ingredients."
        ]
        for candidate in cited:
            recipe = candidate.recipe
            parts.append(f"{recipe.title}: {'; '.join(recipe.ingredients)}")
        return AskResponse(
            answer="\n\n".join(parts),
            citations=[
                Citation(title=c.recipe.title, url=c.recipe.url, recipe_id=c.recipe.id)
                for c in cited
            ],
            refused=True,
            refusal_reason=RefusalReason.safety,
            request_id=request_id,
        )

    async def _generate(
        self, request_id: str, question: str, result: RetrievalResult, log: dict
    ) -> AskResponse:
        recipes = [c.recipe for c in result.candidates]
        messages = generation.build_messages(question, recipes)
        try:
            raw = await self._llm.complete(
                messages, response_format=generation.response_format(), temperature=0
            )
            parsed = generation.parse_answer(raw)
        except Exception as exc:
            log["generation_error"] = repr(exc)
            raise GenerationUnavailable(str(exc)) from exc

        if parsed.refused:
            reason = RefusalReason(parsed.refusal_reason or "out_of_corpus")
            return self._refusal(request_id, reason)

        # Grounding guard (SPEC §4 stage 7): citations restricted to what was
        # actually retrieved; a non-refusal without valid citations is not
        # grounded and becomes an out_of_corpus refusal.
        retrieved = {r.id: r for r in recipes}
        cited = [retrieved[i] for i in dict.fromkeys(parsed.citation_ids) if i in retrieved]
        log["dropped_citation_ids"] = [i for i in parsed.citation_ids if i not in retrieved]
        if not cited or not parsed.answer:
            return self._refusal(request_id, RefusalReason.out_of_corpus)

        return AskResponse(
            answer=parsed.answer,
            citations=[Citation(title=r.title, url=r.url, recipe_id=r.id) for r in cited],
            refused=False,
            refusal_reason=None,
            request_id=request_id,
        )
