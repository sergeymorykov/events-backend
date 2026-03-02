"""
Модуль для работы с изображениями событий.
Генерация афиш только через LLM API (Bothub/ZenMux).
Изображения из Telegram уже загружены парсером в images/.
"""

import asyncio
import logging
import base64
from pathlib import Path
from typing import Optional
from datetime import datetime

import aiohttp

logger = logging.getLogger(__name__)


class ImageHandler:
    """Обработчик изображений для event extraction."""
    
    def __init__(
        self,
        images_dir: str = "images",
        image_llm_base_url: Optional[str] = None,
        image_llm_api_key: Optional[str] = None,
        image_llm_model: Optional[str] = None
    ):
        """
        Инициализация обработчика изображений.
        
        Args:
            images_dir: Папка для сохранения изображений
            image_llm_base_url: Base URL для LLM image generation
            image_llm_api_key: API ключ для генерации изображений
            image_llm_model: Название модели (например: dall-e-3, flux-pro)
        """
        self.images_dir = Path(images_dir)
        self.images_dir.mkdir(exist_ok=True)
        
        # LLM Image Generation настройки
        self.image_llm_base_url = image_llm_base_url
        self.image_llm_api_key = image_llm_api_key
        self.image_llm_model = image_llm_model or "dall-e-3"
        
        if self.image_llm_base_url and self.image_llm_api_key:
            logger.info(f"ImageHandler инициализирован: model={self.image_llm_model}")
        else:
            logger.warning("ImageHandler: генерация изображений не настроена")
    
    async def download_image_from_url(self, url: str) -> Optional[str]:
        """
        Скачивание изображения по URL.
        
        Args:
            url: URL изображения
            
        Returns:
            Относительный путь к сохранённому файлу или None при ошибке
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
                    if extension not in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
                        extension = 'jpg'
                    filename = f"downloaded_{timestamp}.{extension}"
                    filepath = self.images_dir / filename
                    
                    # Сохранение файла
                    content = await response.read()
                    with open(filepath, 'wb') as f:
                        f.write(content)
                    
                    # Проверка существования
                    if not filepath.exists():
                        logger.error(f"Файл не найден после скачивания: {filepath}")
                        return None
                    
                    # Возвращаем относительный путь
                    relative_path = str(filepath.relative_to(Path.cwd()))
                    logger.info(f"Изображение скачано: {relative_path}")
                    return relative_path
                    
        except asyncio.TimeoutError:
            logger.error(f"Таймаут при скачивании изображения: {url}")
            return None
        except Exception as e:
            logger.error(f"Ошибка скачивания изображения: {e}", exc_info=True)
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
            # Нормализация пути
            filepath = Path(image_path)
            if not filepath.is_absolute():
                # Если путь относительный, ищем относительно images_dir
                filepath = self.images_dir / filepath
            filepath = filepath.resolve()
            
            # Проверка существования
            if not filepath.exists():
                logger.error(f"Файл изображения не найден: {filepath}")
                return None
            
            # Проверка, что это файл
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
    
    async def generate_image(
        self,
        prompt: str,
        size: str = "1024x1024"
    ) -> Optional[str]:
        """
        Генерация изображения через OpenAI-совместимый API (Bothub/ZenMux).
        
        Args:
            prompt: Текстовый промпт для генерации
            size: Размер изображения (1024x1024, 512x512 и т.д.)
            
        Returns:
            Относительный путь к сохранённому изображению или None при ошибке
        """
        if not self.image_llm_base_url or not self.image_llm_api_key:
            logger.error("LLM Image Generation не настроен (не указан base_url или API ключ)")
            return None
        
        # Формируем корректный URL
        if self.image_llm_base_url.endswith('/'):
            url = f"{self.image_llm_base_url}images/generations"
        else:
            url = f"{self.image_llm_base_url}/images/generations"
        
        # Подготовка промпта
        full_prompt = f"Сгенерируй изображение по описанию: {prompt[:2000]}"
        
        headers = {
            "Authorization": f"Bearer {self.image_llm_api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "prompt": full_prompt,
            "n": 1,
            "size": size,
            "model": self.image_llm_model
        }
        
        try:
            logger.info("Запрос генерации изображения")
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as response:
                    
                    if response.status == 401:
                        logger.error("Неверный API ключ для генерации изображений (401)")
                        return None
                    
                    if response.status == 429:
                        logger.error("Rate limit (429) при генерации изображения")
                        return None
                    
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Ошибка генерации изображения: {response.status} - {error_text}")
                        return None
                    
                    # Обработка ответа
                    data = await response.json()
                    
                    # Проверка формата ответа (OpenAI-совместимый)
                    if "data" not in data or not data["data"]:
                        logger.error("Некорректный ответ API: отсутствует data")
                        return None
                    
                    image_url = data["data"][0].get("url")
                    if not image_url:
                        logger.error("В ответе отсутствует URL изображения")
                        return None
                    
                    # Скачиваем изображение
                    logger.info(f"Скачивание сгенерированного изображения: {image_url[:50]}...")
                    local_path = await self.download_image_from_url(image_url)
                    
                    if local_path:
                        logger.info(f"✅ Изображение сгенерировано и сохранено: {local_path}")
                        return local_path
                    else:
                        logger.error("Не удалось скачать сгенерированное изображение")
                        return None
                        
        except asyncio.TimeoutError:
            logger.error("Таймаут при генерации изображения")
            return None
        except Exception as e:
            logger.error(f"Ошибка при генерации изображения: {e}", exc_info=True)
            return None
    
    async def generate_event_poster(
        self,
        event_title: str,
        event_description: Optional[str] = None
    ) -> Optional[str]:
        """
        Генерация афиши события через LLM API.
        
        Args:
            event_title: Название события
            event_description: Описание события
            
        Returns:
            Относительный путь к сгенерированной афише или None при ошибке
        """
        # Формируем промпт для генерации афиши
        prompt = f"Создай яркую и привлекательную афишу для события: {event_title}."
        
        if event_description:
            prompt += f" Описание: {event_description[:300]}"
        
        prompt += " Стиль: современный, яркий, с акцентом на название события."
        
        logger.info(f"Генерация афиши для события: {event_title[:50]}...")
        return await self.generate_image(prompt, size="1024x1024")
