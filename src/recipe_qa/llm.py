from typing import Protocol

from openai import AsyncOpenAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from recipe_qa.config import Settings


class LLMClient(Protocol):
    async def complete(self, messages: list[dict[str, str]], **params) -> str: ...


class OpenAILLMClient:
    """Provider-agnostic-by-contract LLM client; default impl calls OpenAI chat completions.

    Kept behind the LLMClient Protocol so a different provider (or an
    internal multi-provider gateway) can be swapped in via env without
    touching the pipeline.
    """

    def __init__(self, settings: Settings, client: AsyncOpenAI | None = None):
        self._model = settings.llm_model
        self._client = client or AsyncOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            timeout=30.0,
        )

    @retry(
        wait=wait_random_exponential(multiplier=1, max=15),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(Exception),
    )
    async def complete(self, messages: list[dict[str, str]], **params) -> str:
        response = await self._client.chat.completions.create(
            model=self._model, messages=messages, **params
        )
        return response.choices[0].message.content or ""
