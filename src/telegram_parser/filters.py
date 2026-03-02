"""
Модуль фильтрации постов по хештегам.
"""

import re
from typing import List, Optional, Tuple


class HashtagFilter:
    """Фильтр постов по хештегам."""
    
    # Регулярное выражение для извлечения хештегов (регистронезависимо)
    HASHTAG_PATTERN = re.compile(r'#([\w\d_]+)', re.IGNORECASE | re.UNICODE)
    
    def __init__(
        self,
        whitelist: Optional[List[str]] = None,
        blacklist: Optional[List[str]] = None
    ):
        """
        Инициализация фильтра.
        
        Args:
            whitelist: Список разрешенных хештегов (в нижнем регистре)
            blacklist: Список запрещенных хештегов (в нижнем регистре)
        """
        self.whitelist = set(whitelist) if whitelist else None
        self.blacklist = set(blacklist) if blacklist else None
    
    @staticmethod
    def extract_hashtags(text: str) -> List[str]:
        """
        Извлечение всех хештегов из текста.
        
        Args:
            text: Текст поста
            
        Returns:
            Список хештегов в нижнем регистре (без #)
        """
        if not text:
            return []
        
        # Извлечение хештегов и приведение к нижнему регистру
        hashtags = HashtagFilter.HASHTAG_PATTERN.findall(text)
        return [ht.lower() for ht in hashtags]
    
    def should_filter(self, hashtags: List[str]) -> Tuple[bool, Optional[str]]:
        """
        Проверка, нужно ли отфильтровать пост.
        
        Args:
            hashtags: Список хештегов поста (в нижнем регистре)
            
        Returns:
            Кортеж (нужно_отфильтровать, причина)
        """
        if not hashtags:
            # Если нет хештегов и задан whitelist — фильтруем
            if self.whitelist:
                return True, "no_hashtags_with_whitelist"
            return False, None
        
        hashtags_set = set(hashtags)
        
        # Проверка blacklist (приоритет выше)
        if self.blacklist:
            blacklisted = hashtags_set & self.blacklist
            if blacklisted:
                return True, f"blacklist:{','.join(blacklisted)}"
        
        # Проверка whitelist
        if self.whitelist:
            whitelisted = hashtags_set & self.whitelist
            if not whitelisted:
                return True, "not_in_whitelist"
        
        return False, None

