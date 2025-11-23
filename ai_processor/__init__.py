"""
AI Processor - модуль для обработки постов через AI.

Основные компоненты:
- AIProcessor: основной класс для обработки постов
- ImageHandler: работа с изображениями
- LLMHandler: интеграция с LLM
- DatabaseHandler: работа с MongoDB
"""

from .processor import AIProcessor
from .models import ProcessedEvent, RawPost, LLMResponse, Category, UserInterest
from .image_handler import ImageHandler
from .llm_handler import LLMHandler
from .db_handler import DatabaseHandler

__version__ = "1.0.0"

__all__ = [
    "AIProcessor",
    "ProcessedEvent",
    "RawPost",
    "LLMResponse",
    "Category",
    "UserInterest",
    "ImageHandler",
    "LLMHandler",
    "DatabaseHandler"
]

