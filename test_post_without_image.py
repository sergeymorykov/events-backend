"""
Тестовый скрипт для обработки поста без изображения.
Проверяет работу AI процессора, когда в посте нет фото.
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
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


async def test_post_without_image():
    """Тестирование обработки поста без изображения."""
    
    logger.info("=" * 80)
    logger.info("ТЕСТИРОВАНИЕ AI ПРОЦЕССОРА (ПОСТ БЕЗ ИЗОБРАЖЕНИЯ)")
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
        
        # Проверка настроек генерации изображений
        logger.info("\nПроверка настроек генерации изображений:")
        logger.info(f"  Kandinsky API Key: {'✅ Установлен' if AIConfig.KANDINSKY_API_KEY else '❌ Не установлен'}")
        logger.info(f"  Kandinsky Secret Key: {'✅ Установлен' if AIConfig.KANDINSKY_SECRET_KEY else '❌ Не установлен'}")
        logger.info(f"  LLM Image Base URL: {'✅ ' + AIConfig.IMAGE_LLM_BASE_URL if AIConfig.IMAGE_LLM_BASE_URL else '❌ Не установлен'}")
        logger.info(f"  LLM Image Model: {'✅ ' + AIConfig.IMAGE_LLM_MODEL if AIConfig.IMAGE_LLM_MODEL else '❌ Не установлен'}")
        image_api_keys = AIConfig.get_image_api_keys()
        logger.info(f"  LLM Image API Keys: {'✅ ' + str(len(image_api_keys)) + ' ключей' if image_api_keys else '❌ Не установлены'}")
        
        if not AIConfig.KANDINSKY_API_KEY and not AIConfig.IMAGE_LLM_BASE_URL:
            logger.warning("\n⚠️  ВНИМАНИЕ: Генерация изображений не настроена!")
            logger.warning("   Для генерации изображений необходимо установить:")
            logger.warning("   - KANDINSKY_API_KEY и KANDINSKY_SECRET_KEY (для Kandinsky)")
            logger.warning("   - или IMAGE_LLM_BASE_URL, IMAGE_LLM_MODEL и IMAGE_LLM_API_KEYS (для LLM генерации)")
            logger.warning("   Пост будет обработан без изображения.\n")
        
        processor = AIProcessor(
            llm_base_url=AIConfig.LLM_BASE_URL,
            llm_api_keys=api_keys,
            llm_model_name=AIConfig.LLM_MODEL_NAME,
            llm_vision_model=AIConfig.LLM_VISION_MODEL,
            llm_temperature=AIConfig.LLM_TEMPERATURE,
            llm_max_tokens=AIConfig.LLM_MAX_TOKENS,
            kandinsky_api_key=AIConfig.KANDINSKY_API_KEY,
            kandinsky_secret_key=AIConfig.KANDINSKY_SECRET_KEY,
            image_llm_base_url=AIConfig.IMAGE_LLM_BASE_URL,
            image_llm_api_keys=image_api_keys,
            image_llm_model=AIConfig.IMAGE_LLM_MODEL,
            mongodb_uri=AIConfig.MONGODB_URI,
            mongodb_db_name=AIConfig.MONGODB_DB_NAME,
            images_dir=AIConfig.IMAGES_DIR,
            telegram_client=telegram_client
        )
        
        # Создаём тестовый пост БЕЗ изображения
        mock_post = {
            'post_id': 999998,
            'text': '''
🎭 Театральная постановка "Гамлет"

📅 15 января 2026, 19:30
📍 Театр драмы и комедии им. Карима Тинчурина
💰 Билеты от 800₽

Классическая постановка шекспировской трагедии в современной интерпретации.
Режиссёр: Иван Петров
В главной роли: Сергей Иванов

Бронирование билетов: +7 (843) 123-45-67
Официальный сайт: teatr-kazan.ru

#театр #драма #культура #событие #казань
            '''.strip(),
            'photo_urls': None,  # Нет изображений
            'photo_url': None,   # Старое поле тоже None
            'hashtags': ['театр', 'драма', 'культура', 'событие', 'казань'],
            'channel': 'test_channel',
            'date_parsed': None,
            'message_date': None,
            'parsed_at': None
        }
        
        logger.info("\nТестовый пост для обработки:")
        logger.info(f"  ID: {mock_post['post_id']}")
        logger.info(f"  Текст: {mock_post['text'][:100]}...")
        logger.info(f"  Хештеги: {mock_post['hashtags']}")
        logger.info(f"  Фото: Нет (photo_urls=None, photo_url=None)")
        
        # Обработка поста
        logger.info("\n" + "=" * 80)
        logger.info("НАЧАЛО ОБРАБОТКИ")
        logger.info("=" * 80 + "\n")
        
        result = await processor.process_raw_post(mock_post)
        
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
            logger.info(f"  Изображения (список): {result.image_urls}")
            logger.info(f"  Описание изображения: {result.image_caption}")
            logger.info(f"  Источник: {result.source_post_url}")
            
            # Проверка результата
            logger.info("\n" + "=" * 80)
            logger.info("АНАЛИЗ РЕЗУЛЬТАТА")
            logger.info("=" * 80)
            
            if result.image_url or result.image_urls:
                logger.info("✅ Изображение было сгенерировано или найдено")
            else:
                logger.info("ℹ️  Изображение отсутствует (ожидаемо для поста без фото)")
            
            if result.image_caption:
                logger.info("✅ Описание изображения сгенерировано")
            else:
                logger.info("ℹ️  Описание изображения отсутствует (ожидаемо, т.к. нет изображения)")
            
            if result.title and result.description:
                logger.info("✅ Основная информация извлечена успешно")
            else:
                logger.warning("⚠️  Не вся информация извлечена")
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


if __name__ == '__main__':
    try:
        asyncio.run(test_post_without_image())
    except KeyboardInterrupt:
        logger.info("\nПрограмма остановлена")

