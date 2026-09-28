"""
NyayaBot — Test configuration and shared fixtures.
"""
import pytest
import sys
from pathlib import Path

# Make sure src/ is on the path for all tests
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(autouse=True)
def allow_all_rate_limits():
    """Every TestClient request comes from the same address, so a live Redis
    would make rate limits trip partway through the suite. Tests that exercise
    limits patch get_rate_limiter themselves, which takes precedence."""
    from unittest.mock import MagicMock, patch

    limiter = MagicMock()
    limiter.is_allowed.return_value = (True, 100)
    with patch("src.cache.redis_store.get_rate_limiter", return_value=limiter):
        yield
