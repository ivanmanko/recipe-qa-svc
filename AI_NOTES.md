# AI usage notes

The assignment permits and recommends coding agents, and asks for the actual
instruction files rather than a summary. This service was built with Claude
Code in a single session. What follows is what I gave it, what I kept, and
what I overrode — including the places where the agent's output was wrong.

## The files I gave the agent

| File | What it is | Committed |
|---|---|---|
| [`docs/ai/agent-handoff.md`](docs/ai/agent-handoff.md) | The full briefing: assignment terms, evaluation criteria, the architectural decisions I had already made, the hour-by-hour plan, the commit sequence, and an explicit "do not build this" section. Verbatim, in Russian | yes |
| [`CLAUDE.md`](CLAUDE.md) | Standing rules the agent must follow on every change in this repository | yes |
| [`SPEC.md`](SPEC.md) | Written first, before any code; the agent implements against it | yes |
| [`docs/adr/`](docs/adr/) | Decisions with alternatives and revisit conditions | yes |

The handoff was deliberate preparation, not a prompt I improvised. Its most
useful section was the negative one — LangGraph-style self-correction loops,
a reranker, a vector database, RAGAS as the primary eval — each with the
reason it was rejected. Agents reach for those patterns by default because
they dominate RAG tutorials; naming them up front, with numbers, is what kept
the build at one LLM call per question instead of seven.

The rules that did the most work in `CLAUDE.md`:

- **SPEC is the source of truth.** Any heuristic affecting observable behavior
  that is not declared in SPEC §7 is a bug. The assignment calls hidden
  hardcoded behavior "the only incorrect option", so it became a hard rule
  rather than a preference.
- **Test before implementation** for deterministic modules, committed as
  separate red/green commits.
- **The `AskResponse` Pydantic model is the only schema definition** — never
  invent or duplicate fields.
- **Never confirm allergen safety**, regardless of what the data suggests.

## What I accepted

Most of the mechanical work: the MediaWiki ingest script, the wikitext parser,
BM25 + embedding retrieval with RRF, the FastAPI wiring, the TypeScript
frontend, the eval harness plumbing, the Dockerfile. This is code where the
specification is precise and the tests are the real check — exactly where an
agent is strongest. I read all of it; the tests are what I trust.

Also accepted with edits: the LLM adapter and embedder, carried over from an
earlier project of mine (`rag-agent`) and stripped of the parts this service
does not need (pgvector, LangGraph, reranker, RAGAS). Reuse was a deliberate
time saver, not the agent's invention.

## What I rejected or rewrote

**The relevance threshold, twice.** This is the one that matters, and both
corrections came from measuring rather than reasoning.

The plan said: put a threshold on the fused retrieval score; below it, refuse
as `out_of_corpus` without calling the LLM. The agent implemented exactly
that. It is wrong twice over, and I only found out by writing
`evals/tune_thresholds.py` to print real scores on the real corpus:

1. **RRF-fused scores carry no relevance signal at all.** Reciprocal Rank
   Fusion is rank-based, so the top document scores identically for every
   query — including "what is the capital of France?". A threshold on it is
   decoration. The gate had to move to raw cosine and BM25 magnitudes.
2. **The refusal reason was wrong.** Measured: questions about dishes *absent*
   from the corpus (sushi, pad thai) score cosine 0.669–0.750 — squarely
   inside the answerable range of 0.626–0.859. Non-food questions score
   ≤ 0.525. So a score gate can detect "not about food", but it cannot detect
   "this dish isn't in our corpus". The gate now returns `out_of_domain`, and
   dish-level absence is decided by the model, which sees the retrieved
   recipes and says they don't answer the question. SPEC §4 and ADR-002 carry
   the numbers.

**The gate was also evaluating the wrong candidate set.** After I fixed the
signal, two constrained questions started failing the golden set: the gate
was measuring the best score *after* metadata filtering, so "vegetarian dinner
under 30 minutes" was judged by how well it matched the handful of eligible
recipes rather than the corpus at large, and got refused. The gate answers
"is this about our domain" and must be filter-independent. Caught by the eval
harness, not by review — which is the argument for having one.

**Structured output mode.** I switched the provider to DeepSeek mid-build.
Rather than assume the OpenAI `json_schema` mechanism carries over, I checked
their documentation: DeepSeek supports only `json_object`, and warns about
occasional empty responses. So the schema moved into the prompt as an explicit
example, a retry was added around invalid output, and strict schema mode
became a config flag for providers that have it. Server-side validation runs
in both modes — the model is never trusted to honor the contract.

**Prices.** `CLAUDE.md` forbids writing model prices from memory; a stale
number in a section explicitly graded on cost is worse than no number. Prices
were read from the vendor's pricing page and cited with the date. Token counts
and latencies in the README come from an actual harness run against the
deployed code path, not estimates — which is also why the README admits we
miss the p95 latency target rather than restating the target as if met.

**Ingest details the plan didn't anticipate.** The category `Pasta recipes`
does not exist on Wikibooks (it is `Recipes using pasta and noodles`), and
recipes like ramen split ingredients into `=== subsections ===`, which the
first parser treated as new top-level sections and so returned zero
ingredients — silently dropping nine recipes. Both were found by looking at
the real API output and the corpus statistics, then locked down with tests.

**Startup behavior.** The service originally started fine with no API key and
failed on the first question. I made it fail fast at startup instead: a
misconfigured container should never accept traffic.

**Torch, removed after measuring.** The plan said `sentence-transformers` for
local embeddings, and the agent implemented it — the conventional choice.
Building the image is what exposed the cost: **6.39 GB**, because torch on
Linux defaults to the CUDA build, plus an outright build failure under
`UV_COMPILE_BYTECODE` (uv's 60 s/file limit, hit on torch's generated test
modules). CPU-only wheels got it to 3.2 GB, which was still absurd for a
service that computes one 384-dim vector per request. Swapping to ONNX
Runtime via `fastembed` — same `bge-small-en-v1.5` weights — landed at
**1.05 GB** and cut query embedding from 220 ms to 13 ms, which incidentally
brought retrieval back inside the SPEC §9 budget it had been missing. I
verified vector equivalence (cosine 0.999999, max delta 0.00045) *before*
swapping, precisely so the tuned relevance thresholds would not silently
shift; re-running the threshold script confirmed identical scores to three
decimals, and the golden set stayed 15/15. The lesson I would repeat: the
dependency an agent reaches for by default is the one worth measuring, and
"same weights, different runtime" is a change you must prove rather than
assume.

## Where I stopped the agent

Adding a payment method to the Northflank account, and passkey-confirming the
GitHub app installation. Both are credential and payment actions — the agent
correctly refused to do them and asked me, which is the behavior I want.

## Honest assessment of the division of labor

The agent wrote most of the lines. The decisions that would come up in a
review — one LLM call instead of seven, no vector store, what a refusal means
and which layer decides it, never asserting allergen safety, what goes in the
log line so a bad answer is diagnosable — were made before the session started
and are defended in the ADRs. The corrections that mattered came from
measurement: a script that printed real scores, and a harness that failed two
questions after a change that looked obviously right. That is the part I would
keep if I had to give up either half.
