import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from .config import Settings
from .db import init_pool, close_pool
from .services import (
    router as model_router,
    working_memory,
    embedding,
    archival_memory,
    summarizer,
    nats_client,
)
from .routes import chat, models_list, documents, sessions, jobs

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("orchestrator")

settings = Settings()

_http_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _http_client
    logger.info("Starting Memory Orchestrator...")

    # Initialize services
    model_router.init_routes(settings)
    embedding.init_embedding(settings.embed_url, settings.embed_model)
    archival_memory.init_archival(settings.lightrag_url)
    summarizer.init_summarizer(settings)

    # Initialize data stores
    await init_pool(settings)
    await working_memory.init_redis(settings.redis_url)
    await nats_client.init_nats(settings.nats_url)

    # Shared HTTP client
    _http_client = httpx.AsyncClient(timeout=300.0)

    # Initialize route modules
    chat.init_chat(settings, _http_client)
    documents.init_documents(settings)

    logger.info("Memory Orchestrator ready")
    yield

    # Shutdown
    logger.info("Shutting down Memory Orchestrator...")
    await nats_client.close_nats()
    await _http_client.aclose()
    await working_memory.close_redis()
    await close_pool()


app = FastAPI(
    title="Memory Orchestrator",
    version="0.1.0",
    description="OpenAI-compatible proxy with 3-tier memory",
    lifespan=lifespan,
)

app.include_router(chat.router)
app.include_router(models_list.router)
app.include_router(documents.router)
app.include_router(sessions.router)
app.include_router(jobs.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
