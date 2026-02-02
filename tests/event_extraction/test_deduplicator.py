"""
Тесты для модуля дедупликации.
"""

import pytest
from datetime import datetime

from src.event_extraction.models import (
    StructuredEvent,
    ScheduleExact,
    EventSource
)
from src.event_extraction.deduplicator import EventDeduplicator


def test_generate_canonical_hash():
    """Тест генерации канонического хэша."""
    schedule = ScheduleExact(date_start=datetime(2025, 12, 15, 19, 0))
    
    event1 = StructuredEvent(
        title="Концерт в Филармонии",
        location="Казанская филармония",
        schedule=schedule,
        sources=[EventSource(channel="test", post_id=1)]
    )
    
    event2 = StructuredEvent(
        title="концерт в филармонии",  # Другой регистр
        location="Казанская филармония",
        schedule=schedule,
        sources=[EventSource(channel="test", post_id=2)]
    )
    
    hash1 = EventDeduplicator.generate_canonical_hash(event1)
    hash2 = EventDeduplicator.generate_canonical_hash(event2)
    
    # Хэши должны совпадать (регистронезависимость)
    assert hash1 == hash2
    assert len(hash1) == 64  # SHA256


def test_normalize_text():
    """Тест нормализации текста."""
    text1 = "Концерт в Филармонии!!!"
    text2 = "концерт в филармонии"
    
    norm1 = EventDeduplicator._normalize_text(text1)
    norm2 = EventDeduplicator._normalize_text(text2)
    
    # Должны быть идентичны после нормализации
    assert norm1 == norm2
    assert norm1 == "концерт в филармонии"


def test_canonical_hash_different_events():
    """Тест хэшей для разных событий."""
    schedule1 = ScheduleExact(date_start=datetime(2025, 12, 15, 19, 0))
    schedule2 = ScheduleExact(date_start=datetime(2025, 12, 16, 19, 0))  # Другая дата
    
    event1 = StructuredEvent(
        title="Концерт",
        location="Филармония",
        schedule=schedule1,
        sources=[EventSource(channel="test", post_id=1)]
    )
    
    event2 = StructuredEvent(
        title="Концерт",
        location="Филармония",
        schedule=schedule2,  # Другая дата
        sources=[EventSource(channel="test", post_id=2)]
    )
    
    hash1 = EventDeduplicator.generate_canonical_hash(event1)
    hash2 = EventDeduplicator.generate_canonical_hash(event2)
    
    # Хэши должны отличаться (разные даты)
    assert hash1 != hash2


@pytest.mark.asyncio
async def test_deduplicator_statistics():
    """Тест получения статистики (требует Qdrant)."""
    # Этот тест требует запущенный Qdrant
    # В реальных условиях нужно использовать моки
    pytest.skip("Требует запущенный Qdrant")
