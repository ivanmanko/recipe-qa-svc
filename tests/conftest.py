from recipe_qa.models import Recipe


class StubEmbedder:
    """Pre-baked vectors; unknown texts get a zero vector."""

    def __init__(self, vectors: dict[str, list[float]] | None = None):
        self._vectors = vectors or {}

    async def embed_documents(self, texts):
        return [self._vectors.get(t, [0.0, 0.0, 0.0]) for t in texts]

    async def embed_query(self, text):
        return self._vectors.get(text, [0.0, 0.0, 0.0])


def make_recipe(id_, title, text, time_minutes=None, diet_tags=(), ingredients=(), steps=()):
    return Recipe(
        id=id_,
        title=title,
        url=f"https://example.org/{id_}",
        ingredients=list(ingredients),
        steps=list(steps),
        time_minutes=time_minutes,
        diet_tags=list(diet_tags),
        text=text,
    )
