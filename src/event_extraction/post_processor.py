"""
Оркестратор обработки постов с проверкой дублей и извлечением событий.
"""

import logging
import re
import time
from typing import List, Dict, Any, Optional
from datetime import datetime

from motor.motor_asyncio import AsyncIOMotorClient
from qdrant_client import QdrantClient
from openai import AsyncOpenAI

from .models import RawPost, StructuredEvent, WeightedInterest
from .langgraph_agent import EventExtractionGraph
from .deduplicator import EventDeduplicator
from .image_handler import ImageHandler
from .exceptions import PostProcessingError, EventDeduplicationError, InsufficientQuotaError

logger = logging.getLogger(__name__)

# Импорт метрик (ленивая инициализация)
try:
    from src.monitoring import get_event_metrics
    METRICS_AVAILABLE = True
except ImportError:
    METRICS_AVAILABLE = False
    logger.warning("Модуль мониторинга недоступен, метрики отключены")


class PostProcessor:
    """Процессор для обработки постов с дедупликацией и извлечением событий."""
    
    def __init__(
        self,
        db_client: AsyncIOMotorClient,
        qdrant_client: QdrantClient,
        llm_client: AsyncOpenAI,
        image_handler: ImageHandler,
        db_name: str = "events_db",
        qdrant_collection: str = "events",
        llm_model: str = "gpt-4o",
        similarity_threshold_global: float = 0.92,
        similarity_threshold_intra_post: float = 0.86
    ):
        """
        Инициализация процессора.
        
        Args:
            db_client: Клиент MongoDB
            qdrant_client: Клиент Qdrant
            llm_client: OpenAI-совместимый клиент
            image_handler: Обработчик изображений
            db_name: Название БД MongoDB
            qdrant_collection: Название коллекции Qdrant
            llm_model: Название LLM модели
            similarity_threshold_global: Порог сходства для межпостовой дедупликации
            similarity_threshold_intra_post: Порог merge для событий внутри одного поста
        """
        self.db = db_client[db_name]
        self.db_name = db_name
        self.llm_client = llm_client
        self.similarity_threshold_intra_post = similarity_threshold_intra_post
        
        # Инициализация компонентов
        self.extraction_agent = EventExtractionGraph(
            llm_client=llm_client,
            image_handler=image_handler,
            qdrant_client=qdrant_client,
            model_name=llm_model
        )
        
        self.deduplicator = EventDeduplicator(
            qdrant_client=qdrant_client,
            collection_name=qdrant_collection,
            similarity_threshold=similarity_threshold_global
        )
        
        logger.info(
            f"PostProcessor инициализирован (MongoDB: db={self.db_name}, "
            f"collections=raw_posts/events/processed_posts)"
        )
    
    async def _is_post_processed(self, post_id: int, channel: str) -> bool:
        """
        Проверка, был ли пост уже обработан.
        
        Args:
            post_id: ID поста
            channel: Название канала
            
        Returns:
            True если пост уже обработан
        """
        try:
            # Проверяем в коллекции processed_posts
            result = await self.db.processed_posts.find_one({
                "post_id": post_id,
                "channel": channel
            })
            
            return result is not None
        
        except Exception as e:
            logger.error(f"Ошибка проверки обработки поста: {e}")
            return False
    
    async def _mark_post_processed(self, post_id: int, channel: str, event_ids: List[str]):
        """
        Отметка поста как обработанного.
        
        Args:
            post_id: ID поста
            channel: Название канала
            event_ids: Список ID извлечённых событий
        """
        try:
            await self.db.processed_posts.update_one(
                {"post_id": post_id, "channel": channel},
                {
                    "$set": {
                        "processed_at": datetime.utcnow(),
                        "event_ids": event_ids,
                        "events_count": len(event_ids)
                    }
                },
                upsert=True
            )
        
        except Exception as e:
            logger.error(f"Ошибка отметки поста: {e}")
    
    async def _get_embedding(self, text: str) -> Optional[List[float]]:
        """
        Получение эмбеддинга текста через OpenAI API.
        
        Args:
            text: Текст для эмбеддинга
            
        Returns:
            Вектор эмбеддинга или None при ошибке
        """
        try:
            response = await self.llm_client.embeddings.create(
                model="text-embedding-ada-002",
                input=text[:8000]  # Ограничение длины
            )
            return response.data[0].embedding
        
        except Exception as e:
            logger.error(f"Ошибка получения эмбеддинга: {e}", exc_info=True)
            return None

    @staticmethod
    def _normalize_location_key(event: StructuredEvent) -> str:
        raw_location = f"{event.location or ''} {event.address or ''}".strip().lower()
        if not raw_location:
            return ""
        compact = re.sub(r"[^\w\s]", " ", raw_location)
        compact = re.sub(r"\s+", " ", compact).strip()
        return compact

    @staticmethod
    def _extract_event_datetime(event: StructuredEvent) -> Optional[datetime]:
        if not event.schedule:
            return None
        if hasattr(event.schedule, "date_start"):
            return event.schedule.date_start
        if hasattr(event.schedule, "valid_from"):
            return event.schedule.valid_from
        if hasattr(event.schedule, "approximate_start"):
            return event.schedule.approximate_start
        return None

    @staticmethod
    def _is_time_close(event_left: StructuredEvent, event_right: StructuredEvent, tolerance_minutes: int = 60) -> bool:
        left_dt = PostProcessor._extract_event_datetime(event_left)
        right_dt = PostProcessor._extract_event_datetime(event_right)
        if not left_dt or not right_dt:
            return True
        delta_seconds = abs((left_dt - right_dt).total_seconds())
        return delta_seconds <= tolerance_minutes * 60

    @staticmethod
    def _cosine_similarity(vec_left: List[float], vec_right: List[float]) -> float:
        if not vec_left or not vec_right or len(vec_left) != len(vec_right):
            return 0.0
        dot = sum(left * right for left, right in zip(vec_left, vec_right))
        norm_left = sum(left * left for left in vec_left) ** 0.5
        norm_right = sum(right * right for right in vec_right) ** 0.5
        if norm_left == 0.0 or norm_right == 0.0:
            return 0.0
        return dot / (norm_left * norm_right)

    @staticmethod
    def _merge_weighted_interests(event_left: StructuredEvent, event_right: StructuredEvent) -> List[WeightedInterest]:
        accumulator: Dict[str, float] = {}
        for interest in event_left.interests + event_right.interests:
            if not interest.name:
                continue
            accumulator[interest.name] = accumulator.get(interest.name, 0.0) + float(interest.weight)

        total = sum(accumulator.values())
        if total <= 0:
            return []
        return [
            WeightedInterest(name=name, weight=round(weight / total, 4))
            for name, weight in sorted(accumulator.items(), key=lambda item: item[1], reverse=True)
        ]

    @staticmethod
    def _build_dedup_embedding_text(event: StructuredEvent, top_interests: int = 5) -> str:
        top_weighted_interests = sorted(
            event.interests,
            key=lambda item: item.weight,
            reverse=True
        )[:top_interests]
        interest_names = [item.name for item in top_weighted_interests if item.name]
        categories = [category for category in event.categories if category]
        parts = [
            event.title or "",
            event.description or "",
            event.location or "",
            event.address or "",
            " ".join(categories),
            " ".join(interest_names),
            event.category_primary or "",
            " ".join(event.category_secondary or []),
        ]
        return " ".join(part for part in parts if part).strip()

    @staticmethod
    def _normalize_image_paths(image_paths: Optional[List[Any]]) -> List[str]:
        """Нормализует список путей изображений и удаляет дубликаты."""
        if not image_paths:
            return []

        normalized: List[str] = []
        seen = set()
        for item in image_paths:
            if not item:
                continue
            path = str(item).strip()
            if not path or path in seen:
                continue
            seen.add(path)
            normalized.append(path)
        return normalized

    @classmethod
    def _merge_events_pair(cls, base_event: StructuredEvent, candidate_event: StructuredEvent) -> StructuredEvent:
        merged_description = base_event.description or ""
        if candidate_event.description and len(candidate_event.description) > len(merged_description):
            merged_description = candidate_event.description

        merged_sources = []
        seen_sources = set()
        for source in base_event.sources + candidate_event.sources:
            key = (source.channel, source.post_id)
            if key in seen_sources:
                continue
            seen_sources.add(key)
            merged_sources.append(source)

        merged_images = []
        seen_images = set()
        for image in base_event.images + candidate_event.images:
            if image in seen_images:
                continue
            seen_images.add(image)
            merged_images.append(image)

        merged_categories = []
        seen_categories = set()
        for category in base_event.categories + candidate_event.categories:
            if category in seen_categories or not category:
                continue
            seen_categories.add(category)
            merged_categories.append(category)

        merged_secondary = []
        seen_secondary = set()
        for category in (base_event.category_secondary or []) + (candidate_event.category_secondary or []):
            if category in seen_secondary or not category:
                continue
            seen_secondary.add(category)
            merged_secondary.append(category)

        merged_interests = cls._merge_weighted_interests(base_event, candidate_event)
        merged_user_interests = [item.name for item in merged_interests]
        merged_primary = base_event.category_primary or candidate_event.category_primary

        return base_event.model_copy(
            update={
                "description": merged_description,
                "sources": merged_sources,
                "images": merged_images,
                "categories": merged_categories,
                "category_primary": merged_primary,
                "category_secondary": merged_secondary,
                "interests": merged_interests,
                "user_interests": merged_user_interests,
            }
        )

    async def merge_similar_events_within_post(self, events: List[StructuredEvent]) -> List[StructuredEvent]:
        """Объединение схожих событий внутри одного поста до глобальной дедупликации."""
        if len(events) < 2:
            return events

        dedup_texts = [self._build_dedup_embedding_text(event) for event in events]
        embeddings = [await self._get_embedding(text) for text in dedup_texts]
        merged_flags = [False] * len(events)
        merged_events: List[StructuredEvent] = []
        merged_pairs = 0

        for index, event in enumerate(events):
            if merged_flags[index]:
                continue

            current_event = event
            for candidate_index in range(index + 1, len(events)):
                if merged_flags[candidate_index]:
                    continue
                candidate_event = events[candidate_index]

                if not self._is_time_close(current_event, candidate_event):
                    continue

                left_location = self._normalize_location_key(current_event)
                right_location = self._normalize_location_key(candidate_event)
                if left_location and right_location and left_location != right_location:
                    continue

                left_embedding = embeddings[index]
                right_embedding = embeddings[candidate_index]
                similarity = self._cosine_similarity(left_embedding or [], right_embedding or [])
                if similarity < self.similarity_threshold_intra_post:
                    continue

                current_event = self._merge_events_pair(current_event, candidate_event)
                merged_flags[candidate_index] = True
                merged_pairs += 1

            merged_events.append(current_event)

        if merged_pairs:
            logger.info(
                f"Внутрипостовый merge: объединено пар={merged_pairs}, "
                f"было={len(events)}, стало={len(merged_events)}"
            )
        return merged_events
    
    async def _save_event(self, event: StructuredEvent) -> Optional[str]:
        """
        Сохранение события в MongoDB.
        
        Args:
            event: Событие для сохранения
            
        Returns:
            ID сохранённого события или None при ошибке
        """
        try:
            # Гарантируем совместимость: user_interests синхронизирован с weighted interests
            if event.interests:
                event.user_interests = [item.name for item in event.interests if item.name]

            # Гарантируем консистентный формат изображений перед сохранением
            event.images = self._normalize_image_paths(event.images)

            # Подготовка документа
            event_dict = event.model_dump(mode='json')
            
            # Преобразование расписания
            if event.schedule:
                event_dict["schedule"] = event.schedule.model_dump(mode='json')

            # Гарантируем наличие поля images в документе
            event_dict["images"] = self._normalize_image_paths(
                event_dict.get("images") or event.images
            )
            
            # Сохранение в коллекцию events
            result = await self.db.events.insert_one(event_dict)
            inserted_id = result.inserted_id

            # Защита от ложноположительного лога: проверяем, что документ реально записан
            inserted_doc = await self.db.events.find_one({"_id": inserted_id}, {"_id": 1})
            if not inserted_doc:
                logger.error(
                    "MongoDB insert_one вернул inserted_id, но документ не найден "
                    f"(db={self.db_name}, collection=events, _id={inserted_id})"
                )
                return None
            
            event_id = str(inserted_id)
            logger.info(
                f"✅ Событие сохранено в MongoDB: {event.title[:50]} "
                f"(db={self.db_name}, collection=events, id={event_id})"
            )
            
            return event_id
        
        except Exception as e:
            logger.error(f"Ошибка сохранения события: {e}", exc_info=True)
            return None
    
    async def _update_event_sources(self, event_id: str, new_source: Dict[str, Any]):
        """
        Обновление источников существующего события.
        
        Args:
            event_id: ID события в MongoDB
            new_source: Новый источник
        """
        try:
            from bson import ObjectId
            
            await self.db.events.update_one(
                {"_id": ObjectId(event_id)},
                {"$addToSet": {"sources": new_source}}
            )
            
            logger.info(f"✅ Источник добавлен к событию {event_id}")
        
        except Exception as e:
            logger.error(f"Ошибка обновления источников: {e}")
    
    async def process_post(self, raw_post: Dict[str, Any]) -> List[StructuredEvent]:
        """
        Обработка одного поста.
        
        Args:
            raw_post: Словарь с данными сырого поста
            
        Returns:
            Список извлечённых событий
        """
        # Начало измерения времени
        start_time = time.time()
        metrics = get_event_metrics() if METRICS_AVAILABLE else None
        
        try:
            # Валидация поста
            post = RawPost(**raw_post)
            
            logger.info("=" * 60)
            logger.info(f"ОБРАБОТКА ПОСТА: {post.channel}/{post.post_id}")
            logger.info("=" * 60)
            
            # Проверка обработки
            if await self._is_post_processed(post.post_id, post.channel):
                logger.info(f"Пост уже обработан, пропускаем")
                return []
            
            # Собираем изображения с поддержкой legacy-поля photo_url
            source_images = self._normalize_image_paths(post.photo_urls)
            if not source_images:
                legacy_photo_url = raw_post.get("photo_url")
                if legacy_photo_url:
                    source_images = self._normalize_image_paths([legacy_photo_url])

            # Извлечение событий через LangGraph агент
            events = await self.extraction_agent.run_extraction_graph(
                text=post.text,
                message_date=post.message_date,
                images=source_images,
                hashtags=post.hashtags,
                channel=post.channel,
                post_id=post.post_id
            )
            
            if not events:
                logger.warning("Не извлечено событий из поста")
                # Всё равно отмечаем как обработанный
                await self._mark_post_processed(post.post_id, post.channel, [])
                return []
            
            logger.info(f"Извлечено событий: {len(events)}")
            events = await self.merge_similar_events_within_post(events)
            logger.info(f"После intra-post merge событий: {len(events)}")
            
            # Обработка каждого события
            saved_event_ids = []
            
            for idx, event in enumerate(events, 1):
                logger.info(f"--- Обработка события {idx}/{len(events)}: {event.title[:50]} ---")
                
                try:
                    # Генерация эмбеддинга для дедупликации
                    embedding_text = self._build_dedup_embedding_text(event)
                    embedding = await self._get_embedding(embedding_text)
                    
                    if not embedding:
                        logger.warning("Не удалось получить эмбеддинг, пропускаем дедупликацию")
                        # Сохраняем без дедупликации
                        event_id = await self._save_event(event)
                        if event_id:
                            saved_event_ids.append(event_id)
                        continue
                    
                    # Проверка дубликатов
                    is_duplicate, original_event_id = await self.deduplicator.is_duplicate_event(
                        event, embedding
                    )
                    
                    if is_duplicate and original_event_id:
                        logger.info(
                            f"⚠️  Найден дубликат события: {event.title[:50]} "
                            f"(оригинал: {original_event_id})"
                        )
                        
                        # Метрика дубликата
                        if metrics:
                            metrics.record_duplicate_found()
                        
                        # Обновляем источники оригинального события
                        new_source = event.sources[0] if event.sources else None
                        if new_source:
                            await self._update_event_sources(
                                original_event_id,
                                {
                                    "channel": new_source.channel,
                                    "post_id": new_source.post_id,
                                    "post_url": new_source.post_url
                                }
                            )
                            await self.deduplicator.update_duplicate_sources(
                                original_event_id, new_source
                            )
                        
                        saved_event_ids.append(original_event_id)
                    
                    else:
                        # Новое событие - сохраняем
                        logger.info(f"Новое событие, сохраняем")
                        
                        # Сохранение в MongoDB
                        event_id = await self._save_event(event)
                        
                        if event_id:
                            # Метрика созданного события
                            if metrics:
                                metrics.record_event_created()
                            
                            # Метрика сгенерированной афиши
                            if event.poster_generated and metrics:
                                metrics.record_poster_generated()
                            
                            # Добавление в Qdrant для будущей дедупликации
                            await self.deduplicator.add_event_to_index(
                                event, embedding, event_id
                            )
                            saved_event_ids.append(event_id)
                
                except Exception as e:
                    logger.error(f"Ошибка обработки события: {e}", exc_info=True)
                    continue
            
            # Отметка поста как обработанного
            await self._mark_post_processed(post.post_id, post.channel, saved_event_ids)
            
            logger.info("=" * 60)
            logger.info(f"ПОСТ ОБРАБОТАН: {len(saved_event_ids)} событий сохранено")
            logger.info("=" * 60)
            
            # Запись времени обработки
            duration = time.time() - start_time
            if metrics:
                metrics.processing_duration.observe(duration)
            
            return events
        
        except InsufficientQuotaError as e:
            # Метрика квоты
            if metrics:
                metrics.record_error("quota")
            raise
        
        except Exception as e:
            # Метрика общей ошибки
            if metrics:
                metrics.record_error("processing")
            
            logger.error(f"Критическая ошибка обработки поста: {e}", exc_info=True)
            raise PostProcessingError(f"Ошибка обработки поста: {e}") from e
    
    async def process_new_posts_batch(self, limit: Optional[int] = None) -> Dict[str, int]:
        """
        Пакетная обработка новых постов из БД.
        
        Args:
            limit: Максимальное количество постов для обработки
            
        Returns:
            Статистика обработки
        """
        logger.info("=" * 60)
        logger.info("НАЧАЛО ПАКЕТНОЙ ОБРАБОТКИ ПОСТОВ")
        logger.info("=" * 60)
        
        # Получение метрик
        metrics = get_event_metrics() if METRICS_AVAILABLE else None
        
        try:
            # Получение необработанных постов
            pipeline = [
                {
                    "$lookup": {
                        "from": "processed_posts",
                        "let": {"post_id": "$post_id", "channel": "$channel"},
                        "pipeline": [
                            {
                                "$match": {
                                    "$expr": {
                                        "$and": [
                                            {"$eq": ["$post_id", "$$post_id"]},
                                            {"$eq": ["$channel", "$$channel"]}
                                        ]
                                    }
                                }
                            }
                        ],
                        "as": "processed"
                    }
                },
                {"$match": {"processed": {"$size": 0}}},
                {"$sort": {"message_date": -1}}
            ]
            
            if limit:
                pipeline.append({"$limit": limit})
            
            cursor = self.db.raw_posts.aggregate(pipeline)
            raw_posts = await cursor.to_list(length=None)
            
            total = len(raw_posts)
            logger.info(f"Найдено необработанных постов: {total}")
            
            # Обновление метрики новых постов
            if metrics:
                metrics.set_pending_posts(total)
            
            if total == 0:
                return {"total": 0, "success": 0, "errors": 0, "events_extracted": 0}
            
            stats = {
                "total": total,
                "success": 0,
                "errors": 0,
                "events_extracted": 0
            }
            
            # Обработка каждого поста
            for idx, raw_post in enumerate(raw_posts, 1):
                logger.info(f"\n--- Пост {idx}/{total} ---")
                
                try:
                    events = await self.process_post(raw_post)
                    stats["success"] += 1
                    stats["events_extracted"] += len(events)
                
                except InsufficientQuotaError as e:
                    # Критическая ошибка - прерываем обработку
                    logger.critical("=" * 60)
                    logger.critical("❌ КРИТИЧЕСКАЯ ОШИБКА: API QUOTA EXCEEDED")
                    logger.critical(f"   Ошибка: {e}")
                    logger.critical(f"   Обработано постов: {idx - 1}/{total}")
                    logger.critical("   Необходимо пополнить баланс API")
                    logger.critical("   Прерывание обработки...")
                    logger.critical("=" * 60)
                    stats["errors"] += 1
                    # Прерываем цикл и прокидываем ошибку выше
                    raise
                
                except Exception as e:
                    logger.error(f"Ошибка обработки поста {idx}: {e}")
                    stats["errors"] += 1
            
            # Итоговая статистика
            logger.info("=" * 60)
            logger.info("ИТОГИ ПАКЕТНОЙ ОБРАБОТКИ:")
            logger.info(f"  Всего постов: {stats['total']}")
            logger.info(f"  Успешно обработано: {stats['success']}")
            logger.info(f"  Ошибок: {stats['errors']}")
            logger.info(f"  Событий извлечено: {stats['events_extracted']}")
            logger.info("=" * 60)
            
            return stats
        
        except Exception as e:
            logger.error(f"Критическая ошибка пакетной обработки: {e}", exc_info=True)
            raise PostProcessingError(f"Ошибка пакетной обработки: {e}") from e
