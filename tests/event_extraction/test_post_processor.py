"""
Тесты для главного процессора постов.
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, AsyncMock, MagicMock

from src.event_extraction.models import (
    RawPost,
    StructuredEvent,
    EventSource,
    ScheduleExact,
    WeightedInterest,
)
from src.event_extraction.post_processor import PostProcessor


@pytest.fixture
def mock_clients():
    """Моки для клиентов."""
    db_client = MagicMock()
    qdrant_client = MagicMock()
    qdrant_client.get_collections.return_value = Mock(collections=[Mock(name="events")])
    llm_client = Mock()
    image_handler = Mock()
    
    return db_client, qdrant_client, llm_client, image_handler


@pytest.mark.asyncio
async def test_is_post_processed(mock_clients):
    """Тест проверки обработки поста."""
    db_client, qdrant_client, llm_client, image_handler = mock_clients
    
    # Настройка мока БД
    db_mock = Mock()
    db_mock.processed_posts.find_one = AsyncMock(return_value={"post_id": 123})
    db_client.__getitem__ = Mock(return_value=db_mock)
    
    processor = PostProcessor(
        db_client=db_client,
        qdrant_client=qdrant_client,
        llm_client=llm_client,
        image_handler=image_handler
    )
    
    result = await processor._is_post_processed(123, "test_channel")
    assert result is True


@pytest.mark.asyncio
async def test_mark_post_processed(mock_clients):
    """Тест отметки поста как обработанного."""
    db_client, qdrant_client, llm_client, image_handler = mock_clients
    
    # Настройка мока БД
    db_mock = Mock()
    db_mock.processed_posts.update_one = AsyncMock()
    db_client.__getitem__ = Mock(return_value=db_mock)
    
    processor = PostProcessor(
        db_client=db_client,
        qdrant_client=qdrant_client,
        llm_client=llm_client,
        image_handler=image_handler
    )
    
    await processor._mark_post_processed(123, "test_channel", ["event1", "event2"])
    
    # Проверяем, что update_one был вызван
    db_mock.processed_posts.update_one.assert_called_once()


def test_raw_post_validation():
    """Тест валидации сырого поста."""
    raw_post = {
        "text": "Концерт 15 декабря",
        "photo_urls": ["image1.jpg"],
        "hashtags": ["#концерт"],
        "post_id": 123,
        "channel": "test_channel",
        "message_date": datetime(2025, 12, 1, 10, 0)
    }
    
    post = RawPost(**raw_post)
    
    assert post.text == "Концерт 15 декабря"
    assert post.post_id == 123
    assert post.channel == "test_channel"


@pytest.mark.asyncio
async def test_get_embedding(mock_clients):
    """Тест получения эмбеддинга."""
    db_client, qdrant_client, llm_client, image_handler = mock_clients
    
    # Настройка мока LLM
    mock_response = Mock()
    mock_response.data = [Mock(embedding=[0.1, 0.2, 0.3])]
    llm_client.embeddings.create = AsyncMock(return_value=mock_response)
    
    processor = PostProcessor(
        db_client=db_client,
        qdrant_client=qdrant_client,
        llm_client=llm_client,
        image_handler=image_handler
    )
    
    embedding = await processor._get_embedding("Test text")
    
    assert embedding == [0.1, 0.2, 0.3]
    llm_client.embeddings.create.assert_called_once()


@pytest.mark.asyncio
async def test_process_post_already_processed(mock_clients):
    """Тест обработки уже обработанного поста."""
    db_client, qdrant_client, llm_client, image_handler = mock_clients
    
    # Настройка моков
    db_mock = Mock()
    db_mock.processed_posts.find_one = AsyncMock(return_value={"post_id": 123})
    db_client.__getitem__ = Mock(return_value=db_mock)
    
    processor = PostProcessor(
        db_client=db_client,
        qdrant_client=qdrant_client,
        llm_client=llm_client,
        image_handler=image_handler
    )
    
    raw_post = {
        "text": "Test",
        "post_id": 123,
        "channel": "test",
        "photo_urls": [],
        "hashtags": []
    }
    
    events = await processor.process_post(raw_post)
    
    # Пост уже обработан, должен вернуться пустой список
    assert events == []


@pytest.mark.asyncio
async def test_merge_similar_events_within_post_combines_duplicates():
    """Схожие события внутри поста объединяются в одну карточку."""
    processor = object.__new__(PostProcessor)
    processor.similarity_threshold_intra_post = 0.85
    processor._get_embedding = AsyncMock(side_effect=[[1.0, 0.0], [0.99, 0.01]])

    schedule = ScheduleExact(date_start=datetime(2026, 3, 10, 19, 0))
    event_left = StructuredEvent(
        title="Фестиваль японской культуры",
        description="Большой фестиваль с лекциями",
        location="Центр культуры",
        address="Кремлевская 1",
        categories=["япония"],
        category_primary="культура",
        category_secondary=["япония"],
        interests=[WeightedInterest(name="япония", weight=1.0)],
        user_interests=["япония"],
        schedule=schedule,
        sources=[EventSource(channel="test", post_id=1)],
    )
    event_right = StructuredEvent(
        title="Фестиваль восточной культуры",
        description="Фестиваль с мастер-классами и рынком",
        location="Центр культуры",
        address="Кремлевская 1",
        categories=["восток"],
        category_primary="культура",
        category_secondary=["восток"],
        interests=[WeightedInterest(name="восток", weight=1.0)],
        user_interests=["восток"],
        schedule=schedule,
        sources=[EventSource(channel="test", post_id=1)],
    )

    merged = await processor.merge_similar_events_within_post([event_left, event_right])

    assert len(merged) == 1
    assert set(merged[0].categories) == {"япония", "восток"}
    assert round(sum(item.weight for item in merged[0].interests), 4) == 1.0
    assert set(merged[0].user_interests) == {"япония", "восток"}
