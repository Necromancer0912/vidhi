"""
NyayaBot — Redis utility hub (Upstash-compatible).

Provides:
  1. SemanticCache       — cosine-sim query cache (sub-50ms hits)
  2. ConversationMemory  — per-session chat history (TTL 30min)
  3. RateLimiter         — token bucket per user/IP
  4. UserProfile         — persistent user preferences
  5. Analytics           — query frequency, hot topics
  6. JobQueue            — background scraping/reindex tasks
"""
from __future__ import annotations

import json
import logging
import time
import hashlib
from typing import Optional, Any

import numpy as np

from src.config import settings

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Redis connection factory
# ─────────────────────────────────────────────────────────────────────────────

def get_redis_client():
    """
    Returns a Redis client.
    Tries Upstash first (cloud), falls back to local Redis.
    """
    if settings.use_upstash:
        # Upstash: HTTP-based Redis, works from anywhere
        from upstash_redis import Redis
        return Redis(
            url=settings.upstash_redis_url,
            token=settings.upstash_redis_token,
        )
    else:
        # Local Redis fallback (for development without Upstash)
        import redis
        return redis.from_url(settings.redis_url, decode_responses=True)


# Singleton
_redis_client = None

def redis_client():
    global _redis_client
    if _redis_client is None:
        try:
            _redis_client = get_redis_client()
            logger.info("✅ Redis connected (Upstash)" if settings.use_upstash else "✅ Redis connected (local)")
        except Exception as e:
            logger.warning(f"⚠ Redis unavailable: {e} — features will degrade gracefully")
    return _redis_client


# ─────────────────────────────────────────────────────────────────────────────
# 1. Semantic Cache
# ─────────────────────────────────────────────────────────────────────────────

class SemanticCache:
    """
    Vector-similarity cache for legal queries.
    
    Stores: embedding + answer + citations in Redis hashes.
    On each query, finds most similar cached query via cosine similarity.
    Hit threshold: 0.95 (nearly identical query).

    Cache invalidation on RAG re-seed:
      Bump CACHE_VERSION in .env by 1. All old keys use a different prefix
      and are never matched again. They expire naturally via 7-day TTL.
    
    Redis usage: ~6KB per cached query → 256MB = 42,000 cached queries
    """

    @property
    def PREFIX(self) -> str:
        return f"nyaya:cache:v{settings.cache_version}:"

    @property
    def INDEX_KEY(self) -> str:
        return f"nyaya:cache:v{settings.cache_version}:index"

    def __init__(self, threshold: float = None):
        self.threshold = threshold or settings.cache_similarity_threshold
        self.r = redis_client()

    def _embed(self, text: str) -> list[float]:
        from src.ingestion.embedder import get_embedding_model
        return get_embedding_model().embed(text)

    def _cosine_sim(self, a: list[float], b: list[float]) -> float:
        va, vb = np.array(a), np.array(b)
        denom = np.linalg.norm(va) * np.linalg.norm(vb)
        return float(np.dot(va, vb) / denom) if denom > 0 else 0.0

    def get(self, query: str) -> Optional[dict]:
        """Check cache. Returns response dict or None."""
        if not self.r:
            return None
        try:
            query_embed = self._embed(query)
            # Scan all cache entries (in production: use Redis SCAN)
            keys = self.r.smembers(self.INDEX_KEY) if hasattr(self.r, 'smembers') else []
            
            best_sim, best_key = 0.0, None
            for key in keys:
                raw = self.r.hget(key, "embedding")
                if not raw:
                    continue
                cached_embed = json.loads(raw)
                sim = self._cosine_sim(query_embed, cached_embed)
                if sim > best_sim:
                    best_sim, best_key = sim, key

            if best_sim >= self.threshold and best_key:
                entry = self.r.hgetall(best_key)
                logger.info(f"✅ Cache HIT (sim={best_sim:.3f})")
                # Bump hit count for analytics
                self.r.hincrby(best_key, "hits", 1)

                def safe_float(val, default):
                    if val is None or val == "" or val == "None":
                        return default
                    try:
                        return float(val)
                    except ValueError:
                        return default

                return {
                    "answer": entry.get("answer", ""),
                    "citations": json.loads(entry.get("citations", "[]")),
                    "confidence_score": safe_float(entry.get("confidence"), 0.8),
                    "legal_standing_score": safe_float(entry.get("legal_standing_score"), 0.0),
                    "route": entry.get("route", "RETRIEVE"),
                    "cache_hit": True,
                    "cache_similarity": best_sim,
                }
        except Exception as e:
            logger.warning(f"Cache get error: {e}")
        return None

    def set(self, query: str, response: dict) -> None:
        """Store query+response in cache with 7-day TTL."""
        if not self.r:
            return
        try:
            embed = self._embed(query)
            key = f"{self.PREFIX}{hashlib.sha256(query.encode()).hexdigest()[:16]}"
            ttl = 7 * 24 * 3600  # 7 days

            data = {
                "query": query,
                "embedding": json.dumps(embed),
                "answer": response.get("answer", ""),
                "citations": json.dumps(response.get("citations", [])),
                "confidence": str(response.get("confidence_score") if response.get("confidence_score") is not None else 0.0),
                "legal_standing_score": str(response.get("legal_standing_score") if response.get("legal_standing_score") is not None else 0.0),
                "route": response.get("route", "RETRIEVE"),
                "created_at": str(time.time()),
                "hits": "0",
            }
            if settings.use_upstash:
                self.r.hset(key, values=data)
            else:
                self.r.hset(key, mapping=data)
            self.r.expire(key, ttl)
            self.r.sadd(self.INDEX_KEY, key)
        except Exception as e:
            logger.warning(f"Cache set error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Conversation Memory
# ─────────────────────────────────────────────────────────────────────────────

class ConversationMemory:
    """
    Per-session conversation history in Redis.

    Key: nyaya:memory:<session_id>  → Redis list of JSON turns
    TTL: 30 minutes (auto-extended on each interaction)
    Max: 10 turns (sliding window)

    Redis usage: ~2KB per session → 256MB = 128,000 concurrent sessions
    """

    PREFIX = "nyaya:memory:"

    def __init__(self):
        self.r = redis_client()
        self.ttl = settings.memory_ttl_seconds
        self.max_turns = settings.memory_max_turns

    def get_history(self, session_id: str) -> list[dict]:
        if not self.r:
            return []
        try:
            key = f"{self.PREFIX}{session_id}"
            raw_turns = self.r.lrange(key, 0, -1) if hasattr(self.r, 'lrange') else []
            self.r.expire(key, self.ttl)  # Refresh TTL on access
            return [json.loads(t) for t in raw_turns]
        except Exception as e:
            logger.warning(f"Memory get error: {e}")
            return []

    def add_turn(self, session_id: str, role: str, content: str) -> None:
        if not self.r:
            return
        try:
            key = f"{self.PREFIX}{session_id}"
            turn = json.dumps({"role": role, "content": content, "ts": time.time()})
            self.r.rpush(key, turn)
            # Trim to max_turns × 2 (user + assistant)
            self.r.ltrim(key, -(self.max_turns * 2), -1)
            self.r.expire(key, self.ttl)
        except Exception as e:
            logger.warning(f"Memory add error: {e}")

    def clear(self, session_id: str) -> None:
        if self.r:
            self.r.delete(f"{self.PREFIX}{session_id}")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Rate Limiter (Token Bucket)
# ─────────────────────────────────────────────────────────────────────────────

class RateLimiter:
    """
    Token bucket rate limiter per user/IP.

    Prevents abuse — limits to N requests per minute per user.
    Free tier: 20 req/min. Authenticated users: 60 req/min.

    Redis usage: ~100 bytes per user → negligible
    """

    PREFIX = "nyaya:ratelimit:"

    def __init__(self, requests_per_minute: int = 20):
        self.r = redis_client()
        self.rpm = requests_per_minute
        self.window = 60  # seconds

    def is_allowed(
        self, identifier: str, rpm: Optional[int] = None, window: Optional[int] = None
    ) -> tuple[bool, int]:
        """
        Check if request is allowed.
        `rpm` is the number of requests allowed per `window` seconds (default 60).
        Returns (allowed: bool, remaining: int)
        """
        limit = rpm if rpm is not None else self.rpm
        window = window or self.window
        if not self.r:
            return True, limit  # Fail open if Redis down

        try:
            key = f"{self.PREFIX}{identifier}:{window}:{int(time.time() // window)}"
            count = self.r.incr(key)
            if count == 1:
                self.r.expire(key, window)
            remaining = max(0, limit - int(count))
            return int(count) <= limit, remaining
        except Exception:
            return True, limit  # Fail open


# ─────────────────────────────────────────────────────────────────────────────
# 4. User Profile
# ─────────────────────────────────────────────────────────────────────────────

class UserProfileStore:
    """
    Persistent user preferences stored in Redis.

    Stores: language, preferred legal domain, query history summary,
            feedback patterns, notification prefs.

    Redis usage: ~500 bytes per user → 256MB = 500,000 user profiles
    """

    PREFIX = "nyaya:profile:"

    def __init__(self):
        self.r = redis_client()

    def get(self, user_id: str) -> dict:
        if not self.r:
            return {}
        try:
            raw = self.r.hgetall(f"{self.PREFIX}{user_id}")
            return raw or {}
        except Exception:
            return {}

    def update(self, user_id: str, **fields) -> None:
        if not self.r:
            return
        try:
            key = f"{self.PREFIX}{user_id}"
            data = {k: str(v) for k, v in fields.items()}
            if settings.use_upstash:
                self.r.hset(key, values=data)
            else:
                self.r.hset(key, mapping=data)
            self.r.expire(key, 90 * 24 * 3600)  # 90-day TTL
        except Exception as e:
            logger.warning(f"Profile update error: {e}")

    def increment_query_count(self, user_id: str) -> int:
        if not self.r:
            return 0
        try:
            return int(self.r.hincrby(f"{self.PREFIX}{user_id}", "query_count", 1))
        except Exception:
            return 0


# ─────────────────────────────────────────────────────────────────────────────
# 5. Analytics
# ─────────────────────────────────────────────────────────────────────────────

class Analytics:
    """
    Real-time query analytics via Redis sorted sets.

    Tracks:
    - Top legal topics (sorted set, score = query count)
    - Daily active queries (hyperloglog for unique count)
    - Route distribution (hash: RETRIEVE/MEMORY/TOOL/CHITCHAT counts)
    - Retry rate (for critic performance monitoring)

    Redis usage: <1MB total for analytics
    """

    def __init__(self):
        self.r = redis_client()

    def track_query(self, route: str, topic: str, retry_count: int = 0) -> None:
        if not self.r:
            return
        try:
            today = time.strftime("%Y-%m-%d")
            # Question text is deliberately not stored: people put names,
            # addresses and case details in legal questions. Aggregates only.
            routes_key = f"nyaya:analytics:routes:{today}"
            self.r.hincrby(routes_key, route, 1)
            self.r.expire(routes_key, 90 * 24 * 3600)
            if retry_count > 0:
                self.r.hincrby("nyaya:analytics:retries", str(retry_count), 1)
        except Exception as e:
            logger.debug(f"Analytics track error: {e}")

    def track_feedback(self, is_positive: bool) -> None:
        if not self.r:
            return
        try:
            field = "positive" if is_positive else "negative"
            self.r.hincrby("nyaya:analytics:feedback", field, 1)
        except Exception:
            pass

    def get_dashboard(self) -> dict:
        """Return analytics summary for admin dashboard."""
        if not self.r:
            return {}
        try:
            today = time.strftime("%Y-%m-%d")
            routes = self.r.hgetall(f"nyaya:analytics:routes:{today}") or {}
            feedback = self.r.hgetall("nyaya:analytics:feedback") or {}
            retries = self.r.hgetall("nyaya:analytics:retries") or {}
            return {
                "today_routes": routes,
                "feedback": feedback,
                "retry_distribution": retries,
            }
        except Exception:
            return {}


# ─────────────────────────────────────────────────────────────────────────────
# Singletons
# ─────────────────────────────────────────────────────────────────────────────

_semantic_cache: Optional[SemanticCache] = None
_conversation_memory: Optional[ConversationMemory] = None
_rate_limiter: Optional[RateLimiter] = None
_user_profiles: Optional[UserProfileStore] = None
_analytics: Optional[Analytics] = None


def get_semantic_cache() -> SemanticCache:
    global _semantic_cache
    if _semantic_cache is None:
        _semantic_cache = SemanticCache()
    return _semantic_cache


def get_conversation_memory() -> ConversationMemory:
    global _conversation_memory
    if _conversation_memory is None:
        _conversation_memory = ConversationMemory()
    return _conversation_memory


def get_rate_limiter(rpm: int = 20) -> RateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter(rpm)
    return _rate_limiter


def get_user_profiles() -> UserProfileStore:
    global _user_profiles
    if _user_profiles is None:
        _user_profiles = UserProfileStore()
    return _user_profiles


def get_analytics() -> Analytics:
    global _analytics
    if _analytics is None:
        _analytics = Analytics()
    return _analytics
