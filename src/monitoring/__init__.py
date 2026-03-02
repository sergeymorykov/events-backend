"""
Модуль мониторинга и метрик для Prometheus.
"""

from .prometheus import (
    EventExtractionMetrics,
    TelegramParserMetrics,
    get_event_metrics,
    get_parser_metrics
)

__all__ = [
    "EventExtractionMetrics",
    "TelegramParserMetrics",
    "get_event_metrics",
    "get_parser_metrics"
]
