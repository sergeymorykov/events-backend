"""
Точка входа в логику Telegram Parser.
НЕ управляет event loop.
"""

import logging
import sys

from .config import Config
from .parser import TelegramParser
from src.common.logging_utils import get_log_path

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(get_log_path('telegram_parser.log'), encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


async def main():
    """Однократный запуск парсера."""
    # Валидация конфигурации
    is_valid, error_message = Config.validate()
    if not is_valid:
        logger.error(f"Ошибка конфигурации: {error_message}")
        logger.error("Проверьте файл .env и убедитесь, что все переменные заполнены")
        return 1  # ← ❗ ВАЖНО

    parser = TelegramParser(Config)
    await parser.run()

    return 0

