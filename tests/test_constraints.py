"""Tests for deterministic query-constraint extraction (SPEC §7.2)."""

from recipe_qa.constraints import extract_constraints


class TestTimeConstraint:
    def test_under_n_minutes(self):
        c = extract_constraints("What's a vegetarian dinner I can make in under 30 minutes?")
        assert c.max_time_minutes == 30

    def test_within_hours(self):
        assert extract_constraints("a dinner within 1 hour").max_time_minutes == 60

    def test_less_than(self):
        assert extract_constraints("soup in less than 45 mins").max_time_minutes == 45

    def test_n_minute_adjective(self):
        assert extract_constraints("a 20-minute soup").max_time_minutes == 20

    def test_quick_maps_to_30(self):
        assert extract_constraints("a quick dessert").max_time_minutes == 30
        assert extract_constraints("something fast for lunch").max_time_minutes == 30

    def test_half_an_hour(self):
        assert extract_constraints("ready in half an hour").max_time_minutes == 30

    def test_no_time_constraint(self):
        assert extract_constraints("How do I make carbonara?").max_time_minutes is None


class TestDietConstraint:
    def test_vegetarian(self):
        assert extract_constraints("a vegetarian dinner").diet == "vegetarian"

    def test_vegan(self):
        assert extract_constraints("vegan soup ideas").diet == "vegan"

    def test_gluten_free_preference(self):
        assert extract_constraints("a gluten-free dessert").diet == "gluten-free"
        assert extract_constraints("gluten free cake").diet == "gluten-free"

    def test_no_diet(self):
        assert extract_constraints("How do I make carbonara?").diet is None


class TestExcludeIngredients:
    def test_without(self):
        c = extract_constraints("a soup without onions")
        assert c.exclude_ingredients == ["onion"]

    def test_with_no(self):
        c = extract_constraints("dessert with no eggs please")
        assert c.exclude_ingredients == ["egg"]

    def test_no_exclusions(self):
        assert extract_constraints("How do I make carbonara?").exclude_ingredients == []


def test_combined_question():
    c = extract_constraints("a quick vegetarian pasta without mushrooms")
    assert c.max_time_minutes == 30
    assert c.diet == "vegetarian"
    assert c.exclude_ingredients == ["mushroom"]
    assert c.any()


def test_unconstrained_question():
    assert not extract_constraints("How do I make carbonara?").any()
