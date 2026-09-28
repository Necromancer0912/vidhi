"""
NyayaBot — Health check endpoints.
"""
from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends

from src.api.main import app_state
from src.api.security import require_admin
from src.config import settings
from src.models import HealthResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """System health check — tests all live dependencies."""
    qdrant_status = "ok"
    redis_status = "ok"
    llm_status = "ok"
    embed_status = "ok"

    # Check Qdrant
    try:
        app_state.qdrant_client.get_collections()
    except Exception:
        qdrant_status = "error"

    # Check Redis (Upstash)
    try:
        from src.cache.redis_store import redis_client
        r = redis_client()
        r.ping()
    except Exception:
        redis_status = "error"

    # Check LLM status based on provider
    if settings.llm_provider == "llamacpp":
        try:
            headers = {"Authorization": f"Bearer {settings.llamacpp_api_key}"} if settings.llamacpp_api_key else {}
            resp = httpx.get(f"{settings.llamacpp_base_url}/health", headers=headers, timeout=3)
            if resp.status_code != 200:
                llm_status = "error"
        except Exception:
            llm_status = "error"
    elif settings.llm_provider == "ollama":
        try:
            resp = httpx.get(f"{settings.ollama_llm_base_url}/api/tags", timeout=3)
            models = [m["name"] for m in resp.json().get("models", [])]
            base_model = settings.llm_model.split(":")[0]
            if not any(base_model in m for m in models):
                llm_status = "warning"
        except Exception:
            llm_status = "error"
    elif settings.llm_provider == "google":
        llm_status = "ok" if settings.google_api_key else "error"
    elif settings.llm_provider == "groq":
        llm_status = "ok" if settings.groq_api_key else "error"
    elif settings.llm_provider == "vllm":
        try:
            resp = httpx.get(
                f"{settings.vllm_base_url}/models",
                headers={"Authorization": f"Bearer {settings.vllm_api_key}"},
                timeout=3,
            )
            llm_status = "ok" if resp.status_code == 200 else "error"
        except Exception:
            llm_status = "error"
    else:
        llm_status = "unknown"

    # Check Embeddings status based on provider
    if settings.embed_provider == "llamacpp":
        try:
            headers = {"Authorization": f"Bearer {settings.llamacpp_api_key}"} if settings.llamacpp_api_key else {}
            resp = httpx.get(f"{settings.llamacpp_embed_url}/health", headers=headers, timeout=3)
            if resp.status_code != 200:
                embed_status = "error"
        except Exception:
            embed_status = "error"
    elif settings.embed_provider == "ollama":
        try:
            resp = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=3)
            models = [m["name"] for m in resp.json().get("models", [])]
            if not any("nomic" in m for m in models):
                embed_status = "warning"
        except Exception:
            embed_status = "error"
    else:
        embed_status = "unknown"

    all_ok = all(s == "ok" or s == "warning" for s in [qdrant_status, redis_status, llm_status, embed_status])

    return {
        "status": "healthy" if all_ok else "degraded",
        "services": {
            "qdrant": qdrant_status,
            "redis": redis_status,
            "llm": llm_status,
            "embeddings": embed_status,
        },
        "graph_ready": app_state.graph is not None,
        "stack": {
            "llm": "configured" if settings.is_production else settings.llm_model,
            "vector_db": "qdrant",
            "cache": "upstash",
        }
    }


@router.get("/metrics", dependencies=[Depends(require_admin)])
async def metrics_info():
    """Return current system metrics."""
    try:
        from src.cache.redis_store import get_analytics
        analytics = get_analytics()
        return {
            "graph_ready": app_state.graph is not None,
            "analytics": analytics.get_dashboard(),
        }
    except Exception as e:
        logger.error(f"Metrics error: {e}")
        return {"error": "metrics unavailable"}
