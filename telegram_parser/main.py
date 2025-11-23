"""
Точка входа в приложение Telegram Parser.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Добавление родительской директории в путь для импорта
sys.path.insert(0, str(Path(__file__).parent.parent))

from telegram_parser.config import Config
from telegram_parser.parser import TelegramParser

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('telegram_parser.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


async def main():
    """Главная функция."""
    try:
        # Валидация конфигурации
        is_valid, error_message = Config.validate()
        if not is_valid:
            logger.error(f"Ошибка конфигурации: {error_message}")
            logger.error("Проверьте файл .env и убедитесь, что все переменные заполнены")
            sys.exit(1)
        
        # Создание и запуск парсера
        parser = TelegramParser(Config)
        await parser.run()
        
    except KeyboardInterrupt:
        logger.info("Парсер остановлен пользователем")
    except Exception as e:
        logger.critical(f"Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())

