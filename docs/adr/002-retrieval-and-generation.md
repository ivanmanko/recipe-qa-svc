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
   (`BAAI/bge-small-en-v1.5`, local, 384-dim, run through **ONNX Runtime via
   `fastembed`**), fused with Reciprocal Rank Fusion. Indexes are built at
   startup from `data/corpus.json`; the embedding matrix for 55 docs is
   ~85 KB — brute-force cosine is microseconds.
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
   (`base_url`/`model`/`key` via env). Default: **DeepSeek
   `deepseek-v4-flash`** — prices verified on the vendor pricing page
   2026-09-01: $0.44 / 1M input tokens, $1.32 / 1M output (peak; off-peak
   half of that; cache-hit input $0.014/M). Alternative measured at decision
   time: OpenAI `gpt-4o-mini`-class models — comparable capability for this
   task, and the switch is three env vars (`LLM_BASE_URL`, `LLM_MODEL`,
   `LLM_SUPPORTS_JSON_SCHEMA=true` for strict schema mode). DeepSeek's API
   supports only `json_object` mode, so the output schema is exemplified in
   the prompt and always validated server-side; one retry on invalid output
   (their docs warn of occasional empty content), then 503.

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
   Rejected: ≥7 LLM calls per question vs 1, and a runtime LLM judge competes
   with the offline eval harness the assignment actually asks for. Measured
   cost of our single call: **$0.00145** per answered question (2117 input +
   391 output tokens), **4.2 s mean** generation latency. A 7-call graph
   would put that at roughly $0.01 and ~30 s per question — untenable against
   the latency budget, for a 55-recipe corpus where the golden set already
   passes 15/15 in one call.
4. **Lexical-only (BM25) retrieval.** Cheapest; rejected because paraphrase
   questions ("dinner idea without meat") share almost no vocabulary with
   recipe pages. Hybrid keeps BM25's exact-name strength and covers
   paraphrase — at the price of shipping an embedding model in the image
   (~350 MB of the 1.05 GB total), which we accept. Measured effect on the gate: raw BM25 alone would not separate the
   golden set's constrained questions (BM25 4.9–9.99) from non-food ones
   (3.4–8.65), while cosine does (0.626+ vs ≤ 0.525) — the two signals are
   complementary, which is why the gate accepts either.
5. **Embeddings via API instead of a local model.** Keeps the image slim;
   rejected as the default because it puts a network call on *every*
   question — including the ones the relevance gate refuses for $0, since
   the gate needs the query vector before it can decide. Still available via
   `EMBEDDING_PROVIDER=openai` for deployments that would rather not ship a
   model at all.
6. **Local embeddings via `sentence-transformers` (torch).** The conventional
   choice, and what this service shipped first. Replaced after measuring:
   torch dragged in the CUDA build on Linux (image **6.39 GB**; CPU-only
   wheels still left **3.2 GB**), broke the build outright under
   `UV_COMPILE_BYTECODE` (60 s/file limit hit on torch's generated test
   modules), and embedded a query in ~220 ms on CPU. ONNX Runtime via
   `fastembed` runs the *same* bge-small weights — verified equivalent at
   cosine 0.999999, max elementwise delta 0.00045, and the golden-set
   retrieval scores are identical to three decimals, so the tuned thresholds
   carried over unchanged. Result: **13 ms** mean query embedding (16× faster,
   and now inside the SPEC §9 budget it previously missed), 57 dependencies
   instead of 86.

## Consequences

- Whole service is one stateless container; corpus updates ship as a git
  commit + redeploy.
- Thresholds are tuned on the golden set and declared in SPEC §7.1
  (`evals/tune_thresholds.py` reproduces the numbers).
- Startup pays model-load + index-build once (~20 s cold, in the container the
  model is baked into the image so no download happens at boot).
- Measured retrieval cost at request time: 220 ms mean, 575 ms max —
  dominated by embedding the query on CPU, not by the 55×384 matrix scan.
  This exceeds the < 100 ms retrieval target in SPEC §9 and is recorded as
  measured; it is ~5% of an LLM-answered request, so it is not the bottleneck
  worth optimizing first (README).

## Revisit when

- Corpus > ~10k documents, corpus updates required without redeploy, or
  multiple instances needing shared state → pgvector.
- Golden-set precision drops as the corpus grows → reranker becomes worth
  re-measuring.
