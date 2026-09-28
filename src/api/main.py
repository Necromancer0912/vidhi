"""
NyayaBot — FastAPI application entry point.
Stack: Qdrant + Upstash Redis + Ollama (MiniMax M3 + nomic-embed-text)
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.api.security import SecurityHeadersMiddleware, signing_key
from src.config import settings
from src.graph.builder import build_graph
from src.observability.prometheus_metrics import setup_prometheus

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


# ─────────────────────────────────────────────
# Application State (shared across requests)
# ─────────────────────────────────────────────


class AppState:
    graph = None
    qdrant_client = None
    redis = None  # Upstash Redis client
    dense_retriever = None
    bm25_retriever = None
    cache = None
    memory = None
    analytics = None


app_state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    logger.info("🚀 NyayaBot starting up...")

    # ── JWT secret enforcement ────────────────
    if not settings.jwt_secret and settings.is_production:
        raise RuntimeError(
            "JWT_SECRET is not set. Generate one with "
            "`python3 -c \"import secrets;print(secrets.token_urlsafe(48))\"` "
            "and add it to the environment before running in production."
        )
    signing_key()  # creates the development key now rather than on first sign-in

    # ── Qdrant Vector DB ──────────────────────
    from src.ingestion.indexer import get_qdrant_client

    app_state.qdrant_client = get_qdrant_client()
    logger.info("✓ Qdrant Vector DB connected")

    # ── Qdrant Dense Retriever ────────────────
    from src.retrieval.dense import DenseRetriever

    app_state.dense_retriever = DenseRetriever(client=app_state.qdrant_client)
    logger.info("✓ Qdrant vector retriever ready")

    # ── BM25 Sparse Retriever ─────────────────
    from src.retrieval.sparse import BM25Retriever

    try:
        app_state.bm25_retriever = BM25Retriever.load_index()
        logger.info("✓ BM25 index loaded")
    except Exception:
        logger.warning("⚠ BM25 index not found — sparse search disabled (run ingestion first)")
        app_state.bm25_retriever = BM25Retriever()

    # ── Upstash Redis (cache + memory + analytics) ──
    from src.cache.redis_store import (
        get_analytics,
        get_conversation_memory,
        get_rate_limiter,
        get_semantic_cache,
    )

    app_state.cache = get_semantic_cache()
    app_state.memory = get_conversation_memory()
    app_state.memory_store = app_state.memory
    app_state.analytics = get_analytics()
    logger.info("✓ Upstash Redis connected (cache + memory + analytics)")

    # ── LangGraph ────────────────────────────
    app_state.graph = build_graph(
        cache=app_state.cache,
        memory_store=app_state.memory,
        dense_retriever=app_state.dense_retriever,
        bm25_retriever=app_state.bm25_retriever,
    )
    active_model = settings.groq_model if settings.llm_provider == "groq" else settings.llm_model
    logger.info(f"✓ LangGraph compiled ({active_model} via {settings.llm_provider})")

    # ── LangSmith tracing (optional) ─────────
    if settings.langchain_api_key:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = settings.langchain_api_key
        os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project
        logger.info(f"✓ LangSmith tracing: {settings.langchain_project}")

    logger.info("✅ Vidhi ready!")
    yield

    # ── Shutdown ─────────────────────────────
    logger.info("Vidhi shutting down...")
    if app_state.qdrant_client:
        app_state.qdrant_client.close()


# ─────────────────────────────────────────────
# FastAPI App
# ─────────────────────────────────────────────

_docs = settings.enable_api_docs
app = FastAPI(
    title="Vidhi API",
    description="Production-grade multi-agent RAG for Indian Legal & Government Services",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if _docs else None,
    redoc_url="/redoc" if _docs else None,
    openapi_url="/openapi.json" if _docs else None,
)


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    # Log the detail, never return it: stack traces and driver errors leak internals.
    logger.error(f"Unhandled error on {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Something went wrong on our side."})


# Starlette CORSMiddleware raises ValueError if allow_origins contains "*" and allow_credentials is True.
# If wildcard is used, we set allow_credentials to False.
cors_origins = settings.cors_origins
allow_credentials = True
if "*" in cors_origins:
    allow_credentials = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=allow_credentials,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Admin-Secret"],
)

app.add_middleware(SecurityHeadersMiddleware)
setup_prometheus(app)

# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────
from src.api.routes import admin, auth, chat, export, feedback, health, retrieve  # noqa: E402

app.include_router(chat.router, prefix="/api/v1", tags=["Chat"])
app.include_router(retrieve.router, prefix="/api/v1", tags=["Retrieval"])
app.include_router(health.router, tags=["Health"])
app.include_router(feedback.router, prefix="/api/v1", tags=["Feedback"])
app.include_router(admin.router, prefix="/api/v1", tags=["Admin"])
app.include_router(export.router, prefix="/api/v1", tags=["Export"])
app.include_router(auth.router, prefix="/api/v1", tags=["Auth"])


# ─────────────────────────────────────────────
# Frontend static file serving
# Serves the built React app from frontend/dist/
# so a single `uvicorn main:app --port 8000` serves
# both the API and the UI. Run `npm run build` in
# frontend/ first to generate the dist/ folder.
# ─────────────────────────────────────────────
_DIST = Path(__file__).parent.parent.parent / "frontend" / "dist"

if _DIST.exists():
    # Serve static assets (JS, CSS, images) under their original paths
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/")
    async def serve_root():
        return FileResponse(_DIST / "index.html")

    # Catch-all: any unknown path returns index.html so client-side routes work
    _DIST_ROOT = _DIST.resolve()

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        if full_path.startswith(("api/", "health", "docs", "redoc", "openapi", "prometheus")):
            raise HTTPException(status_code=404)
        if any(part.startswith(".") for part in full_path.split("/")):
            raise HTTPException(status_code=404)

        # Resolve and confirm the file is inside dist/ so ../ tricks can't escape it.
        file_path = (_DIST_ROOT / full_path).resolve()
        if file_path.is_relative_to(_DIST_ROOT) and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(_DIST_ROOT / "index.html")
else:
    # frontend/dist not built yet — return JSON info at root
    @app.get("/")
    async def root():
        return {
            "name": "Vidhi",
            "description": "AI Legal Assistant for Indian Citizens 🇮🇳",
            "version": "1.0.0",
            "note": "Run 'npm run build' in frontend/ to serve the UI from this port.",
            "stack": {
                "llm": f"{settings.llm_model} via {settings.llm_provider}",
                "vector_db": "Qdrant",
                "cache": "Redis",
            },
            "docs": "/docs",
            "health": "/health",
        }
