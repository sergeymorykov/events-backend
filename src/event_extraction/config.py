"""
Конфигурация event extraction модуля из переменных окружения.
"""

import os
import re
from typing import List, Tuple
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()


class EventExtractionConfig:
    """Конфигурация модуля извлечения событий."""
    
    # ===== LLM настройки =====
    LLM_BASE_URL: str = os.getenv('LLM_BASE_URL', 'https://api.mapleai.de/v1')
    LLM_MODEL_NAME: str = os.getenv('LLM_MODEL_NAME', 'gpt-4o')
    LLM_VISION_MODEL: str = os.getenv('LLM_VISION_MODEL', os.getenv('LLM_MODEL_NAME', 'gpt-4o'))
    LLM_TEMPERATURE: float = float(os.getenv('LLM_TEMPERATURE', '0.7'))
    LLM_MAX_TOKENS: int = int(os.getenv('LLM_MAX_TOKENS', '2000'))
    
    # ===== API ключи LLM =====
    @classmethod
    def get_api_keys(cls) -> List[str]:
        """Получение списка API ключей для ротации."""
        raw_keys = os.getenv("LLM_API_KEYS", "")
        api_keys: List[str] = []
        
        if raw_keys:
            # Поддержка разделителей: запятая, точка с запятой, перенос строки
            for chunk in re.split(r"[,\n;]", raw_keys):
                trimmed = chunk.strip()
                if trimmed and trimmed not in api_keys:
                    api_keys.append(trimmed)
        
        # Fallback на одиночный ключ
        single_key = os.getenv("LLM_API_KEY")
        if not api_keys and single_key:
            api_keys = [single_key]
        
        return api_keys
    
    # ===== Настройки генерации изображений (только LLM API) =====
    IMAGE_LLM_BASE_URL: str = os.getenv(
        'IMAGE_LLM_BASE_URL',
        os.getenv('LLM_BASE_URL', 'https://api.mapleai.de/v1')
    )
    IMAGE_LLM_MODEL: str = os.getenv('IMAGE_LLM_MODEL', 'dall-e-3')
    
    @classmethod
    def get_image_api_keys(cls) -> List[str]:
        """Получение списка API ключей для генерации изображений."""
        raw_keys = os.getenv('IMAGE_LLM_API_KEYS')
        
        if raw_keys:
            api_keys: List[str] = []
            for chunk in re.split(r"[,\n;]", raw_keys):
                trimmed = chunk.strip()
                if trimmed and trimmed not in api_keys:
                    api_keys.append(trimmed)
            return api_keys
        
        # Fallback на основные LLM ключи
        return cls.get_api_keys()
    
    # ===== Qdrant настройки =====
    QDRANT_HOST: str = os.getenv('QDRANT_HOST', 'localhost')
    QDRANT_PORT: int = int(os.getenv('QDRANT_PORT', '6333'))
    QDRANT_API_KEY: str = os.getenv('QDRANT_API_KEY', '')
    QDRANT_COLLECTION: str = os.getenv('QDRANT_COLLECTION', 'events')
    QDRANT_VECTOR_SIZE: int = int(os.getenv('QDRANT_VECTOR_SIZE', '1536'))  # OpenAI embeddings
    QDRANT_SIMILARITY_THRESHOLD: float = float(os.getenv('QDRANT_SIMILARITY_THRESHOLD', '0.92'))
    
    # ===== MongoDB настройки =====
    MONGODB_URI: str = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/')
    MONGODB_DB_NAME: str = os.getenv('MONGODB_DB_NAME', 'events_db')
    
    # ===== Telegram настройки =====
    TG_API_ID: str = os.getenv('TG_API_ID', '')
    TG_API_HASH: str = os.getenv('TG_API_HASH', '')
    TG_SESSION_NAME: str = os.getenv('TG_SESSION_NAME', 'telegram_parser_session')
    
    # ===== Настройки изображений =====
    IMAGES_DIR: str = os.getenv('IMAGES_DIR', 'images')
    
    # ===== Настройки обработки =====
    MAX_EVENTS_PER_POST: int = int(os.getenv('MAX_EVENTS_PER_POST', '5'))
    BATCH_SIZE: int = int(os.getenv('BATCH_SIZE', '10'))
    
    @classmethod
    def validate(cls) -> Tuple[bool, str]:
        """
        Валидация конфигурации.
        
        Returns:
            Кортеж (успех, сообщение об ошибке/предупреждении)
        """
        warnings = []
        
        # Проверка наличия API ключей
        api_keys = cls.get_api_keys()
        if not api_keys:
            return False, "LLM_API_KEY или LLM_API_KEYS должен быть указан"
        
        # Проверка base URL
        if not cls.LLM_BASE_URL:
            return False, "LLM_BASE_URL должен быть указан"
        
        # Проверка модели
        if not cls.LLM_MODEL_NAME:
            return False, "LLM_MODEL_NAME должен быть указан"
        
        # Проверка настроек генерации изображений
        image_keys = cls.get_image_api_keys()
        if not image_keys or not cls.IMAGE_LLM_MODEL:
            warnings.append(
                "ВНИМАНИЕ: Настройки генерации изображений неполные. "
                "Генерация афиш может быть недоступна."
            )
        
        # Проверка Qdrant (опционально)
        if not cls.QDRANT_HOST:
            warnings.append(
                "ВНИМАНИЕ: QDRANT_HOST не указан. "
                "Семантическая дедупликация будет недоступна."
            )
        
        # Проверка Telegram (опционально)
        if not cls.TG_API_ID or not cls.TG_API_HASH:
            warnings.append(
                "ВНИМАНИЕ: Telegram API не настроен. "
                "Скачивание фото из Telegram будет недоступно."
            )
        
        # Возвращаем успех с предупреждениями
        if warnings:
            return True, "\n".join(warnings)
        
        return True, ""
    
    @classmethod
    def print_config(cls):
        """Вывод конфигурации (без секретов)."""
        api_keys = cls.get_api_keys()
        image_keys = cls.get_image_api_keys()
        
        print("=" * 60)
        print("КОНФИГУРАЦИЯ EVENT EXTRACTION:")
        print(f"  LLM Base URL: {cls.LLM_BASE_URL}")
        print(f"  LLM Model: {cls.LLM_MODEL_NAME}")
        print(f"  Vision Model: {cls.LLM_VISION_MODEL}")
        print(f"  Temperature: {cls.LLM_TEMPERATURE}")
        print(f"  Max Tokens: {cls.LLM_MAX_TOKENS}")
        print(f"  API Keys: {len(api_keys)} ключ(ей) настроено")
        print()
        print("  === Генерация изображений ===")
        print(f"  Image LLM Base URL: {cls.IMAGE_LLM_BASE_URL}")
        print(f"  Image LLM Model: {cls.IMAGE_LLM_MODEL}")
        print(f"  Image API Keys: {len(image_keys)} ключ(ей)")
        print()
        print("  === Qdrant ===")
        print(f"  Host: {cls.QDRANT_HOST}:{cls.QDRANT_PORT}")
        print(f"  Collection: {cls.QDRANT_COLLECTION}")
        print(f"  Vector Size: {cls.QDRANT_VECTOR_SIZE}")
        print(f"  Similarity Threshold: {cls.QDRANT_SIMILARITY_THRESHOLD}")
        print(f"  API Key: {'✓ установлен' if cls.QDRANT_API_KEY else '✗ не установлен'}")
        print()
        print(f"  Telegram API: {'✓ настроен' if cls.TG_API_ID else '✗ не настроен'}")
        print(f"  MongoDB URI: {cls.MONGODB_URI}")
        print(f"  MongoDB DB: {cls.MONGODB_DB_NAME}")
        print(f"  Images Dir: {cls.IMAGES_DIR}")
        print(f"  Max Events Per Post: {cls.MAX_EVENTS_PER_POST}")
        print(f"  Batch Size: {cls.BATCH_SIZE}")
        print("=" * 60)
