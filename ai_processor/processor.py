"""
Основной модуль AI процессора для обработки постов.
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List
from pathlib import Path

from telethon import TelegramClient

from .models import RawPost, ProcessedEvent, PriceInfo
from .image_handler import ImageHandler
from .llm_handler import LLMHandler
from .db_handler import DatabaseHandler

logger = logging.getLogger(__name__)


class AIProcessor:
    """Процессор для обработки сырых постов через AI."""
    
    def __init__(
        self,
        # Параметры LLM
        llm_base_url: str,
        llm_api_keys: List[str],
        llm_model_name: str = "gpt-4o",
        llm_vision_model: Optional[str] = None,
        llm_temperature: float = 0.7,
        llm_max_tokens: int = 2000,
        
        # Параметры Kandinsky
        kandinsky_api_key: Optional[str] = None,
        kandinsky_secret_key: Optional[str] = None,
        
        # Параметры LLM Image Generation
        image_llm_base_url: Optional[str] = None,
        image_llm_api_keys: Optional[List[str]] = None,
        image_llm_model: Optional[str] = None,
        
        # Параметры MongoDB
        mongodb_uri: str = "mongodb://localhost:27017/",
        mongodb_db_name: str = "events_db",
        
        # Параметры изображений
        images_dir: str = "images",
        
        # Telegram клиент (опционально)
        telegram_client: Optional[TelegramClient] = None
    ):
        """
        Инициализация AI процессора.
        
        Args:
            llm_base_url: Базовый URL LLM API (ZenMux, OpenAI и др.)
            llm_api_keys: Список API ключей для ротации
            llm_model_name: Название модели
            llm_vision_model: Модель для vision (опционально)
            llm_temperature: Температура генерации
            llm_max_tokens: Максимум токенов
            kandinsky_api_key: API ключ Kandinsky
            kandinsky_secret_key: Secret ключ Kandinsky
            image_llm_base_url: Base URL для LLM image generation
            image_llm_api_keys: Список API ключей для генерации изображений
            image_llm_model: Модель для генерации изображений
            mongodb_uri: URI подключения к MongoDB
            mongodb_db_name: Имя БД
            images_dir: Папка для сохранения изображений
            telegram_client: Telegram клиент для скачивания фото
        """
        # Инициализация компонентов
        self.image_handler = ImageHandler(
            images_dir=images_dir,
            kandinsky_api_key=kandinsky_api_key,
            kandinsky_secret_key=kandinsky_secret_key,
            telegram_client=telegram_client,
            image_llm_base_url=image_llm_base_url,
            image_llm_api_keys=image_llm_api_keys,
            image_llm_model=image_llm_model
        )
        
        self.llm_handler = LLMHandler(
            base_url=llm_base_url,
            api_keys=llm_api_keys,
            model_name=llm_model_name,
            vision_model=llm_vision_model,
            temperature=llm_temperature,
            max_tokens=llm_max_tokens
        )
        
        self.db_handler = DatabaseHandler(
            mongodb_uri=mongodb_uri,
            db_name=mongodb_db_name
        )
        
        # Подключение к БД
        self.db_handler.connect()
        
        logger.info("AI процессор инициализирован")
    
    async def process_raw_post(self, raw_post: Dict[str, Any]) -> Optional[ProcessedEvent]:
        """
        Обработка одного сырого поста.
        
        Args:
            raw_post: Словарь с данными сырого поста из MongoDB
            
        Returns:
            Объект ProcessedEvent или None при ошибке
        """
        try:
            # Валидация входных данных
            post = RawPost(**raw_post)
            post_id = post.post_id or 0
            
            logger.info(f"=" * 60)
            logger.info(f"Обработка поста ID: {post_id}")
            logger.info(f"Текст: {post.text[:100]}...")
            
            # Шаг 1: Обработка изображения
            image_path = None
            image_base64 = None
            
            if post.photo_url:
                # Скачивание существующего изображения
                logger.info("Скачивание изображения из поста...")
                
                # photo_url может быть словарем с информацией о фото
                if isinstance(post.photo_url, dict):
                    image_path = await self.image_handler.download_telegram_photo(
                        post.photo_url,
                        post_id
                    )
                elif isinstance(post.photo_url, str):
                    image_path = await self.image_handler.download_image_from_url(post.photo_url)
            
            if not image_path:
                # Генерация изображения (автоматический выбор метода)
                logger.info("Генерация изображения...")
                
                # Используем текст поста как промпт (ограничиваем длину)
                prompt = post.text[:500] if len(post.text) > 500 else post.text
                image_path = await self.image_handler.generate_image(prompt)
                
                if not image_path:
                    logger.warning("Не удалось сгенерировать изображение")
            
            # Шаг 2: Генерация описания изображения (если изображение есть и было в photo_url)
            image_caption = None
            
            if image_path and post.photo_url:
                logger.info("Генерация описания изображения...")
                image_base64 = self.image_handler.image_to_base64(image_path)
                
                if image_base64:
                    image_caption = await self.llm_handler.generate_image_caption(image_base64)
                    
                    if image_caption:
                        logger.info(f"Описание изображения: {image_caption[:100]}...")
                    else:
                        logger.warning("Не удалось сгенерировать описание изображения")
            
            # Шаг 3: Получение существующих категорий и интересов из БД
            existing_categories = self.db_handler.get_all_categories()
            existing_interests = self.db_handler.get_all_interests()
            
            logger.info(f"Существующих категорий: {len(existing_categories)}")
            logger.info(f"Существующих интересов: {len(existing_interests)}")
            
            # Шаг 4: Генерация структурированных данных через LLM
            logger.info("Генерация данных события через LLM...")
            
            llm_response = await self.llm_handler.generate_event_data(
                post_text=post.text,
                image_caption=image_caption,
                hashtags=post.hashtags,
                existing_categories=existing_categories,
                existing_interests=existing_interests,
                image_base64=image_base64 if image_path and not post.photo_url else None
            )
            
            if not llm_response:
                logger.error("Не удалось получить данные от LLM")
                # Возвращаем частичный результат
                llm_response = type('obj', (object,), {
                    'title': None,
                    'description': None,
                    'date': None,
                    'price': None,
                    'categories': [],
                    'user_interests': []
                })()
            
            # Шаг 5: Формирование результата
            processed_event = ProcessedEvent(
                title=llm_response.title,
                description=llm_response.description,
                date=llm_response.date,
                price=llm_response.price,
                categories=llm_response.categories,
                user_interests=llm_response.user_interests,
                image_url=image_path,
                image_caption=image_caption,
                source_post_url=post.post_url,
                raw_post_id=post_id
            )
            
            logger.info(f"✅ Пост обработан успешно:")
            logger.info(f"  Название: {processed_event.title}")
            logger.info(f"  Дата: {processed_event.date}")
            logger.info(f"  Категории: {processed_event.categories}")
            logger.info(f"  Интересы: {processed_event.user_interests}")
            
            # Шаг 6: Сохранение в БД
            success = self.db_handler.save_processed_event(processed_event)
            
            if not success:
                logger.warning("Не удалось сохранить событие в БД")
            
            return processed_event
            
        except Exception as e:
            logger.error(f"Ошибка обработки поста: {e}", exc_info=True)
            
            # Возвращаем частичный результат с доступными полями
            try:
                partial_event = ProcessedEvent(
                    title=None,
                    description=raw_post.get('text', '')[:200] if 'text' in raw_post else None,
                    source_post_url=raw_post.get('post_url'),
                    raw_post_id=raw_post.get('post_id')
                )
                return partial_event
            except:
                return None
    
    async def process_all_unprocessed_posts(self, limit: Optional[int] = None) -> Dict[str, int]:
        """
        Обработка всех необработанных постов из БД.
        
        Args:
            limit: Максимальное количество постов для обработки
            
        Returns:
            Статистика обработки
        """
        logger.info("=" * 60)
        logger.info("НАЧАЛО ОБРАБОТКИ ПОСТОВ")
        logger.info("=" * 60)
        
        # Получение необработанных постов
        raw_posts = self.db_handler.get_unprocessed_raw_posts(limit=limit)
        
        total = len(raw_posts)
        logger.info(f"Найдено необработанных постов: {total}")
        
        if total == 0:
            logger.info("Нет постов для обработки")
            return {'total': 0, 'success': 0, 'errors': 0}
        
        stats = {
            'total': total,
            'success': 0,
            'errors': 0
        }
        
        # Обработка каждого поста
        for idx, raw_post in enumerate(raw_posts, 1):
            logger.info(f"\n--- Пост {idx}/{total} ---")
            
            try:
                result = await self.process_raw_post(raw_post)
                
                if result:
                    stats['success'] += 1
                else:
                    stats['errors'] += 1
                    
            except Exception as e:
                logger.error(f"Критическая ошибка при обработке поста: {e}")
                stats['errors'] += 1
            
            # Небольшая пауза между запросами
            await asyncio.sleep(1)
        
        # Итоговая статистика
        logger.info("=" * 60)
        logger.info("ИТОГИ ОБРАБОТКИ:")
        logger.info(f"  Всего постов: {stats['total']}")
        logger.info(f"  Успешно обработано: {stats['success']}")
        logger.info(f"  Ошибок: {stats['errors']}")
        logger.info("=" * 60)
        
        # Статистика БД
        db_stats = self.db_handler.get_statistics()
        logger.info("\nСТАТИСТИКА БД:")
        logger.info(f"  Сырых постов: {db_stats.get('raw_posts_count', 0)}")
        logger.info(f"  Обработанных событий: {db_stats.get('processed_events_count', 0)}")
        logger.info(f"  Уникальных категорий: {db_stats.get('categories_count', 0)}")
        logger.info(f"  Уникальных интересов: {db_stats.get('interests_count', 0)}")
        
        if db_stats.get('top_categories'):
            logger.info("\n  Топ категорий:")
            for cat in db_stats['top_categories'][:5]:
                logger.info(f"    - {cat['name']}: {cat['usage_count']}")
        
        if db_stats.get('top_interests'):
            logger.info("\n  Топ интересов:")
            for interest in db_stats['top_interests'][:5]:
                logger.info(f"    - {interest['name']}: {interest['usage_count']}")
        
        return stats
    
    def close(self):
        """Закрытие соединений."""
        self.db_handler.disconnect()
        logger.info("AI процессор остановлен")

