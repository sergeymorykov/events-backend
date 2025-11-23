"""
Скрипт для запуска AI процессора.
Обрабатывает необработанные посты из MongoDB.
"""

import asyncio
import logging
import sys
from pathlib import Path

from telethon import TelegramClient

# Добавляем корневую директорию в путь для импорта
sys.path.insert(0, str(Path(__file__).parent))

from ai_processor import AIProcessor
from ai_processor.config import AIConfig


# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('ai_processor.log', encoding='utf-8')
    ]
)

logger = logging.getLogger(__name__)


async def main():
    """Основная функция запуска AI процессора."""
    
    logger.info("=" * 80)
    logger.info("ЗАПУСК AI ПРОЦЕССОРА")
    logger.info("=" * 80)
    
    # Вывод конфигурации
    AIConfig.print_config()
    
    # Валидация конфигурации
    is_valid, message = AIConfig.validate()
    if not is_valid:
        logger.error(f"Ошибка конфигурации: {message}")
        return
    
    if message:  # Предупреждения
        logger.warning(message)
    
    # Инициализация Telegram клиента (для скачивания фото)
    telegram_client = None
    
    if AIConfig.TG_API_ID and AIConfig.TG_API_HASH:
        try:
            logger.info("Инициализация Telegram клиента...")
            telegram_client = TelegramClient(
                AIConfig.TG_SESSION_NAME,
                int(AIConfig.TG_API_ID),
                AIConfig.TG_API_HASH
            )
            await telegram_client.start()
            
            if await telegram_client.is_user_authorized():
                me = await telegram_client.get_me()
                logger.info(f"Telegram клиент авторизован: {me.first_name} (@{me.username})")
            else:
                logger.warning("Telegram клиент не авторизован")
                await telegram_client.disconnect()
                telegram_client = None
                
        except Exception as e:
            logger.error(f"Ошибка инициализации Telegram клиента: {e}")
            telegram_client = None
    
    # Инициализация AI процессора
    processor = None
    
    try:
        # Получение API ключей
        api_keys = AIConfig.get_api_keys()
        image_api_keys = AIConfig.get_image_api_keys()
        
        processor = AIProcessor(
            llm_base_url=AIConfig.LLM_BASE_URL,
            llm_api_keys=api_keys,
            llm_model_name=AIConfig.LLM_MODEL_NAME,
            llm_vision_model=AIConfig.LLM_VISION_MODEL,
            llm_temperature=AIConfig.LLM_TEMPERATURE,
            llm_max_tokens=AIConfig.LLM_MAX_TOKENS,
            kandinsky_api_key=AIConfig.KANDINSKY_API_KEY,
            kandinsky_secret_key=AIConfig.KANDINSKY_SECRET_KEY,
            image_llm_base_url=AIConfig.IMAGE_LLM_BASE_URL or AIConfig.LLM_BASE_URL,
            image_llm_api_keys=image_api_keys if image_api_keys else None,
            image_llm_model=AIConfig.IMAGE_LLM_MODEL,
            mongodb_uri=AIConfig.MONGODB_URI,
            mongodb_db_name=AIConfig.MONGODB_DB_NAME,
            images_dir=AIConfig.IMAGES_DIR,
            telegram_client=telegram_client
        )
        
        # Обработка всех необработанных постов
        # Можно ограничить количество через limit=N
        stats = await processor.process_all_unprocessed_posts(limit=None)
        
        logger.info("=" * 80)
        logger.info("AI ПРОЦЕССОР ЗАВЕРШИЛ РАБОТУ")
        logger.info(f"Обработано постов: {stats['success']}/{stats['total']}")
        logger.info("=" * 80)
        
    except KeyboardInterrupt:
        logger.info("\nПрервано пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
    finally:
        # Закрытие соединений
        if processor:
            processor.close()
        
        if telegram_client:
            try:
                await telegram_client.disconnect()
                logger.info("Telegram клиент отключен")
            except Exception as e:
                logger.error(f"Ошибка отключения Telegram: {e}")


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\nПрограмма остановлена")

