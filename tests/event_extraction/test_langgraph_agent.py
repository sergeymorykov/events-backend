"""
Тесты для LangGraph агента.
"""

import pytest
from unittest.mock import Mock, AsyncMock
from datetime import datetime, timedelta

from src.event_extraction.langgraph_agent import EventExtractionGraph
from src.event_extraction.models import ExtractionState


@pytest.fixture
def mock_llm_client():
    """Мок LLM клиента."""
    client = Mock()
    client.chat.completions.create = AsyncMock()
    return client


@pytest.fixture
def mock_image_handler():
    """Мок обработчика изображений."""
    handler = Mock()
    handler.generate_event_poster = AsyncMock(return_value="generated_poster.png")
    return handler


def test_agent_initialization(mock_llm_client, mock_image_handler):
    """Тест инициализации агента."""
    agent = EventExtractionGraph(
        llm_client=mock_llm_client,
        image_handler=mock_image_handler,
        model_name="gpt-4o"
    )
    
    assert agent.model_name == "gpt-4o"
    assert agent.temperature == 0.7
    assert agent.graph is not None


@pytest.mark.asyncio
async def test_call_llm_success(mock_llm_client, mock_image_handler):
    """Тест успешного вызова LLM."""
    agent = EventExtractionGraph(
        llm_client=mock_llm_client,
        image_handler=mock_image_handler
    )
    
    # Настройка мока ответа
    mock_response = Mock()
    mock_response.choices = [Mock(message=Mock(content="Test response"))]
    mock_llm_client.chat.completions.create.return_value = mock_response
    
    messages = [{"role": "user", "content": "Test"}]
    response = await agent._call_llm(messages)
    
    assert response == "Test response"


@pytest.mark.asyncio
async def test_split_into_events(mock_llm_client, mock_image_handler):
    """Тест разделения поста на события."""
    agent = EventExtractionGraph(
        llm_client=mock_llm_client,
        image_handler=mock_image_handler
    )
    
    # Настройка мока ответа с JSON
    mock_response = Mock()
    mock_response.choices = [Mock(message=Mock(content='["Событие 1", "Событие 2"]'))]
    mock_llm_client.chat.completions.create.return_value = mock_response
    
    state = ExtractionState(
        raw_text="Концерт 15 декабря. Выставка 20 декабря.",
        channel="test",
        post_id=123
    )
    
    result = await agent._split_into_events(state)
    
    assert len(result.raw_events) == 2
    assert result.current_step == "split_into_events"


@pytest.mark.asyncio
async def test_process_images_with_existing(mock_llm_client, mock_image_handler):
    """Тест обработки изображений (уже есть в посте)."""
    agent = EventExtractionGraph(
        llm_client=mock_llm_client,
        image_handler=mock_image_handler
    )
    
    from src.event_extraction.models import StructuredEvent, EventSource
    
    state = ExtractionState(
        raw_text="Test",
        images=["existing_image.jpg"],
        channel="test",
        post_id=123
    )
    
    # Добавляем тестовое событие
    state.events.append(
        StructuredEvent(
            title="Test Event",
            sources=[EventSource(channel="test", post_id=123)]
        )
    )
    
    result = await agent._process_images(state)
    
    # Изображения из поста должны быть присвоены событиям
    assert result.events[0].images == ["existing_image.jpg"]
    assert not result.events[0].poster_generated


@pytest.mark.asyncio
async def test_process_images_generation(mock_llm_client, mock_image_handler):
    """Тест генерации афиш при отсутствии изображений."""
    agent = EventExtractionGraph(
        llm_client=mock_llm_client,
        image_handler=mock_image_handler
    )
    
    from src.event_extraction.models import StructuredEvent, EventSource
    
    state = ExtractionState(
        raw_text="Test",
        images=[],  # Нет изображений
        channel="test",
        post_id=123
    )
    
    # Добавляем тестовое событие
    state.events.append(
        StructuredEvent(
            title="Test Event",
            sources=[EventSource(channel="test", post_id=123)]
        )
    )
    
    result = await agent._process_images(state)
    
    # Должна быть сгенерирована афиша
    mock_image_handler.generate_event_poster.assert_called_once()
    assert result.events[0].images == ["generated_poster.png"]
    assert result.events[0].poster_generated


def _llm_response(content: str) -> Mock:
    response = Mock()
    response.choices = [Mock(message=Mock(content=content))]
    return response


@pytest.mark.asyncio
async def test_run_extraction_graph_all_past_events_skips_image_generation(
    mock_llm_client,
    mock_image_handler,
):
    """Если все события прошедшие, шаг генерации афиш не запускается."""
    agent = EventExtractionGraph(
        llm_client=mock_llm_client,
        image_handler=mock_image_handler,
    )
    past_date = (datetime.now() - timedelta(days=2)).replace(microsecond=0).isoformat()

    mock_llm_client.chat.completions.create.side_effect = [
        _llm_response('["Событие из прошлого"]'),
        _llm_response(
            f'{{"title":"Событие из прошлого","schedule":{{"type":"exact","date_start":"{past_date}"}},"categories":[],"interests":[]}}'
        ),
    ]

    result_events = await agent.run_extraction_graph(
        text="Анонс прошедшего события",
        message_date=datetime.now(),
        images=[],
        hashtags=[],
        channel="test",
        post_id=1,
    )

    meta = agent.get_last_run_meta()
    assert result_events == []
    assert meta["skip_reason"] == "all_events_in_past"
    assert meta["filtered_past_events_count"] == 1
    mock_image_handler.generate_event_poster.assert_not_called()


@pytest.mark.asyncio
async def test_run_extraction_graph_mixed_events_generates_only_for_upcoming(
    mock_llm_client,
    mock_image_handler,
):
    """В смешанном посте прошедшие события отбрасываются до генерации афиш."""
    agent = EventExtractionGraph(
        llm_client=mock_llm_client,
        image_handler=mock_image_handler,
    )
    past_date = (datetime.now() - timedelta(days=2)).replace(microsecond=0).isoformat()
    future_date = (datetime.now() + timedelta(days=2)).replace(microsecond=0).isoformat()

    mock_llm_client.chat.completions.create.side_effect = [
        _llm_response('["Прошедшее событие", "Будущее событие"]'),
        _llm_response(
            f'{{"title":"Прошедшее событие","schedule":{{"type":"exact","date_start":"{past_date}"}},"categories":[],"interests":[]}}'
        ),
        _llm_response(
            f'{{"title":"Будущее событие","schedule":{{"type":"exact","date_start":"{future_date}"}},"categories":[],"interests":[]}}'
        ),
    ]

    result_events = await agent.run_extraction_graph(
        text="Два события",
        message_date=datetime.now(),
        images=[],
        hashtags=[],
        channel="test",
        post_id=2,
    )

    meta = agent.get_last_run_meta()
    assert len(result_events) == 1
    assert result_events[0].title == "Будущее событие"
    assert meta["filtered_past_events_count"] == 1
    assert meta["skip_reason"] is None
    mock_image_handler.generate_event_poster.assert_called_once()
