import pytest
from unittest.mock import MagicMock, patch
from src.retrieval.translation_service import TranslationService

class MockLLM:
    """Mock LLM for testing fallback translation."""
    def __init__(self, response: str):
        self.response = response

    async def ainvoke(self, messages):
        mock = MagicMock()
        mock.content = self.response
        return mock

@pytest.mark.asyncio
async def test_llm_translation_to_english():
    """Verify that TranslationService falls back to LLM for translating to English."""
    service = TranslationService.get_instance()
    mock_llm = MockLLM("How do I withdraw my EPF online?")
    
    with patch("src.graph.nodes.get_llm", return_value=mock_llm):
        translated = await service.translate_to_english("मेरा EPF ऑनलाइन कैसे निकालें?", "hi")
        assert translated == "How do I withdraw my EPF online?"

@pytest.mark.asyncio
async def test_llm_translation_from_english():
    """Verify that TranslationService falls back to LLM for translating from English."""
    service = TranslationService.get_instance()
    mock_llm = MockLLM("आरटीआई आवेदन कैसे दायर करें")
    
    with patch("src.graph.nodes.get_llm", return_value=mock_llm):
        translated = await service.translate_from_english("How to file an RTI application", "hi")
        assert translated == "आरटीआई आवेदन कैसे दायर करें"

@pytest.mark.asyncio
async def test_english_passthrough():
    """Verify that English queries/responses bypass translation."""
    service = TranslationService.get_instance()
    
    translated_to = await service.translate_to_english("Standard query", "en")
    assert translated_to == "Standard query"
    
    translated_from = await service.translate_from_english("Standard response", "en")
    assert translated_from == "Standard response"
