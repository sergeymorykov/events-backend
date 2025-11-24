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
            post = RawPost(**raw_post)
            post_id = post.post_id or 0
            
            logger.info(f"=" * 60)
            logger.info(f"Обработка поста ID: {post_id}")
            logger.info(f"Текст: {post.text[:100]}...")

            # Получаем список картинок (новое поле)
            photo_urls = post.photo_urls or ([] if post.photo_urls is not None else ([post.photo_url] if post.photo_url else []))
            logger.info(f"Пути к изображениям из БД: {photo_urls}")
            
            # Проверяем существование файлов относительно images_dir
            valid_photo_paths = []
            for p in photo_urls:
                if not p:
                    continue
                # Проверяем путь относительно images_dir
                full_path = self.image_handler.images_dir / p
                if full_path.exists():
                    valid_photo_paths.append(p)
                    logger.info(f"Найден файл: {full_path}")
                else:
                    logger.warning(f"Файл не найден: {full_path}")

            image_base64_list = []
            image_captions = []

            # Если есть хотя бы одна картинка
            if valid_photo_paths:
                logger.info(f"Обработка {len(valid_photo_paths)} изображений (последовательно)...")
                for idx, path in enumerate(valid_photo_paths, 1):
                    logger.info(f"  [{idx}/{len(valid_photo_paths)}] Обработка изображения: {path}")
                    image_base64 = self.image_handler.image_to_base64(path)
                    image_base64_list.append(image_base64)
                    if image_base64:
                        logger.info(f"  [{idx}/{len(valid_photo_paths)}] Генерация описания изображения...")
                        try:
                            cap = await self.llm_handler.generate_image_caption(image_base64)
                            image_captions.append(cap)
                            if cap:
                                logger.info(f"  [{idx}/{len(valid_photo_paths)}] Описание получено: {cap[:100]}...")
                            else:
                                logger.warning(f"  [{idx}/{len(valid_photo_paths)}] Описание не получено (пустой ответ)")
                        except Exception as e:
                            logger.error(f"  [{idx}/{len(valid_photo_paths)}] Ошибка генерации описания: {e}")
                            image_captions.append(None)
                            # Продолжаем обработку даже при ошибке описания
                    else:
                        image_captions.append(None)
                        logger.warning(f"  [{idx}/{len(valid_photo_paths)}] Не удалось конвертировать изображение в base64")
                logger.info(f"✅ Все изображения обработаны ({len(valid_photo_paths)} шт.)")
            else:
                logger.info("📸 Изображения отсутствуют, запуск генерации...")
                prompt = post.text[:500] if len(post.text) > 500 else post.text
                logger.info(f"Промпт для генерации: {prompt[:100]}...")
                
                # Ожидаем полного завершения генерации изображения
                gen_path = await self.image_handler.generate_image(prompt)
                
                if gen_path:
                    logger.info(f"✅ Изображение сгенерировано: {gen_path}")
                    valid_photo_paths = [gen_path]
                    
                    # Конвертация в base64 (после генерации)
                    logger.info("Конвертация сгенерированного изображения в base64...")
                    image_base64 = self.image_handler.image_to_base64(gen_path)
                    image_base64_list.append(image_base64)
                    
                    if image_base64:
                        # Генерация описания (после конвертации)
                        logger.info("Генерация описания сгенерированного изображения...")
                        try:
                            cap = await self.llm_handler.generate_image_caption(image_base64)
                            image_captions.append(cap)
                            if cap:
                                logger.info(f"✅ Описание изображения получено: {cap[:100]}...")
                            else:
                                logger.warning("⚠️  Описание не получено (пустой ответ)")
                        except Exception as e:
                            logger.error(f"Ошибка генерации описания сгенерированного изображения: {e}")
                            image_captions.append(None)
                            # Продолжаем обработку даже при ошибке описания
                    else:
                        image_captions.append(None)
                        logger.warning("⚠️  Не удалось конвертировать сгенерированное изображение в base64")
                else:
                    logger.warning("❌ Не удалось сгенерировать изображение")
            
            # Явная проверка: изображение должно быть готово перед генерацией данных события
            logger.info("=" * 60)
            logger.info("ПРОВЕРКА ГОТОВНОСТИ ИЗОБРАЖЕНИЯ")
            logger.info(f"  Путей к изображениям: {len(valid_photo_paths)}")
            logger.info(f"  Base64 изображений: {len(image_base64_list)}")
            logger.info(f"  Описаний изображений: {len(image_captions)}")
            logger.info("=" * 60)

            # Шаг 3: Получение существующих категорий и интересов из БД
            # (выполняется только после полной обработки изображения)
            logger.info("Получение существующих категорий и интересов из БД...")
            existing_categories = self.db_handler.get_all_categories()
            existing_interests = self.db_handler.get_all_interests()
            logger.info(f"  Существующих категорий: {len(existing_categories)}")
            logger.info(f"  Существующих интересов: {len(existing_interests)}")
            
            # Генерация данных события через LLM
            # Выполняется только после полной обработки/генерации изображения
            logger.info("=" * 60)
            logger.info("ГЕНЕРАЦИЯ ДАННЫХ СОБЫТИЯ ЧЕРЕЗ LLM")
            logger.info("  (изображение уже обработано/сгенерировано)")
            logger.info("=" * 60)
            
            llm_response = await self.llm_handler.generate_event_data(
                post_text=post.text,
                image_caption=image_captions[0] if image_captions else None,
                hashtags=post.hashtags,
                existing_categories=existing_categories,
                existing_interests=existing_interests,
                image_base64=image_base64_list[0] if image_base64_list else None
            )
            
            logger.info("✅ Данные события получены от LLM")
            if not llm_response:
                logger.error("Не удалось получить данные от LLM")
                llm_response = type('obj', (object,), {
                    'title': None,
                    'description': None,
                    'date': None,
                    'price': None,
                    'categories': [],
                    'user_interests': []
                })()
            processed_event = ProcessedEvent(
                title=llm_response.title,
                description=llm_response.description,
                date=llm_response.date,
                price=llm_response.price,
                categories=llm_response.categories,
                user_interests=llm_response.user_interests,
                image_urls=valid_photo_paths if valid_photo_paths else None,
                image_url=valid_photo_paths[0] if valid_photo_paths else None,  # deprecated
                image_caption=image_captions[0] if image_captions else None,
                source_post_url=None,
                raw_post_id=post_id
            )
            logger.info("=" * 60)
            logger.info("✅ ПОСТ ПОЛНОСТЬЮ ОБРАБОТАН")
            logger.info(f"  Название: {processed_event.title}")
            logger.info(f"  Дата: {processed_event.date}")
            logger.info(f"  Категории: {processed_event.categories}")
            logger.info(f"  Интересы: {processed_event.user_interests}")
            logger.info(f"  Изображений: {len(valid_photo_paths) if valid_photo_paths else 0}")
            logger.info("=" * 60)
            
            # Сохранение в БД (после полной обработки)
            logger.info("Сохранение обработанного события в БД...")
            success = self.db_handler.save_processed_event(processed_event)
            if success:
                logger.info("✅ Событие сохранено в БД")
            else:
                logger.warning("⚠️  Не удалось сохранить событие в БД")
            
            # Явное подтверждение завершения обработки
            logger.info("=" * 60)
            logger.info("✅ ОБРАБОТКА ПОСТА ЗАВЕРШЕНА ПОЛНОСТЬЮ")
            logger.info("   (включая изображение и все данные)")
            logger.info("=" * 60)
            
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
        Обработка происходит строго последовательно: каждый пост полностью обрабатывается
        (включая генерацию изображения) перед началом обработки следующего.
        
        Args:
            limit: Максимальное количество постов для обработки
            
        Returns:
            Статистика обработки
        """
        logger.info("=" * 60)
        logger.info("НАЧАЛО ПОСЛЕДОВАТЕЛЬНОЙ ОБРАБОТКИ ПОСТОВ")
        logger.info("=" * 60)
        logger.info("⚠️  Режим: СТРОГО ПОСЛЕДОВАТЕЛЬНАЯ обработка")
        logger.info("   Каждый пост полностью обрабатывается перед следующим")
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
            'errors': 0,
            'rate_limit_skipped': 0  # Счетчик пропущенных из-за rate limit
        }
        
        # СТРОГО ПОСЛЕДОВАТЕЛЬНАЯ обработка каждого поста
        # Каждый пост полностью обрабатывается (включая изображение) перед следующим
        consecutive_rate_limits = 0  # Счетчик последовательных rate limit ошибок
        for idx, raw_post in enumerate(raw_posts, 1):
            logger.info(f"\n{'=' * 60}")
            logger.info(f"НАЧАЛО ОБРАБОТКИ ПОСТА {idx}/{total}")
            logger.info(f"{'=' * 60}")
            
            try:
                # Ожидаем полного завершения обработки поста
                # (включая генерацию изображения, если нужно)
                result = await self.process_raw_post(raw_post)
                
                # Явная проверка завершения обработки
                # Пост считается успешным только если он полностью обработан и сохранен
                if result and result.title:  # Проверяем, что хотя бы title есть
                    stats['success'] += 1
                    consecutive_rate_limits = 0  # Сбрасываем счетчик при успехе
                    logger.info(f"✅ Пост {idx}/{total} успешно обработан и сохранен")
                else:
                    stats['errors'] += 1
                    logger.warning(f"⚠️  Пост {idx}/{total} обработан с ошибками (неполные данные)")
                    
            except Exception as e:
                error_str = str(e)
                # Проверяем, является ли ошибка rate limit
                is_rate_limit = "429" in error_str or "Rate limit" in error_str or "rate_limit" in error_str
                
                if is_rate_limit:
                    consecutive_rate_limits += 1
                    stats['errors'] += 1
                    logger.error(f"❌ Rate limit (429) при обработке поста {idx}/{total}: {e}")
                    
                    # Если 3 поста подряд получили rate limit, делаем длительную паузу
                    if consecutive_rate_limits >= 3:
                        long_delay = 120  # 2 минуты
                        logger.warning(
                            f"⚠️  {consecutive_rate_limits} постов подряд получили rate limit. "
                            f"Делаем длительную паузу {long_delay} сек. перед продолжением..."
                        )
                        await asyncio.sleep(long_delay)
                        consecutive_rate_limits = 0  # Сбрасываем счетчик после паузы
                else:
                    consecutive_rate_limits = 0  # Сбрасываем при других ошибках
                    logger.error(f"❌ Критическая ошибка при обработке поста {idx}/{total}: {e}", exc_info=True)
                    stats['errors'] += 1
            
            logger.info(f"{'=' * 60}")
            logger.info(f"ЗАВЕРШЕНА ОБРАБОТКА ПОСТА {idx}/{total}")
            logger.info(f"{'=' * 60}\n")
            
            # Задержка между постами для избежания rate limit
            # Увеличиваем задержку при ошибках rate limit
            if idx < total:
                # Базовая задержка увеличивается при rate limit ошибках
                if consecutive_rate_limits > 0:
                    delay = 20.0 + (consecutive_rate_limits * 5)  # 20, 25, 30... секунд
                    delay = min(delay, 60.0)  # Максимум 60 секунд
                else:
                    delay = 15.0  # Базовая задержка 15 секунд
                
                logger.info(f"⏳ Пауза {delay:.1f} сек. перед следующим постом (для избежания rate limit)...")
                await asyncio.sleep(delay)
        
        # Итоговая статистика
        logger.info("=" * 60)
        logger.info("ИТОГИ ОБРАБОТКИ:")
        logger.info(f"  Всего постов: {stats['total']}")
        logger.info(f"  Успешно обработано: {stats['success']}")
        logger.info(f"  Ошибок: {stats['errors']}")
        if stats.get('rate_limit_skipped', 0) > 0:
            logger.info(f"  Пропущено из-за rate limit: {stats['rate_limit_skipped']}")
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

