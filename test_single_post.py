"""
Тестовый скрипт для обработки одного поста.
Полезен для отладки и тестирования AI процессора.
"""

import asyncio
import logging
import sys
from pathlib import Path

from telethon import TelegramClient

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent))

from ai_processor import AIProcessor
from ai_processor.config import AIConfig


# Настройка логирования
logging.basicConfig(
    level=logging.DEBUG,  # Подробные логи для отладки
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


async def test_single_post():
    """Тестирование обработки одного поста."""
    
    logger.info("=" * 80)
    logger.info("ТЕСТИРОВАНИЕ AI ПРОЦЕССОРА (ОДИН ПОСТ)")
    logger.info("=" * 80)
    
    # Валидация конфигурации
    is_valid, message = AIConfig.validate()
    if not is_valid:
        logger.error(f"Ошибка конфигурации: {message}")
        return
    
    if message:
        logger.warning(message)
    
    # Инициализация Telegram клиента (опционально)
    telegram_client = None
    
    if AIConfig.TG_API_ID and AIConfig.TG_API_HASH:
        try:
            telegram_client = TelegramClient(
                AIConfig.TG_SESSION_NAME,
                int(AIConfig.TG_API_ID),
                AIConfig.TG_API_HASH
            )
            await telegram_client.start()
            logger.info("Telegram клиент инициализирован")
        except Exception as e:
            logger.warning(f"Telegram клиент недоступен: {e}")
    
    # Инициализация процессора
    processor = None
    
    try:
        api_keys = AIConfig.get_api_keys()
        
        processor = AIProcessor(
            llm_base_url=AIConfig.LLM_BASE_URL,
            llm_api_keys=api_keys,
            llm_model_name=AIConfig.LLM_MODEL_NAME,
            llm_vision_model=AIConfig.LLM_VISION_MODEL,
            llm_temperature=AIConfig.LLM_TEMPERATURE,
            llm_max_tokens=AIConfig.LLM_MAX_TOKENS,
            kandinsky_api_key=AIConfig.KANDINSKY_API_KEY,
            kandinsky_secret_key=AIConfig.KANDINSKY_SECRET_KEY,
            mongodb_uri=AIConfig.MONGODB_URI,
            mongodb_db_name=AIConfig.MONGODB_DB_NAME,
            images_dir=AIConfig.IMAGES_DIR,
            telegram_client=telegram_client
        )
        
        # Получаем один необработанный пост
        raw_posts = processor.db_handler.get_unprocessed_raw_posts(limit=1)
        
        if not raw_posts:
            logger.warning("Нет необработанных постов в БД")
            logger.info("\nПопробуйте сначала запустить парсер:")
            logger.info("  python run_parser.py")
            return
        
        raw_post = raw_posts[0]
        post_id = raw_post.get('post_id', 'unknown')
        
        logger.info(f"\nНайден пост для обработки:")
        logger.info(f"  ID: {post_id}")
        logger.info(f"  Текст: {raw_post.get('text', '')[:100]}...")
        logger.info(f"  Хештеги: {raw_post.get('hashtags', [])}")
        logger.info(f"  Фото: {'Да' if raw_post.get('photo_url') else 'Нет'}")
        
        # Обработка поста
        logger.info("\n" + "=" * 80)
        logger.info("НАЧАЛО ОБРАБОТКИ")
        logger.info("=" * 80 + "\n")
        
        result = await processor.process_raw_post(raw_post)
        
        if result:
            logger.info("\n" + "=" * 80)
            logger.info("✅ УСПЕШНО ОБРАБОТАНО")
            logger.info("=" * 80)
            logger.info(f"\nРезультат:")
            logger.info(f"  Название: {result.title}")
            logger.info(f"  Описание: {result.description}")
            logger.info(f"  Дата: {result.date}")
            logger.info(f"  Цена: {result.price}")
            logger.info(f"  Категории: {result.categories}")
            logger.info(f"  Интересы: {result.user_interests}")
            logger.info(f"  Изображение: {result.image_url}")
            logger.info(f"  Описание изображения: {result.image_caption}")
            logger.info(f"  Источник: {result.source_post_url}")
        else:
            logger.error("\n❌ ОШИБКА ОБРАБОТКИ")
        
    except KeyboardInterrupt:
        logger.info("\nПрервано пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
    finally:
        if processor:
            processor.close()
        
        if telegram_client:
            await telegram_client.disconnect()


async def test_with_mock_data():
    """Тестирование с тестовыми данными (если нет реальных постов)."""
    
    logger.info("=" * 80)
    logger.info("ТЕСТИРОВАНИЕ С MOCK ДАННЫМИ")
    logger.info("=" * 80)
    
    # Валидация конфигурации
    is_valid, message = AIConfig.validate()
    if not is_valid:
        logger.error(f"Ошибка конфигурации: {message}")
        return
    
    api_keys = AIConfig.get_api_keys()
    
    processor = AIProcessor(
        llm_base_url=AIConfig.LLM_BASE_URL,
        llm_api_keys=api_keys,
        llm_model_name=AIConfig.LLM_MODEL_NAME,
        llm_vision_model=AIConfig.LLM_VISION_MODEL,
        llm_temperature=AIConfig.LLM_TEMPERATURE,
        llm_max_tokens=AIConfig.LLM_MAX_TOKENS,
        kandinsky_api_key=AIConfig.KANDINSKY_API_KEY,
        kandinsky_secret_key=AIConfig.KANDINSKY_SECRET_KEY,
        mongodb_uri=AIConfig.MONGODB_URI,
        mongodb_db_name=AIConfig.MONGODB_DB_NAME,
        images_dir=AIConfig.IMAGES_DIR
    )
    
    # Тестовый пост
    mock_post = {
        'post_id': 999999,
        'text': '''
🎵 Концерт группы "Звёзды джаза"

📅 25 ноября 2025, 19:00
📍 Концертный зал "Октябрь"
💰 Билеты от 1500₽

Вечер живой музыки с лучшими джазовыми композициями.
Бронирование: +7 (999) 123-45-67

#концерт #джаз #живаямузыка #событие
        '''.strip(),
        'photo_url': None,
        'post_url': 'https://t.me/test/999999',
        'hashtags': ['концерт', 'джаз', 'живаямузыка', 'событие']
    }
    
    logger.info("Обработка тестового поста...")
    
    try:
        result = await processor.process_raw_post(mock_post)
        
        if result:
            logger.info("\n✅ Успешно обработано:")
            logger.info(f"  Название: {result.title}")
            logger.info(f"  Дата: {result.date}")
            logger.info(f"  Цена: {result.price}")
            logger.info(f"  Категории: {result.categories}")
            logger.info(f"  Интересы: {result.user_interests}")
        else:
            logger.error("❌ Ошибка обработки")
    finally:
        processor.close()


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Тестирование AI процессора')
    parser.add_argument(
        '--mock',
        action='store_true',
        help='Использовать тестовые данные вместо реальных постов из БД'
    )
    
    args = parser.parse_args()
    
    try:
        if args.mock:
            asyncio.run(test_with_mock_data())
        else:
            asyncio.run(test_single_post())
    except KeyboardInterrupt:
        logger.info("\nПрограмма остановлена")

