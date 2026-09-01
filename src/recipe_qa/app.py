import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles

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
        if not settings.llm_api_key:
            raise RuntimeError(
                "LLM_API_KEY is not set — the service refuses to start "
                "misconfigured (fail-fast; see .env.example)"
            )
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
        return {
            "status": "ok",
            "corpus_size": app.state.pipeline.corpus_size,
            "git_sha": get_settings().git_sha,
        }

    @app.post("/ask", response_model=AskResponse)
    async def ask(request: AskRequest, response: Response) -> AskResponse:
        try:
            result = await app.state.pipeline.ask(request.question)
        except GenerationUnavailable:
            raise HTTPException(status_code=503, detail="generation_unavailable") from None
        response.headers["X-Request-ID"] = result.request_id
        return result

    # UI (SPEC §3.3): built frontend served from the same container — one URL,
    # no CORS. Mounted last so API routes keep precedence.
    static_dir = Path(get_settings().static_dir)
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="ui")

    return app


app = create_app()
