"""
Асинхронный парсер Telegram-каналов с использованием Telethon.
Извлекает посты из публичных каналов и сохраняет в MongoDB.
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from pymongo import MongoClient, errors as mongo_errors
from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    ChannelPrivateError,
    ChannelInvalidError,
    RPCError
)
from telethon.tl.types import MessageMediaPhoto

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('telegram_parser.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class TelegramParser:
    """Парсер для извлечения постов из Telegram-каналов."""
    
    def __init__(self):
        """Инициализация парсера с параметрами из переменных окружения."""
        # Telegram API credentials
        self.api_id = os.getenv('TELEGRAM_API_ID')
        self.api_hash = os.getenv('TELEGRAM_API_HASH')
        self.channel_username = os.getenv('TELEGRAM_CHANNEL_USERNAME')
        self.posts_limit = int(os.getenv('POSTS_LIMIT', '100'))
        
        # MongoDB credentials
        self.mongo_uri = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/')
        self.db_name = os.getenv('MONGODB_DB_NAME', 'events_db')
        
        # Session name для Telethon
        self.session_name = os.getenv('TELEGRAM_SESSION_NAME', 'telegram_parser_session')
        
        self._validate_config()
        
        # Инициализация клиентов
        self.client: Optional[TelegramClient] = None
        self.mongo_client: Optional[MongoClient] = None
        self.db = None
        self.collection = None
    
    def _validate_config(self):
        """Валидация обязательных параметров конфигурации."""
        if not self.api_id or not self.api_hash:
            raise ValueError(
                "TELEGRAM_API_ID и TELEGRAM_API_HASH должны быть указаны в переменных окружения"
            )
        
        if not self.channel_username:
            raise ValueError(
                "TELEGRAM_CHANNEL_USERNAME должен быть указан в переменных окружения"
            )
        
        logger.info(f"Конфигурация загружена: канал={self.channel_username}, лимит={self.posts_limit}")
    
    def _init_mongodb(self):
        """Инициализация подключения к MongoDB."""
        try:
            self.mongo_client = MongoClient(self.mongo_uri, serverSelectionTimeoutMS=5000)
            # Проверка подключения
            self.mongo_client.server_info()
            
            self.db = self.mongo_client[self.db_name]
            self.collection = self.db['raw_posts']
            
            # Создание индекса для предотвращения дубликатов
            self.collection.create_index('post_id', unique=True)
            
            logger.info(f"Успешное подключение к MongoDB: {self.db_name}")
        except mongo_errors.ServerSelectionTimeoutError:
            logger.error("Не удалось подключиться к MongoDB: timeout")
            raise
        except Exception as e:
            logger.error(f"Ошибка подключения к MongoDB: {e}")
            raise
    
    async def _init_telegram_client(self):
        """Инициализация Telegram-клиента."""
        try:
            self.client = TelegramClient(
                self.session_name,
                int(self.api_id),
                self.api_hash
            )
            
            await self.client.start()
            
            # Проверка авторизации
            if await self.client.is_user_authorized():
                me = await self.client.get_me()
                logger.info(f"Авторизован как: {me.first_name} (@{me.username})")
            else:
                logger.warning("Клиент не авторизован")
            
        except Exception as e:
            logger.error(f"Ошибка инициализации Telegram-клиента: {e}")
            raise
    
    def _extract_photo_info(self, message) -> Optional[dict]:
        """
        Извлечение информации о фото из сообщения.
        
        Args:
            message: Объект сообщения Telethon
            
        Returns:
            Словарь с информацией о фото или None
        """
        if not message.media:
            return None
        
        if not isinstance(message.media, MessageMediaPhoto):
            return None
        
        photo = message.media.photo
        if not photo:
            return None
        
        # Получаем информацию о максимальном размере
        photo_info = {
            'photo_id': photo.id,
            'access_hash': photo.access_hash,
            'file_reference': photo.file_reference.hex() if hasattr(photo, 'file_reference') else None,
            'date': photo.date,
            'has_stickers': photo.has_stickers if hasattr(photo, 'has_stickers') else False,
            'dc_id': photo.dc_id if hasattr(photo, 'dc_id') else None
        }
        
        # Информация о размерах
        if hasattr(photo, 'sizes') and photo.sizes:
            max_size = photo.sizes[-1]  # Максимальный размер всегда последний
            if hasattr(max_size, 'w') and hasattr(max_size, 'h'):
                photo_info['width'] = max_size.w
                photo_info['height'] = max_size.h
                photo_info['size_type'] = type(max_size).__name__
        
        return photo_info
    
    def _build_post_url(self, message_id: int) -> str:
        """
        Построение URL поста в Telegram.
        
        Args:
            message_id: ID сообщения
            
        Returns:
            URL поста
        """
        # Убираем @ если он есть в username
        username = self.channel_username.lstrip('@')
        return f"https://t.me/{username}/{message_id}"
    
    async def _save_post(self, post_data: dict) -> bool:
        """
        Сохранение поста в MongoDB.
        
        Args:
            post_data: Словарь с данными поста
            
        Returns:
            True если пост сохранен успешно, False если уже существует
        """
        try:
            self.collection.insert_one(post_data)
            logger.info(f"Пост {post_data['post_id']} успешно сохранен")
            return True
        except mongo_errors.DuplicateKeyError:
            logger.debug(f"Пост {post_data['post_id']} уже существует в БД, пропускаем")
            return False
        except Exception as e:
            logger.error(f"Ошибка сохранения поста {post_data['post_id']}: {e}")
            return False
    
    async def parse_channel(self) -> int:
        """
        Парсинг постов из канала.
        
        Returns:
            Количество новых сохраненных постов
        """
        saved_count = 0
        skipped_count = 0
        
        try:
            # Получение entity канала
            channel = await self.client.get_entity(self.channel_username)
            logger.info(f"Начинаем парсинг канала: {channel.title} (@{self.channel_username})")
            
            # Получение сообщений
            messages = []
            async for message in self.client.iter_messages(
                channel,
                limit=self.posts_limit
            ):
                messages.append(message)
            
            logger.info(f"Получено {len(messages)} сообщений из канала")
            
            # Обработка каждого сообщения
            for message in messages:
                # Извлечение информации о фото
                photo_info = self._extract_photo_info(message)
                
                # Извлечение данных
                post_data = {
                    'post_id': message.id,
                    'channel_username': self.channel_username,
                    'text': message.text or '',
                    'date': message.date,
                    'post_url': self._build_post_url(message.id),
                    'photo_info': photo_info,
                    'views': getattr(message, 'views', None),
                    'forwards': getattr(message, 'forwards', None),
                    'parsed_at': datetime.utcnow(),
                    'has_media': message.media is not None,
                    'media_type': type(message.media).__name__ if message.media else None
                }
                
                # Сохранение в БД
                if await self._save_post(post_data):
                    saved_count += 1
                else:
                    skipped_count += 1
            
            logger.info(
                f"Парсинг завершен. Сохранено новых постов: {saved_count}, "
                f"пропущено дубликатов: {skipped_count}"
            )
            
        except FloodWaitError as e:
            wait_seconds = e.seconds
            logger.warning(
                f"Достигнут rate limit. Необходимо подождать {wait_seconds} секунд"
            )
            logger.info(f"Ожидание {wait_seconds} секунд...")
            await asyncio.sleep(wait_seconds)
            # Рекурсивный вызов после ожидания
            return await self.parse_channel()
        
        except ChannelPrivateError:
            logger.error(f"Канал {self.channel_username} является приватным или недоступным")
            raise
        
        except ChannelInvalidError:
            logger.error(f"Некорректный username канала: {self.channel_username}")
            raise
        
        except RPCError as e:
            logger.error(f"Ошибка RPC при парсинге канала: {e}")
            raise
        
        except Exception as e:
            logger.error(f"Неожиданная ошибка при парсинге канала: {e}", exc_info=True)
            raise
        
        return saved_count
    
    async def run(self):
        """Основной метод запуска парсера."""
        try:
            logger.info("=== Запуск Telegram парсера ===")
            
            # Инициализация MongoDB
            self._init_mongodb()
            
            # Инициализация Telegram клиента
            await self._init_telegram_client()
            
            # Парсинг канала
            saved_posts = await self.parse_channel()
            
            logger.info(f"=== Парсинг завершен успешно. Сохранено постов: {saved_posts} ===")
            
        except Exception as e:
            logger.error(f"Критическая ошибка в процессе работы парсера: {e}", exc_info=True)
            raise
        
        finally:
            # Закрытие соединений
            await self.cleanup()
    
    async def cleanup(self):
        """Корректное закрытие всех соединений."""
        logger.info("Закрытие соединений...")
        
        if self.client:
            try:
                await self.client.disconnect()
                logger.info("Telegram клиент отключен")
            except Exception as e:
                logger.error(f"Ошибка при отключении Telegram клиента: {e}")
        
        if self.mongo_client:
            try:
                self.mongo_client.close()
                logger.info("MongoDB соединение закрыто")
            except Exception as e:
                logger.error(f"Ошибка при закрытии MongoDB соединения: {e}")


async def main():
    """Точка входа в приложение."""
    parser = TelegramParser()
    await parser.run()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Парсер остановлен пользователем")
    except Exception as e:
        logger.critical(f"Критическая ошибка: {e}", exc_info=True)
        exit(1)

