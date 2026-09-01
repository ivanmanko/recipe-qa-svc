# Recipe Q&A Service

A question-answering service over a fixed corpus of 55 recipes from the
[Wikibooks Cookbook](https://en.wikibooks.org/wiki/Cookbook). Answers are
grounded only in the corpus, always carry citations, and questions the corpus
cannot answer are refused **machine-readably** (`refused` + a reason enum),
never with a polite paragraph a client has to parse.

Start with **[SPEC.md](SPEC.md)** — it was written before the code and is what
the eval harness asserts against. Decisions and their trade-offs are in
[docs/adr/](docs/adr/).

| | |
|---|---|
| Deployed UI + API | ⚠️ see [Deployment](#deployment) — blocked on a Northflank payment method |
| Container-level access | Northflank project dashboard (see [Deployment](#deployment)) |
| Eval status | **15/15** golden-set questions pass ([latest report](evals/reports/local-deepseek.json)) |
| Tests | 62 unit tests, no LLM or network required |

## What it does

```
POST /ask   {"question": "What's a vegetarian dinner I can make in under 30 minutes?"}

{
  "answer": "Air-fried zucchini is vegetarian and takes about 18 minutes...",
  "citations": [{"title": "Air Fried Zucchini", "url": "https://en.wikibooks.org/...",
                 "recipe_id": "air-fried-zucchini"}],
  "refused": false,
  "refusal_reason": null,
  "request_id": "0b0f...-..."
}
```

Three things the service will not do, by design:

- **Answer from model memory.** Ask for pad thai (not in the corpus) and you
  get `refused: true, refusal_reason: "out_of_corpus"`, not a recipe.
- **Ignore your constraints.** "Vegetarian, under 30 minutes" is a hard
  filter over recipe metadata, not a hint to the model. A cited recipe always
  satisfies the constraint — the eval harness asserts exactly this.
- **Judge safety.** "Is this nut-free?" returns
  `refused: true, refusal_reason: "safety"` plus the cited ingredient lists
  and a disclaimer. The corpus is an open wiki; it cannot establish absence of
  an allergen (traces, contamination, incomplete lists). See
  [ADR-003](docs/adr/003-refusal-policy-and-safety.md).

## Running locally

**Docker (preferred).** The image builds the TypeScript frontend, installs the
backend, and bakes the embedding model in, so startup needs no network beyond
the LLM API:

```bash
docker build -t recipe-qa-svc .
```

```bash
docker run --rm -p 8000:8000 -e LLM_API_KEY=sk-your-key recipe-qa-svc
```

**Without Docker** (needs [uv](https://docs.astral.sh/uv/) and Node 22):

```bash
cp .env.example .env  # then put your LLM_API_KEY in it
```

```bash
uv sync && (cd frontend && npm ci && npm run build) && uv run uvicorn recipe_qa.app:app --port 8000
```

Open http://localhost:8000 for the UI; the API is on the same origin
(`POST /ask`, `GET /health`, OpenAPI at `/docs`).

**Rebuilding the corpus** from scratch (only needs the script — the committed
`data/corpus.json` is the output of exactly this):

```bash
uv run python scripts/ingest.py
```

Selection is deterministic (fixed categories, fixed caps, members sorted by
title), and a re-run was verified to produce a byte-identical file. It is
reproducible against *unchanged* upstream pages — Wikibooks is a live wiki, so
an edit there will legitimately change the output. That is why the built
corpus is committed as well: the deployed image never depends on what the wiki
looks like at build time.

**Tests, lint, evals:**

```bash
uv run pytest && uv run ruff check . && uv run python evals/run_evals.py --target http://localhost:8000
```

## Architecture

One stateless container. No database.

```
question
  → validation (1–500 chars)                          → 422 if bad
  → safety gate      (trigger list, deterministic)    → refused: safety        [$0]
  → constraint parser (regex + vocabulary)
  → hybrid retrieval  (BM25 + bge-small, RRF) + hard metadata filters
  → relevance gate    (raw cosine / BM25 thresholds)  → refused: out_of_domain [$0]
       (no candidates left after filters)             → refused: out_of_corpus [$0]
  → ONE LLM call, structured output, only retrieved recipes in the prompt
  → grounding guard: citations ∩ retrieved; empty ⇒ refused: out_of_corpus
  → response + one structured JSON log line
```

Four of the five refusal paths cost nothing and are covered by unit tests with
no LLM in the loop. Only "the retrieved recipes don't answer this specific
dish question" needs the model — [ADR-002](docs/adr/002-retrieval-and-generation.md)
explains why that one cannot be a score threshold (measured: questions about
dishes *absent* from the corpus score as high as answerable ones; non-food
questions score far lower, which is what the gate keys on).

Deliberately absent, with reasons in the ADRs: vector database, reranker,
agentic/self-correction loops, chunking. At 55 short recipes each would add
cost, latency, and failure modes without measurable gain.

## Cost & Latency

All numbers below are **measured** on the 15-question golden set against
DeepSeek `deepseek-v4-flash`, not estimated. Prices verified on
[DeepSeek's pricing page](https://api-docs.deepseek.com/quick_start/pricing)
on 2026-09-01: $0.44 / 1M input tokens (cache miss), $1.32 / 1M output,
peak rates; **off-peak (11:00–01:00 and 04:00–06:00 UTC) is half of that**.

| Measured per LLM-answered question | |
|---|---|
| Prompt tokens | 2117 mean (848–2885) |
| Output tokens | 391 mean (109–801) |
| **Cost per question** | **$0.00145** peak · $0.00072 off-peak |
| Deterministic refusal (safety, out_of_domain, filtered-out) | **$0.00** |

| Cost per 1,000 questions | Peak | Off-peak |
|---|---|---|
| All questions reach the LLM (worst case) | **$1.45** | $0.72 |
| Golden-set mix (71% reach the LLM) | **$1.03** | $0.52 |

Infrastructure adds a flat $24/month (Northflank `nf-compute-100-2`,
1 vCPU / 2 GB) regardless of volume, which dominates the bill until roughly
20,000 questions/month.

| Measured latency | |
|---|---|
| Deterministic refusals (no LLM) | 6–14 ms |
| Retrieval only | 13 ms mean, 30 ms max |
| LLM call | 4188 ms mean, 7179 ms max |
| End-to-end, LLM-answered | 1.9–7.9 s |

**We miss the p95 < 4 s target in SPEC §9** — end-to-end LLM answers run 5–8 s.
Reported as measured rather than quietly relaxed. Generation is ~99% of that
time, so retrieval is not the thing to optimize.

Retrieval used to be 220 ms and missed its own < 100 ms target; swapping
torch for ONNX embeddings ([ADR-002](docs/adr/002-retrieval-and-generation.md))
cut it to 13 ms and shrank the image at the same time — see
[Deployment](#deployment).

**The bottleneck is output tokens** (391 mean, up to 801), because generation
time scales with tokens produced. What I would do next, in order:

1. **Cap and shorten answers.** The prompt asks for concise answers but sets
   no budget; adding `max_tokens` and tightening the format instruction is a
   one-line change that should cut the tail substantially.
2. **Stream the response.** Time-to-first-token is a fraction of total time;
   the UI could render progressively. Deliberately cut from this build
   (see [Cut scope](#cut-scope)) since the JSON contract is the deliverable.
3. **Cache identical questions.** The pipeline is deterministic at
   temperature 0; a small LRU on normalized question text makes repeats free.
   Worth it only once traffic shows repetition — unmeasured, so unbuilt.
4. **Trim the prompt.** 2117 input tokens for 5 full recipes; passing
   ingredients + steps without the prose preamble would cut this, at some
   risk to answer quality. Cheap in cost, minor in latency — hence last.

**When to change the model.** `deepseek-v4-flash` was chosen for price at
adequate quality; the swap is three environment variables and no code
([ADR-002](docs/adr/002-retrieval-and-generation.md)). Move **up** (e.g.
OpenAI `gpt-4o-mini`-class or `deepseek-v4-pro`) if the golden set starts
failing on grounding or the conflicting-recipe case, or if latency matters
more than cost — but re-run the harness first: that is what it is for.
Move **down** if a cheaper model keeps 15/15. The decision is measurement,
not taste.

## Deployment

**Status: not live.** The Northflank template ran and failed at the resource
step with `Please complete your account by adding a default payment method` —
the account has no payment method attached (the free tier still requires a
card on file). Everything upstream of that is done and verified: the GitHub
integration is linked, the template validates and is created on Northflank,
and the run reaches the project/service creation step. Adding the card is the
one manual, human action left; the deploy command itself is scripted below.

**Building the image locally is what surfaced the torch problem.** The first
image measured **6.39 GB**, because `sentence-transformers` pulls `torch`,
which on Linux defaults to the CUDA build — ~2.5 GB of nvidia libraries for a
service that computes one 384-dim vector per request on CPU. It also failed
the build outright under `UV_COMPILE_BYTECODE=1` (uv's 60 s/file limit, hit on
torch's generated test modules). Pinning CPU-only wheels got it to 3.2 GB;
dropping torch for ONNX Runtime (`fastembed`, same weights) is what actually
fixed it. See [ADR-002](docs/adr/002-retrieval-and-generation.md) for the
equivalence check and the numbers.

**Why Northflank.** AWS with Terraform would have consumed 2–3 hours of the
budget on ECS/IAM/ALB plumbing. Northflank gives git-driven container deploys,
a committed IaC template, and a project dashboard reviewers can be invited to.
Trade-offs and the conditions that would invalidate this choice are in
[ADR-004](docs/adr/004-deployment-northflank.md).

**Infrastructure as code.** [`northflank-template.json`](northflank-template.json)
defines the project, the secret group, and the combined service (build from
this repo's Dockerfile, port 8000 public). Nothing is clicked in a UI:

```bash
curl -X POST -H "Authorization: Bearer $NF_TOKEN" -H "Content-Type: application/json" --data @northflank-template.json https://api.northflank.com/v1/templates
```

```bash
curl -X POST -H "Authorization: Bearer $NF_TOKEN" -H "Content-Type: application/json" -d "{\"arguments\":{\"LLM_API_KEY\":\"$LLM_API_KEY\"}}" https://api.northflank.com/v1/templates/recipe-qa-svc/runs
```

**Safe to run twice.** The template is declarative and the service is
stateless — no database, no migrations, no ingest step in production; the
corpus ships inside the image. A second run of the same revision converges to
the same state instead of duplicating resources. Re-running the template with
`concurrencyPolicy: queue` serializes overlapping runs.

**Secrets** live only in the environment: `LLM_API_KEY` is passed as a
template argument at run time into a Northflank secret group, and as a GitHub
Actions secret for CI. The repository contains `.env.example` only; `.env` is
gitignored. No secret has ever been committed.

**CI/CD** ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)): every push
runs backend tests, ruff, and the frontend build. On `main`, Northflank builds
and deploys from the repo automatically, then CI waits for `/health` and runs
the **full eval harness against production** — a deploy that breaks grounding
or refusals fails the pipeline, not just one that fails to boot.

**Container-level access for reviewers:** invitation to the Northflank project
(Team → Members), which exposes build logs, runtime logs, container status,
and metrics. Chosen over shipping logs elsewhere because it needs no extra
infrastructure and shows the real thing.

## Debugging a bad answer in production

Every request emits exactly one structured JSON log line, and the
`request_id` in it is returned to the client in both the response body and the
`X-Request-ID` header — so a user complaint maps to a specific line. That line
carries: the question, the extracted constraints, whether the safety gate
fired, every retrieved recipe with its **raw BM25, cosine, and fused scores**,
whether the relevance gate passed, the model name, prompt and completion
tokens, per-stage latency, the refusal reason, and the citation ids (plus any
citation ids the model invented that the grounding guard dropped). That is
enough to localize the fault without reproducing it: wrong recipes retrieved
(scores and constraints show whether it was the parser or the ranking), right
recipes but a bad answer (retrieval was fine — a generation problem, and the
prompt is reconstructible from the logged ids), or a refusal that should have
been an answer (the gate's scores say whether it was the threshold or the
filters). The next step is a regression test: the failing question goes into
`evals/golden_set.yaml` with its expected properties, which turns a one-off
complaint into a permanent assertion.

## Cut scope

Deliberately not built, with what closing each gap would take:

| Cut | To close |
|---|---|
| **Auth and rate limiting** | Public unauthenticated endpoint. Add an API key middleware and a per-IP limiter (`slowapi`) fronted by the platform's WAF; ~half a day including tests. |
| **Response streaming** | Contract-first design returns one JSON object. Streaming needs a second SSE endpoint and a UI that renders partial answers while keeping the structured contract for machines. |
| **Conversation history** | Every question is independent; follow-ups like "and without eggs?" don't work. Needs session storage and query rewriting — which reintroduces state, so it would revisit ADR-002. |
| **Corpus updates without redeploy** | The corpus is baked into the image. Live updates need external storage and index rebuild-on-change — see the revisit conditions in ADR-002. |
| **Multi-language** | Corpus, prompts, and the constraint parser are English-only (declared in SPEC §7.8). Non-English questions typically refuse as out-of-domain. |
| **p95 < 4 s latency target** | Missed and documented above, with the optimization order. |
| **Load/soak testing** | Never run under concurrency. The service is stateless so it scales horizontally, but the per-process torch lock (`_local_model_lock.py`) serializes query embedding and is the first thing I would measure under load. |
| **Frontend tests** | The UI is ~120 lines of TypeScript verified by hand across all three states. The API contract it depends on is covered by backend tests. |

This is not production-grade in the sense of a service with real users behind
it: no auth, no rate limiting, no alerting on the logs it emits, single
instance, and no load testing. It *is* production-grade in the practices that
matter for reviewing it — spec first, deterministic behavior under test, an
automated quality gate that runs against production, reproducible builds,
secrets outside the repository, and no hidden hardcoded behavior.

## Repository map

| Path | What |
|---|---|
| [SPEC.md](SPEC.md) | Behavior specification — the contract, edge cases, every declared heuristic |
| [docs/adr/](docs/adr/) | Four ADRs: retrieval unit, retrieval+generation, refusal policy, deployment |
| [AI_NOTES.md](AI_NOTES.md) | How the agent was used, what I accepted, what I rewrote |
| [CLAUDE.md](CLAUDE.md) | The rules given to the coding agent |
| `scripts/ingest.py` | Corpus builder (MediaWiki API → `data/corpus.json`) |
| `src/recipe_qa/` | `pipeline` (stages), `retrieval`, `constraints`, `safety`, `generation`, `schemas` |
| `evals/` | Golden set, harness, threshold-tuning script, reports |
| `tests/` | 62 unit tests, no network or LLM |
| `frontend/` | Vite + vanilla TypeScript single page |
