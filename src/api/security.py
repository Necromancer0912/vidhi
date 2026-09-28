"""
NyayaBot — Request-level security shared by the API routes.

Client identity behind proxies, JWT-backed user dependencies, the admin gate,
rate limiting, and response hardening headers.
"""

from __future__ import annotations

import hmac
import ipaddress
import logging
import os
import secrets
from typing import Optional

from fastapi import Header, HTTPException, Request
import jwt

from src.config import settings

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Client identity
# ─────────────────────────────────────────────


def _valid_ip(value: str) -> Optional[str]:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def edge_peer(request: Request) -> str:
    """The address that actually connected to this machine. Can't be forged.

    The Tailscale Funnel *replaces* X-Forwarded-For with the address that
    connected to it (anything the caller sent is dropped), and nginx then
    appends its own peer. So with TRUSTED_PROXY_HOPS local proxies in front of
    uvicorn (Funnel = 1, Funnel + nginx = 2), the Funnel's entry sits that many
    places from the right. With 0 (local dev) it's the socket peer.
    """
    peer = request.client.host if request.client else "unknown"
    hops = settings.trusted_proxy_hops
    if hops <= 0:
        return peer
    chain = [p for p in (x.strip() for x in request.headers.get("x-forwarded-for", "").split(",")) if p]
    if len(chain) < hops:
        return peer
    return _valid_ip(chain[-hops]) or peer


def client_ip(request: Request) -> str:
    """The visitor's IP, used for per-visitor limits.

    Behind Vercel or the Cloudflare worker, the connecting address is a shared
    edge server; the visitor's own IP arrives in one of CLIENT_IP_HEADER.
    A caller who skips Vercel can set that header to anything, which is why
    edge_peer() carries its own, unforgeable ceiling as well.
    """
    for header in filter(None, (h.strip() for h in settings.client_ip_header.split(","))):
        first = request.headers.get(header, "").split(",")[0]
        ip = _valid_ip(first) if first else None
        if ip:
            return ip
    return edge_peer(request)


# ─────────────────────────────────────────────
# Users
# ─────────────────────────────────────────────


def signing_key() -> str:
    """The JWT secret. Production must set JWT_SECRET (startup refuses to run
    without it); anywhere else a random per-process key is created on first
    use, so tests and fresh checkouts work without a .env."""
    if not settings.jwt_secret:
        if settings.is_production:
            raise RuntimeError("JWT_SECRET is not set")
        settings.jwt_secret = secrets.token_urlsafe(48)
        logger.warning("JWT_SECRET not set: using a random per-process key; sign-ins won't survive restarts.")
    return settings.jwt_secret


def decode_token(token: str) -> Optional[dict]:
    try:
        claims = jwt.decode(
            token,
            signing_key(),
            algorithms=["HS256"],
            options={"require": ["exp", "sub"]},
        )
    except Exception:
        return None
    return claims if claims.get("sub") else None


def _bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1]


def optional_user(authorization: Optional[str] = Header(None)) -> Optional[dict]:
    """Claims for a signed-in caller, None for a guest.

    A token that is present but invalid is an error rather than a silent
    downgrade to guest, so the client learns its session has expired.
    """
    if not authorization:
        return None
    token = _bearer(authorization)
    claims = decode_token(token) if token else None
    if not claims:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return claims


def require_user(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    return optional_user(authorization)


def secrets_match(provided: Optional[str], expected: Optional[str]) -> bool:
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided.encode(), expected.encode())


def admin_secret() -> str:
    return settings.admin_secret or os.environ.get("ADMIN_SECRET", "")


def require_admin(
    x_admin_secret: Optional[str] = Header(None, alias="X-Admin-Secret"),
    authorization: Optional[str] = Header(None),
) -> bool:
    """ADMIN_SECRET header, or a JWT for an account on the ADMIN_EMAILS list.

    Admin rights are checked against the current ADMIN_EMAILS, not the tier
    recorded in the token, so removing someone takes effect immediately.
    """
    if secrets_match(x_admin_secret, admin_secret()):
        return True

    token = _bearer(authorization)
    if token:
        claims = decode_token(token)
        if claims and claims["sub"].lower() in settings.admin_email_set:
            return True
        if claims:
            raise HTTPException(
                status_code=403,
                detail="Forbidden: this endpoint requires a pro-tier account.",
            )

    raise HTTPException(
        status_code=401,
        detail="Unauthorized: requires a valid X-Admin-Secret or a pro-tier JWT.",
    )


# ─────────────────────────────────────────────
# Rate limiting
# ─────────────────────────────────────────────


def enforce_limit(
    bucket: str,
    identifier: str,
    limit: int,
    window: int = 60,
    message: str = "Rate limit exceeded. Please wait a minute and try again.",
) -> None:
    # Looked up at call time so tests can patch the limiter.
    from src.cache import redis_store

    limiter = redis_store.get_rate_limiter()
    kwargs = {"rpm": limit} if window == 60 else {"rpm": limit, "window": window}
    allowed, _ = limiter.is_allowed(f"{bucket}:{identifier}" if bucket else identifier, **kwargs)
    if not allowed:
        raise HTTPException(status_code=429, detail=message)


def enforce_edge_limit(request: Request) -> None:
    """Ceiling per connecting address, shared by everyone behind it."""
    enforce_limit("edge", edge_peer(request), settings.edge_rpm)


def limit_by_ip(bucket: str, limit: int, window: int = 60):
    """Dependency factory: `limit` requests per `window` seconds per client IP."""

    def dependency(request: Request) -> None:
        enforce_limit(bucket, client_ip(request), limit, window)
        enforce_edge_limit(request)

    return dependency


# ─────────────────────────────────────────────
# Response hardening
# ─────────────────────────────────────────────

_SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"x-frame-options", b"DENY"),
    (b"permissions-policy", b"camera=(), microphone=(self), geolocation=(), payment=()"),
    (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
]

_NO_STORE_PREFIXES = ("/api/v1/auth", "/api/v1/chat/history")


class SecurityHeadersMiddleware:
    """Pure ASGI so streamed (SSE) responses pass through untouched."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        no_store = scope.get("path", "").startswith(_NO_STORE_PREFIXES)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                for key, value in _SECURITY_HEADERS:
                    if key not in present:
                        headers.append((key, value))
                if no_store:
                    headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
