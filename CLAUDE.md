# CLAUDE.md — agent rules for this repository

Take-home assignment: Recipe Q&A service over a Wikibooks Cookbook corpus.
The process is graded, not just the code. These rules bind every change an
agent makes here.

## Source of truth

- **SPEC.md defines behavior.** Code implements SPEC; the eval harness
  asserts SPEC. If a change alters behavior, update SPEC.md in the same
  commit. A heuristic or constant that affects observable behavior and is
  not declared in SPEC §7 is a bug ("hidden hardcoded behavior").
- **The `AskResponse` Pydantic model is the single source of the API
  contract.** OpenAPI, the LLM structured-output schema, and eval validation
  all derive from it. Never invent, rename, or duplicate schema fields.
- Architecture decisions live in `docs/adr/`. Do not silently deviate from
  an accepted ADR — flag the conflict instead.

## Engineering discipline

- **Test before implementation** for deterministic modules: ingest metadata
  parser, query constraint parser, retrieval filters/threshold, `/ask`
  contract branches (with a mocked LLM). Commit the failing test first,
  the implementation second.
- LLM calls are never required by unit tests; anything nondeterministic is
  mocked. The eval harness is the only place that exercises the real model.
- Run `uv run pytest` and `uv run ruff check .` before every commit; never
  commit red.
- Commits: small, English, one logical step each, prefixed
  `feat|fix|test|docs|chore|ci|data|eval`. No AI-attribution footers.

## Safety policy (non-negotiable)

The service never confirms that a dish is free of an allergen or safe for a
medical condition — regardless of what retrieved data suggests. Safety
questions return `refused: true, refusal_reason: "safety"` with ingredient
lists and a disclaimer (SPEC §4, ADR-003).

## Scope

Do not add features beyond SPEC (auth, rate limiting, streaming, history,
extra endpoints). Cut scope is recorded in README, not silently implemented.
Secrets exist only in the environment; `.env` is gitignored, `.env.example`
documents the variables.
