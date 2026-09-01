"""Contract tests for GET /recipes/{recipe_id} (SPEC §3.3).

The endpoint exists so a client can render a cited recipe in place instead of
sending the reader off-site; the `url` must survive, because CC BY-SA
attribution depends on it.
"""

from conftest import build_client, make_recipe

CARBONARA = make_recipe(
    "carbonara",
    "Spaghetti alla Carbonara",
    "Spaghetti alla Carbonara. Italian pasta.",
    time_minutes=60,
    ingredients=["400 g spaghetti", "4 eggs"],
    steps=["Boil pasta.", "Mix eggs."],
)
LENTIL_SOUP = make_recipe(
    "lentil-soup",
    "Lentil Soup",
    "Lentil Soup. A warming soup.",
    time_minutes=25,
    diet_tags=["vegetarian", "vegan"],
    ingredients=["1 cup red lentils"],
    steps=["Simmer."],
)
CORPUS = [CARBONARA, LENTIL_SOUP]


def test_returns_full_recipe():
    client, _ = build_client(CORPUS)
    response = client.get("/recipes/carbonara")
    assert response.status_code == 200
    assert response.json() == {
        "id": "carbonara",
        "title": "Spaghetti alla Carbonara",
        "url": "https://example.org/carbonara",
        "time_minutes": 60,
        "diet_tags": [],
        "ingredients": ["400 g spaghetti", "4 eggs"],
        "steps": ["Boil pasta.", "Mix eggs."],
    }


def test_diet_tags_are_returned():
    client, _ = build_client(CORPUS)
    body = client.get("/recipes/lentil-soup").json()
    assert body["diet_tags"] == ["vegetarian", "vegan"]
    assert body["time_minutes"] == 25


def test_unknown_id_is_404():
    client, _ = build_client(CORPUS)
    response = client.get("/recipes/not-a-recipe")
    assert response.status_code == 404
    assert response.json()["detail"] == "recipe_not_found"


def test_source_url_is_always_present():
    # CC BY-SA attribution is impossible without it (SPEC §3.3).
    client, _ = build_client(CORPUS)
    for recipe_id in ("carbonara", "lentil-soup"):
        assert client.get(f"/recipes/{recipe_id}").json()["url"]


def test_ask_citations_can_be_resolved_against_the_endpoint():
    """Every recipe_id a citation can carry must be fetchable — otherwise the
    UI could cite something it cannot then display."""
    client, _ = build_client(CORPUS)
    for recipe in CORPUS:
        assert client.get(f"/recipes/{recipe.id}").status_code == 200
