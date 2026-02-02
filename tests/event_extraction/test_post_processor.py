"""
Тесты для главного процессора постов.
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch

from src.event_extraction.models import RawPost, StructuredEvent, EventSource, ScheduleExact
from src.event_extraction.post_processor import PostProcessor


@pytest.fixture
def mock_clients():
    """Моки для клиентов."""
    db_client = Mock()
    qdrant_client = Mock()
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
