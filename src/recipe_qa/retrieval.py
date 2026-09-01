"""In-memory hybrid retrieval: BM25 + dense vectors fused with RRF (ADR-002).

Indexes are built once at startup from the corpus; ~50 documents make
brute-force cosine over a numpy matrix microseconds-fast. Hard constraint
filters and the relevance threshold implement SPEC §4 stages 4–5 and §5.
"""

import re
from dataclasses import dataclass

import numpy as np
from rank_bm25 import BM25Okapi

from recipe_qa.config import Settings
from recipe_qa.constraints import Constraints
from recipe_qa.embedder import Embedder
from recipe_qa.models import Recipe

_TOKEN = re.compile(r"\w+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def matches_constraints(recipe: Recipe, constraints: Constraints) -> bool:
    """Hard filters (SPEC §5). Unknown metadata under a constraint excludes
    the recipe (SPEC §7.7)."""
    if constraints.max_time_minutes is not None:
        if recipe.time_minutes is None or recipe.time_minutes > constraints.max_time_minutes:
            return False
    if constraints.diet is not None and constraints.diet not in recipe.diet_tags:
        return False
    if constraints.exclude_ingredients:
        ingredients = " ".join(recipe.ingredients).lower()
        for excluded in constraints.exclude_ingredients:
            if excluded in ingredients:
                return False
    return True


@dataclass
class RetrievedRecipe:
    recipe: Recipe
    bm25_score: float
    vector_score: float
    fused_score: float


@dataclass
class RetrievalResult:
    candidates: list[RetrievedRecipe]  # eligible, sorted by fused score, top-k
    threshold_passed: bool


class RecipeIndex:
    def __init__(self, recipes: list[Recipe], embedder: Embedder, settings: Settings):
        self._recipes = recipes
        self._embedder = embedder
        self._settings = settings
        self._bm25: BM25Okapi | None = None
        self._doc_matrix: np.ndarray | None = None

    @property
    def recipes(self) -> list[Recipe]:
        return self._recipes

    async def build(self) -> None:
        texts = [r.text for r in self._recipes]
        self._bm25 = BM25Okapi([_tokenize(t) for t in texts])
        vectors = np.array(await self._embedder.embed_documents(texts), dtype=np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        self._doc_matrix = vectors / norms

    async def retrieve(self, question: str, constraints: Constraints) -> RetrievalResult:
        assert self._bm25 is not None and self._doc_matrix is not None, "index not built"
        bm25_scores = np.asarray(self._bm25.get_scores(_tokenize(question)), dtype=np.float32)

        query = np.array(await self._embedder.embed_query(question), dtype=np.float32)
        query_norm = np.linalg.norm(query)
        if query_norm > 0:
            query = query / query_norm
        vector_scores = self._doc_matrix @ query

        fused = self._rrf(bm25_scores, vector_scores)

        eligible = [
            RetrievedRecipe(
                recipe=recipe,
                bm25_score=float(bm25_scores[i]),
                vector_score=float(vector_scores[i]),
                fused_score=float(fused[i]),
            )
            for i, recipe in enumerate(self._recipes)
            if matches_constraints(recipe, constraints)
        ]
        eligible.sort(key=lambda c: c.fused_score, reverse=True)
        candidates = eligible[: self._settings.retrieval_top_k]

        # Relevance gate on RAW signals over the UNFILTERED corpus: the gate
        # answers "is this question about our food domain at all", so it must
        # not depend on constraint filters (a "vegetarian under 30 minutes"
        # question scores lower against its few eligible recipes than against
        # the corpus-wide best match — measured in evals/tune_thresholds.py).
        # Raw scores, not RRF-fused: RRF is rank-based, its scale is
        # query-independent and carries no relevance signal. An emptied
        # candidate set is reported separately (pipeline → out_of_corpus).
        threshold_passed = len(self._recipes) > 0 and (
            float(vector_scores.max()) >= self._settings.vector_score_threshold
            or float(bm25_scores.max()) >= self._settings.bm25_score_threshold
        )
        return RetrievalResult(candidates=candidates, threshold_passed=threshold_passed)

    def _rrf(self, *score_lists: np.ndarray) -> np.ndarray:
        """Reciprocal Rank Fusion: Σ 1/(k + rank). Ranks computed over the
        whole corpus so filtering does not distort fusion."""
        k = self._settings.rrf_k
        fused = np.zeros(len(self._recipes), dtype=np.float32)
        for scores in score_lists:
            order = np.argsort(-scores)
            ranks = np.empty_like(order)
            ranks[order] = np.arange(1, len(order) + 1)
            fused += 1.0 / (k + ranks)
        return fused
