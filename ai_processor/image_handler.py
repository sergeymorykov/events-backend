"""
Модуль для работы с изображениями:
- Скачивание изображений из Telegram
- Генерация изображений через Kandinsky 3.1 API
- Сохранение изображений локально
"""

import os
import asyncio
import logging
import base64
import json
import time
from pathlib import Path
from typing import Optional, List
from datetime import datetime

import aiohttp
from telethon import TelegramClient
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class ImageHandler:
    """Обработчик изображений для AI процессора."""
    
    def __init__(
        self,
        images_dir: str = "images",
        kandinsky_api_key: Optional[str] = None,
        kandinsky_secret_key: Optional[str] = None,
        telegram_client: Optional[TelegramClient] = None,
        # Новые параметры для LLM-генерации
        image_llm_base_url: Optional[str] = None,
        image_llm_api_keys: Optional[List[str]] = None,
        image_llm_model: Optional[str] = None
    ):
        """
        Инициализация обработчика изображений.
        
        Args:
            images_dir: Папка для сохранения изображений
            kandinsky_api_key: API ключ для Kandinsky
            kandinsky_secret_key: Secret ключ для Kandinsky
            telegram_client: Клиент Telegram для скачивания фото
            image_llm_base_url: Base URL для LLM image generation (ZenMax, OpenAI и др.)
            image_llm_api_keys: Список API ключей для ротации
            image_llm_model: Название модели (например: dall-e-3, flux-pro)
        """
        self.images_dir = Path(images_dir)
        self.images_dir.mkdir(exist_ok=True)
        
        # Kandinsky настройки
        self.kandinsky_api_key = kandinsky_api_key
        self.kandinsky_secret_key = kandinsky_secret_key
        self.telegram_client = telegram_client
        
        # URL для Kandinsky API
        self.kandinsky_url = "https://api-key.fusionbrain.ai/"
        self._model_id = None
        
        # LLM Image Generation настройки
        self.image_llm_base_url = image_llm_base_url
        self.image_llm_api_keys = image_llm_api_keys or []
        self.image_llm_model = image_llm_model
        self._current_image_key_idx = 0
        
        # Инициализация OpenAI клиента для генерации изображений
        if self.image_llm_base_url and self.image_llm_api_keys and self.image_llm_model:
            self._image_client = AsyncOpenAI(
                base_url=self.image_llm_base_url,
                api_key=self.image_llm_api_keys[0]
            )
            logger.info(f"LLM Image Generator инициализирован: model={self.image_llm_model}")
        else:
            self._image_client = None
    
    async def download_image_from_url(self, url: str) -> Optional[str]:
        """
        Скачивание изображения по URL.
        
        Args:
            url: URL изображения
            
        Returns:
            Абсолютный путь к сохраненному файлу или None при ошибке
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status != 200:
                        logger.error(f"Ошибка скачивания изображения: HTTP {response.status}")
                        return None
                    
                    # Генерация имени файла
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    extension = url.split('.')[-1].split('?')[0] or 'jpg'
                    filename = f"downloaded_{timestamp}.{extension}"
                    filepath = self.images_dir / filename
                    
                    # Преобразуем в абсолютный путь
                    filepath = filepath.resolve()
                    
                    # Сохранение файла
                    content = await response.read()
                    with open(filepath, 'wb') as f:
                        f.write(content)
                    
                    # Проверяем существование файла
                    if not filepath.exists():
                        logger.error(f"Файл не найден после скачивания: {filepath}")
                        return None
                    
                    absolute_path = str(filepath.absolute())
                    logger.info(f"Изображение скачано: {absolute_path}")
                    return absolute_path
                    
        except asyncio.TimeoutError:
            logger.error(f"Таймаут при скачивании изображения: {url}")
            return None
        except Exception as e:
            logger.error(f"Ошибка скачивания изображения: {e}", exc_info=True)
            return None
    
    async def download_telegram_photo(self, photo_info: dict, message_id: int) -> Optional[str]:
        """
        Скачивание фото из Telegram через Telethon.
        
        Args:
            photo_info: Информация о фото из raw_post
            message_id: ID сообщения
            
        Returns:
            Абсолютный путь к сохраненному файлу или None при ошибке
        """
        if not self.telegram_client:
            logger.error("Telegram клиент не инициализирован")
            return None
        
        if not photo_info:
            return None
        
        try:
            # Генерация имени файла
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"telegram_{message_id}_{timestamp}.jpg"
            filepath = self.images_dir / filename
            
            # Преобразуем в абсолютный путь перед скачиванием
            filepath = filepath.resolve()
            
            # Скачивание через Telethon
            # photo_info содержит photo_id, access_hash, date
            await self.telegram_client.download_media(
                photo_info,
                file=str(filepath)
            )
            
            # Проверяем, что файл действительно скачан
            if not filepath.exists():
                logger.error(f"Файл не найден после скачивания: {filepath}")
                return None
            
            # Возвращаем абсолютный путь как строку
            absolute_path = str(filepath.absolute())
            logger.info(f"Фото из Telegram скачано: {absolute_path}")
            return absolute_path
            
        except Exception as e:
            logger.error(f"Ошибка скачивания фото из Telegram: {e}", exc_info=True)
            return None
    
    async def _get_kandinsky_token(self) -> Optional[str]:
        """
        Получение токена авторизации для Kandinsky API.
        
        Returns:
            Токен авторизации или None при ошибке
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.kandinsky_url}key/api/v1/auth/token",
                    json={
                        "api_key": self.kandinsky_api_key,
                        "secret_key": self.kandinsky_secret_key
                    },
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status != 200:
                        logger.error(f"Ошибка получения токена Kandinsky: HTTP {response.status}")
                        return None
                    
                    data = await response.json()
                    return data.get('token')
                    
        except Exception as e:
            logger.error(f"Ошибка при получении токена Kandinsky: {e}", exc_info=True)
            return None
    
    async def _get_kandinsky_model_id(self, token: str) -> Optional[int]:
        """
        Получение ID модели Kandinsky 3.1.
        
        Args:
            token: Токен авторизации
            
        Returns:
            ID модели или None при ошибке
        """
        if self._model_id:
            return self._model_id
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.kandinsky_url}key/api/v1/models",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status != 200:
                        logger.error(f"Ошибка получения списка моделей: HTTP {response.status}")
                        return None
                    
                    models = await response.json()
                    # Ищем модель Kandinsky 3.1
                    for model in models:
                        if 'kandinsky' in model.get('name', '').lower() and '3.1' in model.get('version', ''):
                            self._model_id = model['id']
                            return self._model_id
                    
                    # Если не нашли конкретную версию, берем первую доступную
                    if models:
                        self._model_id = models[0]['id']
                        return self._model_id
                    
                    logger.error("Не найдена модель Kandinsky")
                    return None
                    
        except Exception as e:
            logger.error(f"Ошибка при получении ID модели: {e}", exc_info=True)
            return None
    
    async def generate_image_kandinsky(self, prompt: str, timeout: int = 300) -> Optional[str]:
        """
        Генерация изображения через Kandinsky 3.1 API.
        
        Args:
            prompt: Текстовый промпт для генерации
            timeout: Максимальное время ожидания в секундах
            
        Returns:
            Путь к сохраненному изображению или None при ошибке
        """
        if not self.kandinsky_api_key or not self.kandinsky_secret_key:
            logger.error("Kandinsky API ключи не настроены")
            return None
        
        try:
            # Получение токена
            token = await self._get_kandinsky_token()
            if not token:
                return None
            
            # Получение ID модели
            model_id = await self._get_kandinsky_model_id(token)
            if not model_id:
                return None
            
            # Отправка запроса на генерацию
            async with aiohttp.ClientSession() as session:
                # Параметры генерации
                params = {
                    "type": "GENERATE",
                    "style": "DEFAULT",
                    "width": 1024,
                    "height": 1024,
                    "num_images": 1,
                    "negativePromptUnclip": "",
                    "generateParams": {
                        "query": prompt[:1000]  # Ограничение длины промпта
                    }
                }
                
                # Формирование запроса
                form_data = aiohttp.FormData()
                form_data.add_field('model_id', str(model_id))
                form_data.add_field('params', json.dumps(params), content_type='application/json')
                
                # Отправка запроса
                async with session.post(
                    f"{self.kandinsky_url}key/api/v1/text2image/run",
                    headers={"Authorization": f"Bearer {token}"},
                    data=form_data,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status != 200:
                        text = await response.text()
                        logger.error(f"Ошибка запроса генерации: HTTP {response.status}, {text}")
                        return None
                    
                    result = await response.json()
                    request_uuid = result.get('uuid')
                    
                    if not request_uuid:
                        logger.error("Не получен UUID запроса")
                        return None
                
                # Ожидание завершения генерации
                start_time = time.time()
                while time.time() - start_time < timeout:
                    await asyncio.sleep(10)  # Проверка каждые 10 секунд
                    
                    async with session.get(
                        f"{self.kandinsky_url}key/api/v1/text2image/status/{request_uuid}",
                        headers={"Authorization": f"Bearer {token}"},
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as check_response:
                        if check_response.status != 200:
                            logger.error(f"Ошибка проверки статуса: HTTP {check_response.status}")
                            return None
                        
                        status_data = await check_response.json()
                        status = status_data.get('status')
                        
                        if status == 'DONE':
                            # Получение изображения
                            images = status_data.get('images', [])
                            if not images:
                                logger.error("Изображения не найдены в ответе")
                                return None
                            
                            # Декодирование и сохранение
                            image_base64 = images[0]
                            image_data = base64.b64decode(image_base64)
                            
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            filename = f"generated_{timestamp}.png"
                            filepath = self.images_dir / filename
                            
                            with open(filepath, 'wb') as f:
                                f.write(image_data)
                            
                            logger.info(f"Изображение сгенерировано: {filepath}")
                            return str(filepath)
                        
                        elif status == 'FAIL':
                            error_msg = status_data.get('error', 'Unknown error')
                            logger.error(f"Ошибка генерации изображения: {error_msg}")
                            return None
                        
                        # Статус INITIAL или PROCESSING - продолжаем ожидание
                        logger.info(f"Статус генерации: {status}")
                
                logger.error(f"Таймаут генерации изображения ({timeout}s)")
                return None
                
        except asyncio.TimeoutError:
            logger.error(f"Таймаут при генерации изображения")
            return None
        except Exception as e:
            logger.error(f"Ошибка генерации изображения через Kandinsky: {e}", exc_info=True)
            return None
    
    async def generate_image_llm(self, prompt: str, size: str = "1024x1024") -> Optional[str]:
        """
        Генерация изображения через LLM API (ZenMax, OpenAI DALL-E, Flux и др.).
        
        Args:
            prompt: Текстовый промпт для генерации
            size: Размер изображения (1024x1024, 1792x1024 и т.д.)
            
        Returns:
            Путь к сохраненному изображению или None при ошибке
        """
        if not self._image_client or not self.image_llm_model:
            logger.error("LLM Image Generation не настроен")
            return None
        
        try:
            logger.info(f"Генерация изображения через {self.image_llm_model}...")
            
            # Генерация изображения
            response = await self._image_client.images.generate(
                model=self.image_llm_model,
                prompt=prompt[:1000],  # Ограничение длины промпта
                size=size,
                n=1
            )
            
            if not response.data or len(response.data) == 0:
                logger.error("Не получено изображение от LLM API")
                return None
            
            image_data = response.data[0]
            
            # Поддержка разных форматов ответа
            if hasattr(image_data, 'url') and image_data.url:
                # URL-формат - скачиваем изображение
                return await self.download_image_from_url(image_data.url)
            elif hasattr(image_data, 'b64_json') and image_data.b64_json:
                # Base64-формат - сохраняем напрямую
                image_bytes = base64.b64decode(image_data.b64_json)
                
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"llm_generated_{timestamp}.png"
                filepath = self.images_dir / filename
                
                with open(filepath, 'wb') as f:
                    f.write(image_bytes)
                
                logger.info(f"Изображение сгенерировано через LLM: {filepath}")
                return str(filepath)
            else:
                logger.error("Неизвестный формат ответа от LLM API")
                return None
                
        except Exception as e:
            logger.error(f"Ошибка генерации изображения через LLM: {e}", exc_info=True)
            return None
    
    async def generate_image(self, prompt: str) -> Optional[str]:
        """
        Универсальный метод генерации изображения.
        Автоматически выбирает доступный метод (приоритет: LLM -> Kandinsky).
        
        Args:
            prompt: Текстовый промпт для генерации
            
        Returns:
            Путь к сохраненному изображению или None при ошибке
        """
        # Приоритет: LLM Image Generation
        if self._image_client and self.image_llm_model:
            logger.info("Используется LLM генерация изображений")
            result = await self.generate_image_llm(prompt)
            if result:
                return result
            logger.warning("LLM генерация не удалась, пробуем Kandinsky...")
        
        # Fallback на Kandinsky
        if self.kandinsky_api_key and self.kandinsky_secret_key:
            logger.info("Используется Kandinsky генерация изображений")
            return await self.generate_image_kandinsky(prompt)
        
        logger.error("Нет доступных методов генерации изображений")
        return None
    
    def image_to_base64(self, image_path: str) -> Optional[str]:
        """
        Конвертация изображения в base64.
        
        Args:
            image_path: Путь к изображению (относительный или абсолютный)
            
        Returns:
            Строка base64 или None при ошибке
        """
        try:
            # Нормализуем путь и делаем абсолютным
            filepath = Path(image_path)
            if not filepath.is_absolute():
                # Если путь относительный, ищем относительно images_dir
                filepath = self.images_dir / filepath
            filepath = filepath.resolve()
            
            # Проверяем существование файла
            if not filepath.exists():
                logger.error(f"Файл изображения не найден: {filepath}")
                return None
            
            # Проверяем, что это файл, а не директория
            if not filepath.is_file():
                logger.error(f"Указанный путь не является файлом: {filepath}")
                return None
            
            # Читаем файл
            with open(filepath, 'rb') as f:
                image_data = f.read()
                return base64.b64encode(image_data).decode('utf-8')
                
        except Exception as e:
            logger.error(f"Ошибка конвертации изображения в base64: {e}", exc_info=True)
            return None

