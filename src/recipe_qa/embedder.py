import asyncio
import threading
from typing import Protocol

from openai import AsyncOpenAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from recipe_qa.config import Settings


class Embedder(Protocol):
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    async def embed_query(self, text: str) -> list[float]: ...


class LocalEmbedder:
    """ONNX-runtime embedder (fastembed) — no API key, no per-call cost.

    Runs the same BAAI/bge-small-en-v1.5 weights sentence-transformers would,
    verified equivalent to cosine 0.999999 (see ADR-002), but without torch:
    the CUDA-flavoured torch stack cost 3.2 GB of image for one query vector
    per request. Local embedding is what keeps deterministic refusals at $0 —
    the relevance gate needs the query vector before it can refuse.
    """

    def __init__(self, settings: Settings):
        self._model_name = settings.embedding_model
        self._batch_size = settings.embedding_batch_size
        self._model = None
        # Guards lazy construction only; onnxruntime inference is thread-safe.
        self._load_lock = threading.Lock()

    def _get_model(self):
        if self._model is None:
            with self._load_lock:
                if self._model is None:
                    from fastembed import TextEmbedding

                    self._model = TextEmbedding(model_name=self._model_name)
        return self._model

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return await asyncio.to_thread(self._embed_sync, texts)

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        # fastembed yields L2-normalized vectors for bge models and preserves
        # input order. Batch size is capped (config) because embedding the
        # whole corpus in one batch peaks at ~1.4 GB on these recipe lengths.
        model = self._get_model()
        return [v.tolist() for v in model.embed(texts, batch_size=self._batch_size)]

    async def embed_query(self, text: str) -> list[float]:
        embeddings = await self.embed_documents([text])
        return embeddings[0]


class OpenAIEmbedder:
    """API embeddings — available via env for deployments that would rather
    not ship the model at all. Trade-off (ADR-002): it puts a network call on
    every question, including the ones that currently refuse for $0."""

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
    if settings.embedding_provider == "local":
        return LocalEmbedder(settings)
    if settings.embedding_provider == "openai":
        return OpenAIEmbedder(settings)
    raise ValueError(f"Unknown embedding_provider: {settings.embedding_provider!r}")
