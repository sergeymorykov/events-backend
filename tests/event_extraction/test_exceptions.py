"""
Тесты для исключений модуля.
"""

import pytest
from src.event_extraction.exceptions import (
    InsufficientQuotaError,
    PostProcessingError,
    EventDeduplicationError
)


def test_insufficient_quota_error():
    """Тест InsufficientQuotaError."""
    error = InsufficientQuotaError("API quota exceeded")
    
    assert isinstance(error, Exception)
    assert str(error) == "API quota exceeded"


def test_post_processing_error():
    """Тест PostProcessingError."""
    error = PostProcessingError("Processing failed")
    
    assert isinstance(error, Exception)
    assert str(error) == "Processing failed"


def test_event_deduplication_error():
    """Тест EventDeduplicationError."""
    error = EventDeduplicationError("Deduplication failed")
    
    assert isinstance(error, Exception)
    assert str(error) == "Deduplication failed"
