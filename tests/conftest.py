import asyncio
import json

from fastapi.testclient import TestClient

from recipe_qa.app import create_app
from recipe_qa.config import Settings
from recipe_qa.llm import Completion
from recipe_qa.models import Recipe
from recipe_qa.pipeline import Pipeline
from recipe_qa.rate_limit import SlidingWindowLimiter
from recipe_qa.retrieval import RecipeIndex


class StubEmbedder:
    """Pre-baked vectors; unknown texts get a zero vector."""

    def __init__(self, vectors: dict[str, list[float]] | None = None):
        self._vectors = vectors or {}

    async def embed_documents(self, texts):
        return [self._vectors.get(t, [0.0, 0.0, 0.0]) for t in texts]

    async def embed_query(self, text):
        return self._vectors.get(text, [0.0, 0.0, 0.0])


class MockLLM:
    def __init__(self, responses=None, error: Exception | None = None):
        self.responses = list(responses or [])
        self.error = error
        self.calls: list = []

    async def complete(self, messages, **params) -> Completion:
        self.calls.append((messages, params))
        if self.error is not None:
            raise self.error
        return Completion(
            content=self.responses.pop(0), prompt_tokens=1234, completion_tokens=56
        )


def llm_json(answer=None, citation_ids=(), refused=False, refusal_reason=None) -> str:
    return json.dumps(
        {
            "answer": answer,
            "citation_ids": list(citation_ids),
            "refused": refused,
            "refusal_reason": refusal_reason,
        }
    )


def make_recipe(id_, title, text, time_minutes=None, diet_tags=(), ingredients=(), steps=()):
    return Recipe(
        id=id_,
        title=title,
        url=f"https://example.org/{id_}",
        ingredients=list(ingredients),
        steps=list(steps),
        time_minutes=time_minutes,
        diet_tags=list(diet_tags),
        text=text,
    )


def build_client(
    corpus: list[Recipe],
    llm: MockLLM | None = None,
    embedder: StubEmbedder | None = None,
    **settings_overrides,
) -> tuple[TestClient, MockLLM]:
    """App with an injected pipeline: stub embedder, mocked LLM, tiny corpus."""
    llm = llm or MockLLM()
    # Stub embedder yields zero vectors and the tiny corpora yield small BM25
    # scores, so the production thresholds would block everything: disable
    # the gate by default, tests of the gate itself override explicitly.
    settings_overrides.setdefault("vector_score_threshold", 0.0)
    settings_overrides.setdefault("bm25_score_threshold", 0.0)
    settings = Settings(llm_api_key="test-key", **settings_overrides)
    index = RecipeIndex(corpus, embedder or StubEmbedder(), settings)
    asyncio.run(index.build())
    app = create_app()
    app.state.pipeline = Pipeline(index=index, llm=llm, settings=settings)
    app.state.limiter = SlidingWindowLimiter(settings.rate_limit_per_minute)
    return TestClient(app), llm
