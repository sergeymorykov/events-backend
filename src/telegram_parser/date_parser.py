"""
Модуль парсинга дат из текста постов.
Поддерживает различные форматы дат на русском языке.
"""

import re
from datetime import datetime, timedelta
from typing import Optional, Match
import logging

logger = logging.getLogger(__name__)


class DateParser:
    """Парсер дат из текста постов."""
    
    # Месяцы на русском (в родительном падеже)
    MONTHS = {
        'января': 1, 'янв': 1,
        'февраля': 2, 'фев': 2, 'февр': 2,
        'марта': 3, 'мар': 3, 'март': 3,
        'апреля': 4, 'апр': 4,
        'мая': 5, 'май': 5,
        'июня': 6, 'июн': 6,
        'июля': 7, 'июл': 7,
        'августа': 8, 'авг': 8,
        'сентября': 9, 'сен': 9, 'сент': 9,
        'октября': 10, 'окт': 10,
        'ноября': 11, 'ноя': 11, 'нояб': 11,
        'декабря': 12, 'дек': 12,
    }
    
    # Паттерны для разных форматов дат
    PATTERNS = [
        # "23 ноября", "23 ноября 2025"
        (
            re.compile(r'(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря|янв|фев|мар|апр|май|июн|июл|авг|сен|окт|ноя|дек)(?:\s+(\d{4}))?', re.IGNORECASE),
            'day_month_year'
        ),
        # "10.12.2025", "10.12.25"
        (
            re.compile(r'(\d{1,2})\.(\d{1,2})\.(\d{2,4})'),
            'dmy_dots'
        ),
        # "2025-12-10"
        (
            re.compile(r'(\d{4})-(\d{1,2})-(\d{1,2})'),
            'ymd_dashes'
        ),
        # "10/12/2025"
        (
            re.compile(r'(\d{1,2})/(\d{1,2})/(\d{4})'),
            'dmy_slashes'
        ),
    ]
    
    # Паттерны для относительных дат
    RELATIVE_PATTERNS = [
        (re.compile(r'\bсегодня\b', re.IGNORECASE), 'today'),
        (re.compile(r'\bзавтра\b', re.IGNORECASE), 'tomorrow'),
        (re.compile(r'\bпослезавтра\b', re.IGNORECASE), 'day_after_tomorrow'),
    ]
    
    @staticmethod
    def parse_date(text: str) -> Optional[datetime]:
        """
        Парсинг даты из текста.
        
        Args:
            text: Текст поста
            
        Returns:
            Объект datetime или None если дата не найдена
        """
        if not text:
            return None
        
        # Проверка относительных дат
        for pattern, date_type in DateParser.RELATIVE_PATTERNS:
            if pattern.search(text):
                return DateParser._parse_relative_date(date_type)
        
        # Проверка абсолютных дат
        for pattern, format_type in DateParser.PATTERNS:
            match = pattern.search(text)
            if match:
                try:
                    result = DateParser._parse_absolute_date(match, format_type)
                    if result:
                        return result
                except Exception as e:
                    logger.debug(f"Ошибка парсинга даты '{match.group()}': {e}")
                    continue
        
        return None
    
    @staticmethod
    def _parse_relative_date(date_type: str) -> datetime:
        """
        Парсинг относительных дат (сегодня, завтра).
        
        Args:
            date_type: Тип даты ('today', 'tomorrow', 'day_after_tomorrow')
            
        Returns:
            Объект datetime
        """
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        if date_type == 'today':
            return today
        elif date_type == 'tomorrow':
            return today + timedelta(days=1)
        elif date_type == 'day_after_tomorrow':
            return today + timedelta(days=2)
        
        return today
    
    @staticmethod
    def _parse_absolute_date(match: Match, format_type: str) -> Optional[datetime]:
        """
        Парсинг абсолютных дат.
        
        Args:
            match: Объект совпадения регулярного выражения
            format_type: Тип формата даты
            
        Returns:
            Объект datetime или None
        """
        current_year = datetime.now().year
        
        try:
            if format_type == 'day_month_year':
                # "23 ноября" или "23 ноября 2025"
                day = int(match.group(1))
                month_str = match.group(2).lower()
                month = DateParser.MONTHS.get(month_str)
                year = int(match.group(3)) if match.group(3) else current_year
                
                if not month:
                    return None
                
                return datetime(year, month, day)
            
            elif format_type == 'dmy_dots':
                # "10.12.2025" или "10.12.25"
                day = int(match.group(1))
                month = int(match.group(2))
                year_str = match.group(3)
                
                # Если год двузначный, добавляем 2000
                year = int(year_str)
                if year < 100:
                    year += 2000
                
                return datetime(year, month, day)
            
            elif format_type == 'ymd_dashes':
                # "2025-12-10"
                year = int(match.group(1))
                month = int(match.group(2))
                day = int(match.group(3))
                
                return datetime(year, month, day)
            
            elif format_type == 'dmy_slashes':
                # "10/12/2025"
                day = int(match.group(1))
                month = int(match.group(2))
                year = int(match.group(3))
                
                return datetime(year, month, day)
        
        except (ValueError, IndexError) as e:
            logger.debug(f"Некорректная дата в тексте: {e}")
            return None
        
        return None
    
    @staticmethod
    def is_date_valid(event_date: datetime) -> bool:
        """
        Проверка, что дата события в будущем или сегодня.
        
        Args:
            event_date: Дата события
            
        Returns:
            True если дата валидна (сегодня или в будущем)
        """
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        event_date_normalized = event_date.replace(hour=0, minute=0, second=0, microsecond=0)
        
        return event_date_normalized >= today

