import asyncio
from typing import Protocol

from openai import AsyncOpenAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from recipe_qa._local_model_lock import TORCH_INFERENCE_LOCK
from recipe_qa.config import Settings


class Embedder(Protocol):
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    async def embed_query(self, text: str) -> list[float]: ...


class HuggingFaceEmbedder:
    """Local sentence-transformers embedder — no API key or network cost per call.

    Default: every question is embedded locally, so deterministic refusals
    stay at $0 and the service has no external dependency besides the LLM.
    """

    def __init__(self, settings: Settings):
        self._model_name = settings.embedding_model
        self._model = None

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
        return self._model

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return await asyncio.to_thread(self._embed_sync, texts)

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        # Guards both lazy model construction and inference — see
        # _local_model_lock.py for why this is process-wide.
        with TORCH_INFERENCE_LOCK:
            model = self._get_model()
            vectors = model.encode(texts, normalize_embeddings=True)
            return vectors.tolist()

    async def embed_query(self, text: str) -> list[float]:
        embeddings = await self.embed_documents([text])
        return embeddings[0]


class OpenAIEmbedder:
    """API embeddings — the slim-image fallback if the torch image is too heavy
    for the deploy target (ADR-002 alt. 5, ADR-004). Selected via env."""

    def __init__(self, settings: Settings, client: AsyncOpenAI | None = None):
        self._model = settings.embedding_model
        self._client = client or AsyncOpenAI(api_key=settings.llm_api_key)

    @retry(
        wait=wait_random_exponential(multiplier=1, max=20),
        stop=stop_after_attempt(5),
        retry=retry_if_exception_type(Exception),
    )
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = await self._client.embeddings.create(model=self._model, input=texts)
        return [item.embedding for item in response.data]

    async def embed_query(self, text: str) -> list[float]:
        embeddings = await self.embed_documents([text])
        return embeddings[0]


def get_embedder(settings: Settings) -> Embedder:
    if settings.embedding_provider == "huggingface":
        return HuggingFaceEmbedder(settings)
    if settings.embedding_provider == "openai":
        return OpenAIEmbedder(settings)
    raise ValueError(f"Unknown embedding_provider: {settings.embedding_provider!r}")
