from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM — any OpenAI-compatible endpoint; the provider is configuration, not code.
    llm_api_key: str = ""
    llm_base_url: str | None = None
    llm_model: str = "gpt-4o-mini"

    # Embeddings: local by default (no key, no per-call cost); "openai" is the
    # documented slim-image fallback (ADR-002 alt. 5).
    embedding_provider: str = "huggingface"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

    # Retrieval — values mirrored in SPEC §7; change them there in the same commit.
    retrieval_top_k: int = 5
    rrf_k: int = 60
    # RRF-fused score of the best candidate below this => out_of_corpus refusal
    # without an LLM call. Tuned on the golden set (SPEC §7.1).
    relevance_threshold: float = 0.0

    corpus_path: str = "data/corpus.json"
    max_question_length: int = 500

    api_host: str = "0.0.0.0"
    api_port: int = 8000


@lru_cache
def get_settings() -> Settings:
    return Settings()
