from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM — any OpenAI-compatible endpoint; the provider is configuration, not code.
    # Defaults target DeepSeek (ADR-002); OpenAI needs base_url/model overrides
    # plus llm_supports_json_schema=true.
    llm_api_key: str = ""
    llm_base_url: str | None = "https://api.deepseek.com"
    llm_model: str = "deepseek-v4-flash"
    # DeepSeek's API accepts only {'type': 'json_object'}; providers with
    # strict json_schema support (OpenAI) can flip this on. Either way the
    # output is validated server-side against the schema (SPEC §7.11).
    llm_supports_json_schema: bool = False

    # Embeddings: local by default (no key, no per-call cost); "openai" is the
    # documented slim-image fallback (ADR-002 alt. 5).
    embedding_provider: str = "huggingface"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

    # Retrieval — values mirrored in SPEC §7; change them there in the same commit.
    retrieval_top_k: int = 5
    rrf_k: int = 60
    # Relevance gate (SPEC §7.1): the best eligible candidate must clear at
    # least one RAW-signal threshold, else the question is refused as
    # out_of_domain without an LLM call. Raw signals, not RRF-fused ones:
    # RRF is rank-based and its scale is identical for any query. Values
    # tuned on the golden set (evals/tune_thresholds.py): non-food questions
    # score vector <= 0.53 / bm25 <= 8.7, answerable ones >= 0.63 / exact
    # dish names >= 12.5.
    vector_score_threshold: float = 0.57
    bm25_score_threshold: float = 10.0

    corpus_path: str = "data/corpus.json"
    static_dir: str = "frontend/dist"
    max_question_length: int = 500

    api_host: str = "0.0.0.0"
    api_port: int = 8000


@lru_cache
def get_settings() -> Settings:
    return Settings()
