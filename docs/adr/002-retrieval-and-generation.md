# ADR-002: In-memory hybrid retrieval + single-call generation

- **Status:** Accepted
- **Date:** 2026-09-01

## Context

~50 short documents; questions mix lexical anchors (dish names: "carbonara")
with semantic paraphrases ("something warm for a cold evening") and hard
constraints (time, diet, excluded ingredients). The assignment scores cost
and latency explicitly, and requires refusals for out-of-corpus questions
plus deployment simplicity ("safe to deploy twice", no manual steps).

## Decision

1. **Hybrid retrieval, in-memory:** BM25 (`rank-bm25`) + dense embeddings
   (`BAAI/bge-small-en-v1.5`, local, 384-dim), fused with Reciprocal Rank
   Fusion. Indexes are built at startup from `data/corpus.json`; the
   embedding matrix for 50 docs is ~75 KB — brute-force cosine is
   microseconds.
2. **Hard metadata filters** (time / diet / excluded ingredients) applied on
   top of fused ranking, from a deterministic constraint parser (SPEC §7.2).
3. **Relevance gate before the LLM:** the best eligible candidate must clear
   a raw-signal threshold (cosine ≥ 0.57 OR BM25 ≥ 10.0) ⇒ otherwise an
   `out_of_domain` refusal with zero LLM cost (SPEC §4 stage 5). Two
   measured findings shaped this (evals/tune_thresholds.py, real corpus +
   bge-small):
   - RRF-fused scores are rank-based — identical scale for every query, no
     relevance signal — so the gate uses raw scores.
   - Food questions about dishes *absent* from the corpus score cosine
     0.669–0.750, inside the answerable range (0.626–0.859), while non-food
     questions stay ≤ 0.525. A score gate therefore detects "not about
     food"; dish-level absence is decided by the model in the single
     generation call, which sees the retrieved recipes. `out_of_corpus`
     stays $0 only when constraint filters empty the candidate set.
4. **Generation = one LLM call** with structured output, prompt limited to
   the retrieved recipes. Provider behind an OpenAI-compatible adapter
   (`base_url`/`model`/`key` via env); default `gpt-4o-mini`
   (cost numbers: TODO after measurement, prices verified on vendor page).

## Alternatives considered

1. **Vector database (pgvector/Qdrant/…).** Rejected: adds a second service,
   state, volumes and migrations — and turns ingest into a production step,
   conflicting with "new deployment without manual steps". Statelessness
   makes repeat-deploy idempotency true *by construction*. At 50 docs a DB
   buys nothing measurable.
2. **Cross-encoder reranker.** Rejected: +~400 MB image, +latency per
   question, over a candidate pool that metadata filters already shrink to a
   handful. No measurable precision win available at this corpus size.
3. **Agentic / self-correcting pipeline (LangGraph-style grading loops).**
   Rejected: ≥7 LLM calls per question vs 1 (7–20× cost and latency —
   explicit eval criteria), and a runtime LLM judge competes with the
   offline eval harness the assignment actually asks for. TODO: final
   measured single-call latency/cost in README.
4. **Lexical-only (BM25) retrieval.** Cheapest; rejected because paraphrase
   questions ("dinner idea without meat") share almost no vocabulary with
   recipe pages. Hybrid keeps BM25's exact-name strength and covers
   paraphrase — at the price of a local embedding model in the image
   (~size TODO), which we accept.
5. **Embeddings via API instead of local model.** Keeps the image slim;
   rejected as default because it adds a paid dependency and a network hop to
   every question (including ones that end in $0 refusals). The adapter
   already supports it via env — this is the documented fallback if the
   torch image proves too heavy for the deploy target (ADR-004).

## Consequences

- Whole service is one stateless container; corpus updates ship as a git
  commit + redeploy.
- Threshold θ must be tuned on the golden set and declared in SPEC §7.1.
- Startup pays model-load + index-build once (~seconds; measured → README).

## Revisit when

- Corpus > ~10k documents, corpus updates required without redeploy, or
  multiple instances needing shared state → pgvector.
- Golden-set precision drops as the corpus grows → reranker becomes worth
  re-measuring.
