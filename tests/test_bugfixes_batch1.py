"""
NyayaBot — Unit tests for BUG-2 and BUG-3.
"""
from __future__ import annotations

import time
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi.testclient import TestClient

from src.api.main import app
from src.graph.nodes import _FallbackLLM


# ─────────────────────────────────────────────────────────────────────────────
# BUG-2: Feedback Endpoint Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_submit_feedback_success():
    """Verify that submit_feedback successfully stores feedback in Redis."""
    mock_redis = MagicMock()
    
    with patch("src.api.routes.feedback.redis_client", return_value=mock_redis):
        client = TestClient(app)
        response = client.post(
            "/api/v1/feedback",
            json={
                "session_id": "test-session-123",
                "message_id": "test-message-456",
                "thumbs_up": True,
                "comment": "Very helpful!"
            }
        )
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        
        # Verify lpush and ltrim were called on the mock Redis client
        assert mock_redis.lpush.called
        assert mock_redis.ltrim.called
        
        # Verify arguments sent to lpush
        call_key, call_data = mock_redis.lpush.call_args[0]
        assert call_key == "nyayabot:feedback"
        assert "test-session-123" in call_data
        assert "test-message-456" in call_data
        assert '"thumbs_up": true' in call_data


def test_submit_feedback_redis_unavailable():
    """Verify that submit_feedback returns error when Redis is unavailable."""
    with patch("src.api.routes.feedback.redis_client", return_value=None):
        client = TestClient(app)
        response = client.post(
            "/api/v1/feedback",
            json={
                "session_id": "test-session-123",
                "message_id": "test-message-456",
                "thumbs_up": False
            }
        )
        assert response.status_code == 200
        assert response.json() == {"status": "error", "message": "Redis unavailable"}


# ─────────────────────────────────────────────────────────────────────────────
# BUG-3: _FallbackLLM Cooldown Recovery Tests
# ─────────────────────────────────────────────────────────────────────────────

class MockModel:
    """Mock LangChain LLM supporting ainvoke and astream."""
    def __init__(self, name: str, should_fail: bool = False, fail_message: str = "429: Resource Exhausted"):
        self.name = name
        self.should_fail = should_fail
        self.fail_message = fail_message
        self.calls = 0

    async def ainvoke(self, *args, **kwargs):
        self.calls += 1
        if self.should_fail:
            raise Exception(self.fail_message)
        mock_response = MagicMock()
        mock_response.content = f"Response from {self.name}"
        return mock_response

    async def astream(self, *args, **kwargs):
        self.calls += 1
        if self.should_fail:
            raise Exception(self.fail_message)
        yield MagicMock(content=f"Stream chunk from {self.name}")


@pytest.mark.asyncio
async def test_fallback_llm_cooldown_and_recovery():
    """Verify that FallbackLLM recovers and retries primary model after cooldown."""
    primary = MockModel("PrimaryModel", should_fail=True)
    fallback = MockModel("FallbackModel", should_fail=False)

    fallback_llm = _FallbackLLM(primary, fallback)
    fallback_llm._cooldown_seconds = 0.5  # Short cooldown for test fast-forward

    # 1. First call: primary is tried, raises 429, switches to fallback
    result = await fallback_llm.ainvoke("Hello")
    assert "Response from FallbackModel" in result.content
    assert primary.calls == 1
    assert fallback.calls == 1
    assert fallback_llm._fallback_until > time.time()

    # 2. Second call (immediate): fallback is used directly without trying primary
    result2 = await fallback_llm.ainvoke("Hello again")
    assert "Response from FallbackModel" in result2.content
    assert primary.calls == 1  # Still 1, primary wasn't tried
    assert fallback.calls == 2

    # 3. Wait for cooldown to expire
    time.sleep(0.6)

    # 4. Third call: cooldown expired, so primary should be tried again.
    # Primary will fail again (should_fail=True) and trigger fallback again.
    result3 = await fallback_llm.ainvoke("After cooldown")
    assert "Response from FallbackModel" in result3.content
    assert primary.calls == 2  # Primary was tried again!
    assert fallback.calls == 3

    # 5. Make primary succeed now
    primary.should_fail = False
    time.sleep(0.6)  # Wait for the new cooldown to expire

    # 6. Fourth call: primary succeeds, so fallback is not used
    result4 = await fallback_llm.ainvoke("Succeeding primary")
    assert "Response from PrimaryModel" in result4.content
    assert primary.calls == 3
    assert fallback.calls == 3  # Fallback calls stayed at 3
