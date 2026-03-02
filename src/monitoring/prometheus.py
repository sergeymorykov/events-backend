"""
Prometheus метрики для мониторинга системы обработки событий.
"""

import logging
from typing import Optional

from prometheus_client import Counter, Histogram, Gauge, Summary

logger = logging.getLogger(__name__)


class TelegramParserMetrics:
    """Метрики для Telegram парсера."""
    
    def __init__(self):
        """Инициализация метрик парсера."""
        # Счётчик обработанных постов
        self.posts_processed = Counter(
            'telegram_parser_posts_processed_total',
            'Общее количество обработанных постов парсером',
            ['channel', 'status']  # status: saved, filtered, duplicate
        )
        
        # Счётчик скачанных изображений
        self.images_downloaded = Counter(
            'telegram_parser_images_downloaded_total',
            'Количество скачанных изображений',
            ['channel']
        )
        
        # Продолжительность парсинга канала
        self.parsing_duration = Histogram(
            'telegram_parser_duration_seconds',
            'Время парсинга канала в секундах',
            ['channel'],
            buckets=[10, 30, 60, 120, 300, 600]
        )
        
        # Ошибки парсинга
        self.errors = Counter(
            'telegram_parser_errors_total',
            'Ошибки при парсинге',
            ['channel', 'error_type']  # error_type: flood_wait, channel_private, other
        )
    
    def record_post(self, channel: str, status: str):
        """
        Запись обработанного поста.
        
        Args:
            channel: Название канала
            status: Статус (saved, filtered, duplicate)
        """
        self.posts_processed.labels(channel=channel, status=status).inc()
    
    def record_image(self, channel: str):
        """Запись скачанного изображения."""
        self.images_downloaded.labels(channel=channel).inc()
    
    def record_error(self, channel: str, error_type: str):
        """Запись ошибки парсинга."""
        self.errors.labels(channel=channel, error_type=error_type).inc()


class EventExtractionMetrics:
    """Метрики для event extraction модуля."""
    
    def __init__(self):
        """Инициализация метрик extraction."""
        # Счётчик созданных событий
        self.events_created = Counter(
            'event_extraction_events_created_total',
            'Количество созданных событий'
        )
        
        # Счётчик дубликатов
        self.duplicates_found = Counter(
            'event_extraction_duplicates_found_total',
            'Количество найденных дубликатов событий'
        )
        
        # Счётчик сгенерированных афиш
        self.posters_generated = Counter(
            'event_extraction_posters_generated_total',
            'Количество сгенерированных афиш'
        )
        
        # Ошибки с детализацией по типам
        self.errors = Counter(
            'event_extraction_errors_total',
            'Ошибки при извлечении событий',
            ['type']  # type: quota, llm, dedup, processing
        )
        
        # Продолжительность обработки поста
        self.processing_duration = Histogram(
            'event_extraction_duration_seconds',
            'Время обработки одного поста в секундах',
            buckets=[1, 2, 5, 10, 20, 30, 60]
        )
        
        # Продолжительность генерации афиши
        self.poster_generation_duration = Histogram(
            'event_extraction_poster_generation_seconds',
            'Время генерации афиши в секундах',
            buckets=[1, 5, 10, 15, 30]
        )
        
        # Gauge для новых необработанных постов
        self.new_posts_pending = Gauge(
            'event_extraction_new_posts_pending',
            'Количество необработанных постов'
        )
        
        # Summary для LangGraph шагов
        self.langgraph_step_duration = Summary(
            'event_extraction_langgraph_step_seconds',
            'Время выполнения шагов LangGraph',
            ['step']  # step: split, extract, images
        )
    
    def record_event_created(self):
        """Запись созданного события."""
        self.events_created.inc()
    
    def record_duplicate_found(self):
        """Запись найденного дубликата."""
        self.duplicates_found.inc()
    
    def record_poster_generated(self):
        """Запись сгенерированной афиши."""
        self.posters_generated.inc()
    
    def record_error(self, error_type: str):
        """
        Запись ошибки.
        
        Args:
            error_type: Тип ошибки (quota, llm, dedup, processing)
        """
        self.errors.labels(type=error_type).inc()
        
        # Если ошибка quota - логируем критическое сообщение
        if error_type == "quota":
            logger.critical(
                "❌ КРИТИЧЕСКАЯ ОШИБКА: API quota exceeded. "
                "Необходимо пополнить баланс API!"
            )
    
    def set_pending_posts(self, count: int):
        """
        Установка количества необработанных постов.
        
        Args:
            count: Количество постов
        """
        self.new_posts_pending.set(count)


# Глобальные экземпляры метрик
_event_metrics: Optional[EventExtractionMetrics] = None
_parser_metrics: Optional[TelegramParserMetrics] = None


def get_event_metrics() -> EventExtractionMetrics:
    """
    Получение глобального экземпляра метрик event extraction.
    
    Returns:
        EventExtractionMetrics instance
    """
    global _event_metrics
    if _event_metrics is None:
        _event_metrics = EventExtractionMetrics()
    return _event_metrics


def get_parser_metrics() -> TelegramParserMetrics:
    """
    Получение глобального экземпляра метрик telegram parser.
    
    Returns:
        TelegramParserMetrics instance
    """
    global _parser_metrics
    if _parser_metrics is None:
        _parser_metrics = TelegramParserMetrics()
    return _parser_metrics
