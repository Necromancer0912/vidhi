"""
NyayaBot — Unit tests for Complete Security Overhaul (SEC-2, SEC-3, and SEC-4).
"""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.config import settings

client = TestClient(app)


# ─────────────────────────────────────────────────────────────────────────────
# SEC-2: Backend Authentication Endpoint Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_auth_signup_success():
    """Verify signup endpoint registers a user and returns a token."""
    mock_redis = MagicMock()
    # Mock get returns None (user doesn't exist yet)
    mock_redis.get.return_value = None

    with patch("src.api.routes.auth.redis_client", return_value=mock_redis):
        response = client.post(
            "/api/v1/auth/signup",
            json={"name": "Sayan Roy", "email": "testsignup@example.com", "password": "mypassword"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "token" in data
        assert data["user"]["email"] == "testsignup@example.com"
        assert data["user"]["tier"] == "free"

        # Verify user details were saved to Redis
        assert mock_redis.set.called
        call_key, call_val = mock_redis.set.call_args[0]
        assert call_key == "nyaya:users:testsignup@example.com"

        saved_data = json.loads(call_val)
        assert saved_data["name"] == "Sayan Roy"
        assert "password_hash" in saved_data


def test_auth_login_unknown_user_rejected():
    """No demo-user auto-seeding: unknown emails must fail login."""
    mock_redis = MagicMock()
    mock_redis.get.return_value = None

    with patch("src.api.routes.auth.redis_client", return_value=mock_redis):
        response = client.post(
            "/api/v1/auth/login", json={"email": "someone@example.com", "password": "password"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["error"] == "Invalid email or password"


def test_auth_login_invalid_credentials():
    """Verify login fails with wrong password."""
    mock_redis = MagicMock()
    # Set up user in Redis
    from src.api.routes.auth import hash_password

    user_data = {
        "name": "Jane Doe",
        "email": "jane@example.com",
        "password_hash": hash_password("securepassword"),
        "tier": "free",
    }
    mock_redis.get.return_value = json.dumps(user_data)

    with patch("src.api.routes.auth.redis_client", return_value=mock_redis):
        response = client.post(
            "/api/v1/auth/login", json={"email": "jane@example.com", "password": "wrongpassword"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["token"] == ""
        assert "Invalid email or password" in data["error"]


# ─────────────────────────────────────────────────────────────────────────────
# SEC-4: Protected Chat History Routes Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_chat_history_unauthorized():
    """Verify endpoint returns 401 when Authorization header is missing."""
    response = client.get("/api/v1/chat/history")
    assert response.status_code == 401
    assert "Missing Authorization header" in response.json()["detail"]


def test_chat_history_invalid_token():
    """Verify endpoint returns 401 when token is malformed."""
    response = client.get("/api/v1/chat/history", headers={"Authorization": "Bearer badtoken"})
    assert response.status_code == 401
    assert "Invalid or expired token" in response.json()["detail"]


def test_chat_history_authorized_success():
    """Verify authorized request successfully accesses the correct user's history."""
    from src.api.routes.auth import create_token

    token = create_token({"email": "authorized@example.com", "name": "Auth User", "tier": "free"})

    mock_redis = MagicMock()
    history_data = {
        "sessions": [{"id": 1, "question": "test", "messages": []}],
        "active_chat": None,
    }
    mock_redis.get.return_value = json.dumps(history_data)

    with patch("src.api.routes.chat.redis_client", return_value=mock_redis):
        response = client.get("/api/v1/chat/history", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.json()["sessions"][0]["id"] == 1

        # Verify correct user-specific Redis key was queried
        mock_redis.get.assert_called_with("nyaya:history:authorized@example.com")


# ─────────────────────────────────────────────────────────────────────────────
# SEC-3: Ingestion Unset Admin Secret Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_ingest_unset_admin_secret_fails_503():
    """Verify ingestion refuses requests when ADMIN_SECRET is unset in the environment."""
    with patch.dict(os.environ, {}, clear=True):
        # Make sure clear removes it from env
        if "ADMIN_SECRET" in os.environ:
            del os.environ["ADMIN_SECRET"]

        response = client.post(
            "/api/v1/ingest/text",
            json={
                "project": "Test Project",
                "text": "Indian Legal Code text...",
                "secret": "admin",
            },
        )
        assert response.status_code == 503
        assert "Ingestion is disabled" in response.json()["detail"]


def test_ingest_correct_secret_passes():
    """Verify ingestion accepts request when secret matches configured ADMIN_SECRET."""
    with patch.dict(os.environ, {"ADMIN_SECRET": "my_secure_admin_key"}):
        with patch("src.api.routes.admin.app_state") as mock_app_state:
            # Mock qdrant client is None (fails after verification, but passes secret check)
            mock_app_state.qdrant_client = None

            response = client.post(
                "/api/v1/ingest/text",
                json={
                    "project": "Test Project",
                    "text": "Indian Legal Code text...",
                    "secret": "my_secure_admin_key",
                },
            )
            # Fails with 500 Qdrant connection not initialized, which means it passed the secret auth check!
            assert response.status_code == 500
            assert "Qdrant connection not initialized" in response.json()["detail"]


# ─────────────────────────────────────────────────────────────────────────────
# SEC-5: Protected Statistics Endpoint Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_stats_unauthorized():
    """Verify stats endpoint returns 401 without X-Admin-Secret or JWT token."""
    response = client.get("/api/v1/stats")
    assert response.status_code == 401
    assert "Unauthorized" in response.json()["detail"]


def test_stats_free_tier_jwt_forbidden():
    """SEC-5: Verify stats endpoint returns 403 for a valid but free-tier JWT."""
    from src.api.routes.auth import create_token

    token = create_token({"email": "regular@example.com", "name": "Regular User", "tier": "free"})
    response = client.get("/api/v1/stats", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
    assert "pro-tier" in response.json()["detail"]


def test_stats_authorized_jwt():
    """Verify stats endpoint succeeds when called with a valid pro-tier JWT token."""
    from src.api.routes.auth import create_token

    token = create_token({"email": "admin@example.com", "name": "Admin User", "tier": "pro"})

    mock_indexer = MagicMock()
    mock_indexer.get_stats.return_value = {"chunks": 42}

    mock_qdrant = MagicMock()
    mock_qdrant.scroll.return_value = ([], None)

    mock_analytics = MagicMock()
    mock_analytics.get_dashboard.return_value = {"today_routes": {"RETRIEVE": 5}}

    with (
        patch("src.api.routes.admin.app_state") as mock_app_state,
        patch("src.api.routes.admin.QdrantIndexer", return_value=mock_indexer),
        patch("src.cache.redis_store.get_analytics", return_value=mock_analytics),
        patch("src.api.security.settings.admin_emails", "admin@example.com"),
    ):
        mock_app_state.qdrant_client = mock_qdrant

        response = client.get("/api/v1/stats", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["vectorStore"]["totalChunks"] == 42
        assert data["queryLog"]["totalLogs"] == 5


def test_stats_authorized_secret():
    """Verify stats endpoint succeeds when called with correct X-Admin-Secret header."""
    mock_indexer = MagicMock()
    mock_indexer.get_stats.return_value = {"chunks": 99}

    mock_qdrant = MagicMock()
    mock_qdrant.scroll.return_value = ([], None)

    mock_analytics = MagicMock()
    mock_analytics.get_dashboard.return_value = {"today_routes": {"RETRIEVE": 12}}

    with (
        patch.dict(os.environ, {"ADMIN_SECRET": "my_secure_admin_key"}),
        patch("src.api.routes.admin.app_state") as mock_app_state,
        patch("src.api.routes.admin.QdrantIndexer", return_value=mock_indexer),
        patch("src.cache.redis_store.get_analytics", return_value=mock_analytics),
    ):
        mock_app_state.qdrant_client = mock_qdrant

        response = client.get("/api/v1/stats", headers={"X-Admin-Secret": "my_secure_admin_key"})
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["vectorStore"]["totalChunks"] == 99
        assert data["queryLog"]["totalLogs"] == 12


# ─────────────────────────────────────────────────────────────────────────────
# SEC-6, SEC-7, SEC-8: Redis TTL, CORS middleware and Rate Limiting Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_chat_history_ttl():
    """Verify saving chat history sets Redis key with a 90-day TTL (SEC-6)."""
    from src.api.routes.auth import create_token

    token = create_token({"email": "ttl@example.com", "name": "TTL User", "tier": "free"})

    mock_redis = MagicMock()

    with patch("src.api.routes.chat.redis_client", return_value=mock_redis):
        response = client.post(
            "/api/v1/chat/history",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "sessions": [{"id": 1, "question": "hello", "messages": []}],
                "active_chat": None,
            },
        )
        assert response.status_code == 200
        assert response.json() == {"success": True}

        # Verify set was called with ex parameter (90 days)
        mock_redis.set.assert_called_once()
        args, kwargs = mock_redis.set.call_args
        assert args[0] == "nyaya:history:ttl@example.com"
        assert kwargs.get("ex") == 90 * 24 * 3600


def test_cors_headers():
    """Verify CORS middleware restricts headers and methods (SEC-7)."""
    response = client.options(
        "/api/v1/chat",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    assert response.status_code == 200
    headers = response.headers
    # Verify allowed headers is NOT wildcard (*)
    assert headers.get("access-control-allow-headers") is not None
    assert "*" not in headers.get("access-control-allow-headers")
    assert "Authorization" in headers.get("access-control-allow-headers")
    assert "X-Admin-Secret" in headers.get("access-control-allow-headers")

    # Verify allowed methods is NOT wildcard (*)
    assert headers.get("access-control-allow-methods") is not None
    assert "*" not in headers.get("access-control-allow-methods")
    assert "POST" in headers.get("access-control-allow-methods")


def test_rate_limiter_blocks_abuse():
    """Verify that when the rate limiter returns false, 429 Too Many Requests is raised (SEC-8)."""
    mock_limiter = MagicMock()
    mock_limiter.is_allowed.return_value = (False, 0)

    with patch("src.cache.redis_store.get_rate_limiter", return_value=mock_limiter):
        response = client.post(
            "/api/v1/chat/sync",
            json={"message": "hello", "session_id": "test_session", "conversation_history": []},
        )
        assert response.status_code == 429
        assert "Rate limit exceeded" in response.json()["detail"]

        # Verify rate limiter was checked with default guest rpm=20
        mock_limiter.is_allowed.assert_called_once()
        args, kwargs = mock_limiter.is_allowed.call_args
        assert kwargs.get("rpm") == 20


def test_rate_limiter_auth_user():
    """Verify that when an authenticated user requests, the rate limiter uses a higher limit (SEC-8)."""
    from src.api.routes.auth import create_token

    token = create_token({"email": "rate@example.com", "name": "Rate User", "tier": "pro"})

    mock_limiter = MagicMock()
    mock_limiter.is_allowed.return_value = (True, 60)

    with (
        patch("src.cache.redis_store.get_rate_limiter", return_value=mock_limiter),
        patch("src.api.routes.chat.app_state") as mock_app_state,
    ):
        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(return_value={"answer": "ok"})
        mock_app_state.graph = mock_graph

        mock_memory = MagicMock()
        mock_app_state.memory_store = mock_memory

        response = client.post(
            "/api/v1/chat/sync",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "hello", "session_id": "test_session", "conversation_history": []},
        )
        assert response.status_code == 200

        # Verify is_allowed was called with rpm=60 and email as identifier
        mock_limiter.is_allowed.assert_called_once()
        args, kwargs = mock_limiter.is_allowed.call_args
        assert args[0] == "rate@example.com"
        assert kwargs.get("rpm") == 60


def test_chat_history_pruning():
    """Verify saving chat history prunes to top 50 sessions and latest 50 messages per session (BUG-5)."""
    from src.api.routes.auth import create_token

    token = create_token({"email": "prune@example.com", "name": "Prune User", "tier": "free"})

    mock_redis = MagicMock()

    # Generate 60 sessions, each with 60 messages
    sessions = []
    for i in range(60):
        messages = [
            {"role": "user" if j % 2 == 0 else "assistant", "text": f"msg {j}"} for j in range(60)
        ]
        sessions.append(
            {
                "id": 1000 + i,  # timestamp
                "question": f"Q {i}",
                "messages": messages,
            }
        )

    active_chat = {"id": 2000, "messages": [{"role": "user", "text": "active"} for _ in range(70)]}

    with patch("src.api.routes.chat.redis_client", return_value=mock_redis):
        response = client.post(
            "/api/v1/chat/history",
            headers={"Authorization": f"Bearer {token}"},
            json={"sessions": sessions, "active_chat": active_chat},
        )
        assert response.status_code == 200

        # Verify set was called
        mock_redis.set.assert_called_once()
        args, kwargs = mock_redis.set.call_args
        saved_data = json.loads(args[1])

        # Should be pruned to exactly 50 sessions
        assert len(saved_data["sessions"]) == 50

        # Each session's messages should be pruned to exactly 50 messages
        for s in saved_data["sessions"]:
            assert len(s["messages"]) == 50

        # Active chat's messages should be pruned to exactly 50 messages
        assert len(saved_data["active_chat"]["messages"]) == 50
