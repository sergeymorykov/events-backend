"""
Модуль конфигурации парсера.
Загружает и валидирует переменные окружения.
"""

import os
from typing import List, Optional, Dict, Tuple
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()


class Config:
    """Конфигурация парсера из переменных окружения."""
    
    # Telegram API
    TG_API_ID: str = os.getenv('TG_API_ID', '')
    TG_API_HASH: str = os.getenv('TG_API_HASH', '')
    TG_SESSION_NAME: str = os.getenv('TG_SESSION_NAME', 'telegram_parser_session')
    
    # Каналы для парсинга (через запятую)
    CHANNEL_USERNAME: str = os.getenv('CHANNEL_USERNAME', '')
    
    # Период парсинга (сколько месяцев назад искать посты)
    MONTHS_BACK: int = int(os.getenv('MONTHS_BACK', '3'))
    
    # Глобальные фильтры по хештегам (по умолчанию для всех каналов)
    HASHTAG_WHITELIST: str = os.getenv('HASHTAG_WHITELIST', '')
    HASHTAG_BLACKLIST: str = os.getenv('HASHTAG_BLACKLIST', '')
    
    # MongoDB
    MONGODB_URI: str = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/')
    MONGODB_DB_NAME: str = os.getenv('MONGODB_DB_NAME', 'events_db')
    
    @classmethod
    def get_channels(cls) -> List[str]:
        """
        Получение списка каналов для парсинга.
        
        Поддерживает:
        - Публичные каналы: username (с @ или без)
        - Приватные каналы по ID: -1001234567890 или 1234567890
        - Приватные каналы по hash: +hash
        - Полные ссылки: t.me/channel или t.me/+hash
        
        Returns:
            Список идентификаторов каналов
        """
        if not cls.CHANNEL_USERNAME:
            return []
        
        channels = []
        for ch in cls.CHANNEL_USERNAME.split(','):
            ch = ch.strip()
            if not ch:
                continue
            
            # Обработка полных ссылок t.me/...
            if 't.me/' in ch:
                # Извлекаем часть после t.me/
                ch = ch.split('t.me/')[-1]
            
            # Убираем @ для публичных каналов, но сохраняем + и - для приватных
            if ch.startswith('@'):
                ch = ch[1:]
            
            # Если это число без минуса, добавляем префикс -100
            # ID каналов всегда начинаются с -100
            if ch.isdigit():
                ch = f'-100{ch}'
            
            channels.append(ch)
        
        return [ch for ch in channels if ch]
    
    @classmethod
    def _parse_hashtag_list(cls, value: str) -> Optional[List[str]]:
        """
        Парсинг списка хештегов из строки.
        
        Args:
            value: Строка с хештегами через запятую
            
        Returns:
            Список хештегов в нижнем регистре или None если пусто
        """
        if not value:
            return None
        
        # Разделение по запятой, очистка и приведение к нижнему регистру
        hashtags = [ht.strip().lstrip('#').lower() for ht in value.split(',')]
        return [ht for ht in hashtags if ht] or None
    
    @classmethod
    def get_whitelist_hashtags(cls, channel: Optional[str] = None) -> Optional[List[str]]:
        """
        Получение списка разрешенных хештегов для канала.
        
        Args:
            channel: Username канала или +hash. Если None - вернет глобальный whitelist
        
        Returns:
            Список хештегов в нижнем регистре или None если не задан
        """
        # Сначала проверяем специфичный whitelist для канала
        if channel:
            # Нормализуем имя канала (убираем + для приватных)
            normalized_channel = cls._normalize_channel_name_for_env(channel)
            channel_key = f'CHANNEL_{normalized_channel}_WHITELIST'
            channel_whitelist = os.getenv(channel_key, '')
            if channel_whitelist:
                return cls._parse_hashtag_list(channel_whitelist)
        
        # Если нет специфичного, используем глобальный
        return cls._parse_hashtag_list(cls.HASHTAG_WHITELIST)
    
    @classmethod
    def get_blacklist_hashtags(cls, channel: Optional[str] = None) -> Optional[List[str]]:
        """
        Получение списка запрещенных хештегов для канала.
        
        Args:
            channel: Username канала или +hash. Если None - вернет глобальный blacklist
        
        Returns:
            Список хештегов в нижнем регистре или None если не задан
        """
        # Сначала проверяем специфичный blacklist для канала
        if channel:
            # Нормализуем имя канала (убираем + для приватных)
            normalized_channel = cls._normalize_channel_name_for_env(channel)
            channel_key = f'CHANNEL_{normalized_channel}_BLACKLIST'
            channel_blacklist = os.getenv(channel_key, '')
            if channel_blacklist:
                return cls._parse_hashtag_list(channel_blacklist)
        
        # Если нет специфичного, используем глобальный
        return cls._parse_hashtag_list(cls.HASHTAG_BLACKLIST)
    
    @classmethod
    def _normalize_channel_name_for_env(cls, channel: str) -> str:
        """
        Нормализация имени канала для использования в переменных окружения.
        
        Для приватных каналов убирает + в начале и - для ID.
        Переменные окружения не могут начинаться с + или -.
        
        Args:
            channel: Идентификатор канала (username, +hash, или -ID)
            
        Returns:
            Нормализованное имя для переменной окружения
        """
        # Убираем + для приватных каналов (invite hash)
        if channel.startswith('+'):
            return channel[1:]
        
        # Убираем - и 100 для ID каналов (-1001234567890 -> 1234567890)
        if channel.startswith('-'):
            clean_id = channel[1:]  # Убираем минус
            # Убираем 100 в начале если есть
            if clean_id.startswith('100'):
                return clean_id[3:]
            return clean_id
        
        return channel
    
    @classmethod
    def get_channel_filters(cls, channel: str) -> Dict[str, Optional[List[str]]]:
        """
        Получение всех фильтров для конкретного канала.
        
        Args:
            channel: Username канала или +hash (для приватных)
            
        Returns:
            Словарь с whitelist и blacklist для канала
        """
        return {
            'whitelist': cls.get_whitelist_hashtags(channel),
            'blacklist': cls.get_blacklist_hashtags(channel)
        }
    
    @classmethod
    def validate(cls) -> Tuple[bool, str]:
        """
        Валидация обязательных параметров конфигурации.
        
        Returns:
            Кортеж (успех, сообщение об ошибке)
        """
        if not cls.TG_API_ID or not cls.TG_API_HASH:
            return False, "TG_API_ID и TG_API_HASH должны быть указаны"
        
        if not cls.CHANNEL_USERNAME:
            return False, "CHANNEL_USERNAME должен быть указан"
        
        channels = cls.get_channels()
        if not channels:
            return False, "Не удалось распарсить список каналов из CHANNEL_USERNAME"
        
        return True, ""

