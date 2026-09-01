import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response

from recipe_qa.config import get_settings
from recipe_qa.embedder import get_embedder
from recipe_qa.llm import OpenAILLMClient
from recipe_qa.models import Recipe
from recipe_qa.pipeline import GenerationUnavailable, Pipeline
from recipe_qa.retrieval import RecipeIndex
from recipe_qa.schemas import AskRequest, AskResponse


@asynccontextmanager
async def _lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # Tests inject a pre-built pipeline (stub embedder, mocked LLM) before
    # startup; production builds the real one from the corpus file.
    if getattr(app.state, "pipeline", None) is None:
        settings = get_settings()
        corpus_file = Path(settings.corpus_path)
        recipes = (
            [Recipe(**item) for item in json.loads(corpus_file.read_text())]
            if corpus_file.exists()
            else []
        )
        index = RecipeIndex(recipes, get_embedder(settings), settings)
        await index.build()
        app.state.pipeline = Pipeline(
            index=index, llm=OpenAILLMClient(settings), settings=settings
        )
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Recipe Q&A Service", lifespan=_lifespan)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "corpus_size": app.state.pipeline.corpus_size}

    @app.post("/ask", response_model=AskResponse)
    async def ask(request: AskRequest, response: Response) -> AskResponse:
        try:
            result = await app.state.pipeline.ask(request.question)
        except GenerationUnavailable:
            raise HTTPException(status_code=503, detail="generation_unavailable") from None
        response.headers["X-Request-ID"] = result.request_id
        return result

    return app


app = create_app()
