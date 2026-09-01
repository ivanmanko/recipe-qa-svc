"""Choose and audit the relevance-gate thresholds (SPEC §7.1).

    uv run python evals/tune_thresholds.py

Reads `evals/tuning_set.yaml`, which shares no question with the golden set.
That separation is the point: thresholds picked on the same questions that
later measure the service would make the pass rate self-confirming. Prints
the raw scores per group and, most importantly, the **margin** between the
configured thresholds and the nearest question on each side — a threshold
pressed against a group boundary is the signature of overfitting.

Uses the real corpus and the real embedding model. No LLM is involved.
"""

import asyncio
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from recipe_qa.config import Settings  # noqa: E402
from recipe_qa.constraints import Constraints  # noqa: E402
from recipe_qa.embedder import get_embedder  # noqa: E402
from recipe_qa.models import Recipe  # noqa: E402
from recipe_qa.retrieval import RecipeIndex  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


async def score_group(index: RecipeIndex, questions: list[str]) -> list[tuple]:
    rows = []
    for question in questions:
        result = await index.retrieve(question, Constraints())
        best_vector = max(c.vector_score for c in result.candidates)
        best_bm25 = max(c.bm25_score for c in result.candidates)
        rows.append((question, best_vector, best_bm25, result.candidates[0].recipe.id))
    return rows


def print_group(name: str, rows: list[tuple]) -> None:
    print(f"\n== {name} ({len(rows)} questions)")
    print(f"{'cosine':>8} {'bm25':>7}  question")
    for question, vector, bm25, _ in sorted(rows, key=lambda r: r[1]):
        print(f"{vector:>8.3f} {bm25:>7.2f}  {question[:58]}")


async def main() -> int:
    settings = Settings()
    recipes = [Recipe(**r) for r in json.loads((ROOT / "data" / "corpus.json").read_text())]
    index = RecipeIndex(recipes, get_embedder(settings), settings)
    await index.build()

    tuning = yaml.safe_load((ROOT / "evals" / "tuning_set.yaml").read_text())

    # Guard the property this whole file exists to preserve.
    golden = yaml.safe_load((ROOT / "evals" / "golden_set.yaml").read_text())
    golden_questions = {case["question"].strip().lower() for case in golden}
    tuning_questions = {
        q.strip().lower() for group in tuning.values() for q in group
    }
    overlap = golden_questions & tuning_questions
    if overlap:
        print(f"FAIL: tuning set overlaps the golden set: {sorted(overlap)}")
        return 1

    answerable = await score_group(index, tuning["answerable"])
    non_food = await score_group(index, tuning["not_about_food"])
    absent = await score_group(index, tuning["absent_dishes"])

    print_group("answerable", answerable)
    print_group("not about food", non_food)
    print_group("food, but absent from the corpus", absent)

    v_threshold = settings.vector_score_threshold
    b_threshold = settings.bm25_score_threshold

    lowest_answerable_v = min(r[1] for r in answerable)
    highest_nonfood_v = max(r[1] for r in non_food)
    highest_nonfood_b = max(r[2] for r in non_food)

    print("\n== configured thresholds")
    print(f"vector {v_threshold:.3f} | bm25 {b_threshold:.2f}")
    print(
        f"\nanswerable cosine range   {min(r[1] for r in answerable):.3f}"
        f" – {max(r[1] for r in answerable):.3f}"
    )
    print(
        f"not-about-food cosine max {highest_nonfood_v:.3f}"
        f" | bm25 max {highest_nonfood_b:.2f}"
    )
    print(
        f"absent-dish cosine range  {min(r[1] for r in absent):.3f}"
        f" – {max(r[1] for r in absent):.3f}   <- inside the answerable range,"
        " which is why the gate refuses out_of_domain, not out_of_corpus"
    )

    margin_below = v_threshold - highest_nonfood_v
    margin_above = lowest_answerable_v - v_threshold
    print("\n== margin (larger is safer; a threshold hugging a boundary is overfitted)")
    print(f"above the loudest non-food question : {margin_below:+.3f}")
    print(f"below the quietest answerable one   : {margin_above:+.3f}")

    if margin_below <= 0 or margin_above <= 0:
        print("\nFAIL: the configured threshold does not separate the two groups")
        return 1
    print("\nOK: threshold sits in the gap between the groups")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
