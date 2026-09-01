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

    # Embeddings: "local" (ONNX via fastembed, no key, no per-call cost) or
    # "openai" (API — see ADR-002 for why it is not the default).
    embedding_provider: str = "local"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384
    # Startup index build embeds the corpus in batches. Measured peak RSS for
    # 55 recipes: batch 55 (default) 1381 MB, 16 -> 667 MB, 8 -> 472 MB,
    # 4 -> 345 MB. Long recipe texts make attention memory scale with batch
    # size, so a small batch is what lets the service run on a 512 MB plan.
    embedding_batch_size: int = 4
    # ONNX Runtime sizes its thread pool from the *host's* visible cores, not
    # the container's CPU limit, and every thread carries its own allocation
    # arena. On a big cloud node that OOM-killed a 512 MB container at startup
    # (exit 137) while the same image ran fine on a laptop. Pinning the count
    # makes memory independent of whatever host we land on.
    embedding_threads: int = 1

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
