import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from recipe_qa.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    corpus_file = Path(settings.corpus_path)
    app.state.corpus = json.loads(corpus_file.read_text()) if corpus_file.exists() else []
    yield


app = FastAPI(title="Recipe Q&A Service", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "corpus_size": len(app.state.corpus)}
