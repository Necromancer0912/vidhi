"""
NyayaBot — Central configuration using Pydantic Settings.
All config is loaded from environment variables / .env file.

Production stack:
  LLM      → gemma4:31b-cloud via Ollama Cloud (benchmarked fastest free model;
             see scripts/benchmark_llm.py and data/benchmarks/)
  Embed    → nomic-embed-text (768-dim) via local Ollama
  Reranker → BAAI/bge-reranker-v2-m3 (behind ENABLE_RERANKER, CUDA hosts only)
  VectorDB → Qdrant
  Cache    → Redis
"""

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.environ.get("ENV_FILE", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── LLM ──────────────────────────────────────────────────────────────
    # Primary: gemma4:31b-cloud via Ollama Cloud (free tier; cloud proxy, no
    # download). Fallback path: Groq / Gemini via LLM_FALLBACK_MODEL.
    google_api_key: str = ""
    llm_model: str = "gemini-2.0-flash"
    llm_fallback_model: str = "gemini-1.5-flash"  # used automatically on 429
    llm_provider: str = "google"  # "google" | "groq" | "ollama" | "vllm"
    ollama_llm_base_url: str = "http://localhost:11434"
    vllm_base_url: str = "http://localhost:8000/v1"
    # Set in .env. A default here would be a public, shared key for any server started with it.
    vllm_api_key: str = ""

    # ── llama.cpp ──────────────────────────────────────────────────────────────────
    # LLM server (port 8080) and embedding server (port 8081) are separate
    # llama-server instances on a separate GPU PC, reached via Tailscale.
    llamacpp_base_url: str = "http://localhost:8080"  # LLM inference server
    llamacpp_embed_url: str = "http://localhost:8081"  # embedding server (separate instance)
    llamacpp_api_key: str = ""  # same key for both servers; set LLAMACPP_API_KEY in .env
    llamacpp_embed_model: str = "nomic-embed-text"  # model name sent to /v1/embeddings

    # ── Embed provider ────────────────────────────────────────────────────
    # NOTE: get_embedding_model() is cached per-process via lru_cache.
    # Changing EMBED_PROVIDER requires a full server restart to take effect.
    embed_provider: str = "ollama"  # "ollama" | "llamacpp"

    # ── Groq (free, 14400 req/day — great for testing) ───────────────────
    # Get free key: https://console.groq.com → API Keys
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"  # 131K TPM — best for concurrent testing

    # ── Ollama (for GPU embedding on your 4060 Ti PC) ────────────────────
    ollama_base_url: str = "http://localhost:11434"  # on 4060 Ti PC when local
    ollama_embed_model: str = "nomic-embed-text"  # 768-dim, fast on GPU
    # ↑ Options: nomic-embed-text (768d) | mxbai-embed-large (1024d) | bge-m3 (1024d)

    # ── Qdrant Vector DB ──────────────────────────────────────────────────
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "legal_docs"

    # ── Redis (Upstash free tier for cache + memory) ──────────────────────
    upstash_redis_url: str = ""
    upstash_redis_token: str = ""
    redis_url: str = "redis://localhost:6379"  # local fallback

    # ── Observability ─────────────────────────────────────────────────────
    langchain_api_key: str = ""
    langchain_project: str = "nyayabot-prod"
    langchain_tracing_v2: str = "true"

    # ── App Config ────────────────────────────────────────────────────────
    max_retries: int = 2
    critic_threshold: float = 0.7
    critic_min_failures: int = 2
    top_k_retrieval: int = 20
    top_k_rerank: int = 5
    token_budget: int = 3000
    cache_similarity_threshold: float = 0.92
    cache_version: int = 1  # bump to invalidate all cached answers after re-seeding
    memory_ttl_seconds: int = 1800
    memory_max_turns: int = 10

    # ── Models ────────────────────────────────────────────────────────────
    # Embedding dim depends on the ollama model chosen:
    #   nomic-embed-text → 768
    #   mxbai-embed-large → 1024
    #   bge-m3 → 1024
    embedding_dim: int = 768
    # Reranker model options (in order of quality/size):
    #   BAAI/bge-reranker-v2-m3          — best: multilingual, handles Hindi, ~0.6GB VRAM  ← prod default
    #   cross-encoder/ms-marco-MiniLM-L-6-v2  — fast but English-only, ~200MB            ← test default
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    # Cross-encoder rerank inside the chat pipeline. Off by default: measured
    # 1.9-4.3s per query on MacBook Air MPS (top-20 candidates). Enable on a
    # CUDA host (~15ms on RTX 4060 Ti) via ENABLE_RERANKER=true.
    enable_reranker: bool = False
    disable_indictrans2: bool = False

    # ── App ───────────────────────────────────────────────────────────────
    environment: str = "development"
    log_level: str = "INFO"
    allowed_origins: str = "http://localhost:3000"
    # Must be set via env in production; startup fails otherwise. In dev a
    # random per-process secret is generated (tokens won't survive restarts).
    jwt_secret: str = ""
    # Comma-separated emails granted the "pro" tier at login/signup.
    admin_emails: str = ""
    # OAuth client ID the frontend signs in with. Google access tokens are only
    # accepted when they were issued to this client.
    google_client_id: str = ""
    jwt_ttl_days: int = 7
    # Shared secret for admin/ingest endpoints (X-Admin-Secret). Empty disables it.
    admin_secret: str = ""

    # ── Abuse limits ──────────────────────────────────────────────────────
    # Local proxies in front of uvicorn: 0 = none (local dev), 1 = Tailscale
    # Funnel (make run), 2 = Funnel + nginx (make scale). Used to find the
    # address that connected to this machine; see src/api/security.py.
    trusted_proxy_hops: int = 0
    # Headers carrying the visitor's IP from the hosting edge, first match wins:
    # Vercel sets x-vercel-forwarded-for; the Cloudflare Pages worker sets
    # x-client-ip. Empty = use the connecting address only.
    client_ip_header: str = "x-vercel-forwarded-for,x-client-ip"
    # Server-side ceilings for requests without an account. The browser shows
    # a 5-answer guest allowance; these catch anyone scripting around it.
    guest_daily_limit: int = 20
    guest_global_rpm: int = 30
    # Requests per minute from one connecting address (the Vercel edge node, or
    # a caller hitting the Funnel directly). Forged X-Forwarded-For can't dodge it.
    edge_rpm: int = 240
    # Expose /docs and /openapi.json. Off unless explicitly enabled.
    enable_api_docs: bool = False

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]

    @property
    def use_upstash(self) -> bool:
        return bool(self.upstash_redis_url and self.upstash_redis_token)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


# Trigger config reload
settings = get_settings()
