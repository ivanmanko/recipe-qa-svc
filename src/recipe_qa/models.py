from pydantic import BaseModel


class Recipe(BaseModel):
    """One corpus entry = one whole recipe (ADR-001)."""

    id: str
    title: str
    url: str
    categories: list[str] = []
    ingredients: list[str] = []
    steps: list[str] = []
    time_minutes: int | None = None
    diet_tags: list[str] = []
    allergen_flags: list[str] = []
    text: str
