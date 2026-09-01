"""Print best-candidate raw retrieval scores for answerable vs unanswerable
questions — the data behind the relevance-gate thresholds (SPEC §7.1).

    uv run python evals/tune_thresholds.py

Uses the real corpus and the real embedding model, no LLM. The chosen
thresholds must separate the two groups with a margin; the picked values are
recorded in config.py and mirrored in SPEC §7.1.
"""

import asyncio
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import json  # noqa: E402

from recipe_qa.config import Settings  # noqa: E402
from recipe_qa.constraints import Constraints  # noqa: E402
from recipe_qa.embedder import get_embedder  # noqa: E402
from recipe_qa.models import Recipe  # noqa: E402
from recipe_qa.retrieval import RecipeIndex  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# Extra unanswerable probes beyond the golden set, to see the score floor.
EXTRA_NEGATIVE = [
    "How do I fix a flat bicycle tire?",
    "Best strategy for chess openings?",
    "How do I make okonomiyaki?",
    "Recipe for beef wellington",
    "Tell me about the weather tomorrow",
]


async def main() -> None:
    settings = Settings()
    recipes = [Recipe(**r) for r in json.loads((ROOT / "data" / "corpus.json").read_text())]
    index = RecipeIndex(recipes, get_embedder(settings), settings)
    await index.build()

    cases = yaml.safe_load((ROOT / "evals" / "golden_set.yaml").read_text())
    groups: dict[str, list[tuple[str, str]]] = {"answerable": [], "unanswerable": []}
    for case in cases:
        expect = case["expect"]
        if "http_status" in expect or expect.get("refusal_reason") == "safety":
            continue  # decided before the relevance gate
        group = "unanswerable" if expect.get("refused") else "answerable"
        groups[group].append((case["id"], case["question"]))
    groups["unanswerable"] += [(f"extra-{i}", q) for i, q in enumerate(EXTRA_NEGATIVE)]

    for group, questions in groups.items():
        print(f"\n== {group} ==")
        print(f"{'case':32} {'best_vector':>11} {'best_bm25':>10}  top candidate")
        for case_id, question in questions:
            result = await index.retrieve(question, Constraints())
            top = result.candidates[0]
            best_vector = max(c.vector_score for c in result.candidates)
            best_bm25 = max(c.bm25_score for c in result.candidates)
            print(
                f"{case_id:32} {best_vector:>11.3f} {best_bm25:>10.2f}  {top.recipe.id}"
            )


if __name__ == "__main__":
    asyncio.run(main())
