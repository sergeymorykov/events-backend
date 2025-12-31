"""
Скрипт для скачивания фото из постов, сохраненных в MongoDB.
Использует информацию из photo_info для скачивания файлов через Telethon.
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pymongo import MongoClient
from telethon import TelegramClient
from telethon.tl.types import InputPhotoFileLocation

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('download_photos.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class PhotoDownloader:
    """Загрузчик фото из Telegram постов."""
    
    def __init__(self):
        """Инициализация загрузчика."""
        # Telegram API credentials
        self.api_id = os.getenv('TG_API_ID')
        self.api_hash = os.getenv('TG_API_HASH')
        self.session_name = os.getenv('TELEGRAM_SESSION_NAME', 'telegram_parser_session')
        
        # MongoDB credentials
        self.mongo_uri = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/')
        self.db_name = os.getenv('MONGODB_DB_NAME', 'events_db')
        
        # Директория для сохранения фото
        self.download_dir = Path(os.getenv('PHOTOS_DIR', 'downloaded_photos'))
        self.download_dir.mkdir(exist_ok=True)
        
        # Клиенты
        self.client: Optional[TelegramClient] = None
        self.mongo_client: Optional[MongoClient] = None
        self.collection = None
    
    def _init_mongodb(self):
        """Инициализация подключения к MongoDB."""
        try:
            self.mongo_client = MongoClient(self.mongo_uri, serverSelectionTimeoutMS=5000)
            self.mongo_client.server_info()
            
            db = self.mongo_client[self.db_name]
            self.collection = db['raw_posts']
            
            logger.info(f"Подключение к MongoDB успешно: {self.db_name}")
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
            
            if await self.client.is_user_authorized():
                me = await self.client.get_me()
                logger.info(f"Авторизован как: {me.first_name}")
            
        except Exception as e:
            logger.error(f"Ошибка инициализации Telegram-клиента: {e}")
            raise
    
    async def download_photo(self, post_id: int, photo_info: dict) -> Optional[str]:
        """
        Скачивание фото по информации из поста.
        
        Args:
            post_id: ID поста
            photo_info: Словарь с информацией о фото
            
        Returns:
            Путь к скачанному файлу или None
        """
        try:
            # Создание директории для канала
            channel_dir = self.download_dir / self.collection.find_one({'post_id': post_id})['channel_username']
            channel_dir.mkdir(exist_ok=True)
            
            # Имя файла
            filename = f"post_{post_id}_photo_{photo_info['photo_id']}.jpg"
            file_path = channel_dir / filename
            
            # Проверка, не скачан ли уже файл
            if file_path.exists():
                logger.debug(f"Файл уже существует: {file_path}")
                return str(file_path)
            
            # Создание InputPhotoFileLocation для скачивания
            location = InputPhotoFileLocation(
                id=photo_info['photo_id'],
                access_hash=photo_info['access_hash'],
                file_reference=bytes.fromhex(photo_info['file_reference']) if photo_info.get('file_reference') else b'',
                thumb_size='x'  # 'x' - максимальный размер
            )
            
            # Скачивание файла
            await self.client.download_file(location, file=str(file_path))
            
            logger.info(f"Фото скачано: {file_path}")
            return str(file_path)
            
        except Exception as e:
            logger.error(f"Ошибка скачивания фото для поста {post_id}: {e}")
            return None
    
    async def download_all_photos(self, limit: Optional[int] = None):
        """
        Скачивание всех фото из постов в БД.
        
        Args:
            limit: Максимальное количество фото для скачивания (None = все)
        """
        try:
            # Получение постов с фото
            query = {'photo_info': {'$ne': None}}
            posts = list(self.collection.find(query).limit(limit if limit else 0))
            
            logger.info(f"Найдено постов с фото: {len(posts)}")
            
            downloaded_count = 0
            skipped_count = 0
            error_count = 0
            
            for post in posts:
                post_id = post['post_id']
                photo_info = post['photo_info']
                
                result = await self.download_photo(post_id, photo_info)
                
                if result:
                    downloaded_count += 1
                elif result is None and not Path(result or '').exists():
                    error_count += 1
                else:
                    skipped_count += 1
                
                # Небольшая задержка между скачиваниями
                await asyncio.sleep(0.5)
            
            logger.info(
                f"Скачивание завершено. Скачано: {downloaded_count}, "
                f"пропущено: {skipped_count}, ошибок: {error_count}"
            )
            
        except Exception as e:
            logger.error(f"Ошибка при скачивании фото: {e}", exc_info=True)
            raise
    
    async def run(self, limit: Optional[int] = None):
        """
        Основной метод запуска загрузчика.
        
        Args:
            limit: Максимальное количество фото для скачивания
        """
        try:
            logger.info("=== Запуск загрузчика фото ===")
            
            # Инициализация
            self._init_mongodb()
            await self._init_telegram_client()
            
            # Скачивание фото
            await self.download_all_photos(limit)
            
            logger.info("=== Загрузка завершена ===")
            
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}", exc_info=True)
            raise
        
        finally:
            await self.cleanup()
    
    async def cleanup(self):
        """Закрытие соединений."""
        logger.info("Закрытие соединений...")
        
        if self.client:
            await self.client.disconnect()
        
        if self.mongo_client:
            self.mongo_client.close()


async def main():
    """Точка входа."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Скачивание фото из Telegram постов')
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Максимальное количество фото для скачивания (по умолчанию: все)'
    )
    
    args = parser.parse_args()
    
    downloader = PhotoDownloader()
    await downloader.run(limit=args.limit)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Загрузчик остановлен пользователем")
    except Exception as e:
        logger.critical(f"Критическая ошибка: {e}", exc_info=True)
        exit(1)

