"""
Модуль для работы с LLM:
- OpenAI-совместимое API (OpenAI, ZenMux, и др.)
- GigaChat API
- Универсальный интерфейс для генерации JSON
"""

import asyncio
import logging
import json
from typing import Optional, List, Tuple

from openai import AsyncOpenAI, BadRequestError, RateLimitError, AuthenticationError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_random_exponential
)

from .models import LLMResponse, PriceInfo

logger = logging.getLogger(__name__)


class InsufficientQuotaError(Exception):
    """Исключение для ошибки нехватки квоты/токенов."""
    pass


class LLMHandler:
    """Обработчик запросов к различным LLM через OpenAI-совместимый API."""
    
    def __init__(
        self,
        base_url: str,
        api_keys: List[str],
        model_name: str = "gpt-4o",
        temperature: float = 0.7,
        max_tokens: int = 2000,
        vision_model: Optional[str] = None
    ):
        """
        Инициализация обработчика LLM.
        
        Args:
            base_url: Базовый URL API (ZenMux, OpenAI, и др.)
            api_keys: Список API ключей для ротации
            model_name: Название модели
            temperature: Температура генерации
            max_tokens: Максимальное количество токенов
            vision_model: Модель для обработки изображений (опционально)
        """
        self.base_url = base_url
        self.model_name = model_name
        self.vision_model = vision_model or model_name
        self.temperature = temperature
        self.max_tokens = max_tokens
        
        # Инициализация API ключей
        self._api_keys: List[str] = api_keys if isinstance(api_keys, list) else [api_keys]
        self._current_key_idx = 0
        
        # Создание клиента
        self._client = self._build_client(self._api_keys[self._current_key_idx])
        
        logger.info(f"LLM Handler инициализирован: base_url={base_url}, model={model_name}, ключей={len(self._api_keys)}")
    
    def _build_client(self, api_key: str) -> AsyncOpenAI:
        """Создание OpenAI клиента с указанным ключом."""
        return AsyncOpenAI(
            base_url=self.base_url,
            api_key=api_key,
        )
    
    def _rotate_key(self) -> bool:
        """Ротация API ключа при rate limit."""
        if len(self._api_keys) <= 1:
            return False
        
        self._current_key_idx = (self._current_key_idx + 1) % len(self._api_keys)
        new_key = self._api_keys[self._current_key_idx]
        self._client = self._build_client(new_key)
        
        logger.warning(f"Переключение на следующий API ключ (index={self._current_key_idx})")
        return True
    
    @staticmethod
    def _should_rotate_key(exc: Exception) -> bool:
        """Проверка, нужна ли ротация ключа при ошибке."""
        status = getattr(exc, "status_code", None)
        message = str(getattr(exc, "message", "")) or str(exc)
        
        if isinstance(exc, RateLimitError):
            return True
        if isinstance(exc, BadRequestError) and status in (400, 429):
            return "too many" in message.lower()
        if status in (400, 429):
            return "too many" in message.lower() or status == 429
        
        return False
    
    @staticmethod
    def _is_authentication_error(exc: Exception) -> bool:
        """Проверка, является ли ошибка ошибкой аутентификации."""
        if isinstance(exc, AuthenticationError):
            return True
        
        status = getattr(exc, "status_code", None)
        if status in (401, 403):
            return True
        
        message = str(getattr(exc, "message", "")) or str(exc)
        error_lower = message.lower()
        if any(keyword in error_lower for keyword in ["invalid api key", "unauthorized", "authentication", "invalid key"]):
            return True
        
        return False
    
    @staticmethod
    def _is_quota_exceeded_error(exc: Exception) -> bool:
        """Проверка, является ли ошибка ошибкой превышения квоты."""
        message = str(getattr(exc, "message", "")) or str(exc)
        error_lower = message.lower()
        
        # Проверяем различные варианты сообщений о квоте
        quota_keywords = [
            "insufficient_quota",
            "quota exceeded",
            "quota_exceeded",
            "out of quota",
            "billing hard limit",
            "exceeded your current quota"
        ]
        
        return any(keyword in error_lower for keyword in quota_keywords)
    
    @staticmethod
    def _should_retry(exc: Exception) -> bool:
        """Проверка, нужно ли повторять запрос при ошибке."""
        # Не повторяем ошибки аутентификации - они не временные
        if LLMHandler._is_authentication_error(exc):
            return False
        
        # Повторяем остальные ошибки (timeout, rate limit, временные сбои)
        return True
    
    def _build_system_prompt(
        self,
        existing_categories: List[str],
        existing_interests: List[str]
    ) -> str:
        """
        Построение системного промпта для LLM.
        
        Args:
            existing_categories: Список существующих категорий
            existing_interests: Список существующих интересов
            
        Returns:
            Системный промпт
        """
        from datetime import datetime
        current_year = datetime.now().year
        
        prompt = f"""Ты — ассистент, извлекающий информацию о событиях из постов в Telegram.

Твоя задача:
1. Проанализировать текст поста, описание изображения и хештеги
2. Извлечь структурированную информацию о событии
3. Вернуть JSON в строго заданной схеме

Схема JSON:
{{
  "title": "название события (str) или null",
  "description": "описание события (str) или null",
  "date": "дата в ISO 8601 формате (str) или null",
  "price": {{
    "amount": число (int) или null,
    "currency": "валюта (RUB, USD, EUR и т.д.) (str) или null"
  }} или null,
  "categories": ["список категорий"],
  "user_interests": ["список интересов пользователя"]
}}

Правила:
- Если информация не найдена или не может быть логически выведена — используй null или []
- Дата должна быть в формате ISO 8601 (например: "2025-11-23T19:00:00")
- ВАЖНО: Если в тексте/изображении указаны ТОЛЬКО день и месяц без года (например, "15 декабря"), используй ТЕКУЩИЙ год {current_year}
- Если указан конкретный год в тексте — используй его точно как указано
- Не пытайся угадывать или корректировать год — система автоматически скорректирует его на основе даты публикации поста
- Цена: 
  * Если событие бесплатное (вход свободный, бесплатно, free и т.д.) — верни price: null
  * Если цена НЕ указана в тексте — верни price: null
  * Если цена указана — извлеки число и валюту: {{"amount": число, "currency": "RUB"}}
- categories: тип события (концерт, выставка, фестиваль, спорт, театр и т.д.)
- user_interests: интересы аудитории (музыка, искусство, спорт, технологии, семейный отдых и т.д.)

ВАЖНО: Используй существующие категории и интересы из базы данных, чтобы избежать дублирования!
Если новая категория или интерес синонимичны существующим — используй существующий вариант.

"""
        
        if existing_categories:
            prompt += f"\nСуществующие категории в базе:\n{', '.join(existing_categories)}\n"
        
        if existing_interests:
            prompt += f"\nСуществующие интересы в базе:\n{', '.join(existing_interests)}\n"
        
        prompt += "\nОтветь ТОЛЬКО валидным JSON, без дополнительного текста."
        
        return prompt
    
    def _build_user_prompt(
        self,
        post_text: str,
        image_captions: Optional[List[str]],
        hashtags: List[str]
    ) -> str:
        """
        Построение пользовательского промпта.
        
        Args:
            post_text: Текст поста
            image_captions: Список описаний изображений (может быть несколько)
            hashtags: Хештеги поста
            
        Returns:
            Пользовательский промпт
        """
        prompt = f"Текст поста:\n{post_text}\n\n"
        
        # Обработка ВСЕХ описаний изображений
        if image_captions:
            # Фильтруем None и пустые описания
            valid_captions = [cap for cap in image_captions if cap]
            
            if len(valid_captions) == 1:
                prompt += f"Описание изображения:\n{valid_captions[0]}\n\n"
            elif len(valid_captions) > 1:
                prompt += f"Описания изображений ({len(valid_captions)} шт.):\n"
                for idx, caption in enumerate(valid_captions, 1):
                    prompt += f"{idx}. {caption}\n"
                prompt += "\n"
        
        if hashtags:
            prompt += f"Хештеги:\n{', '.join(hashtags)}\n\n"
        
        prompt += """Проанализируй эту информацию и верни JSON согласно схеме.
ВАЖНО: Если информация о дате есть ТОЛЬКО на изображении - это нормально, используй её!
Если дата не найдена НИ в тексте, НИ на изображениях - укажи date: null."""
        
        return prompt
    
    def _normalize_messages(self, messages: List[dict]) -> List[dict]:
        """Нормализация сообщений для API."""
        normalized: List[dict] = []
        
        for message in messages:
            role = message.get("role")
            content = message.get("content", "")
            
            if role not in {"user", "assistant", "system"}:
                raise ValueError(f"Неподдерживаемая роль: {role}")
            
            # Поддержка разных форматов content
            if isinstance(content, list):
                normalized.append({"role": role, "content": content})
            elif isinstance(content, dict) and "type" in content:
                normalized.append({"role": role, "content": [content]})
            else:
                normalized.append({"role": role, "content": str(content)})
        
        return normalized
    
    async def _call_llm(
        self,
        messages: List[dict],
        image_base64: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None
    ) -> Optional[str]:
        """
        Универсальный вызов LLM через OpenAI-совместимый API.
        
        Args:
            messages: Список сообщений
            image_base64: Изображение в base64 (если есть)
            temperature: Температура генерации
            max_tokens: Максимум токенов
            
        Returns:
            Текст ответа или None при ошибке
        """
        # Если есть изображение, добавляем его в сообщение
        if image_base64:
            for msg in messages:
                if msg["role"] == "user":
                    original_content = msg["content"]
                    msg["content"] = [
                        {"type": "text", "text": original_content},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_base64}"
                            }
                        }
                    ]
                    break
        
        payload = self._normalize_messages(messages)
        temp = temperature or self.temperature
        max_tok = max_tokens or self.max_tokens
        
        # Выбор модели в зависимости от наличия изображения
        model = self.vision_model if image_base64 else self.model_name
        
        initial_key_idx = self._current_key_idx
        keys_rotated = 0
        
        # Retry механизм с ротацией ключей
        # Не повторяем ошибки аутентификации - они не временные
        # Для rate limit используем более длительные задержки (до 60 секунд)
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),  # Уменьшаем попытки, но увеличиваем задержки
            wait=wait_random_exponential(min=10, max=60),  # Увеличиваем задержку до 60 сек для rate limit
            retry=retry_if_not_exception_type(AuthenticationError),
            reraise=True,
        ):
            with attempt:
                try:
                    completion = await self._client.chat.completions.create(
                        model=model,
                        messages=payload,
                        temperature=temp,
                        max_tokens=max_tok,
                    )
                    message = completion.choices[0].message
                    return message.content or ""
                    
                except Exception as exc:
                    # Проверка на превышение квоты - критическая ошибка, требующая остановки
                    if self._is_quota_exceeded_error(exc):
                        logger.critical(
                            f"❌ КРИТИЧЕСКАЯ ОШИБКА: Квота API исчерпана! "
                            f"Необходимо пополнить баланс или проверить лимиты. "
                            f"Ошибка: {exc}"
                        )
                        raise InsufficientQuotaError(
                            f"API quota exceeded. Please check your billing and limits. Error: {exc}"
                        ) from exc
                    
                    # Проверка на rate limit - логируем отдельно и добавляем дополнительную задержку
                    if isinstance(exc, RateLimitError):
                        attempt_num = attempt.retry_state.attempt_number
                        logger.warning(
                            f"⚠️  Rate limit (429) - попытка {attempt_num}/3. "
                            f"Ожидание перед повтором (может занять до 60 сек)..."
                        )
                        # Дополнительная задержка при rate limit (чем больше попытка, тем дольше ждем)
                        if attempt_num < 3:
                            extra_delay = 15 * attempt_num  # 15, 30 секунд
                            logger.info(f"⏳ Дополнительная задержка {extra_delay} сек. из-за rate limit...")
                            await asyncio.sleep(extra_delay)
                    
                    # Проверка на ошибку аутентификации - не повторяем и не ротируем ключи
                    if self._is_authentication_error(exc):
                        logger.error(
                            f"Ошибка аутентификации API (401/403). "
                            f"Проверьте правильность API ключа. "
                            f"Ошибка: {exc}"
                        )
                        raise  # Прерываем выполнение, не повторяем
                    
                    # Проверка на необходимость ротации ключа
                    if self._should_rotate_key(exc):
                        logger.debug(
                            f"Rate limit. Текущий ключ: {self._current_key_idx}, "
                            f"переключений: {keys_rotated}/{len(self._api_keys)}"
                        )
                        
                        if keys_rotated < len(self._api_keys):
                            if self._rotate_key():
                                keys_rotated += 1
                                logger.info(f"Ключ переключён после ошибки: {exc}")
                                
                                if self._current_key_idx == initial_key_idx and keys_rotated > 0:
                                    logger.warning(
                                        f"Полный круг по всем ключам ({len(self._api_keys)}), "
                                        f"но ошибка сохраняется"
                                    )
                                    keys_rotated = len(self._api_keys)
                        else:
                            logger.warning(
                                f"Все ключи перебраны ({len(self._api_keys)}), "
                                f"ошибка сохраняется: {exc}"
                            )
                    raise
        
        return None
    
    async def generate_event_data(
        self,
        post_text: str,
        image_captions: Optional[List[str]],
        hashtags: List[str],
        existing_categories: List[str],
        existing_interests: List[str],
        image_base64: Optional[str] = None
    ) -> Optional[LLMResponse]:
        """
        Генерация структурированных данных о событии через LLM.
        
        Args:
            post_text: Текст поста
            image_captions: Список описаний изображений (может быть несколько)
            hashtags: Хештеги
            existing_categories: Существующие категории в БД
            existing_interests: Существующие интересы в БД
            image_base64: Изображение в base64 (опционально, для vision моделей)
            
        Returns:
            Объект LLMResponse или None при ошибке
        """
        # Построение промптов
        system_prompt = self._build_system_prompt(existing_categories, existing_interests)
        user_prompt = self._build_user_prompt(post_text, image_captions, hashtags)
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        # Вызов LLM API
        response_text = await self._call_llm(messages, image_base64)
        
        if not response_text:
            logger.error("Не получен ответ от LLM")
            return None
        
        # Парсинг JSON из ответа
        try:
            # Попытка извлечь JSON из markdown блока
            if "```json" in response_text:
                json_start = response_text.find("```json") + 7
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()
            elif "```" in response_text:
                json_start = response_text.find("```") + 3
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()
            
            # Парсинг JSON
            data = json.loads(response_text)
            
            # Валидация через Pydantic
            llm_response = LLMResponse(**data)
            return llm_response
            
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON от LLM: {e}")
            logger.debug(f"Ответ LLM: {response_text}")
            return None
        except Exception as e:
            logger.error(f"Ошибка валидации ответа LLM: {e}", exc_info=True)
            return None
    
    async def generate_image_caption(
        self,
        image_base64: str
    ) -> Optional[str]:
        """
        Генерация описания изображения через LLM.
        
        Args:
            image_base64: Изображение в base64
            
        Returns:
            Текстовое описание изображения или None при ошибке
        """
        messages = [
            {
                "role": "system",
                "content": "Ты — ассистент, описывающий изображения. Опиши изображение кратко и информативно на русском языке."
            },
            {
                "role": "user",
                "content": "Опиши это изображение:"
            }
        ]
        
        # Вызов LLM API с изображением
        response_text = await self._call_llm(messages, image_base64)
        
        return response_text

