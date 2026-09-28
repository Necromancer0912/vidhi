"""
NyayaBot — Prometheus metrics setup.
Tracks: request latency, critic retries, cache hits, routing decisions, confidence scores.
"""

from __future__ import annotations

import time

from prometheus_client import Counter, Gauge, Histogram, make_asgi_app

# Custom metrics
CRITIC_RETRIES = Counter(
    "nyayabot_critic_retries_total",
    "Total number of critic-triggered query retries",
    ["route"],
)

CACHE_HITS = Counter(
    "nyayabot_cache_hits_total",
    "Total semantic cache hits",
)

CACHE_MISSES = Counter(
    "nyayabot_cache_misses_total",
    "Total semantic cache misses",
)

ROUTING_DECISIONS = Counter(
    "nyayabot_routing_decisions_total",
    "Query routing decisions by type",
    ["route"],
)

CONFIDENCE_HISTOGRAM = Histogram(
    "nyayabot_confidence_score",
    "Distribution of answer confidence scores",
    buckets=[0.3, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0],
)

RETRIEVAL_LATENCY = Histogram(
    "nyayabot_retrieval_latency_seconds",
    "Retrieval pipeline latency (dense + BM25 + rerank)",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
)

GENERATION_LATENCY = Histogram(
    "nyayabot_generation_latency_seconds",
    "LLM generation latency",
    buckets=[0.5, 1.0, 2.0, 3.0, 5.0, 10.0],
)

ACTIVE_SESSIONS = Gauge(
    "nyayabot_active_sessions",
    "Number of active conversation sessions",
)


REQUEST_COUNT = Counter(
    "nyayabot_http_requests_total",
    "HTTP requests by method, route template and status code",
    ["method", "route", "status"],
)

REQUEST_LATENCY = Histogram(
    "nyayabot_http_request_duration_seconds",
    "HTTP request duration by route template (streams: until the last byte)",
    ["method", "route"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120],
)


class RequestMetricsMiddleware:
    """Pure ASGI, so SSE streams pass through untouched. Labels use the route
    template ("/api/v1/chat"), never the raw path, to keep cardinality fixed."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path", "").startswith("/prometheus"):
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status = {"code": 500}

        async def record_status(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, record_status)
        finally:
            route = getattr(scope.get("route"), "path", None) or "unmatched"
            REQUEST_COUNT.labels(scope["method"], route, str(status["code"])).inc()
            REQUEST_LATENCY.labels(scope["method"], route).observe(time.perf_counter() - start)


def setup_prometheus(app):
    """Record request metrics and mount /prometheus for local scrapers."""
    app.add_middleware(RequestMetricsMiddleware)
    metrics_app = make_asgi_app()
    app.mount("/prometheus", _local_only(metrics_app))


def _local_only(inner):
    """Serve metrics to a scraper on this machine only.

    Anything that came through nginx, the Funnel or Vercel carries an
    X-Forwarded-For header, so the loopback peer alone isn't enough.
    """

    async def guarded(scope, receive, send):
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        peer = (scope.get("client") or ("", 0))[0]
        if peer not in ("127.0.0.1", "::1") or b"x-forwarded-for" in headers:
            await send({"type": "http.response.start", "status": 404,
                        "headers": [(b"content-type", b"text/plain")]})
            await send({"type": "http.response.body", "body": b"Not Found"})
            return
        await inner(scope, receive, send)

    return guarded
