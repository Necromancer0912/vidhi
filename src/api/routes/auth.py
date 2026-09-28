"""
NyayaBot — Backend Authentication and Authorization endpoints.
Provides signup, login, and Google sign-in using PBKDF2 password hashes and JWTs.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from src.api.security import client_ip, enforce_edge_limit, enforce_limit, require_user, signing_key
from src.cache.redis_store import redis_client
from src.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

# ─────────────────────────────────────────────
# Password hashing
# ─────────────────────────────────────────────
# Current format: pbkdf2_sha256$<iterations>$<salt hex>$<hash hex>
# Legacy format:  <salt hex>:<hash hex> at 100k iterations, upgraded on next login.

PBKDF2_ITERATIONS = 600_000
_LEGACY_ITERATIONS = 100_000


def _pbkdf2(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = _pbkdf2(password, salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        if hashed_password.startswith("pbkdf2_sha256$"):
            _, iterations, salt_hex, hash_hex = hashed_password.split("$")
            iterations = int(iterations)
        else:
            salt_hex, hash_hex = hashed_password.split(":")
            iterations = _LEGACY_ITERATIONS
        actual = _pbkdf2(plain_password, bytes.fromhex(salt_hex), iterations)
        return hmac.compare_digest(actual, bytes.fromhex(hash_hex))
    except Exception:
        return False


def needs_rehash(hashed_password: str) -> bool:
    return not hashed_password.startswith(f"pbkdf2_sha256${PBKDF2_ITERATIONS}$")


# ─────────────────────────────────────────────
# Request / response models
# ─────────────────────────────────────────────

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")


def _clean_email(v: Any) -> Any:
    if isinstance(v, str):
        v = v.strip()
        if len(v) > 254 or not _EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address")
    return v


class SignupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: str
    password: str = Field(min_length=8, max_length=128)

    @field_validator("name", mode="before")
    @classmethod
    def clean_name(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = " ".join(v.split())
            if any(c in v for c in "<>"):
                raise ValueError("Name contains characters that aren't allowed")
        return v

    @field_validator("email", mode="before")
    @classmethod
    def clean_email(cls, v: Any) -> Any:
        return _clean_email(v)


class LoginRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def strip_email(cls, v: Any) -> Any:
        return v.strip() if isinstance(v, str) else v


class GoogleLoginRequest(BaseModel):
    access_token: str = Field(min_length=10, max_length=4096)


class AuthResponse(BaseModel):
    success: bool
    token: str
    user: Dict[str, Any]
    error: Optional[str] = None


def _fail(error: str) -> AuthResponse:
    return AuthResponse(success=False, token="", user={}, error=error)


def _ok(user_data: dict) -> AuthResponse:
    return AuthResponse(
        success=True,
        token=create_token(user_data),
        user={"email": user_data["email"], "name": user_data["name"], "tier": user_data["tier"]},
    )


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────


def resolve_tier(email: str) -> str:
    """Server-side tier assignment from the ADMIN_EMAILS allowlist."""
    return "pro" if email.lower() in settings.admin_email_set else "free"


def get_user_from_store(r, email: str) -> Optional[dict]:
    raw = r.get(f"nyaya:users:{email.lower()}")
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            return None
    return None


def create_token(user_data: dict) -> str:
    now = datetime.now(timezone.utc)
    to_encode = {
        "sub": user_data["email"],
        "name": user_data["name"],
        "tier": user_data["tier"],
        "iat": now,
        "exp": now + timedelta(days=settings.jwt_ttl_days),
    }
    return jwt.encode(to_encode, signing_key(), algorithm="HS256")


def _require_redis():
    r = redis_client()
    if not r:
        raise HTTPException(status_code=503, detail="Sign-in is temporarily unavailable")
    return r


def auth_ip_limit(request: Request) -> None:
    """Shared throttle for every auth endpoint: 10 attempts per minute per IP."""
    enforce_limit(
        "auth",
        client_ip(request),
        limit=10,
        message="Too many sign-in attempts. Wait a minute and try again.",
    )
    enforce_edge_limit(request)


# Failed password attempts per account before a 15-minute lockout.
_MAX_FAILURES = 8
_LOCKOUT_SECONDS = 15 * 60


def _failure_key(email: str) -> str:
    return f"nyaya:auth:failures:{email}"


def _locked_out(r, email: str) -> bool:
    try:
        return int(r.get(_failure_key(email)) or 0) >= _MAX_FAILURES
    except Exception:
        return False


def _record_failure(r, email: str) -> None:
    try:
        key = _failure_key(email)
        if r.incr(key) == 1:
            r.expire(key, _LOCKOUT_SECONDS)
    except Exception:
        pass


# ─────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────


@router.post("/auth/signup", response_model=AuthResponse, dependencies=[Depends(auth_ip_limit)])
def signup(request: SignupRequest):
    """Register a new user, hash password, and return a JWT."""
    r = _require_redis()
    email_lower = request.email.lower()

    if get_user_from_store(r, email_lower):
        return _fail("An account with this email already exists. Sign in instead.")

    user_data = {
        "name": request.name,
        "email": request.email,
        "password_hash": hash_password(request.password),
        "tier": resolve_tier(email_lower),
    }
    r.set(f"nyaya:users:{email_lower}", json.dumps(user_data))
    return _ok(user_data)


@router.post("/auth/login", response_model=AuthResponse, dependencies=[Depends(auth_ip_limit)])
def login(request: LoginRequest):
    """Authenticate email and password, returning user profile and JWT."""
    r = _require_redis()
    email_lower = request.email.lower()

    if _locked_out(r, email_lower):
        raise HTTPException(
            status_code=429,
            detail="Too many failed attempts for this account. Try again in 15 minutes.",
        )

    user_data = get_user_from_store(r, email_lower)
    stored_hash = (user_data or {}).get("password_hash") or ""
    if not user_data or not stored_hash or not verify_password(request.password, stored_hash):
        _record_failure(r, email_lower)
        return _fail("Invalid email or password")

    r.delete(_failure_key(email_lower))
    if needs_rehash(stored_hash):
        user_data["password_hash"] = hash_password(request.password)
        r.set(f"nyaya:users:{email_lower}", json.dumps(user_data))

    return _ok(user_data)


async def _verified_google_profile(access_token: str) -> dict:
    """Fetch the profile behind a Google access token, and only accept tokens
    that Google issued to *our* OAuth client for a verified address.

    Without the audience check, an access token a user granted to any other
    app could be replayed here to sign in as them.
    """
    if not settings.google_client_id:
        raise HTTPException(status_code=503, detail="Google sign-in isn't configured on this server")

    async with httpx.AsyncClient(timeout=5.0) as client:
        info = await client.get(
            "https://oauth2.googleapis.com/tokeninfo", params={"access_token": access_token}
        )
        if info.status_code != 200:
            raise ValueError("token rejected by Google")
        claims = info.json()
        audience = claims.get("aud") or claims.get("azp")
        if audience != settings.google_client_id:
            raise ValueError("token issued to a different client")
        if str(claims.get("email_verified")).lower() != "true" or not claims.get("email"):
            raise ValueError("email not verified")

        profile = await client.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        name = profile.json().get("name") if profile.status_code == 200 else None

    return {"email": claims["email"], "name": (name or "").strip()[:80]}


@router.post("/auth/google", response_model=AuthResponse, dependencies=[Depends(auth_ip_limit)])
async def google_login(request: GoogleLoginRequest):
    """Verify a Google access token, sync the user in Redis, and return a JWT."""
    r = _require_redis()

    try:
        profile = await _verified_google_profile(request.access_token)
    except HTTPException:
        raise
    except httpx.HTTPError as e:
        logger.error(f"Google verification unreachable: {e}")
        return _fail("Couldn't reach Google to confirm your sign-in. Try again.")
    except Exception as e:
        logger.warning(f"Google token rejected: {e}")
        return _fail("Google sign-in couldn't be verified. Try again.")

    email_lower = profile["email"].lower()
    name = profile["name"] or profile["email"].split("@")[0]
    user_data = get_user_from_store(r, email_lower)

    if user_data:
        if user_data.get("name") != name:
            user_data["name"] = name
            r.set(f"nyaya:users:{email_lower}", json.dumps(user_data))
    else:
        user_data = {
            "name": name,
            "email": profile["email"],
            "password_hash": "",  # Google accounts do not use a password
            "tier": resolve_tier(email_lower),
        }
        r.set(f"nyaya:users:{email_lower}", json.dumps(user_data))

    return _ok(user_data)


@router.delete("/auth/account")
def delete_account(user: dict = Depends(require_user)):
    """Erase the account and everything stored against it."""
    r = _require_redis()
    email = user["sub"].lower()
    r.delete(f"nyaya:users:{email}", f"nyaya:history:{email}", _failure_key(email))
    logger.info("Account deleted")
    return {"success": True}
