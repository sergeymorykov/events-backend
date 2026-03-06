"""
Тесты для модуля дедупликации.
"""

import pytest
from datetime import datetime
from unittest.mock import Mock

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


@pytest.mark.asyncio
async def test_add_event_to_index_saves_canonical_payload():
    """Payload в Qdrant содержит канонические поля для диагностики дедупа."""
    qdrant_client = Mock()
    qdrant_client.get_collections.return_value = Mock(collections=[Mock(name="events")])
    qdrant_client.upsert.return_value = None

    deduplicator = EventDeduplicator(
        qdrant_client=qdrant_client,
        collection_name="events",
    )

    event = StructuredEvent(
        title="Тестовое событие",
        categories=["музыка"],
        category_primary="культура",
        category_secondary=["музыка"],
        interests=[],
        user_interests=[],
        sources=[EventSource(channel="test", post_id=1)],
    )
    ok = await deduplicator.add_event_to_index(
        event=event,
        embedding=[0.1, 0.2, 0.3],
        event_id="abc123",
    )

    assert ok is True
    assert qdrant_client.upsert.call_count == 1
    upsert_kwargs = qdrant_client.upsert.call_args.kwargs
    payload = upsert_kwargs["points"][0].payload
    assert payload["canonical_categories"] == ["музыка"]
    assert payload["category_primary"] == "культура"
    assert payload["category_secondary"] == ["музыка"]


@pytest.mark.asyncio
async def test_add_event_to_index_uses_passed_canonical_hash():
    """Если canonical_hash передан явно, в payload уходит именно он."""
    qdrant_client = Mock()
    qdrant_client.get_collections.return_value = Mock(collections=[Mock(name="events")])
    qdrant_client.upsert.return_value = None

    deduplicator = EventDeduplicator(
        qdrant_client=qdrant_client,
        collection_name="events",
    )

    event = StructuredEvent(
        title="Событие без предрасчета",
        sources=[EventSource(channel="test", post_id=99)],
    )

    ok = await deduplicator.add_event_to_index(
        event=event,
        embedding=[0.1, 0.2, 0.3],
        event_id="event-1",
        canonical_hash="explicit-canonical-hash",
    )

    assert ok is True
    upsert_kwargs = qdrant_client.upsert.call_args.kwargs
    payload = upsert_kwargs["points"][0].payload
    assert payload["canonical_hash"] == "explicit-canonical-hash"
