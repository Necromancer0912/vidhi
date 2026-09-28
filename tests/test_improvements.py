"""
NyayaBot — Unit tests for IMP improvements.
"""

from __future__ import annotations

import asyncio
import json
import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.routes.chat import get_current_user_email
from src.config import Settings
from src.models import ChatRequest, ConversationTurn

# ─────────────────────────────────────────────────────────────────────────────
# IMP-5: /health Redaction Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_health_check_development():
    """Verify that in development/non-production environments, the LLM model name is returned."""
    mock_settings = Settings(
        environment="development",
        llm_model="gemini-2.0-flash",
    )
    mock_qdrant = MagicMock()
    mock_qdrant.get_collections.return_value = []

    mock_app_state = MagicMock()
    mock_app_state.qdrant_client = mock_qdrant
    mock_app_state.graph = MagicMock()

    with (
        patch("src.api.routes.health.settings", mock_settings),
        patch("src.api.routes.health.app_state", mock_app_state),
        patch("src.cache.redis_store.redis_client") as mock_redis_func,
    ):
        mock_redis = MagicMock()
        mock_redis_func.return_value = mock_redis

        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["stack"]["llm"] == "gemini-2.0-flash"


def test_health_check_production():
    """Verify that in production, the LLM model name is redacted to 'configured'."""
    mock_settings = Settings(
        environment="production",
        llm_model="gemini-2.0-flash",
    )
    mock_qdrant = MagicMock()
    mock_qdrant.get_collections.return_value = []

    mock_app_state = MagicMock()
    mock_app_state.qdrant_client = mock_qdrant
    mock_app_state.graph = MagicMock()

    with (
        patch("src.api.routes.health.settings", mock_settings),
        patch("src.api.routes.health.app_state", mock_app_state),
        patch("src.cache.redis_store.redis_client") as mock_redis_func,
    ):
        mock_redis = MagicMock()
        mock_redis_func.return_value = mock_redis

        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["stack"]["llm"] == "configured"


# ─────────────────────────────────────────────────────────────────────────────
# IMP-6: ChatRequest max-length guard Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_chat_request_validation():
    """Verify that ChatRequest correctly limits conversation_history to 50 turns."""
    # Under 50 turns should succeed
    valid_history = [ConversationTurn(role="user", content="hello")] * 50
    req = ChatRequest(message="test", conversation_history=valid_history)
    assert len(req.conversation_history) == 50

    # Over 50 turns should raise Pydantic validation error
    invalid_history = [ConversationTurn(role="user", content="hello")] * 51
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as excinfo:
        ChatRequest(message="test", conversation_history=invalid_history)

    assert "List should have at most 50 items" in str(excinfo.value) or "max_length" in str(
        excinfo.value
    )


# ─────────────────────────────────────────────────────────────────────────────
# IMP-2 & IMP-3: Chat history save with TTL and pruning Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_save_chat_history_pruning_and_ttl():
    """Verify that save_user_history prunes sessions and messages, and sets Redis key with a 90-day TTL."""
    # Mock a JWT token
    mock_email = "testuser@example.com"

    # 60 sessions, each with 60 messages
    large_sessions = []
    for i in range(60):
        large_sessions.append(
            {
                "id": i + 1,  # ID represents timestamp
                "messages": [{"role": "user", "content": f"msg {j}"} for j in range(60)],
            }
        )

    request_payload = {
        "sessions": large_sessions,
        "active_chat": {
            "id": 999,
            "messages": [{"role": "user", "content": f"active msg {j}"} for j in range(70)],
        },
    }

    mock_redis = MagicMock()
    app.dependency_overrides[get_current_user_email] = lambda: mock_email

    try:
        with patch("src.api.routes.chat.redis_client", return_value=mock_redis):
            client = TestClient(app)
            response = client.post("/api/v1/chat/history", json=request_payload)

            assert response.status_code == 200
            assert response.json() == {"success": True}

            # Verify Redis key and ex (TTL)
            assert mock_redis.set.called
            args, kwargs = mock_redis.set.call_args

            assert args[0] == f"nyaya:history:{mock_email.lower()}"
            assert kwargs.get("ex") == 90 * 24 * 3600

            # Parse saved payload to check pruning
            saved_data = json.loads(args[1])
            saved_sessions = saved_data["sessions"]
            saved_active_chat = saved_data["active_chat"]

            # 1. Pruned sessions list to latest 50 (max)
            assert len(saved_sessions) == 50

            # 2. Checked order: sorted by ID descending, so IDs should be 11 to 60 (or largest first depending on request)
            # Since it sorts by ID descending, the processed IDs in sorted list are 60 down to 1.
            # The slice [:50] should be IDs 60 down to 11.
            session_ids = [s["id"] for s in saved_sessions]
            assert session_ids[0] == 60
            assert session_ids[-1] == 11

            # 3. Message list trimmed to last 50
            for s in saved_sessions:
                assert len(s["messages"]) == 50
                # Should have the latest messages (i.e. starting from index 10 to 59)
                assert s["messages"][0]["content"] == "msg 10"
                assert s["messages"][-1]["content"] == "msg 59"

            # 4. Active chat trimmed to last 50 messages
            assert len(saved_active_chat["messages"]) == 50
            assert saved_active_chat["messages"][0]["content"] == "active msg 20"
            assert saved_active_chat["messages"][-1]["content"] == "active msg 69"
    finally:
        app.dependency_overrides.clear()


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────




# ─────────────────────────────────────────────────────────────────────────────
# IMP-10: Pydantic Input Sanitization
# ─────────────────────────────────────────────────────────────────────────────


def test_input_sanitization_escapes_and_nulls():
    """Verify that ChatRequest and ConversationTurn strip control characters, null bytes, and ANSI escapes."""
    # 1. Test ConversationTurn sanitization
    turn = ConversationTurn(
        role="user", content="Hello \x00World!\x1b[31m Red Text\x07 Alert\nFormatted\tLine"
    )
    assert turn.content == "Hello World! Red Text Alert\nFormatted\tLine"

    # 2. Test ChatRequest sanitization
    req = ChatRequest(message="Hello \x00World!\x1b[31m Red Text\x07 Alert\nFormatted\tLine")
    assert req.message == "Hello World! Red Text Alert\nFormatted\tLine"

    # 3. Test validation error when message is entirely control characters / empty
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as excinfo:
        ChatRequest(message="\x00\x07\x1b[31m")

    assert "Message cannot be empty or contain only control characters" in str(excinfo.value)


# ─────────────────────────────────────────────────────────────────────────────
# IMP-9: Ingestion background thread verification
# ─────────────────────────────────────────────────────────────────────────────


def test_asyncio_thread_ingestion():
    """Verify that /ingest/text offloads work to asyncio.to_thread and does not crash."""
    mock_settings = Settings(qdrant_collection="test_collection")

    request_payload = {
        "project": "Test Project",
        "text": "This is some custom legal text to ingest. It must be at least one hundred characters long to prevent the LegalChunker from discarding it as a trivial snippet.",
        "category": "civil_law",
        "secret": "secret123",
    }

    # Mock all backend components in the ingest pipeline
    mock_qdrant = MagicMock()
    mock_app_state = MagicMock()
    mock_app_state.qdrant_client = mock_qdrant
    mock_app_state.bm25_retriever = MagicMock()

    # Mock get_collections and scroll to prevent actual Qdrant calls
    mock_qdrant.get_collection.return_value = MagicMock()
    mock_qdrant.scroll.return_value = ([], None)

    with (
        patch("src.api.routes.admin.settings", mock_settings),
        patch("src.api.routes.admin.app_state", mock_app_state),
        patch.dict(os.environ, {"ADMIN_SECRET": "secret123"}),
        patch("src.ingestion.embedder.get_embedding_model") as mock_embedder_func,
    ):
        mock_embedder = MagicMock()
        mock_embedder.embed_batch.return_value = [[0.1] * 768]
        mock_embedder_func.return_value = mock_embedder

        # Wrap asyncio.to_thread to assert it gets called
        with patch("asyncio.to_thread", wraps=asyncio.to_thread) as mock_to_thread:
            client = TestClient(app)
            response = client.post("/api/v1/ingest/text", json=request_payload)

            assert response.status_code == 200
            assert response.json()["success"] is True

            # Assert that asyncio.to_thread was called to run the ingest process in the background thread
            assert mock_to_thread.called


# ───────────────────────────────────────────────────────────────────────────────
# SEC-9: Google Auth Token Verification Tests
# ───────────────────────────────────────────────────────────────────────────────


CLIENT_ID = "vidhi-test-client.apps.googleusercontent.com"


def _google_http(tokeninfo_status=200, tokeninfo=None, userinfo=None):
    """Mock httpx.AsyncClient answering tokeninfo first, then userinfo."""
    from unittest.mock import AsyncMock, MagicMock

    info = MagicMock(status_code=tokeninfo_status)
    info.json.return_value = tokeninfo or {}
    profile = MagicMock(status_code=200)
    profile.json.return_value = userinfo or {}

    http = AsyncMock()
    http.get = AsyncMock(side_effect=[info, profile])
    http.__aenter__ = AsyncMock(return_value=http)
    http.__aexit__ = AsyncMock(return_value=False)
    return http


def _google_login(http, token="some_google_access_token"):
    from unittest.mock import MagicMock

    mock_redis = MagicMock()
    mock_redis.get.return_value = None
    with (
        patch("src.api.routes.auth.redis_client", return_value=mock_redis),
        patch("httpx.AsyncClient", return_value=http),
        patch("src.api.routes.auth.settings.google_client_id", CLIENT_ID),
    ):
        return TestClient(app).post("/api/v1/auth/google", json={"access_token": token})


def test_google_auth_rejects_invalid_token():
    """SEC-9: a token Google's tokeninfo rejects never signs anyone in."""
    response = _google_login(_google_http(tokeninfo_status=400))
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert data["token"] == ""


def test_google_auth_rejects_token_for_other_client():
    """A valid Google token issued to a different app must not sign in here."""
    http = _google_http(
        tokeninfo={"aud": "someone-elses-app.apps.googleusercontent.com",
                   "email": "victim@example.com", "email_verified": "true"},
    )
    data = _google_login(http).json()
    assert data["success"] is False
    assert data["token"] == ""


def test_google_auth_rejects_unverified_email():
    http = _google_http(tokeninfo={"aud": CLIENT_ID, "email": "x@example.com", "email_verified": "false"})
    assert _google_login(http).json()["success"] is False


def test_google_auth_accepts_valid_token():
    """SEC-9: a token issued to our client for a verified email yields a JWT."""
    http = _google_http(
        tokeninfo={"aud": CLIENT_ID, "email": "testuser@example.com", "email_verified": "true"},
        userinfo={"email": "testuser@example.com", "name": "Test User"},
    )
    response = _google_login(http)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["token"]
    assert data["user"]["email"] == "testuser@example.com"
    assert data["user"]["name"] == "Test User"


# ───────────────────────────────────────────────────────────────────────────────
# BUG-8: RAG Retry Loop — hyde_embedding Reset Tests
# ───────────────────────────────────────────────────────────────────────────────


def test_rag_retry_loop_embed_reset():
    """
    BUG-8: Verify that refine_query_node resets hyde_embedding to None so
    that hybrid_search_node re-embeds the refined query instead of reusing
    the stale original-query embedding.
    """
    from src.graph.nodes import refine_query_node
    from src.models import Claim

    failed_claim = Claim(
        text="The RTI Act requires 30-day response",
        grounding_score=0.2,
        is_grounded=False,
    )

    state = {
        "query": "What is the RTI Act response time?",
        "failed_claims": [failed_claim],
        "retry_count": 0,
        "route": "RETRIEVE",
        "hyde_embedding": [0.1, 0.2, 0.3],  # Stale embedding from first pass
    }

    mock_llm = MagicMock()

    async def mock_refine(query, failed_claims, llm):
        return "Under RTI Act 2005 what is the mandatory officer response deadline?"

    with (
        patch("src.graph.nodes.get_llm", return_value=mock_llm),
        patch("src.graph.nodes.refine_query", side_effect=mock_refine),
    ):
        result = asyncio.run(refine_query_node(state))

    # The returned state patch must reset hyde_embedding to None
    assert result["hyde_embedding"] is None, (
        "BUG-8: hyde_embedding was NOT reset to None after query refinement"
    )
    assert result["retry_count"] == 1
    assert "RTI" in result["query"]


# ───────────────────────────────────────────────────────────────────────────────
# BUG-6 & BUG-7: Category Filtering Tests (Dense + BM25)
# ───────────────────────────────────────────────────────────────────────────────


def test_bm25_retrieval_category_filtering():
    """
    BUG-7: Verify that BM25Retriever.retrieve correctly filters out chunks
    whose act_category does not match the requested category_filter.
    """
    from src.models import ActCategory, Chunk, ChunkMetadata
    from src.retrieval.sparse import BM25Retriever

    # Build a small corpus with two categories
    def make_chunk(idx, text, category):
        return Chunk(
            id=str(idx),
            text=text,
            metadata=ChunkMetadata(
                chunk_id=str(idx),
                source_url="",
                document_title="Test Act",
                section="",
                act_category=ActCategory(category),
                chunk_index=idx,
            ),
            score=0.0,
            embedding=None,
        )

    chunks = [
        make_chunk(0, "RTI Act information disclosure transparency government", "transparency_law"),
        make_chunk(1, "RTI Act appeal mechanism transparency officer", "transparency_law"),
        make_chunk(2, "Consumer protection defective goods refund rights", "consumer_rights"),
        make_chunk(3, "Labour act minimum wages employment contract", "labour_law"),
    ]

    retriever = BM25Retriever(chunks=chunks)

    # Unfiltered: should return all matching chunks (all have some score for "RTI"/"act")
    all_results = retriever.retrieve(query="RTI Act information", top_k=10)
    categories_returned = {c.metadata.act_category.value for c in all_results}
    # Without filter, multiple categories may be returned
    assert len(all_results) > 0

    # Filtered: should only return transparency_law chunks
    filtered_results = retriever.retrieve(
        query="RTI Act information",
        top_k=10,
        category_filter="transparency_law",
    )
    assert len(filtered_results) > 0, "Expected at least one transparency_law chunk"
    for chunk in filtered_results:
        assert chunk.metadata.act_category.value == "transparency_law", (
            f"BUG-7: Got chunk with category '{chunk.metadata.act_category.value}' when filter was 'transparency_law'"
        )

    # Filtered for consumer_rights: should not include RTI chunks
    consumer_results = retriever.retrieve(
        query="RTI Act information",
        top_k=10,
        category_filter="consumer_rights",
    )
    for chunk in consumer_results:
        assert chunk.metadata.act_category.value == "consumer_rights", (
            f"BUG-7: Got non-consumer chunk with category '{chunk.metadata.act_category.value}'"
        )


# ───────────────────────────────────────────────────────────────────────────────
# BUG-9: Prometheus Metrics Recording Tests
# ───────────────────────────────────────────────────────────────────────────────


def test_prometheus_cache_miss_recorded_on_cache_miss():
    """
    BUG-9: Verify that cache_check_node increments CACHE_MISSES on a cache miss
    and CACHE_HITS on a cache hit.
    """
    from src.observability.prometheus_metrics import CACHE_HITS, CACHE_MISSES

    mock_cache = MagicMock()

    # — Test CACHE_MISS —
    mock_cache.get.return_value = None  # Cache miss

    from src.graph.nodes import cache_check_node

    miss_before = CACHE_MISSES._value.get()
    result = asyncio.run(
        cache_check_node({"query": "what is RTI", "deep_search": False}, mock_cache)
    )
    miss_after = CACHE_MISSES._value.get()

    assert result["cache_hit"] is False
    assert miss_after == miss_before + 1, "BUG-9: CACHE_MISSES was not incremented on cache miss"

    # — Test CACHE_HIT —
    mock_cache.get.return_value = {
        "answer": "RTI stands for Right to Information",
        "citations": [],
        "confidence_score": 0.9,
        "legal_standing_score": 0.85,
        "route": "RETRIEVE",
    }

    hit_before = CACHE_HITS._value.get()
    result = asyncio.run(
        cache_check_node({"query": "what is RTI", "deep_search": False}, mock_cache)
    )
    hit_after = CACHE_HITS._value.get()

    assert result["cache_hit"] is True
    assert hit_after == hit_before + 1, "BUG-9: CACHE_HITS was not incremented on cache hit"


def test_prometheus_routing_decision_recorded():
    """
    BUG-9: Verify that router_node increments ROUTING_DECISIONS with the correct route label.
    """
    from src.graph.nodes import router_node
    from src.observability.prometheus_metrics import ROUTING_DECISIONS

    class MockDecision:
        class route:
            value = "RETRIEVE"

        confidence = 0.95

    with (
        patch("src.graph.nodes.get_llm", return_value=MagicMock()),
        patch("src.graph.nodes.route_query", return_value=MockDecision()) as mock_route,
    ):

        async def async_route(q, llm):
            return MockDecision()

        mock_route.side_effect = async_route

        before = ROUTING_DECISIONS.labels(route="RETRIEVE")._value.get()
        result = asyncio.run(router_node({"query": "what is RTI Act"}))
        after = ROUTING_DECISIONS.labels(route="RETRIEVE")._value.get()

    assert result["route"] == "RETRIEVE"
    assert after == before + 1, "BUG-9: ROUTING_DECISIONS counter was not incremented"
