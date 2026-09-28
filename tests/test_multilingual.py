"""
NyayaBot — Multilingual prompts unit tests.
Verifies that system and emergency prompts contain specific language instructions and script rules.
"""
from __future__ import annotations

import pytest
from src.agents.generator import GENERATOR_SYSTEM_PROMPT, EMERGENCY_SYSTEM_PROMPT, _build_messages
from src.models import Chunk, ChunkMetadata, ActCategory

def test_generator_system_prompt_language_rules():
    """Verify that the Generator System Prompt contains language consistency guidelines."""
    prompt = GENERATOR_SYSTEM_PROMPT.lower()
    
    assert "language" in prompt
    assert "hindi" in prompt
    assert "hinglish" in prompt
    assert "devanagari" in prompt
    assert "roman/english" in prompt
    assert "script" in prompt
    assert "english names" in prompt


def test_emergency_system_prompt_language_rules():
    """Verify that the Emergency System Prompt contains language matching guidelines."""
    prompt = EMERGENCY_SYSTEM_PROMPT.lower()
    
    assert "language matching" in prompt
    assert "hindi" in prompt
    assert "hinglish" in prompt
    assert "english" in prompt


def test_build_messages_injects_correct_prompt():
    """Verify that _build_messages applies the correct system instructions."""
    query = "Police ne mujhe roka, kya karna chahiye?"
    context = "Retrieved documents context"
    history_text = "No previous conversation."
    
    # 1. Normal mode
    messages = _build_messages(query, context, history_text, emergency=False)
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert "LANGUAGE & STYLE CONSISTENCY" in messages[0]["content"]
    assert "Devanagari" in messages[0]["content"]
    
    # 2. Emergency mode
    em_messages = _build_messages(query, context, history_text, emergency=True)
    assert len(em_messages) == 2
    assert em_messages[0]["role"] == "system"
    assert "LANGUAGE MATCHING" in em_messages[0]["content"]


from unittest.mock import MagicMock
from src.agents.generator import translate_to_english

class MockLLM:
    """Mock LLM for translation test."""
    def __init__(self, response: str):
        self.response = response

    async def ainvoke(self, messages):
        mock = MagicMock()
        mock.content = self.response
        return mock

@pytest.mark.asyncio
async def test_translate_to_english_hindi():
    llm = MockLLM("How do I withdraw my EPF online?")
    translated = await translate_to_english("मेरा EPF ऑनलाइन कैसे निकालें?", llm)
    assert translated == "How do I withdraw my EPF online?"

@pytest.mark.asyncio
async def test_translate_to_english_already_english():
    llm = MockLLM("What are my consumer rights?")
    translated = await translate_to_english("What are my consumer rights?", llm)
    assert translated == "What are my consumer rights?"


from fastapi.testclient import TestClient
from src.api.main import app
from unittest.mock import patch

def test_translate_endpoint_success():
    """Verify that POST /api/v1/chat/translate successfully invokes LLM and translates text."""
    llm = MockLLM("आरटीआई आवेदन कैसे दायर करें")
    with patch("src.graph.nodes.get_llm", return_value=llm), \
         patch.dict("os.environ", {"ADMIN_SECRET": "translate-test-secret"}):
        client = TestClient(app)
        response = client.post(
            "/api/v1/chat/translate",
            headers={"X-Admin-Secret": "translate-test-secret"},
            json={"text": "How to file an RTI application", "target_language": "hi"}
        )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["translated_text"] == "आरटीआई आवेदन कैसे दायर करें"

def test_translate_endpoint_english_passthrough():
    """Verify that POST /api/v1/chat/translate returns original text if English target is specified."""
    client = TestClient(app)
    with patch.dict("os.environ", {"ADMIN_SECRET": "translate-test-secret"}):
        response = client.post(
            "/api/v1/chat/translate",
            headers={"X-Admin-Secret": "translate-test-secret"},
            json={"text": "How to file an RTI application", "target_language": "en"}
        )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["translated_text"] == "How to file an RTI application"



def test_translate_endpoint_requires_admin():
    """An open translation endpoint is a free LLM proxy; it must be locked."""
    client = TestClient(app)
    response = client.post(
        "/api/v1/chat/translate",
        json={"text": "How to file an RTI application", "target_language": "hi"}
    )
    assert response.status_code == 401
