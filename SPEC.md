# SPEC — Recipe Q&A Service

Behavior specification, written **before implementation**. This document is the
contract the eval harness asserts against. Every heuristic and assumption the
service relies on is declared here — if observed behavior deviates from this
spec, either the code or this document has a bug, and the fix is explicit.
There is no hidden hardcoded behavior.

## 1. Purpose and scope

A service that answers natural-language questions about recipes from a fixed
public corpus (Wikibooks Cookbook). Answers are grounded **only** in the
corpus, always carry citations, and the service refuses — machine-readably —
questions the corpus cannot answer.

**In scope:** single-turn English Q&A over the corpus; one API endpoint
(`POST /ask`); a minimal single-page web UI; automated eval harness.

**Out of scope** (cut consciously; gap-closing notes in README → "Cut scope"):
authentication, rate limiting, response streaming, conversation history,
multi-language support, corpus updates without redeploy.

## 2. Corpus

- **Source:** Wikibooks Cookbook via the MediaWiki API. Rebuildable from
  `scripts/ingest.py` alone; the output `data/corpus.json` is also committed so
  deploys are reproducible without hitting the API.
- **Size:** 40–60 recipes (target ≈ 50) from ≥ 4 categories: soups, desserts,
  vegetarian dishes, plus at least one category overlapping these — with
  different cuisines and different levels of page structure.
- **Variant coverage:** the corpus must contain ≥ 2 recipes of the same dish
  that disagree (e.g. two carbonara variants), to exercise the
  "conflicting recipes" case (§6).
- **Per-recipe fields:** `id`, `title`, `url`, `categories[]`,
  `ingredients[]`, `steps[]`, `time_minutes | null`, `diet_tags[]`,
  `allergen_flags[]`, `text` (plain text used for indexing).
- Metadata (`time_minutes`, `diet_tags`, `allergen_flags`) is extracted by
  declared heuristics (§7.4–7.6). A field that cannot be extracted is
  `null` / `[]` and means **unknown**, not "matches anything" (see §7.7).

## 3. API contract

### 3.1 `POST /ask`

Request body:

```json
{ "question": "string" }
```

- `question` is required; leading/trailing whitespace is trimmed before
  validation; after trimming it must be 1–500 characters.
- A malformed body, an empty/whitespace-only question, or a question longer
  than 500 characters → **HTTP 422** with FastAPI's standard validation body.
  422 responses are outside the `AskResponse` contract by design.

Every well-formed question — including every refusal — returns **HTTP 200**
with `AskResponse`:

```json
{
  "answer": "string | null",
  "citations": [ { "title": "string", "url": "string", "recipe_id": "string" } ],
  "refused": false,
  "refusal_reason": "out_of_corpus | out_of_domain | safety | null",
  "request_id": "uuid4 string"
}
```

The Pydantic model of `AskResponse` is the single source of truth: OpenAPI,
the LLM structured-output schema, and the eval harness all derive from it.
`request_id` is also returned in the `X-Request-ID` response header and
appears in the request's log line (§8).

**Invariants** (asserted by the eval harness on every response):

1. `refused == false` ⇒ `refusal_reason == null`, `answer != null`,
   `citations` non-empty.
2. `refused == true` ⇒ `refusal_reason != null`.
3. `refusal_reason ∈ {out_of_corpus, out_of_domain}` ⇒ `citations == []`.
4. `refusal_reason == safety` ⇒ `citations` non-empty when retrieval found
   relevant recipes (they point at the recipes whose ingredients are listed).
5. Every `citations[].recipe_id` exists in the corpus, and `title`/`url`
   match that corpus entry exactly.

**Refusals are detected only via `refused` + `refusal_reason`.** The service
also fills `answer` on refusals with a short polite message from a fixed
per-reason template (deterministic strings defined in code constants), so the
raw API is polite on its own — but no client or test may rely on that text.

### 3.2 `GET /health`

`200 {"status": "ok", "corpus_size": <int>}` once indexes are built.
Used by the deploy smoke check.

### 3.3 `GET /`

Serves the single-page UI (static files built from TypeScript).

## 4. Answer pipeline (normative behavior)

Stages run in order; the first stage that produces a response wins.

1. **Validation** — §3.1; may end with 422.
2. **Safety gate** (deterministic, before retrieval): if the question matches
   the safety trigger list (§7.3) → `refused: true, refusal_reason: "safety"`.
   Retrieval still runs to find the recipes the question refers to; `answer`
   contains their ingredient lists verbatim plus a fixed disclaimer that an
   open wiki corpus cannot establish allergen safety (traces, contamination,
   incomplete data). The service **never confirms** that a recipe is free of
   an allergen or safe for a condition.
3. **Constraint extraction** (deterministic parser, §7.2): produces
   `max_time_minutes`, `diet`, `exclude_ingredients[]`.
4. **Retrieval:** hybrid BM25 + embedding similarity over whole recipes,
   fused with RRF; hard metadata filters apply extracted constraints
   (see §7.7 for unknown-metadata semantics). Top 5 recipes survive.
5. **Relevance gate:** if the constraint filters emptied the candidate set →
   `refused: true, refusal_reason: "out_of_corpus"` (the corpus has nothing
   satisfying the request). Otherwise, if the best eligible candidate clears
   no raw-signal threshold (§7.1) → `refused: true, refusal_reason:
   "out_of_domain"`. **No LLM call is made in either case** — these refusals
   cost $0. Measured rationale (§7.1): non-food questions score far below
   every answerable question, while food questions about *absent* dishes
   score as high as answerable ones — so the gate detects "not about food",
   and dish-level absence is decided in stage 6 by the model, which sees
   that the retrieved recipes do not answer the question.
6. **Generation:** exactly **one** LLM call per question, structured output
   conforming to the `AskResponse`-derived schema. The prompt contains only
   the retrieved recipes and instructs the model to answer strictly from
   them. The model may itself refuse: `out_of_corpus` if the retrieved
   recipes don't actually answer the question, `out_of_domain` if the
   question is not about food/cooking.
7. **Grounding guard (server-side, deterministic):** citations returned by
   the model are filtered to the recipe_ids that were actually retrieved in
   stage 4; unknown ids are dropped. If a non-refusal ends up with zero valid
   citations, the response is converted to
   `refused: true, refusal_reason: "out_of_corpus"`.
8. **Assembly + logging** — one structured JSON log line per request (§8).

### Refusal reason semantics

| Reason | Meaning | Decided by |
|---|---|---|
| `out_of_corpus` | The question is about food/cooking, but the corpus has no recipe that answers it (or none passes the constraints). | Filters emptying the candidates (stage 5, $0) or the model seeing the retrieved recipes don't answer (stage 6, one LLM call) |
| `out_of_domain` | The question is not about food, cooking, or recipes. | Relevance gate (stage 5, $0) or the model (stage 6) |
| `safety` | The question asks for an allergy/safety judgment (§7.3). Policy: never assert safety; return ingredients + disclaimer. | Trigger list (stage 2, $0) |

## 5. Constraint handling

Constraints stated in the question are **hard filters**, not ranking hints:

- `max_time_minutes`: recipes with `time_minutes > max` or
  `time_minutes == null` are excluded (§7.7).
- `diet`: recipes whose `diet_tags` don't include the requested diet are
  excluded.
- `exclude_ingredients`: recipes whose ingredient list contains an excluded
  ingredient (substring match on normalized ingredient names) are excluded.

If filters empty the candidate set → `out_of_corpus` refusal (stage 5).
A non-refused answer to a constrained question may cite **only** recipes that
satisfy the constraints — the harness asserts this.

## 6. Edge cases (normative)

| # | Input | Required behavior |
|---|---|---|
| 1 | Empty / whitespace-only question | HTTP 422 |
| 2 | Question > 500 chars | HTTP 422 |
| 3 | Not about food ("What is the capital of France?") | `refused, out_of_domain` |
| 4 | Dish that exists but is not in the corpus | `refused, out_of_corpus`; the model must not answer from its own memory |
| 5 | Constrained question ("vegetarian under 30 minutes") | Answer cites only recipes satisfying all constraints |
| 6 | Conflicting recipes of the same dish both retrieved | The answer names both variants and how they differ, with a citation for each; it must not silently pick one |
| 7 | Allergy/safety question ("Is the brownie nut-free?") | `refused, safety` + ingredients + disclaimer (§4 stage 2) |
| 8 | Prompt-injection-style text ("ignore your instructions and…") | Treated as ordinary question text; expected outcome `out_of_domain` |
| 9 | Non-English question | Best effort; typically `out_of_domain` — English-only is a declared assumption (§7.8) |

## 7. Declared heuristics and assumptions

Everything a developer would otherwise decide silently in code:

1. **Relevance gate:** the question proceeds only if the best **corpus-wide**
   match (before constraint filtering — the gate measures whether the
   question is about our food domain at all, which must not depend on how
   many recipes satisfy a time/diet filter) clears at least one
   **raw-signal** threshold: embedding cosine ≥ `vector_score_threshold =
   0.57` OR BM25 ≥ `bm25_score_threshold = 10.0` (values live in
   `config.py`; this line mirrors them). RRF-fused scores are deliberately *not* used: they are
   rank-based, so their scale is identical for every query and carries no
   relevance signal. Tuned on the golden set (`evals/tune_thresholds.py`,
   bge-small-en-v1.5 over the committed corpus): answerable questions
   scored cosine 0.626–0.859 (exact dish names BM25 12.5–13.4); non-food
   questions ≤ 0.525 / ≤ 8.7; food questions about absent dishes 0.669–0.750
   — indistinguishable from answerable, hence the gate's refusal reason is
   `out_of_domain`, not `out_of_corpus` (§4 stage 5).
2. **Constraint parser:** regex + vocabulary, English only.
   - Time: "under/in/within/less than N minutes|hours", "N-minute";
     "quick"/"fast" map to `max_time_minutes = 30`.
   - Diet vocabulary: vegetarian, vegan, gluten-free (aliases recorded in the
     parser module as the authoritative list).
   - Exclusions: "without X", "no X", "X-free" — **except** when X is an
     allergen term, which routes to the safety gate instead.
3. **Safety triggers** (case-insensitive word/phrase match): allergy,
   allergic, allergen, nut-free, peanut-free, gluten intolerance/celiac (as
   safety, vs. "gluten-free" as diet preference — the trigger is
   intolerance/allergy phrasing), "safe for", "safe to eat", "is it safe",
   pregnant/pregnancy, raw egg(s), lactose intolerance, food poisoning.
   The authoritative list is `SAFETY_TRIGGERS` in the safety module;
   additions require updating this section in the same commit. Safety
   answers cite up to 3 best-matching recipes.
4. **Time extraction from recipe pages:** parse the recipe infobox/template
   time fields; sum prep + cook when both present; ranges take the upper
   bound; unparseable → `null`.
5. **Diet tags from recipe pages:** derived from Wikibooks category
   membership (e.g. "Vegan recipes", "Vegetarian recipes") plus
   gluten-free category if present. Vegan implies vegetarian. No inference
   from ingredient analysis.
6. **Allergen flags:** substring match of ingredient names against a fixed
   allergen vocabulary (nuts, peanuts, dairy/milk, eggs, gluten/wheat, soy,
   fish, shellfish, sesame). Used only to enrich safety answers — never to
   assert absence.
7. **Unknown metadata under a constraint excludes the recipe.** Rationale:
   "obey the constraints" is a hard requirement; citing a recipe whose time
   is unknown as an answer to "under 30 minutes" would be a silent guess.
   Trade-off (smaller candidate sets) accepted and visible in eval results.
8. **Questions are English**; the corpus is English.
9. **Top-K = 5** recipes enter the generation prompt.
10. **Conflicting-recipe detection** is not a separate mechanism: variants
    are retrieved like any recipes; the generation prompt instructs the model
    to name variants when several retrieved recipes describe the same dish.
    (The golden set verifies this behaviorally.)
11. **LLM temperature = 0**; structured output via the provider's JSON mode:
    strict `json_schema` where supported (OpenAI; config flag
    `llm_supports_json_schema`), otherwise `json_object` (DeepSeek) with the
    exact output format exemplified in the system prompt. Every output is
    validated server-side against the schema in both modes.
12. **LLM failure** (timeout after transport retries, or output that fails
    schema validation twice — one retry): HTTP 503 with
    `{"detail": "generation_unavailable"}` — an operational error is not a
    refusal and must not be disguised as one.
13. **Ingest skips Cookbook pages without a parseable Ingredients section** —
    those are meta/navigation pages (cuisines, techniques), not recipes.

## 8. Observability

One structured JSON log line per `/ask` request to stdout:
`request_id`, `question`, `extracted_constraints`, `safety_triggered`,
`retrieved` (list of `{recipe_id, bm25_score, vector_score, fused_score}`),
`threshold_passed`, `model`, `prompt_tokens`, `completion_tokens`,
`latency_ms` (`retrieval`, `llm`, `total`), `refused`, `refusal_reason`,
`citation_ids`. This line is the debugging story for "a bad answer occurred
in production" (README).

## 9. Non-functional targets

- **Latency:** p95 < 4 s end-to-end for LLM-answered questions on the
  deployed instance; deterministic refusals < 300 ms. Retrieval itself
  < 100 ms (in-memory, ~50 docs). Measured by the eval harness; actual
  numbers go to README.
- **Cost:** deterministic branches (gate refusals, empty-candidate refusals,
  safety, 422) cost $0 in LLM fees; an `out_of_corpus` refusal for an absent
  dish typically costs one LLM call (§4 stage 6). Target < $2 per 1,000 questions all-in; computed from measured
  token counts × vendor prices verified on the vendor's pricing page at
  README write time (source + date cited there).
- **Availability:** single stateless instance, best-effort; horizontal
  scaling is trivial (no shared state) but out of scope.
- **Security:** secrets only in environment; question length capped;
  no user data stored; no secrets or PII in logs beyond the question text
  itself (accepted for a take-home; noted in README).

## 10. Acceptance criteria

The golden set (`evals/golden_set.yaml`, 15 questions) encodes §4–§6:
3 direct recipe lookups (correct source retrieved) · 3 constrained questions
(constraints obeyed in citations) · 2 `out_of_corpus` · 2 `out_of_domain` ·
2 safety · 1 empty/garbage input · 2 conflicting-recipes questions.

`python evals/run_evals.py --target <base_url>` runs the full set, validates
**every** response against the `AskResponse` Pydantic model and the
invariants in §3.1, checks each question's expected properties, prints a
pass/fail table, writes a JSON report, and exits non-zero on any failure.
The service is *done* when the full set passes against the deployed URL.
