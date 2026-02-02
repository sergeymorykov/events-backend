"""
Модуль семантической дедупликации событий через Qdrant.
"""

import hashlib
import logging
import re
from typing import Optional, List, Dict, Any
from datetime import datetime

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue
)

from .models import StructuredEvent, EventSource

logger = logging.getLogger(__name__)


class EventDeduplicator:
    """Дедупликатор событий с использованием Qdrant и канонических хэшей."""
    
    def __init__(
        self,
        qdrant_client: QdrantClient,
        collection_name: str,
        similarity_threshold: float = 0.92,
        vector_size: int = 1536
    ):
        """
        Инициализация дедупликатора.
        
        Args:
            qdrant_client: Клиент Qdrant
            collection_name: Название коллекции
            similarity_threshold: Порог сходства для дубликатов (0-1)
            vector_size: Размер вектора эмбеддинга
        """
        self.client = qdrant_client
        self.collection_name = collection_name
        self.similarity_threshold = similarity_threshold
        self.vector_size = vector_size
        
        # Инициализация коллекции
        self._init_collection()
    
    def _init_collection(self):
        """Инициализация коллекции Qdrant если не существует."""
        try:
            # Проверка существования коллекции
            collections = self.client.get_collections().collections
            exists = any(col.name == self.collection_name for col in collections)
            
            if not exists:
                logger.info(f"Создание коллекции Qdrant: {self.collection_name}")
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=self.vector_size,
                        distance=Distance.COSINE
                    )
                )
                logger.info(f"✅ Коллекция {self.collection_name} создана")
            else:
                logger.info(f"Коллекция {self.collection_name} уже существует")
        
        except Exception as e:
            logger.error(f"Ошибка инициализации коллекции Qdrant: {e}", exc_info=True)
            raise
    
    @staticmethod
    def _normalize_text(text: str) -> str:
        """
        Нормализация текста для хэширования.
        
        Args:
            text: Исходный текст
            
        Returns:
            Нормализованный текст
        """
        if not text:
            return ""
        
        # Приведение к нижнему регистру
        normalized = text.lower()
        
        # Удаление спецсимволов и лишних пробелов
        normalized = re.sub(r'[^\w\s]', '', normalized)
        normalized = re.sub(r'\s+', ' ', normalized)
        
        return normalized.strip()
    
    @staticmethod
    def generate_canonical_hash(event: StructuredEvent) -> str:
        """
        Генерация канонического хэша события для быстрого фильтра.
        
        Хэш вычисляется на основе:
        - Нормализованного названия
        - Локации (если есть)
        - Даты начала (только день, без времени)
        
        Args:
            event: Событие
            
        Returns:
            SHA256 хэш в hex формате
        """
        # Нормализация названия
        title_norm = EventDeduplicator._normalize_text(event.title)
        
        # Нормализация локации
        location_norm = ""
        if event.location:
            location_norm = EventDeduplicator._normalize_text(event.location)
        
        # Извлечение даты (только день, без времени)
        date_str = ""
        if event.schedule:
            if hasattr(event.schedule, 'date_start'):
                # ScheduleExact
                date_obj = event.schedule.date_start
                date_str = date_obj.strftime('%Y-%m-%d') if date_obj else ""
            elif hasattr(event.schedule, 'valid_from'):
                # ScheduleRecurringWeekly
                date_obj = event.schedule.valid_from
                date_str = date_obj.strftime('%Y-%m-%d') if date_obj else ""
            elif hasattr(event.schedule, 'approximate_start'):
                # ScheduleFuzzy
                date_obj = event.schedule.approximate_start
                date_str = date_obj.strftime('%Y-%m-%d') if date_obj else ""
        
        # Формирование строки для хэширования
        hash_input = f"{title_norm}|{location_norm}|{date_str}"
        
        # SHA256 хэш
        return hashlib.sha256(hash_input.encode('utf-8')).hexdigest()
    
    async def is_duplicate_event(
        self,
        event: StructuredEvent,
        embedding: List[float]
    ) -> tuple[bool, Optional[str]]:
        """
        Проверка, является ли событие дубликатом.
        
        Алгоритм:
        1. Быстрый фильтр по каноническому хэшу
        2. Векторный поиск с порогом сходства
        
        Args:
            event: Событие для проверки
            embedding: Вектор эмбеддинга события
            
        Returns:
            Кортеж (является_дубликатом, id_оригинального_события)
        """
        try:
            # Генерация канонического хэша
            canonical_hash = self.generate_canonical_hash(event)
            
            # Шаг 1: Быстрый фильтр по хэшу
            hash_filter = Filter(
                must=[
                    FieldCondition(
                        key="canonical_hash",
                        match=MatchValue(value=canonical_hash)
                    )
                ]
            )
            
            hash_results = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=hash_filter,
                limit=1,
                with_payload=True
            )
            
            if hash_results and hash_results[0]:
                # Найден точный дубликат по хэшу
                point = hash_results[0][0]
                logger.info(
                    f"Найден дубликат по хэшу: {event.title[:50]} "
                    f"(hash={canonical_hash[:8]}...)"
                )
                return True, str(point.id)
            
            # Шаг 2: Семантический поиск
            search_results = self.client.search(
                collection_name=self.collection_name,
                query_vector=embedding,
                limit=5,  # Ищем топ-5 похожих
                score_threshold=self.similarity_threshold,
                with_payload=True
            )
            
            if search_results:
                # Найдены семантически похожие события
                best_match = search_results[0]
                logger.info(
                    f"Найден семантический дубликат: {event.title[:50]} "
                    f"(score={best_match.score:.3f}, threshold={self.similarity_threshold})"
                )
                logger.debug(
                    f"Оригинал: {best_match.payload.get('title', 'N/A')[:50]}"
                )
                return True, str(best_match.id)
            
            # Дубликатов не найдено
            return False, None
        
        except Exception as e:
            logger.error(f"Ошибка проверки дубликата: {e}", exc_info=True)
            # В случае ошибки считаем событие НЕ дубликатом
            return False, None
    
    async def add_event_to_index(
        self,
        event: StructuredEvent,
        embedding: List[float],
        event_id: str
    ) -> bool:
        """
        Добавление события в индекс Qdrant.
        
        Args:
            event: Событие
            embedding: Вектор эмбеддинга
            event_id: Уникальный ID события (MongoDB ObjectId)
            
        Returns:
            Успех операции
        """
        try:
            # Генерация канонического хэша
            canonical_hash = self.generate_canonical_hash(event)
            
            # Подготовка payload
            payload = {
                "event_id": event_id,
                "canonical_hash": canonical_hash,
                "title": event.title,
                "description": event.description or "",
                "location": event.location or "",
                "categories": event.categories,
                "user_interests": event.user_interests,
                "sources": [
                    {
                        "channel": src.channel,
                        "post_id": src.post_id,
                        "post_url": src.post_url
                    }
                    for src in event.sources
                ],
                "processed_at": event.processed_at.isoformat()
            }
            
            # Добавление расписания
            if event.schedule:
                if hasattr(event.schedule, 'date_start'):
                    payload["schedule_type"] = "exact"
                    payload["date_start"] = event.schedule.date_start.isoformat()
                elif hasattr(event.schedule, 'schedule'):
                    payload["schedule_type"] = "recurring_weekly"
                    payload["schedule_data"] = event.schedule.schedule
                elif hasattr(event.schedule, 'description'):
                    payload["schedule_type"] = "fuzzy"
                    payload["schedule_description"] = event.schedule.description
            
            # Создание точки в Qdrant
            point = PointStruct(
                id=event_id,
                vector=embedding,
                payload=payload
            )
            
            self.client.upsert(
                collection_name=self.collection_name,
                points=[point]
            )
            
            logger.info(f"✅ Событие добавлено в Qdrant: {event.title[:50]} (id={event_id})")
            return True
        
        except Exception as e:
            logger.error(f"Ошибка добавления события в Qdrant: {e}", exc_info=True)
            return False
    
    async def update_duplicate_sources(
        self,
        original_event_id: str,
        new_source: EventSource
    ) -> bool:
        """
        Обновление источников существующего события при обнаружении дубликата.
        
        Args:
            original_event_id: ID оригинального события
            new_source: Новый источник для добавления
            
        Returns:
            Успех операции
        """
        try:
            # Получение текущего payload
            point = self.client.retrieve(
                collection_name=self.collection_name,
                ids=[original_event_id],
                with_payload=True
            )
            
            if not point:
                logger.error(f"Событие не найдено в Qdrant: {original_event_id}")
                return False
            
            current_payload = point[0].payload
            
            # Добавление нового источника
            sources = current_payload.get("sources", [])
            new_source_dict = {
                "channel": new_source.channel,
                "post_id": new_source.post_id,
                "post_url": new_source.post_url
            }
            
            # Проверка, что источник ещё не добавлен
            if not any(
                src.get("channel") == new_source.channel and
                src.get("post_id") == new_source.post_id
                for src in sources
            ):
                sources.append(new_source_dict)
                
                # Обновление payload
                self.client.set_payload(
                    collection_name=self.collection_name,
                    payload={"sources": sources},
                    points=[original_event_id]
                )
                
                logger.info(
                    f"✅ Источник добавлен к событию {original_event_id}: "
                    f"{new_source.channel}/{new_source.post_id}"
                )
            else:
                logger.debug(f"Источник уже существует, пропускаем")
            
            return True
        
        except Exception as e:
            logger.error(f"Ошибка обновления источников: {e}", exc_info=True)
            return False
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Получение статистики по коллекции.
        
        Returns:
            Словарь со статистикой
        """
        try:
            collection_info = self.client.get_collection(self.collection_name)
            
            return {
                "total_events": collection_info.points_count,
                "vector_size": collection_info.config.params.vectors.size,
                "distance": collection_info.config.params.vectors.distance.name
            }
        
        except Exception as e:
            logger.error(f"Ошибка получения статистики: {e}")
            return {}
