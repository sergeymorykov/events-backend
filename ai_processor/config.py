"""
Конфигурация AI процессора из переменных окружения.
"""

import os
import re
from typing import Optional, List, Tuple
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()


class AIConfig:
    """Конфигурация AI процессора."""
    
    # LLM настройки (новый универсальный подход)
    LLM_BASE_URL: str = os.getenv('LLM_BASE_URL', 'https://api.mapleai.de/v1')
    LLM_MODEL_NAME: str = os.getenv('LLM_MODEL_NAME', 'gpt-4o')
    LLM_VISION_MODEL: Optional[str] = os.getenv('LLM_VISION_MODEL')  # Если None, используется LLM_MODEL_NAME
    LLM_TEMPERATURE: float = float(os.getenv('LLM_TEMPERATURE', '0.7'))
    LLM_MAX_TOKENS: int = int(os.getenv('LLM_MAX_TOKENS', '2000'))
    
    # API ключи (поддержка множественных ключей для ротации)
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
        
        # Поддержка старых переменных для обратной совместимости
        if not api_keys:
            gigachat_token = os.getenv('GIGACHAT_TOKEN')
            openai_key = os.getenv('OPENAI_API_KEY')
            
            if gigachat_token:
                api_keys.append(gigachat_token)
            if openai_key:
                api_keys.append(openai_key)
        
        return api_keys
    
    # Настройки генерации изображений
    # Kandinsky настройки
    KANDINSKY_API_KEY: Optional[str] = os.getenv('KANDINSKY_API_KEY')
    KANDINSKY_SECRET_KEY: Optional[str] = os.getenv('KANDINSKY_SECRET_KEY')
    
    # LLM Image Generation настройки (ZenMax, OpenAI DALL-E и др.)
    IMAGE_LLM_BASE_URL: Optional[str] = os.getenv('IMAGE_LLM_BASE_URL')  # Если не указан, используется LLM_BASE_URL
    IMAGE_LLM_MODEL: Optional[str] = os.getenv('IMAGE_LLM_MODEL')  # Например: dall-e-3, flux-pro
    IMAGE_LLM_API_KEYS: Optional[str] = os.getenv('IMAGE_LLM_API_KEYS')  # Если не указаны, используется LLM_API_KEYS
    
    @classmethod
    def get_image_api_keys(cls) -> List[str]:
        """Получение списка API ключей для генерации изображений."""
        raw_keys = cls.IMAGE_LLM_API_KEYS
        
        if raw_keys:
            api_keys: List[str] = []
            for chunk in re.split(r"[,\n;]", raw_keys):
                trimmed = chunk.strip()
                if trimmed and trimmed not in api_keys:
                    api_keys.append(trimmed)
            return api_keys
        
        # Fallback на основные LLM ключи
        return cls.get_api_keys()
    
    # MongoDB настройки (используем те же, что и для парсера)
    MONGODB_URI: str = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/')
    MONGODB_DB_NAME: str = os.getenv('MONGODB_DB_NAME', 'events_db')
    
    # Telegram настройки (для скачивания фото)
    TG_API_ID: str = os.getenv('TG_API_ID', '')
    TG_API_HASH: str = os.getenv('TG_API_HASH', '')
    TG_SESSION_NAME: str = os.getenv('TG_SESSION_NAME', 'telegram_parser_session')
    
    # Настройки изображений
    IMAGES_DIR: str = os.getenv('IMAGES_DIR', 'images')
    
    @classmethod
    def validate(cls) -> Tuple[bool, str]:
        """
        Валидация конфигурации.
        
        Returns:
            Кортеж (успех, сообщение об ошибке)
        """
        # Проверка наличия API ключей
        api_keys = cls.get_api_keys()
        if not api_keys:
            return False, "LLM_API_KEY, LLM_API_KEYS или хотя бы один из GIGACHAT_TOKEN/OPENAI_API_KEY должен быть указан"
        
        # Проверка base URL
        if not cls.LLM_BASE_URL:
            return False, "LLM_BASE_URL должен быть указан"
        
        # Проверка модели
        if not cls.LLM_MODEL_NAME:
            return False, "LLM_MODEL_NAME должен быть указан"
        
        # Проверка настроек генерации изображений (опционально)
        has_kandinsky = cls.KANDINSKY_API_KEY and cls.KANDINSKY_SECRET_KEY
        has_image_llm = cls.IMAGE_LLM_MODEL or cls.IMAGE_LLM_BASE_URL
        
        if not has_kandinsky and not has_image_llm:
            return True, "ВНИМАНИЕ: Настройки генерации изображений не заданы (ни Kandinsky, ни IMAGE_LLM). Генерация изображений будет недоступна."
        
        # Проверка Telegram (опционально)
        if not cls.TG_API_ID or not cls.TG_API_HASH:
            return True, "ВНИМАНИЕ: Telegram API не настроен. Скачивание фото из Telegram будет недоступно."
        
        return True, ""
    
    @classmethod
    def print_config(cls):
        """Вывод конфигурации (без секретов)."""
        api_keys = cls.get_api_keys()
        
        print("=" * 60)
        print("КОНФИГУРАЦИЯ AI ПРОЦЕССОРА:")
        print(f"  LLM Base URL: {cls.LLM_BASE_URL}")
        print(f"  LLM Model: {cls.LLM_MODEL_NAME}")
        print(f"  Vision Model: {cls.LLM_VISION_MODEL or cls.LLM_MODEL_NAME}")
        print(f"  Temperature: {cls.LLM_TEMPERATURE}")
        print(f"  Max Tokens: {cls.LLM_MAX_TOKENS}")
        print(f"  API Keys: {len(api_keys)} ключ(ей) настроено")
        print(f"")
        print(f"  === Генерация изображений ===")
        print(f"  Kandinsky API: {'✓ настроен' if cls.KANDINSKY_API_KEY else '✗ не настроен'}")
        if cls.IMAGE_LLM_MODEL or cls.IMAGE_LLM_BASE_URL:
            image_keys = cls.get_image_api_keys()
            print(f"  Image LLM: ✓ настроен")
            print(f"    Base URL: {cls.IMAGE_LLM_BASE_URL or cls.LLM_BASE_URL}")
            print(f"    Model: {cls.IMAGE_LLM_MODEL}")
            print(f"    API Keys: {len(image_keys)} ключ(ей)")
        else:
            print(f"  Image LLM: ✗ не настроен")
        print(f"")
        print(f"  Telegram API: {'✓ настроен' if cls.TG_API_ID else '✗ не настроен'}")
        print(f"  MongoDB URI: {cls.MONGODB_URI}")
        print(f"  MongoDB DB: {cls.MONGODB_DB_NAME}")
        print(f"  Images Dir: {cls.IMAGES_DIR}")
        print("=" * 60)

