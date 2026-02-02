"""
Скрипт для запуска обработки постов через новый Event Extraction модуль.
"""

import asyncio
import logging
import sys
from motor.motor_asyncio import AsyncIOMotorClient
from qdrant_client import QdrantClient
from openai import AsyncOpenAI

from src.event_extraction import (
    PostProcessor,
    EventExtractionConfig,
    ImageHandler
)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('event_extraction.log')
    ]
)

logger = logging.getLogger(__name__)


async def main():
    """Главная функция для запуска обработки постов."""
    try:
        # Валидация конфигурации
        logger.info("Проверка конфигурации...")
        valid, message = EventExtractionConfig.validate()
        
        if not valid:
            logger.error(f"❌ Ошибка конфигурации: {message}")
            return
        
        if message:
            logger.warning(f"⚠️  Предупреждения конфигурации:\n{message}")
        
        # Вывод конфигурации
        EventExtractionConfig.print_config()
        
        # Инициализация клиентов
        logger.info("Инициализация клиентов...")
        
        db_client = AsyncIOMotorClient(EventExtractionConfig.MONGODB_URI)
        
        qdrant_client = QdrantClient(
            host=EventExtractionConfig.QDRANT_HOST,
            port=EventExtractionConfig.QDRANT_PORT,
            api_key=EventExtractionConfig.QDRANT_API_KEY or None
        )
        
        llm_client = AsyncOpenAI(
            base_url=EventExtractionConfig.LLM_BASE_URL,
            api_key=EventExtractionConfig.get_api_keys()[0]
        )
        
        image_handler = ImageHandler(
            images_dir=EventExtractionConfig.IMAGES_DIR,
            image_llm_base_url=EventExtractionConfig.IMAGE_LLM_BASE_URL,
            image_llm_api_keys=EventExtractionConfig.get_image_api_keys(),
            image_llm_model=EventExtractionConfig.IMAGE_LLM_MODEL
        )
        
        # Инициализация процессора
        logger.info("Инициализация PostProcessor...")
        processor = PostProcessor(
            db_client=db_client,
            qdrant_client=qdrant_client,
            llm_client=llm_client,
            image_handler=image_handler,
            db_name=EventExtractionConfig.MONGODB_DB_NAME,
            qdrant_collection=EventExtractionConfig.QDRANT_COLLECTION,
            llm_model=EventExtractionConfig.LLM_MODEL_NAME,
            similarity_threshold=EventExtractionConfig.QDRANT_SIMILARITY_THRESHOLD
        )
        
        # Обработка новых постов
        logger.info("Начало обработки новых постов...")
        
        # Можно указать лимит через аргумент командной строки
        limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
        
        stats = await processor.process_new_posts_batch(limit=limit)
        
        # Итоговая статистика
        print("\n" + "=" * 60)
        print("ИТОГОВАЯ СТАТИСТИКА")
        print("=" * 60)
        print(f"Всего постов обработано: {stats['total']}")
        print(f"Успешно: {stats['success']}")
        print(f"Ошибок: {stats['errors']}")
        print(f"Событий извлечено: {stats['events_extracted']}")
        print("=" * 60)
        
        logger.info("✅ Обработка завершена успешно")
    
    except KeyboardInterrupt:
        logger.info("⚠️  Обработка прервана пользователем")
    
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    print("""
╔════════════════════════════════════════════════════════════╗
║   Event Extraction - Обработка Telegram постов             ║
║   Версия: 1.0.0                                            ║
╚════════════════════════════════════════════════════════════╝
    """)
    
    asyncio.run(main())
