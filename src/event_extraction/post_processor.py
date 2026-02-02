"""
Оркестратор обработки постов с проверкой дублей и извлечением событий.
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

from motor.motor_asyncio import AsyncIOMotorClient
from qdrant_client import QdrantClient
from openai import AsyncOpenAI

from .models import RawPost, StructuredEvent
from .langgraph_agent import EventExtractionGraph
from .deduplicator import EventDeduplicator
from .image_handler import ImageHandler

logger = logging.getLogger(__name__)


class PostProcessingError(Exception):
    """Исключение при ошибке обработки поста."""
    pass


class EventDeduplicationError(Exception):
    """Исключение при ошибке дедупликации события."""
    pass


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
        similarity_threshold: float = 0.92
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
            similarity_threshold: Порог сходства для дедупликации
        """
        self.db = db_client[db_name]
        self.llm_client = llm_client
        
        # Инициализация компонентов
        self.extraction_agent = EventExtractionGraph(
            llm_client=llm_client,
            image_handler=image_handler,
            model_name=llm_model
        )
        
        self.deduplicator = EventDeduplicator(
            qdrant_client=qdrant_client,
            collection_name=qdrant_collection,
            similarity_threshold=similarity_threshold
        )
        
        logger.info("PostProcessor инициализирован")
    
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
    
    async def _save_event(self, event: StructuredEvent) -> Optional[str]:
        """
        Сохранение события в MongoDB.
        
        Args:
            event: Событие для сохранения
            
        Returns:
            ID сохранённого события или None при ошибке
        """
        try:
            # Подготовка документа
            event_dict = event.model_dump(mode='json')
            
            # Преобразование расписания
            if event.schedule:
                event_dict["schedule"] = event.schedule.model_dump(mode='json')
            
            # Сохранение
            result = await self.db.events.insert_one(event_dict)
            
            event_id = str(result.inserted_id)
            logger.info(f"✅ Событие сохранено в MongoDB: {event.title[:50]} (id={event_id})")
            
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
            
            # Извлечение событий через LangGraph агент
            events = await self.extraction_agent.run_extraction_graph(
                text=post.text,
                message_date=post.message_date,
                images=post.photo_urls or [],
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
            
            # Обработка каждого события
            saved_event_ids = []
            
            for idx, event in enumerate(events, 1):
                logger.info(f"--- Обработка события {idx}/{len(events)}: {event.title[:50]} ---")
                
                try:
                    # Генерация эмбеддинга для дедупликации
                    embedding_text = f"{event.title} {event.description or ''} {event.location or ''}"
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
            
            return events
        
        except Exception as e:
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
