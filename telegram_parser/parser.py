"""
Основной модуль парсера Telegram-каналов.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

import os
from pathlib import Path
from pymongo import MongoClient, errors as mongo_errors
from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    ChannelPrivateError,
    ChannelInvalidError,
    RPCError,
    UserAlreadyParticipantError
)
from telethon.tl.types import MessageMediaPhoto
from telethon.tl.functions.messages import ImportChatInviteRequest

from .config import Config
from .filters import HashtagFilter
from .date_parser import DateParser

logger = logging.getLogger(__name__)


class TelegramParser:
    """Парсер для извлечения событий из Telegram-каналов."""
    
    def __init__(self, config: Config):
        """
        Инициализация парсера.
        
        Args:
            config: Объект конфигурации
        """
        self.config = config
        
        # Инициализация парсера дат
        self.date_parser = DateParser()
        
        # Словарь фильтров для каждого канала
        self.channel_filters: Dict[str, HashtagFilter] = {}
        
        # Клиенты
        self.telegram_client: Optional[TelegramClient] = None
        self.mongo_client: Optional[MongoClient] = None
        self.collection = None
        
        # Статистика
        self.stats = {
            'total_posts': 0,
            'saved_posts': 0,
            'filtered_hashtags': 0,
            'filtered_date': 0,
            'filtered_no_date': 0,
            'duplicates': 0,
            'errors': 0,
            'skipped_no_text': 0
        }
        
        # Статистика по каждому каналу
        self.channel_stats: Dict[str, Dict[str, int]] = {}
    
    def _init_mongodb(self):
        """Инициализация подключения к MongoDB."""
        try:
            self.mongo_client = MongoClient(
                self.config.MONGODB_URI,
                serverSelectionTimeoutMS=5000
            )
            # Проверка подключения
            self.mongo_client.server_info()
            
            db = self.mongo_client[self.config.MONGODB_DB_NAME]
            self.collection = db['raw_posts']
            
            # Создание индекса для предотвращения дубликатов
            self.collection.create_index('post_id', unique=True)
            
            logger.info(f"Подключение к MongoDB успешно: {self.config.MONGODB_DB_NAME}")
        except mongo_errors.ServerSelectionTimeoutError:
            logger.error("Не удалось подключиться к MongoDB: timeout")
            raise
        except Exception as e:
            logger.error(f"Ошибка подключения к MongoDB: {e}")
            raise
    
    async def _init_telegram_client(self):
        """Инициализация Telegram-клиента."""
        try:
            self.telegram_client = TelegramClient(
                self.config.TG_SESSION_NAME,
                int(self.config.TG_API_ID),
                self.config.TG_API_HASH
            )
            
            await self.telegram_client.start()
            
            if await self.telegram_client.is_user_authorized():
                me = await self.telegram_client.get_me()
                logger.info(f"Авторизован как: {me.first_name} (@{me.username})")
            else:
                logger.warning("Клиент не авторизован")
            
        except Exception as e:
            logger.error(f"Ошибка инициализации Telegram-клиента: {e}")
            raise
    
    def _extract_photo_info(self, message) -> Optional[Dict[str, Any]]:
        """
        Извлечение информации о фото из сообщения.
        
        Args:
            message: Объект сообщения Telethon
            
        Returns:
            Словарь с информацией о фото или None
        """
        if not message.media or not isinstance(message.media, MessageMediaPhoto):
            return None
        
        photo = message.media.photo
        if not photo:
            return None
        
        photo_info = {
            'photo_id': photo.id,
            'access_hash': photo.access_hash,
            'date': photo.date
        }
        
        # Информация о размерах
        if hasattr(photo, 'sizes') and photo.sizes:
            max_size = photo.sizes[-1]
            if hasattr(max_size, 'w') and hasattr(max_size, 'h'):
                photo_info['width'] = max_size.w
                photo_info['height'] = max_size.h
        
        return photo_info
    
    def _build_post_url(self, channel_username: str, message_id: int) -> str:
        """
        Построение URL поста в Telegram.
        
        Args:
            channel_username: Username канала
            message_id: ID сообщения
            
        Returns:
            URL поста
        """
        username = channel_username.lstrip('@')
        return f"https://t.me/{username}/{message_id}"
    
    def _get_channel_filter(self, channel_username: str) -> HashtagFilter:
        """
        Получение или создание фильтра для канала.
        
        Args:
            channel_username: Username канала
            
        Returns:
            Объект HashtagFilter для канала
        """
        if channel_username not in self.channel_filters:
            # Получение фильтров для конкретного канала
            filters = self.config.get_channel_filters(channel_username)
            self.channel_filters[channel_username] = HashtagFilter(
                whitelist=filters['whitelist'],
                blacklist=filters['blacklist']
            )
        
        return self.channel_filters[channel_username]
    
    async def _download_photo(self, message, channel_username: str) -> Optional[str]:
        """Скачивает фото из сообщения, сохраняет в images/{channel}, возвращает относительный путь или None."""
        if not message.media or not isinstance(message.media, MessageMediaPhoto):
            return None
        photo = message.media.photo
        if not photo:
            return None
        images_dir = Path('images') / channel_username
        images_dir.mkdir(parents=True, exist_ok=True)
        file_name = f'{message.id}_{photo.id}.jpg'
        file_path = images_dir / file_name
        if file_path.exists():
            return str(file_path)
        await self.telegram_client.download_media(message, file=str(file_path))
        return str(file_path)
    
    async def _process_post(
        self,
        message,
        channel_username: str,
        original_channel: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Обработка и фильтрация поста.
        
        Args:
            message: Объект сообщения Telethon
            channel_username: Username канала (может быть ID)
            original_channel: Оригинальный username канала для статистики
            
        Returns:
            Словарь с данными поста или None если пост отфильтрован
        """
        text = message.text or ''
        
        # Извлечение хештегов
        hashtags = HashtagFilter.extract_hashtags(text)
        
        # Получение фильтра для конкретного канала
        channel_filter = self._get_channel_filter(channel_username)
        
        # Проверка фильтра по хештегам
        should_filter, filter_reason = channel_filter.should_filter(hashtags)
        if should_filter:
            logger.info(f"Пост {message.id} отфильтрован по хештегам: {filter_reason} | хештеги: {hashtags}")
            self.stats['filtered_hashtags'] += 1
            if original_channel and original_channel in self.channel_stats:
                self.channel_stats[original_channel]['filtered_hashtags'] += 1
            return None  # Не сохраняем отфильтрованные посты
        
        # Парсинг даты из текста
        event_date = self.date_parser.parse_date(text)
        
        # Если дата не найдена — фильтруем пост
        if not event_date:
            text_preview = text[:100] + '...' if len(text) > 100 else text
            logger.info(f"Пост {message.id}: дата не найдена | текст: {text_preview}")
            self.stats['filtered_no_date'] += 1
            if original_channel and original_channel in self.channel_stats:
                self.channel_stats[original_channel]['filtered_no_date'] += 1
            return None  # Не сохраняем посты без даты
        
        # Проверка, что дата в будущем или сегодня
        if not self.date_parser.is_date_valid(event_date):
            text_preview = text[:100] + '...' if len(text) > 100 else text
            logger.info(f"Пост {message.id}: дата события в прошлом ({event_date.date()}) | текст: {text_preview}")
            self.stats['filtered_date'] += 1
            if original_channel and original_channel in self.channel_stats:
                self.channel_stats[original_channel]['filtered_date'] += 1
            return None  # Не сохраняем посты с датой в прошлом
        
        # Пост прошел все фильтры
        text_preview = text[:100] + '...' if len(text) > 100 else text
        logger.info(f"✅ Пост {message.id} прошел фильтры | дата события: {event_date.date()} | хештеги: {hashtags} | текст: {text_preview}")
        # Скачиваем фото, если есть 
        photo_path = await self._download_photo(message, channel_username)
        post_data = {
            'post_id': message.id,
            'channel': channel_username,
            'text': text,
            'date_parsed': event_date,
            'hashtags': hashtags,
            'photo_url': photo_path,
            'views': getattr(message, 'views', None),
            'forwards': getattr(message, 'forwards', None),
            'message_date': message.date,
            'parsed_at': datetime.utcnow()
        }
        return post_data
    
    async def _save_post(self, post_data: Dict[str, Any]) -> bool:
        """
        Сохранение валидного поста в MongoDB.
        
        Args:
            post_data: Словарь с данными поста
            
        Returns:
            True если пост сохранен успешно, False если уже существует
        """
        try:
            self.collection.insert_one(post_data)
            logger.info(f"Пост {post_data['post_id']} сохранен: {post_data.get('date_parsed')}")
            self.stats['saved_posts'] += 1
            return True
        except mongo_errors.DuplicateKeyError:
            logger.debug(f"Пост {post_data['post_id']} уже существует (дубликат)")
            self.stats['duplicates'] += 1
            return False
        except Exception as e:
            logger.error(f"Ошибка сохранения поста {post_data['post_id']}: {e}")
            self.stats['errors'] += 1
            return False
    
    async def parse_channel(self, channel_username: str) -> int:
        """
        Парсинг постов из канала за последние N месяцев.
        
        Args:
            channel_username: Username канала или invite hash (+hash для приватных)
            
        Returns:
            Количество сохраненных постов
        """
        saved_count = 0
        
        # Инициализация статистики для канала
        self.channel_stats[channel_username] = {
            'total': 0,
            'saved': 0,
            'filtered_hashtags': 0,
            'filtered_date': 0,
            'filtered_no_date': 0,
            'skipped_no_text': 0,
            'duplicates': 0
        }
        
        try:
            # Для приватных каналов (invite hash) может потребоваться присоединение
            if channel_username.startswith('+'):
                channel = None
                
                try:
                    # Попытка получить entity напрямую по hash (работает если уже кэшировано)
                    channel = await self.telegram_client.get_entity(channel_username)
                    logger.info(f"Канал найден в кэше")
                except ValueError:
                    # Entity не найден, нужно присоединиться или получить из диалогов
                    logger.info(f"Поиск приватного канала: {channel_username}")
                    
                    try:
                        # Пытаемся присоединиться
                        result = await self.telegram_client(ImportChatInviteRequest(channel_username[1:]))
                        logger.info(f"Успешно присоединились к каналу")
                        # Получаем entity из результата присоединения
                        channel = result.chats[0]
                    except UserAlreadyParticipantError:
                        # Уже участники - нужно найти канал в диалогах
                        logger.info(f"Вы уже являетесь участником канала, поиск в диалогах...")
                        
                        # Ищем канал по hash в наших диалогах
                        async for dialog in self.telegram_client.iter_dialogs():
                            if dialog.entity and hasattr(dialog.entity, 'username'):
                                # Пропускаем каналы с username
                                continue
                            # Проверяем приватные каналы/чаты
                            try:
                                # Получаем invite link этого чата
                                if hasattr(dialog.entity, 'id'):
                                    # Это может быть наш канал, сохраняем его
                                    # Telethon не предоставляет прямой способ сопоставить hash с каналом
                                    # поэтому сохраним первый приватный канал
                                    # Лучше использовать полную ссылку или ID
                                    channel = dialog.entity
                                    break
                            except:
                                continue
                        
                        if not channel:
                            raise ValueError(
                                f"Не удалось найти канал {channel_username}. "
                                f"Попробуйте использовать ID канала вместо invite hash, "
                                f"или откройте канал в Telegram перед запуском парсера."
                            )
                    except Exception as e:
                        logger.error(f"Ошибка при работе с приватным каналом: {e}")
                        raise
            else:
                # Обычный публичный канал или ID канала
                # Если это отрицательное число (ID), преобразуем в int
                if channel_username.startswith('-') and channel_username[1:].isdigit():
                    # Это ID канала, преобразуем в int
                    channel = await self.telegram_client.get_entity(int(channel_username))
                else:
                    # Это username
                    channel = await self.telegram_client.get_entity(channel_username)
            
            # Определяем удобное имя для логов
            channel_display = getattr(channel, 'title', channel_username)
            channel_id = getattr(channel, 'id', 'unknown')
            
            logger.info(f"Начинаем парсинг канала: {channel_display} (ID: {channel_id})")
            
            # Вычисление даты начала парсинга (N месяцев назад)
            months_back = self.config.MONTHS_BACK
            # Используем utcnow() для timezone-aware datetime (Telethon использует UTC)
            from datetime import timezone
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=months_back * 30)
            
            logger.info(f"Парсинг постов с {cutoff_date.date()} (последние {months_back} мес.)")
            
            # Получение сообщений за период
            # iter_messages по умолчанию идет от новых к старым
            messages = []
            async for message in self.telegram_client.iter_messages(channel):
                # message.date от Telethon уже в UTC с timezone
                # Прерываем если сообщение старше cutoff_date
                if message.date < cutoff_date:
                    break
                
                messages.append(message)
            
            logger.info(f"Получено {len(messages)} сообщений из канала")
            self.stats['total_posts'] += len(messages)
            self.channel_stats[channel_username]['total'] = len(messages)
            
            # Используем ID канала или username для идентификации
            channel_identifier = channel_username if not channel_username.startswith('+') else str(channel_id)
            
            # Обработка каждого сообщения
            for message in messages:
                # Пропуск сервисных сообщений
                if not message.text:
                    logger.debug(f"Пропуск сообщения {message.id}: нет текста")
                    self.stats['skipped_no_text'] += 1
                    self.channel_stats[channel_username]['skipped_no_text'] += 1
                    continue
                
                # Обработка поста
                post_data = await self._process_post(message, channel_identifier, channel_username)
                
                # Если пост прошел фильтры (не None), сохраняем его
                if post_data:
                    is_saved = await self._save_post(post_data)
                    
                    if is_saved:
                        self.channel_stats[channel_username]['saved'] += 1
                    else:
                        # Дубликат
                        self.channel_stats[channel_username]['duplicates'] += 1
            
            logger.info(f"Парсинг канала {channel_display} завершен")
            logger.info(f"  Статистика: обработано={self.channel_stats[channel_username]['total']}, "
                       f"сохранено={self.channel_stats[channel_username]['saved']}, "
                       f"отфильтровано по хештегам={self.channel_stats[channel_username]['filtered_hashtags']}, "
                       f"отфильтровано по дате={self.channel_stats[channel_username]['filtered_date']}, "
                       f"без даты={self.channel_stats[channel_username]['filtered_no_date']}")
            
        except FloodWaitError as e:
            wait_seconds = e.seconds
            logger.warning(f"Rate limit для {channel_username}. Ожидание {wait_seconds} сек")
            await asyncio.sleep(wait_seconds)
            # Рекурсивный вызов после ожидания
            return await self.parse_channel(channel_username)
        
        except ChannelPrivateError:
            logger.error(f"Канал приватный или недоступен: {channel_username}")
            logger.error(f"Убедитесь, что вы присоединились к каналу")
            raise
        
        except ChannelInvalidError:
            logger.error(f"Некорректный идентификатор канала: {channel_username}")
            logger.error(f"Проверьте формат: username, +hash, или t.me/...")
            raise
        
        except RPCError as e:
            logger.error(f"Ошибка RPC при парсинге канала: {e}")
            raise
        
        except Exception as e:
            logger.error(
                f"Неожиданная ошибка при парсинге канала {channel_username}: {e}",
                exc_info=True
            )
            raise
        
        return saved_count
    
    async def parse_all_channels(self) -> Dict[str, int]:
        """
        Парсинг всех каналов из конфигурации.
        
        Returns:
            Словарь с результатами парсинга по каждому каналу
        """
        channels = self.config.get_channels()
        results = {}
        
        for channel_username in channels:
            try:
                logger.info(f"=" * 60)
                saved = await self.parse_channel(channel_username)
                results[channel_username] = saved
            except Exception as e:
                logger.error(f"Ошибка парсинга канала {channel_username}: {e}")
                results[channel_username] = 0
        
        return results
    
    def _print_stats(self):
        """Вывод статистики парсинга."""
        logger.info("=" * 60)
        logger.info("📊 СТАТИСТИКА ПАРСИНГА:")
        logger.info(f"  Всего сообщений получено: {self.stats['total_posts']}")
        logger.info(f"  ⏭️  Пропущено (нет текста): {self.stats['skipped_no_text']}")
        logger.info(f"  ✅ Сохранено валидных постов: {self.stats['saved_posts']}")
        logger.info(f"  ❌ Отфильтровано по хештегам: {self.stats['filtered_hashtags']}")
        logger.info(f"  ❌ Отфильтровано по дате (прошлое): {self.stats['filtered_date']}")
        logger.info(f"  ❌ Без даты в тексте: {self.stats['filtered_no_date']}")
        logger.info(f"  ⏭️  Дубликаты: {self.stats['duplicates']}")
        logger.info(f"  ⚠️  Ошибки: {self.stats['errors']}")
        logger.info("=" * 60)
    
    async def run(self):
        """Основной метод запуска парсера."""
        try:
            logger.info("=" * 60)
            logger.info("🚀 ЗАПУСК TELEGRAM ПАРСЕРА")
            logger.info("=" * 60)
            
            # Вывод конфигурации
            channels = self.config.get_channels()
            logger.info(f"Каналы: {', '.join(channels)}")
            
            # Глобальные фильтры
            global_whitelist = self.config.get_whitelist_hashtags()
            global_blacklist = self.config.get_blacklist_hashtags()
            
            if global_whitelist:
                logger.info(f"Глобальный whitelist: {', '.join(global_whitelist)}")
            if global_blacklist:
                logger.info(f"Глобальный blacklist: {', '.join(global_blacklist)}")
            
            # Специфичные фильтры для каждого канала
            for channel in channels:
                channel_whitelist = self.config.get_whitelist_hashtags(channel)
                channel_blacklist = self.config.get_blacklist_hashtags(channel)
                
                # Показываем только если отличаются от глобальных
                if channel_whitelist != global_whitelist or channel_blacklist != global_blacklist:
                    logger.info(f"Фильтры для канала {channel}:")
                    if channel_whitelist:
                        logger.info(f"  • whitelist: {', '.join(channel_whitelist)}")
                    if channel_blacklist:
                        logger.info(f"  • blacklist: {', '.join(channel_blacklist)}")
            
            logger.info(f"Период парсинга: последние {self.config.MONTHS_BACK} месяцев")
            logger.info("=" * 60)
            
            # Инициализация
            self._init_mongodb()
            await self._init_telegram_client()
            
            # Парсинг всех каналов
            results = await self.parse_all_channels()
            
            # Статистика
            self._print_stats()
            
            logger.info("✅ ПАРСИНГ ЗАВЕРШЕН УСПЕШНО")
            
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}", exc_info=True)
            raise
        
        finally:
            await self.cleanup()
    
    async def cleanup(self):
        """Корректное закрытие всех соединений."""
        logger.info("Закрытие соединений...")
        
        if self.telegram_client:
            try:
                await self.telegram_client.disconnect()
                logger.info("Telegram клиент отключен")
            except Exception as e:
                logger.error(f"Ошибка при отключении Telegram: {e}")
        
        if self.mongo_client:
            try:
                self.mongo_client.close()
                logger.info("MongoDB соединение закрыто")
            except Exception as e:
                logger.error(f"Ошибка при закрытии MongoDB: {e}")

