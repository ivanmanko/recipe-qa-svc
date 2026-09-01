# ADR-001: A whole recipe is the retrieval unit (no chunking)

- **Status:** Accepted
- **Date:** 2026-09-01

## Context

RAG pipelines usually split documents into chunks sized for an embedding
model's context. Our corpus is ~50 Wikibooks recipes; a recipe page is short
(roughly 200–400 tokens of useful content) and internally coupled: the
ingredient list only makes sense next to its steps, and constraint filtering
(time, diet, allergens) is a property of the *recipe*, not of a fragment.

## Decision

Index and retrieve whole recipes. One corpus entry = one recipe = one
embedding = one BM25 document. The generation prompt receives complete
recipes (top-5, see SPEC §7.9).

## Alternatives considered

1. **Chunk into ingredients / steps sections.** Standard for long documents.
   Rejected: recipes fit whole into both the embedding input and the prompt;
   splitting breaks the ingredients↔steps linkage the answers depend on, adds
   a re-assembly step for citations (a citation must point at a recipe URL,
   not a fragment), and complicates metadata filtering for zero retrieval
   gain at this document size.
2. **Recipe + section-level hybrid (parent-child).** Useful when questions
   target a specific step in long documents. Rejected: unnecessary machinery
   at 200–400 tokens/document; nothing in the golden set needs sub-recipe
   resolution.

## Consequences

- Simplest possible citation model: retrieved id = cited id.
- Prompt size bounded: 5 recipes × ~400 tokens ≈ 2k tokens of context
  (measured value → README Cost & Latency).
- Long pages (if any slip in) are truncated at ingest to a declared cap
  rather than chunked — recorded in SPEC §7 if triggered.

## Revisit when

- Documents grow beyond ~1–2k tokens (e.g. multi-recipe pages or a corpus of
  full cooking guides), or
- Eval shows retrieval confusing recipes that share ingredients, where
  section-level embeddings would separate them.
