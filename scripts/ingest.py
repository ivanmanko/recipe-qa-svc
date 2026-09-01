"""Build data/corpus.json from the Wikibooks Cookbook via the MediaWiki API.

The corpus is fully rebuildable from this script alone:

    uv run python scripts/ingest.py

Selection is declarative and deterministic: fixed categories with fixed
per-category caps (members sorted by title), plus EXTRA_PAGES that guarantee
the conflicting-recipe pair required by SPEC §2. Pages without a parseable
Ingredients section are meta/navigation pages, not recipes, and are skipped
(SPEC §7.13).
"""

import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from recipe_qa.ingest import parse_recipe_page  # noqa: E402
from recipe_qa.models import Recipe  # noqa: E402

API = "https://en.wikibooks.org/w/api.php"
USER_AGENT = "recipe-qa-takehome/0.1 (contact: ivanmankos@gmail.com)"
COOKBOOK_NS = 102

# category → max pages taken (alphabetical by title, deterministic)
CATEGORIES: dict[str, int] = {
    "Category:Soup recipes": 15,
    "Category:Dessert recipes": 15,
    "Category:Vegetarian recipes": 15,
    "Category:Recipes using pasta and noodles": 10,
}

# Guaranteed inclusions: two recipes of the same dish that disagree (SPEC §2).
EXTRA_PAGES = [
    "Cookbook:Spaghetti alla Carbonara",
    "Cookbook:Carbonara Pasta",
]

OUTPUT = Path(__file__).resolve().parent.parent / "data" / "corpus.json"


def _get(client: httpx.Client, **params) -> dict:
    params |= {"format": "json"}
    response = client.get(API, params=params)
    response.raise_for_status()
    return response.json()


def category_members(client: httpx.Client, category: str, limit: int) -> list[str]:
    data = _get(
        client,
        action="query",
        list="categorymembers",
        cmtitle=category,
        cmnamespace=COOKBOOK_NS,
        cmlimit=500,
    )
    titles = sorted(m["title"] for m in data["query"]["categorymembers"])
    return titles[:limit]


def fetch_pages(client: httpx.Client, titles: list[str]) -> list[dict]:
    """Content + categories + canonical URL for up to 10 titles per call
    (small batches keep category lists complete without continuation)."""
    pages = []
    for start in range(0, len(titles), 10):
        batch = titles[start : start + 10]
        data = _get(
            client,
            action="query",
            titles="|".join(batch),
            redirects=1,
            prop="revisions|categories|info",
            rvprop="content",
            rvslots="main",
            cllimit=500,
            inprop="url",
        )
        for page in data["query"]["pages"].values():
            if "missing" in page or "revisions" not in page:
                print(f"  ! skipping missing page: {page.get('title')}")
                continue
            pages.append(page)
    return pages


def build_corpus() -> list[Recipe]:
    recipes: dict[str, Recipe] = {}
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30) as client:
        selected: list[str] = []
        for category, cap in CATEGORIES.items():
            members = category_members(client, category, cap)
            print(f"{category}: {len(members)} pages")
            selected += members
        selected += EXTRA_PAGES
        # dedupe, preserve order
        selected = list(dict.fromkeys(selected))

        for page in fetch_pages(client, selected):
            wikitext = page["revisions"][0]["slots"]["main"]["*"]
            categories = [
                c["title"].removeprefix("Category:") for c in page.get("categories", [])
            ]
            recipe = parse_recipe_page(
                title=page["title"],
                url=page["fullurl"],
                wikitext=wikitext,
                categories=categories,
            )
            if not recipe.ingredients:
                print(f"  ! no ingredients section, skipping: {page['title']}")
                continue
            recipes[recipe.id] = recipe
    return sorted(recipes.values(), key=lambda r: r.id)


def main() -> None:
    corpus = build_corpus()
    if not 40 <= len(corpus) <= 60:
        print(f"WARNING: corpus size {len(corpus)} outside the 40–60 target (SPEC §2)")
    with_time = sum(1 for r in corpus if r.time_minutes is not None)
    with_diet = sum(1 for r in corpus if r.diet_tags)
    print(f"\n{len(corpus)} recipes | time_minutes: {with_time} | diet_tags: {with_diet}")
    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(
        json.dumps([r.model_dump() for r in corpus], indent=2, ensure_ascii=False) + "\n"
    )
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
