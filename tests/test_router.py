"""
NyayaBot — Router agent unit tests.
Tests 20 queries × 4 route categories with fast-path and LLM routing.
"""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.agents.router import route_query
from src.models import RouteType
from src.config import settings
from src.graph.nodes import get_llm



class MockLLM:
    """Mock LLM for testing router without API calls."""

    def __init__(self, response: str):
        self.response = response

    async def ainvoke(self, messages):
        mock = MagicMock()
        mock.content = self.response
        return mock


# ─────────────────────────────────────────────
# Fast-path regex tests (no LLM needed)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cnr_routes_to_tool():
    llm = MockLLM('{"route": "RETRIEVE", "reasoning": "test", "confidence": 0.9}')
    decision = await route_query("Check CNR number MHAU0100123456", llm)
    assert decision.route == RouteType.TOOL

@pytest.mark.asyncio
async def test_case_status_routes_to_tool():
    llm = MockLLM('{"route": "RETRIEVE", "reasoning": "test", "confidence": 0.9}')
    decision = await route_query("What is my case status in court?", llm)
    assert decision.route == RouteType.TOOL

@pytest.mark.asyncio
async def test_greeting_routes_to_chitchat():
    llm = MockLLM('{"route": "RETRIEVE", "reasoning": "test", "confidence": 0.9}')
    decision = await route_query("Hello!", llm)
    assert decision.route == RouteType.CHITCHAT

@pytest.mark.asyncio
async def test_thanks_routes_to_chitchat():
    llm = MockLLM('{"route": "RETRIEVE", "reasoning": "test", "confidence": 0.9}')
    decision = await route_query("Thanks", llm)
    assert decision.route == RouteType.CHITCHAT

@pytest.mark.asyncio
async def test_memory_reference_routes_to_memory():
    llm = MockLLM('{"route": "RETRIEVE", "reasoning": "test", "confidence": 0.9}')
    decision = await route_query("You said earlier I could appeal. What did you mean?", llm)
    assert decision.route == RouteType.MEMORY

# ─────────────────────────────────────────────
# LLM-based routing tests
# ─────────────────────────────────────────────

RETRIEVE_QUERIES = [
    "How do I file an RTI application?",
    "What are my rights under the Consumer Protection Act?",
    "How can I withdraw my PF amount?",
    "What is the procedure to file an FIR?",
    "How do I register my property in India?",
    "What is the minimum wage in Maharashtra?",
    "How to file income tax return for salaried person?",
    "What are tenant rights under rent control act?",
    "How to get free legal aid in India?",
    "What is the process for RERA complaint?",
    "How to start a company in India?",
    "What are the penalties for domestic violence?",
    "How to appeal in consumer court?",
    "What documents do I need for Aadhaar update?",
    "What is the time limit to file consumer complaint?",
]

@pytest.mark.asyncio
@pytest.mark.parametrize("query", RETRIEVE_QUERIES)
async def test_legal_queries_route_to_retrieve(query):
    if settings.llm_provider == "ollama":
        llm = get_llm()
    else:
        llm = MockLLM('{"route": "RETRIEVE", "reasoning": "Legal query", "confidence": 0.95}')
    decision = await route_query(query, llm)
    assert decision.route == RouteType.RETRIEVE

# ─────────────────────────────────────────────
# Fallback behavior
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_malformed_llm_response_defaults_to_retrieve():
    """When LLM returns garbage, should fall back to RETRIEVE safely."""
    llm = MockLLM("I am unable to classify this.")
    decision = await route_query("Tell me about section 6 of RTI", llm)
    assert decision.route == RouteType.RETRIEVE

@pytest.mark.asyncio
async def test_route_decision_confidence_range():
    """Confidence must always be 0-1."""
    if settings.llm_provider == "ollama":
        llm = get_llm()
    else:
        llm = MockLLM('{"route": "RETRIEVE", "reasoning": "test", "confidence": 0.87}')
    decision = await route_query("How to file RTI?", llm)
    assert 0.0 <= decision.confidence <= 1.0


EMERGENCY_QUERIES = [
    "police stopped me at the checkpost",
    "officer is asking for bribe",
    "the traffic cop took bribe from me",
    "help! i am being arrested right now",
    "police is threatening me to sign paper",
    "what to do right now help!",
    "he is issuing a challan without documents",
    "police seized my registration",
    "what are my rights right now?",
    "emergency legal support",
    "fir file nahi kar raha thana",
    "police nahi sun raha complaint",
]

@pytest.mark.asyncio
@pytest.mark.parametrize("query", EMERGENCY_QUERIES)
async def test_emergency_fast_paths(query):
    llm = MockLLM('{"route": "RETRIEVE", "reasoning": "test", "confidence": 0.9}')
    decision = await route_query(query, llm)
    assert decision.route == RouteType.EMERGENCY

