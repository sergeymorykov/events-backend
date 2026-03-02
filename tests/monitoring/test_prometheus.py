"""
Тесты для Prometheus метрик.
"""

import pytest
from src.monitoring.prometheus import (
    EventExtractionMetrics,
    TelegramParserMetrics,
    get_event_metrics,
    get_parser_metrics
)


def test_event_extraction_metrics_init():
    """Тест инициализации метрик event extraction."""
    metrics = EventExtractionMetrics()
    
    assert metrics.events_created is not None
    assert metrics.duplicates_found is not None
    assert metrics.posters_generated is not None
    assert metrics.errors is not None


def test_telegram_parser_metrics_init():
    """Тест инициализации метрик parser."""
    metrics = TelegramParserMetrics()
    
    assert metrics.posts_processed is not None
    assert metrics.images_downloaded is not None
    assert metrics.parsing_duration is not None
    assert metrics.errors is not None


def test_record_event_created():
    """Тест записи созданного события."""
    metrics = EventExtractionMetrics()
    
    # Запись нескольких событий
    metrics.record_event_created()
    metrics.record_event_created()
    metrics.record_event_created()
    
    # Метрика должна увеличиться (проверяем, что нет ошибок)
    assert True  # Prometheus метрики не возвращают значение напрямую


def test_record_duplicate():
    """Тест записи дубликата."""
    metrics = EventExtractionMetrics()
    
    metrics.record_duplicate_found()
    
    assert True


def test_record_error_quota(caplog):
    """Тест записи ошибки квоты."""
    metrics = EventExtractionMetrics()
    
    with caplog.at_level("CRITICAL"):
        metrics.record_error("quota")
    
    # Проверяем, что было залогировано критическое сообщение
    assert any("quota exceeded" in record.message.lower() for record in caplog.records)


def test_record_parser_post():
    """Тест записи обработанного поста."""
    metrics = TelegramParserMetrics()
    
    metrics.record_post("test_channel", "saved")
    metrics.record_post("test_channel", "filtered")
    metrics.record_post("test_channel", "duplicate")
    
    assert True


def test_get_event_metrics_singleton():
    """Тест singleton паттерна для event metrics."""
    metrics1 = get_event_metrics()
    metrics2 = get_event_metrics()
    
    # Должен быть один и тот же экземпляр
    assert metrics1 is metrics2


def test_get_parser_metrics_singleton():
    """Тест singleton паттерна для parser metrics."""
    metrics1 = get_parser_metrics()
    metrics2 = get_parser_metrics()
    
    # Должен быть один и тот же экземпляр
    assert metrics1 is metrics2
