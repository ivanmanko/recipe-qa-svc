"""Tests for hybrid retrieval: BM25 + vectors + RRF, hard filters, threshold.

The embedder is stubbed with fixed vectors, so every assertion here is
deterministic and LLM/network-free (SPEC §4 stages 4–5).
"""

import pytest

from recipe_qa.config import Settings
from recipe_qa.constraints import Constraints
from recipe_qa.models import Recipe
from recipe_qa.retrieval import RecipeIndex, matches_constraints


def make_recipe(id_, title, text, time_minutes=None, diet_tags=(), ingredients=()):
    return Recipe(
        id=id_,
        title=title,
        url=f"https://example.org/{id_}",
        ingredients=list(ingredients),
        time_minutes=time_minutes,
        diet_tags=list(diet_tags),
        text=text,
    )


CARBONARA = make_recipe(
    "carbonara",
    "Spaghetti alla Carbonara",
    "Spaghetti alla Carbonara. Italian pasta with eggs, pecorino and guanciale.",
    time_minutes=60,
    ingredients=["400 g spaghetti", "4 eggs", "100 g pecorino"],
)
LENTIL_SOUP = make_recipe(
    "lentil-soup",
    "Lentil Soup",
    "Lentil Soup. A warming soup of red lentils and vegetables.",
    time_minutes=25,
    diet_tags=["vegetarian", "vegan"],
    ingredients=["1 cup red lentils", "1 onion", "2 carrots"],
)
BROWNIES = make_recipe(
    "brownies",
    "Brownies",
    "Brownies. Rich chocolate dessert squares with walnuts.",
    time_minutes=45,
    ingredients=["200 g chocolate", "2 eggs", "1 cup flour", "1 cup walnuts"],
)
NO_TIME = make_recipe(
    "mystery-stew",
    "Mystery Stew",
    "Mystery Stew. A stew of unknown provenance and duration.",
    ingredients=["1 mystery vegetable"],
)

CORPUS = [CARBONARA, LENTIL_SOUP, BROWNIES, NO_TIME]


class StubEmbedder:
    """Returns pre-baked vectors; unknown texts get a zero vector."""

    def __init__(self, vectors: dict[str, list[float]]):
        self._vectors = vectors

    async def embed_documents(self, texts):
        return [self._vectors.get(t, [0.0, 0.0, 0.0]) for t in texts]

    async def embed_query(self, text):
        return self._vectors.get(text, [0.0, 0.0, 0.0])


def neutral_embedder():
    return StubEmbedder({})


async def build_index(embedder=None, **settings_overrides) -> RecipeIndex:
    settings = Settings(llm_api_key="unused", **settings_overrides)
    index = RecipeIndex(CORPUS, embedder or neutral_embedder(), settings)
    await index.build()
    return index


class TestMatchesConstraints:
    def test_max_time_excludes_slower_and_unknown(self):
        c = Constraints(max_time_minutes=30)
        assert matches_constraints(LENTIL_SOUP, c)
        assert not matches_constraints(CARBONARA, c)
        # unknown time is excluded under a time constraint (SPEC §7.7)
        assert not matches_constraints(NO_TIME, c)

    def test_diet_filter(self):
        c = Constraints(diet="vegetarian")
        assert matches_constraints(LENTIL_SOUP, c)
        assert not matches_constraints(CARBONARA, c)

    def test_exclude_ingredients_substring(self):
        c = Constraints(exclude_ingredients=["onion"])
        assert not matches_constraints(LENTIL_SOUP, c)  # "1 onion"
        assert matches_constraints(CARBONARA, c)

    def test_no_constraints_matches_all(self):
        c = Constraints()
        assert all(matches_constraints(r, c) for r in CORPUS)


class TestRetrieve:
    @pytest.mark.asyncio
    async def test_lexical_match_ranks_first(self):
        index = await build_index()
        result = await index.retrieve("how do I make carbonara", Constraints())
        assert result.candidates[0].recipe.id == "carbonara"
        assert result.threshold_passed

    @pytest.mark.asyncio
    async def test_semantic_match_without_lexical_overlap(self):
        query = "a warming legume dinner"
        embedder = StubEmbedder(
            {
                query: [1.0, 0.0, 0.0],
                LENTIL_SOUP.text: [0.99, 0.1, 0.0],
                CARBONARA.text: [0.0, 1.0, 0.0],
                BROWNIES.text: [0.0, 0.0, 1.0],
                NO_TIME.text: [0.0, 0.9, 0.4],
            }
        )
        index = await build_index(embedder)
        result = await index.retrieve(query, Constraints())
        assert result.candidates[0].recipe.id == "lentil-soup"

    @pytest.mark.asyncio
    async def test_filters_drop_ineligible_candidates(self):
        index = await build_index()
        result = await index.retrieve("soup", Constraints(max_time_minutes=30))
        ids = [c.recipe.id for c in result.candidates]
        assert ids == ["lentil-soup"]

    @pytest.mark.asyncio
    async def test_filters_can_empty_the_result(self):
        index = await build_index()
        result = await index.retrieve("dessert", Constraints(diet="vegan", max_time_minutes=10))
        assert result.candidates == []
        assert not result.threshold_passed

    @pytest.mark.asyncio
    async def test_threshold_blocks_weak_matches(self):
        index = await build_index(relevance_threshold=999.0)
        result = await index.retrieve("how do I make carbonara", Constraints())
        assert result.candidates  # candidates are still reported for logging
        assert not result.threshold_passed

    @pytest.mark.asyncio
    async def test_top_k_limit(self):
        index = await build_index(retrieval_top_k=2)
        result = await index.retrieve("recipe", Constraints())
        assert len(result.candidates) <= 2

    @pytest.mark.asyncio
    async def test_scores_are_recorded_for_logging(self):
        index = await build_index()
        result = await index.retrieve("carbonara", Constraints())
        top = result.candidates[0]
        assert top.fused_score > 0
        assert top.bm25_score >= 0
        assert top.vector_score is not None
