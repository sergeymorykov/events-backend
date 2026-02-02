"""
Event Extraction модуль для извлечения событий из Telegram постов.

Основные компоненты:
- PostProcessor: главный оркестратор обработки
- EventExtractionGraph: LangGraph агент для извлечения
- EventDeduplicator: дедупликация через Qdrant
- ImageHandler: обработка и генерация изображений
"""

from .models import (
    RawPost,
    StructuredEvent,
    ScheduleExact,
    ScheduleRecurringWeekly,
    ScheduleFuzzy,
    PriceInfo,
    EventSource,
    ExtractionState,
    Category,
    UserInterest,
    ScheduleType
)

from .config import EventExtractionConfig

from .post_processor import (
    PostProcessor,
    PostProcessingError,
    EventDeduplicationError
)

from .langgraph_agent import EventExtractionGraph

from .deduplicator import EventDeduplicator

from .image_handler import ImageHandler

__all__ = [
    # Модели
    "RawPost",
    "StructuredEvent",
    "ScheduleExact",
    "ScheduleRecurringWeekly",
    "ScheduleFuzzy",
    "PriceInfo",
    "EventSource",
    "ExtractionState",
    "Category",
    "UserInterest",
    "ScheduleType",
    
    # Конфигурация
    "EventExtractionConfig",
    
    # Процессоры
    "PostProcessor",
    "EventExtractionGraph",
    "EventDeduplicator",
    "ImageHandler",
    
    # Исключения
    "PostProcessingError",
    "EventDeduplicationError",
]

__version__ = "1.0.0"
