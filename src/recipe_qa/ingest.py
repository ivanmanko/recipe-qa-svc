"""Wikitext → Recipe parsing (SPEC §7.4–7.6).

All extraction here is declaredly heuristic: a value that cannot be parsed
becomes None/[] ("unknown"), never a guess. The authoritative vocabularies
(diet categories, allergen terms) live in this module and are mirrored in
SPEC §7.
"""

import re

from recipe_qa.models import Recipe

# SPEC §7.5 — diet tags come only from Wikibooks category membership.
# Vegan implies vegetarian.
DIET_CATEGORY_MAP: dict[str, list[str]] = {
    "vegan recipes": ["vegan", "vegetarian"],
    "vegetarian recipes": ["vegetarian"],
    "gluten-free recipes": ["gluten-free"],
}

# SPEC §7.6 — allergen flags via word-boundary match of ingredient lines.
# Over-flagging is acceptable (flags only enrich safety answers and never
# assert absence); missing a term is the failure mode to avoid.
ALLERGEN_VOCAB: dict[str, list[str]] = {
    "nuts": ["nut", "nuts", "walnut", "almond", "pecan", "hazelnut", "cashew", "pistachio"],
    "peanuts": ["peanut", "peanuts"],
    "eggs": ["egg", "eggs", "yolk", "yolks", "mayonnaise"],
    "dairy": [
        "milk", "butter", "cream", "cheese", "parmesan", "parmigiano", "pecorino",
        "yogurt", "yoghurt", "mozzarella", "ricotta", "ghee", "lactose",
    ],
    "gluten": [
        "flour", "wheat", "pasta", "spaghetti", "penne", "noodle", "noodles",
        "bread", "breadcrumbs", "barley", "rye", "semolina", "couscous",
    ],
    "soy": ["soy", "soybean", "tofu", "edamame"],
    "fish": ["fish", "anchovy", "anchovies", "salmon", "tuna", "cod", "sardine", "sardines"],
    "shellfish": ["shrimp", "prawn", "prawns", "crab", "lobster", "clam", "clams",
                  "mussel", "mussels", "oyster", "oysters", "scallop", "scallops"],
    "sesame": ["sesame", "tahini"],
}

_DURATION_RANGE = re.compile(r"(\d+)\s*(?:-|–|—|\bto\b)\s*(\d+)")
_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|h\b|minutes?|mins?|m\b)", re.I)
_SUMMARY_TEMPLATE = re.compile(r"\{\{\s*recipe\s*summary(.*?)\}\}", re.I | re.S)
_HEADING = re.compile(r"^(=+)\s*(.*?)\s*=+\s*$")
_WIKI_LINK = re.compile(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]")
_NON_CONTENT_LINK = re.compile(r"\[\[(?:Category|File|Image)\s*:[^\]]*\]\]", re.I)
_REF = re.compile(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", re.I | re.S)
_HTML = re.compile(r"<!--.*?-->|<[^>]+>", re.S)
_TEMPLATE = re.compile(r"\{\{[^{}]*\}\}")


def parse_duration_minutes(text: str | None) -> int | None:
    """'1 hour 30 minutes' → 90; ranges take the upper bound; unparseable → None."""
    if not text:
        return None
    # "20-30 minutes" → "30 minutes" (upper bound, SPEC §7.4)
    text = _DURATION_RANGE.sub(lambda m: m.group(2), text)
    total = 0.0
    for value, unit in _DURATION_PART.findall(text):
        multiplier = 60 if unit.lower().startswith("h") else 1
        total += float(value) * multiplier
    return round(total) if total else None


def extract_summary_params(wikitext: str) -> dict[str, str]:
    """Parameters of {{recipesummary}} / {{Recipe summary}}, keys lowercased,
    spaces removed ('Prep Time' → 'preptime')."""
    match = _SUMMARY_TEMPLATE.search(wikitext)
    if not match:
        return {}
    body = _WIKI_LINK.sub("", match.group(1))  # drop links so their pipes don't split params
    params: dict[str, str] = {}
    for part in body.split("|"):
        if "=" not in part:
            continue
        key, _, value = part.partition("=")
        key = re.sub(r"\s+", "", key).lower()
        if key:
            params[key] = value.strip()
    return params


def diet_tags_from_categories(categories: list[str]) -> list[str]:
    tags: list[str] = []
    for category in categories:
        for tag in DIET_CATEGORY_MAP.get(category.strip().lower(), []):
            if tag not in tags:
                tags.append(tag)
    return tags


def allergen_flags_from_ingredients(ingredients: list[str]) -> list[str]:
    joined = " ".join(ingredients).lower()
    flags = []
    for flag, terms in ALLERGEN_VOCAB.items():
        pattern = r"\b(?:" + "|".join(re.escape(t) + "s?" for t in terms) + r")\b"
        if re.search(pattern, joined):
            flags.append(flag)
    return flags


def clean_wikitext(text: str) -> str:
    """Strip refs, templates, links and markup down to plain text."""
    text = _REF.sub("", text)
    text = _HTML.sub("", text)
    for _ in range(5):  # innermost-out, handles nested templates
        stripped = _TEMPLATE.sub("", text)
        if stripped == text:
            break
        text = stripped
    text = _NON_CONTENT_LINK.sub("", text)
    text = _WIKI_LINK.sub(lambda m: m.group(1), text)
    text = text.replace("'''", "").replace("''", "")
    return re.sub(r"[ \t]+", " ", text).strip()


def _split_sections(wikitext: str) -> dict[str, list[str]]:
    """Map of lowercased level-2 heading → its lines.

    Deeper headings (=== Subsection ===) do not start a new section: recipes
    like ramen split ingredients into subsections ("Soup", "Noodles"), and
    those lines belong to the enclosing Ingredients/Procedure section.
    """
    sections: dict[str, list[str]] = {}
    current = ""
    for line in wikitext.splitlines():
        heading = _HEADING.match(line.strip())
        if heading and len(heading.group(1)) <= 2:
            current = heading.group(2).lower()
            sections.setdefault(current, [])
        elif not heading:
            sections.setdefault(current, []).append(line)
    return sections


def _list_items(lines: list[str], marker: str) -> list[str]:
    items = []
    for line in lines:
        if line.lstrip().startswith(marker):
            cleaned = clean_wikitext(line.lstrip().lstrip(marker).strip())
            if cleaned:
                items.append(cleaned)
    return items


def _slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def parse_recipe_page(
    title: str, url: str, wikitext: str, categories: list[str]
) -> Recipe:
    display_title = title.removeprefix("Cookbook:").strip()
    sections = _split_sections(wikitext)
    ingredients = _list_items(sections.get("ingredients", []), "*")
    steps = _list_items(sections.get("procedure", []), "#")

    params = extract_summary_params(wikitext)
    if params.get("preptime") and params.get("cooktime"):
        prep = parse_duration_minutes(params["preptime"]) or 0
        cook = parse_duration_minutes(params["cooktime"]) or 0
        time_minutes = (prep + cook) or None
    else:
        time_minutes = parse_duration_minutes(params.get("time"))

    body_text = clean_wikitext(wikitext)
    body_text = re.sub(r"\n{3,}", "\n\n", body_text)

    return Recipe(
        id=_slugify(display_title),
        title=display_title,
        url=url,
        categories=categories,
        ingredients=ingredients,
        steps=steps,
        time_minutes=time_minutes,
        diet_tags=diet_tags_from_categories(categories),
        allergen_flags=allergen_flags_from_ingredients(ingredients),
        text=f"{display_title}\n\n{body_text}",
    )
