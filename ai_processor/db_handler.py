"""
Модуль для работы с базой данных MongoDB:
- Управление категориями
- Управление интересами пользователей
- Сохранение обработанных событий
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime

from pymongo import MongoClient, errors as mongo_errors
from pymongo.database import Database
from pymongo.collection import Collection

from .models import ProcessedEvent, Category, UserInterest

logger = logging.getLogger(__name__)


class DatabaseHandler:
    """Обработчик базы данных для AI процессора."""
    
    def __init__(self, mongodb_uri: str, db_name: str):
        """
        Инициализация обработчика БД.
        
        Args:
            mongodb_uri: URI подключения к MongoDB
            db_name: Имя базы данных
        """
        self.mongodb_uri = mongodb_uri
        self.db_name = db_name
        
        self.client: Optional[MongoClient] = None
        self.db: Optional[Database] = None
        
        # Коллекции
        self.processed_events: Optional[Collection] = None
        self.categories: Optional[Collection] = None
        self.user_interests: Optional[Collection] = None
        self.raw_posts: Optional[Collection] = None
    
    def connect(self):
        """Подключение к MongoDB и инициализация коллекций."""
        try:
            self.client = MongoClient(
                self.mongodb_uri,
                serverSelectionTimeoutMS=5000
            )
            
            # Проверка подключения
            self.client.server_info()
            
            self.db = self.client[self.db_name]
            
            # Инициализация коллекций
            self.processed_events = self.db['processed_events']
            self.categories = self.db['categories']
            self.user_interests = self.db['user_interests']
            self.raw_posts = self.db['raw_posts']
            
            # Создание индексов
            self._create_indexes()
            
            logger.info(f"Подключение к MongoDB успешно: {self.db_name}")
            
        except mongo_errors.ServerSelectionTimeoutError:
            logger.error("Не удалось подключиться к MongoDB: timeout")
            raise
        except Exception as e:
            logger.error(f"Ошибка подключения к MongoDB: {e}")
            raise
    
    def _create_indexes(self):
        """Создание индексов для оптимизации запросов."""
        try:
            # Индекс для processed_events
            self.processed_events.create_index('raw_post_id', unique=True, sparse=True)
            self.processed_events.create_index('processed_at')
            self.processed_events.create_index('date')
            self.processed_events.create_index('categories')
            self.processed_events.create_index('user_interests')
            
            # Индекс для categories
            self.categories.create_index('name', unique=True)
            self.categories.create_index('usage_count')
            
            # Индекс для user_interests
            self.user_interests.create_index('name', unique=True)
            self.user_interests.create_index('usage_count')
            
            logger.info("Индексы созданы успешно")
            
        except Exception as e:
            logger.warning(f"Ошибка создания индексов: {e}")
    
    def disconnect(self):
        """Закрытие подключения к MongoDB."""
        if self.client:
            try:
                self.client.close()
                logger.info("MongoDB соединение закрыто")
            except Exception as e:
                logger.error(f"Ошибка закрытия MongoDB: {e}")
    
    def get_all_categories(self) -> List[str]:
        """
        Получение всех категорий из базы данных.
        
        Returns:
            Список названий категорий
        """
        try:
            categories = self.categories.find({}, {'name': 1, '_id': 0}).sort('usage_count', -1)
            return [cat['name'] for cat in categories]
        except Exception as e:
            logger.error(f"Ошибка получения категорий: {e}")
            return []
    
    def get_all_interests(self) -> List[str]:
        """
        Получение всех интересов из базы данных.
        
        Returns:
            Список названий интересов
        """
        try:
            interests = self.user_interests.find({}, {'name': 1, '_id': 0}).sort('usage_count', -1)
            return [interest['name'] for interest in interests]
        except Exception as e:
            logger.error(f"Ошибка получения интересов: {e}")
            return []
    
    def add_or_update_category(self, name: str) -> bool:
        """
        Добавление или обновление категории.
        
        Args:
            name: Название категории
            
        Returns:
            True при успехе, False при ошибке
        """
        try:
            # Используем upsert для атомарного обновления
            self.categories.update_one(
                {'name': name.lower()},
                {
                    '$inc': {'usage_count': 1},
                    '$setOnInsert': {
                        'name': name.lower(),
                        'created_at': datetime.utcnow()
                    }
                },
                upsert=True
            )
            return True
        except Exception as e:
            logger.error(f"Ошибка добавления категории '{name}': {e}")
            return False
    
    def add_or_update_interest(self, name: str) -> bool:
        """
        Добавление или обновление интереса пользователя.
        
        Args:
            name: Название интереса
            
        Returns:
            True при успехе, False при ошибке
        """
        try:
            # Используем upsert для атомарного обновления
            self.user_interests.update_one(
                {'name': name.lower()},
                {
                    '$inc': {'usage_count': 1},
                    '$setOnInsert': {
                        'name': name.lower(),
                        'created_at': datetime.utcnow()
                    }
                },
                upsert=True
            )
            return True
        except Exception as e:
            logger.error(f"Ошибка добавления интереса '{name}': {e}")
            return False
    
    def save_processed_event(self, event: ProcessedEvent) -> bool:
        """
        Сохранение обработанного события в БД.
        
        Args:
            event: Объект ProcessedEvent
            
        Returns:
            True при успехе, False при ошибке
        """
        try:
            # Конвертация в словарь
            event_dict = event.model_dump(exclude_none=False)
            
            # Обновление счетчиков для категорий и интересов
            for category in event.categories:
                if category:
                    self.add_or_update_category(category)
            
            for interest in event.user_interests:
                if interest:
                    self.add_or_update_interest(interest)
            
            # Сохранение события
            self.processed_events.insert_one(event_dict)
            logger.info(f"Событие сохранено: {event.title or 'Без названия'} (raw_post_id: {event.raw_post_id})")
            return True
            
        except mongo_errors.DuplicateKeyError:
            logger.warning(f"Событие с raw_post_id={event.raw_post_id} уже существует")
            return False
        except Exception as e:
            logger.error(f"Ошибка сохранения события: {e}", exc_info=True)
            return False
    
    def get_processed_event_by_raw_post_id(self, raw_post_id: int) -> Optional[Dict[str, Any]]:
        """
        Получение обработанного события по ID сырого поста.
        
        Args:
            raw_post_id: ID сырого поста
            
        Returns:
            Словарь с данными события или None
        """
        try:
            return self.processed_events.find_one({'raw_post_id': raw_post_id})
        except Exception as e:
            logger.error(f"Ошибка получения события: {e}")
            return None
    
    def get_raw_post_by_id(self, post_id: int) -> Optional[Dict[str, Any]]:
        """
        Получение сырого поста по ID.
        
        Args:
            post_id: ID поста
            
        Returns:
            Словарь с данными поста или None
        """
        try:
            return self.raw_posts.find_one({'post_id': post_id})
        except Exception as e:
            logger.error(f"Ошибка получения сырого поста: {e}")
            return None
    
    def get_unprocessed_raw_posts(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Получение необработанных сырых постов.
        
        Args:
            limit: Максимальное количество постов (None = все)
            
        Returns:
            Список словарей с данными постов
        """
        try:
            # Получаем ID обработанных постов
            processed_ids = set()
            for doc in self.processed_events.find({}, {'raw_post_id': 1}):
                if doc.get('raw_post_id'):
                    processed_ids.add(doc['raw_post_id'])
            
            # Получаем необработанные посты
            query = {'post_id': {'$nin': list(processed_ids)}} if processed_ids else {}
            cursor = self.raw_posts.find(query).sort('parsed_at', -1)
            
            if limit:
                cursor = cursor.limit(limit)
            
            return list(cursor)
            
        except Exception as e:
            logger.error(f"Ошибка получения необработанных постов: {e}")
            return []
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Получение статистики по базе данных.
        
        Returns:
            Словарь со статистикой
        """
        try:
            stats = {
                'raw_posts_count': self.raw_posts.count_documents({}),
                'processed_events_count': self.processed_events.count_documents({}),
                'categories_count': self.categories.count_documents({}),
                'interests_count': self.user_interests.count_documents({}),
                'top_categories': [],
                'top_interests': []
            }
            
            # Топ категорий
            top_cats = self.categories.find({}, {'name': 1, 'usage_count': 1, '_id': 0}).sort('usage_count', -1).limit(10)
            stats['top_categories'] = list(top_cats)
            
            # Топ интересов
            top_ints = self.user_interests.find({}, {'name': 1, 'usage_count': 1, '_id': 0}).sort('usage_count', -1).limit(10)
            stats['top_interests'] = list(top_ints)
            
            return stats
            
        except Exception as e:
            logger.error(f"Ошибка получения статистики: {e}")
            return {}

