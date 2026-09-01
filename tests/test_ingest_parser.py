"""Tests for the ingest wikitext parser (SPEC §7.4–7.6).

Fixtures replicate real Wikibooks Cookbook markup: the {{recipesummary}}
template exists in both inline-lowercase and block-capitalized forms,
ingredients are bullet lists with [[Cookbook:X|display]] links, procedure
is a numbered list.
"""

from recipe_qa.ingest import (
    allergen_flags_from_ingredients,
    diet_tags_from_categories,
    extract_summary_params,
    parse_duration_minutes,
    parse_recipe_page,
)

INLINE_SUMMARY = (
    "{{recipesummary|category=Pasta recipes|servings=6|time=1 hour"
    "|difficulty=2|Image = [[Image:Foo.JPG|300px]]}}"
)

BLOCK_SUMMARY = """{{Recipe summary
| Category = Pasta recipes
| Servings = 4
| Difficulty = 3
}}"""

PAGE = """{{Recipe summary
| Category = Pasta recipes
| Servings = 4
| Time = 25 minutes
| Difficulty = 3
}}

{{recipe}}

This dish uses raw eggs.<ref>Some citation</ref>

==Ingredients==
* 4 free-range [[Cookbook:Egg|eggs]] with large yolks
* 3 [[Cookbook:Ounce|oz]] (65 g) fresh Italian [[Cookbook:Pancetta|pancetta]]
* Grated [[Cookbook:Parmesan Cheese|parmigiano]] cheese
* 12 oz (340 g) uncooked [[Cookbook:Pasta|pasta]]

==Procedure==
# Put on the desired quantity of [[Cookbook:Pasta|pasta]] to cook.
# [[Cookbook:Frying|Fry]] the pancetta until it is crispy.
# Mix and serve immediately.

== Notes, tips, and variations ==
* Some note.

[[Category:Italian recipes]]
[[Category:Recipes using egg]]
"""


class TestParseDurationMinutes:
    def test_hours(self):
        assert parse_duration_minutes("1 hour") == 60
        assert parse_duration_minutes("2 hours") == 120

    def test_minutes(self):
        assert parse_duration_minutes("20 minutes") == 20
        assert parse_duration_minutes("45 min") == 45

    def test_hours_and_minutes_sum(self):
        assert parse_duration_minutes("1 hour 30 minutes") == 90

    def test_range_takes_upper_bound(self):
        assert parse_duration_minutes("20-30 minutes") == 30
        assert parse_duration_minutes("20–30 minutes") == 30

    def test_unparseable_is_none(self):
        assert parse_duration_minutes("overnight") is None
        assert parse_duration_minutes("") is None
        assert parse_duration_minutes(None) is None


class TestExtractSummaryParams:
    def test_inline_lowercase_form(self):
        params = extract_summary_params(INLINE_SUMMARY)
        assert params["category"] == "Pasta recipes"
        assert params["time"] == "1 hour"
        assert params["servings"] == "6"

    def test_block_capitalized_form(self):
        params = extract_summary_params(BLOCK_SUMMARY)
        assert params["category"] == "Pasta recipes"
        assert params["servings"] == "4"
        assert "time" not in params

    def test_no_template(self):
        assert extract_summary_params("plain text, no template") == {}


class TestDietTags:
    def test_vegetarian_category(self):
        assert diet_tags_from_categories(["Vegetarian recipes", "Soup recipes"]) == ["vegetarian"]

    def test_vegan_implies_vegetarian(self):
        tags = diet_tags_from_categories(["Vegan recipes"])
        assert set(tags) == {"vegan", "vegetarian"}

    def test_gluten_free(self):
        assert diet_tags_from_categories(["Gluten-free recipes"]) == ["gluten-free"]

    def test_no_diet_categories(self):
        assert diet_tags_from_categories(["Italian recipes"]) == []


class TestAllergenFlags:
    def test_flags_from_ingredient_text(self):
        flags = allergen_flags_from_ingredients(
            [
                "4 free-range eggs with large yolks",
                "12 oz uncooked pasta",
                "Grated parmesan cheese",
                "1 cup chopped walnuts",
            ]
        )
        assert set(flags) == {"eggs", "gluten", "dairy", "nuts"}

    def test_clean_ingredients_have_no_flags(self):
        assert allergen_flags_from_ingredients(["2 carrots", "1 onion", "salt"]) == []


class TestParseRecipePage:
    def test_full_page(self):
        recipe = parse_recipe_page(
            title="Cookbook:Carbonara Pasta",
            url="https://en.wikibooks.org/wiki/Cookbook:Carbonara_Pasta",
            wikitext=PAGE,
            categories=["Italian recipes", "Recipes using egg"],
        )
        assert recipe.id == "carbonara-pasta"
        assert recipe.title == "Carbonara Pasta"
        assert recipe.url.endswith("Carbonara_Pasta")
        assert recipe.time_minutes == 25
        assert recipe.diet_tags == []
        # wiki links resolved to display text
        assert recipe.ingredients[0] == "4 free-range eggs with large yolks"
        assert recipe.ingredients[3] == "12 oz (340 g) uncooked pasta"
        assert len(recipe.steps) == 3
        assert recipe.steps[1] == "Fry the pancetta until it is crispy."
        assert "eggs" in recipe.allergen_flags
        # indexing text contains title, ingredients and steps; refs stripped
        assert "Carbonara" in recipe.text
        assert "Some citation" not in recipe.text
        assert "{{" not in recipe.text

    def test_page_without_time_or_sections(self):
        recipe = parse_recipe_page(
            title="Cookbook:Mystery Dish",
            url="https://example.org/mystery",
            wikitext="Just a paragraph of text, no structure.",
            categories=[],
        )
        assert recipe.time_minutes is None
        assert recipe.ingredients == []
        assert recipe.steps == []
        assert "paragraph of text" in recipe.text
