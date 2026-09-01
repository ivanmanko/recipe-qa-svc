# ADR-003: Machine-readable refusal policy and allergy safety gate

- **Status:** Accepted
- **Date:** 2026-09-01

## Context

The assignment requires refusals that are detectable "without analysis of
natural language", and flags allergy questions ("Is this nut-free?") as a
case where we must decide what "careful" means. A wrong "yes, it's nut-free"
is the single most harmful output this service could produce: the corpus is
an open wiki with no guarantees about completeness of ingredient lists,
traces, or cross-contamination.

## Decision

1. **Refusal = `refused: true` + closed enum** `refusal_reason ∈
   {out_of_corpus, out_of_domain, safety}` (SPEC §3.1, §4). Polite text also
   appears in `answer` from fixed templates, but carries no contract weight.
2. **Refusal decisions are deterministic wherever possible:** the relevance
   threshold (out_of_corpus) and the safety gate fire before any LLM call;
   only the distinction "retrieved recipes don't actually answer this" /
   "not about food at all" is delegated to the model, constrained by
   structured output to the same enum.
3. **Safety policy: never confirm safety.** Questions matching the declared
   trigger list (SPEC §7.3) are answered with `refused: true,
   refusal_reason: "safety"`, citations to the relevant recipes, their
   ingredient lists verbatim, and a fixed disclaimer. The service states
   what the corpus *says*, and refuses the judgment itself.

## Alternatives considered

1. **Let the LLM decide all refusals.** Simplest pipeline; rejected: refusals
   become non-deterministic and untestable without an LLM in the loop, every
   refusal costs a paid call, and safety hinges on prompt compliance —
   exactly the failure mode the assignment warns about.
2. **Answer allergy questions from `allergen_flags` metadata.** Tempting
   ("the data is right there"); rejected: our flags come from substring
   heuristics over a community wiki — a "no nuts found" is evidence of
   absence in *our extraction*, not absence in the dish. The flags enrich
   the safety answer; they never assert absence.
3. **Hard-refuse safety questions with no information at all.** Safest to
   implement, but strictly less useful: showing the cited ingredient lists
   lets the user make their own judgment with sources. Kept the
   ingredients + disclaimer variant.

## Consequences

- The eval harness can assert refusal behavior exactly (flag + enum), with
  zero LLM calls for threshold/safety cases.
- The trigger list is a declared constant (SPEC §7.3) — false negatives are
  possible for unusual phrasings; the generation prompt carries a backstop
  instruction to route safety-flavored questions to the safety template.
  TODO: verify backstop wording during implementation.
- Some borderline questions ("gluten-free dessert?") are treated as diet
  preference, not safety — the boundary (intolerance/allergy phrasing) is
  declared in SPEC §7.3.

## Revisit when

- Real user traffic shows safety phrasings the trigger list misses (observed
  via the per-request log), or
- The corpus gains authoritative allergen data (curated source), which would
  justify metadata-based allergen *filtering* (still not safety assertions).
