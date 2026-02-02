"""
LangGraph агент для многошагового извлечения событий из постов.
"""

import logging
import json
from typing import List, Optional, Dict, Any
from datetime import datetime

from langgraph.graph import StateGraph, END
from openai import AsyncOpenAI

from .models import (
    ExtractionState,
    StructuredEvent,
    ScheduleExact,
    ScheduleRecurringWeekly,
    ScheduleFuzzy,
    PriceInfo,
    EventSource
)
from .image_handler import ImageHandler

logger = logging.getLogger(__name__)


class EventExtractionGraph:
    """LangGraph агент для извлечения событий."""
    
    def __init__(
        self,
        llm_client: AsyncOpenAI,
        image_handler: ImageHandler,
        model_name: str = "gpt-4o",
        temperature: float = 0.7,
        max_tokens: int = 2000
    ):
        """
        Инициализация агента.
        
        Args:
            llm_client: OpenAI-совместимый клиент
            image_handler: Обработчик изображений
            model_name: Название модели LLM
            temperature: Температура генерации
            max_tokens: Максимум токенов
        """
        self.llm_client = llm_client
        self.image_handler = image_handler
        self.model_name = model_name
        self.temperature = temperature
        self.max_tokens = max_tokens
        
        # Инициализация графа
        self.graph = self._build_graph()
    
    def _build_graph(self) -> StateGraph:
        """Построение графа обработки."""
        workflow = StateGraph(ExtractionState)
        
        # Определение узлов
        workflow.add_node("split_into_events", self._split_into_events)
        workflow.add_node("extract_event_data", self._extract_event_data)
        workflow.add_node("process_images", self._process_images)
        
        # Определение рёбер
        workflow.set_entry_point("split_into_events")
        workflow.add_edge("split_into_events", "extract_event_data")
        workflow.add_edge("extract_event_data", "process_images")
        workflow.add_edge("process_images", END)
        
        return workflow.compile()
    
    async def _call_llm(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None
    ) -> Optional[str]:
        """
        Вызов LLM API.
        
        Args:
            messages: Список сообщений
            temperature: Температура генерации
            max_tokens: Максимум токенов
            
        Returns:
            Ответ LLM или None при ошибке
        """
        try:
            completion = await self.llm_client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=temperature or self.temperature,
                max_tokens=max_tokens or self.max_tokens
            )
            return completion.choices[0].message.content or ""
        
        except Exception as e:
            logger.error(f"Ошибка вызова LLM: {e}", exc_info=True)
            return None
    
    async def _split_into_events(self, state: ExtractionState) -> ExtractionState:
        """
        Узел 1: Разделение поста на отдельные события.
        
        Args:
            state: Текущее состояние
            
        Returns:
            Обновлённое состояние
        """
        logger.info("Шаг 1: Разделение поста на события")
        state.current_step = "split_into_events"
        
        system_prompt = """Ты — ассистент, разделяющий посты на отдельные события.

Твоя задача:
1. Определить, сколько ОТДЕЛЬНЫХ событий упоминается в посте
2. Разделить текст на части, каждая из которых описывает одно событие
3. Вернуть JSON список текстов событий

Правила:
- Если пост описывает ОДНО событие — верни массив с одним элементом
- Если несколько событий (например, афиша на неделю) — разделяй
- Каждый элемент должен содержать полное описание события
- Сохраняй важную информацию: дата, место, цена, описание

Ответь ТОЛЬКО валидным JSON массивом строк, без дополнительного текста.
Формат: ["событие 1", "событие 2", ...]"""
        
        user_prompt = f"Текст поста:\n{state.raw_text}\n\nХештеги: {', '.join(state.hashtags) if state.hashtags else 'нет'}"
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        response = await self._call_llm(messages)
        
        if not response:
            logger.error("Не получен ответ от LLM на этапе разделения")
            state.errors.append("Ошибка разделения событий")
            state.raw_events = [state.raw_text]  # Fallback: считаем пост одним событием
            return state
        
        # Парсинг JSON
        try:
            # Извлечение JSON из markdown
            if "```json" in response:
                json_start = response.find("```json") + 7
                json_end = response.find("```", json_start)
                response = response[json_start:json_end].strip()
            elif "```" in response:
                json_start = response.find("```") + 3
                json_end = response.find("```", json_start)
                response = response[json_start:json_end].strip()
            
            raw_events = json.loads(response)
            
            if not isinstance(raw_events, list):
                raise ValueError("Ответ не является массивом")
            
            state.raw_events = [str(event) for event in raw_events if event]
            logger.info(f"✅ Найдено событий: {len(state.raw_events)}")
        
        except Exception as e:
            logger.error(f"Ошибка парсинга разделённых событий: {e}")
            state.errors.append(f"Ошибка парсинга: {e}")
            state.raw_events = [state.raw_text]  # Fallback
        
        return state
    
    async def _extract_event_data(self, state: ExtractionState) -> ExtractionState:
        """
        Узел 2: Извлечение структурированных данных о каждом событии.
        
        Args:
            state: Текущее состояние
            
        Returns:
            Обновлённое состояние
        """
        logger.info("Шаг 2: Извлечение структурированных данных")
        state.current_step = "extract_event_data"
        
        current_year = datetime.now().year
        
        system_prompt = f"""Ты — ассистент, извлекающий структурированную информацию о событии.

Схема JSON:
{{
  "title": "название события (str) или null",
  "description": "описание (str) или null",
  "location": "место проведения (str) или null",
  "address": "адрес (str) или null",
  "schedule": {{
    "type": "exact|recurring_weekly|fuzzy",
    "date_start": "ISO 8601 дата начала (для exact)",
    "schedule": {{"monday": ["19:00"], "friday": ["20:00"]}} (для recurring_weekly),
    "description": "текстовое описание (для fuzzy)"
  }},
  "price": {{
    "amount": число (int) или null,
    "currency": "RUB/USD/EUR (str)",
    "is_free": true/false
  }},
  "categories": ["категория1", "категория2"],
  "user_interests": ["интерес1", "интерес2"]
}}

Правила:
- Если информация не найдена — используй null или []
- Дата в ISO 8601 (например: "2025-11-23T19:00:00")
- Если указан ТОЛЬКО день и месяц без года — используй текущий год {current_year}
- Для расписания: exact (конкретная дата), recurring_weekly (по дням недели), fuzzy (нечёткое)
- Цена: если бесплатно — is_free: true, amount: null
- categories: тип события (концерт, выставка, фестиваль, спорт, театр)
- user_interests: интересы аудитории (музыка, искусство, спорт, технологии)

Ответь ТОЛЬКО валидным JSON, без дополнительного текста."""
        
        for event_text in state.raw_events:
            user_prompt = f"Текст события:\n{event_text}"
            
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
            
            response = await self._call_llm(messages)
            
            if not response:
                logger.error("Не получен ответ от LLM на этапе извлечения")
                state.errors.append("Ошибка извлечения данных события")
                continue
            
            # Парсинг JSON
            try:
                # Извлечение JSON
                if "```json" in response:
                    json_start = response.find("```json") + 7
                    json_end = response.find("```", json_start)
                    response = response[json_start:json_end].strip()
                elif "```" in response:
                    json_start = response.find("```") + 3
                    json_end = response.find("```", json_start)
                    response = response[json_start:json_end].strip()
                
                data = json.loads(response)
                
                # Проверка обязательных полей
                if not data.get("title"):
                    logger.warning("Событие без названия, пропускаем")
                    continue
                
                # Парсинг расписания
                schedule = None
                if data.get("schedule"):
                    sched_data = data["schedule"]
                    sched_type = sched_data.get("type", "exact")
                    
                    if sched_type == "exact" and sched_data.get("date_start"):
                        try:
                            date_start = datetime.fromisoformat(
                                sched_data["date_start"].replace('Z', '+00:00')
                            )
                            schedule = ScheduleExact(date_start=date_start)
                        except Exception as e:
                            logger.warning(f"Ошибка парсинга даты: {e}")
                    
                    elif sched_type == "recurring_weekly" and sched_data.get("schedule"):
                        schedule = ScheduleRecurringWeekly(schedule=sched_data["schedule"])
                    
                    elif sched_type == "fuzzy" and sched_data.get("description"):
                        schedule = ScheduleFuzzy(description=sched_data["description"])
                
                # Парсинг цены
                price = None
                if data.get("price"):
                    price_data = data["price"]
                    price = PriceInfo(
                        amount=price_data.get("amount"),
                        currency=price_data.get("currency", "RUB"),
                        is_free=price_data.get("is_free", False)
                    )
                
                # Создание источника
                source = EventSource(
                    channel=state.channel,
                    post_id=state.post_id,
                    message_date=state.message_date
                )
                
                # Создание события
                event = StructuredEvent(
                    title=data["title"],
                    description=data.get("description"),
                    location=data.get("location"),
                    address=data.get("address"),
                    schedule=schedule,
                    price=price,
                    categories=data.get("categories", []),
                    user_interests=data.get("user_interests", []),
                    sources=[source]
                )
                
                state.events.append(event)
                logger.info(f"✅ Извлечено событие: {event.title[:50]}")
            
            except Exception as e:
                logger.error(f"Ошибка парсинга данных события: {e}", exc_info=True)
                state.errors.append(f"Ошибка парсинга: {e}")
        
        logger.info(f"Всего извлечено событий: {len(state.events)}")
        return state
    
    async def _process_images(self, state: ExtractionState) -> ExtractionState:
        """
        Узел 3: Обработка изображений (скачивание или генерация афиш).
        
        Args:
            state: Текущее состояние
            
        Returns:
            Обновлённое состояние
        """
        logger.info("Шаг 3: Обработка изображений")
        state.current_step = "process_images"
        
        # Если есть изображения в посте, используем их для всех событий
        if state.images:
            logger.info(f"Используем изображения из поста: {len(state.images)} шт.")
            for event in state.events:
                event.images = state.images.copy()
        
        else:
            # Генерация афиш для событий без изображений
            logger.info("Изображения отсутствуют, генерируем афиши")
            
            for event in state.events:
                try:
                    logger.info(f"Генерация афиши для: {event.title[:50]}")
                    poster_path = await self.image_handler.generate_event_poster(
                        event_title=event.title,
                        event_description=event.description
                    )
                    
                    if poster_path:
                        event.images = [poster_path]
                        event.poster_generated = True
                        logger.info(f"✅ Афиша сгенерирована: {poster_path}")
                    else:
                        logger.warning(f"⚠️  Не удалось сгенерировать афишу")
                
                except Exception as e:
                    logger.error(f"Ошибка генерации афиши: {e}", exc_info=True)
                    state.errors.append(f"Ошибка генерации афиши: {e}")
        
        return state
    
    async def run_extraction_graph(
        self,
        text: str,
        message_date: Optional[datetime] = None,
        images: Optional[List[str]] = None,
        hashtags: Optional[List[str]] = None,
        channel: str = "",
        post_id: int = 0
    ) -> List[StructuredEvent]:
        """
        Запуск графа извлечения событий.
        
        Args:
            text: Текст поста
            message_date: Дата публикации
            images: Список путей к изображениям
            hashtags: Хештеги
            channel: Название канала
            post_id: ID поста
            
        Returns:
            Список извлечённых событий
        """
        logger.info("=" * 60)
        logger.info("ЗАПУСК LANGGRAPH АГЕНТА")
        logger.info("=" * 60)
        
        # Инициализация состояния
        initial_state = ExtractionState(
            raw_text=text,
            images=images or [],
            hashtags=hashtags or [],
            message_date=message_date,
            channel=channel,
            post_id=post_id
        )
        
        try:
            # Запуск графа
            result = await self.graph.ainvoke(initial_state)
            
            logger.info("=" * 60)
            logger.info("РЕЗУЛЬТАТ ИЗВЛЕЧЕНИЯ:")
            logger.info(f"  Событий извлечено: {len(result.events)}")
            logger.info(f"  Ошибок: {len(result.errors)}")
            if result.errors:
                for error in result.errors:
                    logger.warning(f"    - {error}")
            logger.info("=" * 60)
            
            return result.events
        
        except Exception as e:
            logger.error(f"Критическая ошибка в графе: {e}", exc_info=True)
            return []
