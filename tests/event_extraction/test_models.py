"""
Тесты для Pydantic моделей.
"""

import pytest
from datetime import datetime

from src.event_extraction.models import (
    StructuredEvent,
    ScheduleExact,
    ScheduleRecurringWeekly,
    ScheduleFuzzy,
    PriceInfo,
    EventSource,
    ExtractionState
)


def test_schedule_exact():
    """Тест создания точного расписания."""
    schedule = ScheduleExact(
        date_start=datetime(2025, 12, 15, 19, 0),
        date_end=datetime(2025, 12, 15, 22, 0)
    )
    
    assert schedule.type.value == "exact"
    assert schedule.date_start.year == 2025
    assert schedule.timezone == "Europe/Moscow"


def test_schedule_recurring_weekly():
    """Тест создания повторяющегося расписания."""
    schedule = ScheduleRecurringWeekly(
        schedule={
            "monday": ["19:00", "21:00"],
            "friday": ["20:00"]
        }
    )
    
    assert schedule.type.value == "recurring_weekly"
    assert "monday" in schedule.schedule
    assert len(schedule.schedule["monday"]) == 2


def test_schedule_fuzzy():
    """Тест создания нечёткого расписания."""
    schedule = ScheduleFuzzy(
        description="Каждые выходные в декабре"
    )
    
    assert schedule.type.value == "fuzzy"
    assert "выходные" in schedule.description


def test_price_info():
    """Тест информации о цене."""
    # Платное событие
    price = PriceInfo(amount=500, currency="RUB", is_free=False)
    assert price.amount == 500
    assert not price.is_free
    
    # Бесплатное событие
    free_price = PriceInfo(is_free=True)
    assert free_price.is_free
    assert free_price.amount is None


def test_event_source():
    """Тест источника события."""
    source = EventSource(
        channel="kazankay",
        post_id=12345,
        post_url="https://t.me/kazankay/12345",
        message_date=datetime(2025, 12, 1, 10, 0)
    )
    
    assert source.channel == "kazankay"
    assert source.post_id == 12345


def test_structured_event():
    """Тест структурированного события."""
    schedule = ScheduleExact(date_start=datetime(2025, 12, 15, 19, 0))
    
    price = PriceInfo(amount=500, currency="RUB")
    
    source = EventSource(
        channel="kazankay",
        post_id=12345
    )
    
    event = StructuredEvent(
        title="Концерт в филармонии",
        description="Классическая музыка",
        schedule=schedule,
        location="Казанская филармония",
        price=price,
        categories=["концерт", "музыка"],
        user_interests=["классика"],
        sources=[source]
    )
    
    assert event.title == "Концерт в филармонии"
    assert event.categories == ["концерт", "музыка"]
    assert len(event.sources) == 1
    assert not event.poster_generated


def test_extraction_state():
    """Тест состояния LangGraph."""
    state = ExtractionState(
        raw_text="Концерт 15 декабря",
        channel="kazankay",
        post_id=12345
    )
    
    assert state.raw_text == "Концерт 15 декабря"
    assert len(state.events) == 0
    assert state.current_step == "init"


def test_categories_validation():
    """Тест валидации списка категорий."""
    event = StructuredEvent(
        title="Тест",
        categories=["  концерт  ", "", "музыка", "  "]
    )
    
    # Должны быть удалены пустые строки и обрезаны пробелы
    assert event.categories == ["концерт", "музыка"]
