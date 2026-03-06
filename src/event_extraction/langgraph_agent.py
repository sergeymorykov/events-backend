"""
LangGraph агент для многошагового извлечения событий из постов.
"""

import logging
import json
from typing import List, Optional, Dict, Any
from datetime import datetime

from langgraph.graph import StateGraph, END
from openai import AsyncOpenAI
from qdrant_client import QdrantClient

from .models import (
    ExtractionState,
    StructuredEvent,
    ScheduleExact,
    ScheduleRecurringWeekly,
    ScheduleFuzzy,
    PriceInfo,
    EventSource,
    WeightedInterest
)
from .image_handler import ImageHandler
from .normalization import TagNormalizer

logger = logging.getLogger(__name__)


class EventExtractionGraph:
    """LangGraph агент для извлечения событий."""
    
    def __init__(
        self,
        llm_client: AsyncOpenAI,
        image_handler: ImageHandler,
        qdrant_client: Optional[QdrantClient] = None,
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
        self.normalizer = TagNormalizer(
            llm_client=llm_client,
            model_name=model_name,
            qdrant_client=qdrant_client,
        )
        
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
  "interests": [
    {{"name": "интерес1", "weight": 0.6}},
    {{"name": "интерес2", "weight": 0.4}}
  ],
  "user_interests": ["интерес1", "интерес2"]  // legacy fallback, если не удалось взвесить
}}

Правила:
- Если информация не найдена — используй null или []
- Дата в ISO 8601 (например: "2025-11-23T19:00:00")
- Если указан ТОЛЬКО день и месяц без года — используй текущий год {current_year}
- Для расписания: exact (конкретная дата), recurring_weekly (по дням недели), fuzzy (нечёткое)
- Цена: если бесплатно — is_free: true, amount: null
- categories: тип события (концерт, выставка, фестиваль, спорт, театр)
- interests: интересы аудитории с весом преобладания в контексте
- Если interests не удаётся заполнить, верни user_interests как fallback
- Для interests используй веса в диапазоне [0, 1], сумма весов должна быть около 1.0

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
                    raw_is_free = price_data.get("is_free")
                    if isinstance(raw_is_free, bool):
                        is_free = raw_is_free
                    elif raw_is_free is None:
                        is_free = False
                    elif isinstance(raw_is_free, (int, float)):
                        is_free = raw_is_free != 0
                    else:
                        is_free = str(raw_is_free).strip().lower() in {
                            "true", "1", "yes", "да", "free", "бесплатно"
                        }

                    raw_amount = price_data.get("amount")
                    amount = raw_amount if isinstance(raw_amount, int) else None
                    if amount is None and isinstance(raw_amount, str):
                        amount_digits = "".join(ch for ch in raw_amount if ch.isdigit())
                        amount = int(amount_digits) if amount_digits else None

                    price = PriceInfo(
                        amount=amount,
                        currency=price_data.get("currency", "RUB"),
                        is_free=is_free
                    )
                
                # Создание источника
                source = EventSource(
                    channel=state.channel,
                    post_id=state.post_id,
                    message_date=state.message_date
                )

                # Парсинг weighted interests с fallback на legacy user_interests
                raw_weighted_interests = self._parse_weighted_interests(data)
                weighted_interests, interest_ids = await self.normalizer.normalize_weighted_interests_with_ids(
                    raw_weighted_interests
                )
                normalized_categories, category_ids = await self.normalizer.normalize_categories_with_ids(
                    data.get("categories", [])
                )
                category_primary, category_secondary = self.normalizer.infer_category_hierarchy(
                    normalized_categories
                )

                legacy_user_interests = [interest.name for interest in weighted_interests]
                if not legacy_user_interests:
                    legacy_user_interests = [
                        str(item).strip()
                        for item in (data.get("user_interests") or [])
                        if item and str(item).strip()
                    ]
                
                # Создание события
                event = StructuredEvent(
                    title=data["title"],
                    description=data.get("description"),
                    location=data.get("location"),
                    address=data.get("address"),
                    schedule=schedule,
                    price=price,
                    categories=normalized_categories,
                    category_ids=category_ids,
                    category_primary=category_primary,
                    category_secondary=category_secondary,
                    interests=weighted_interests,
                    interest_ids=interest_ids,
                    user_interests=legacy_user_interests,
                    sources=[source]
                )
                
                state.events.append(event)
                logger.info(f"✅ Извлечено событие: {event.title[:50]}")
            
            except Exception as e:
                logger.error(f"Ошибка парсинга данных события: {e}", exc_info=True)
                state.errors.append(f"Ошибка парсинга: {e}")
        
        logger.info(f"Всего извлечено событий: {len(state.events)}")
        return state

    @staticmethod
    def _parse_weighted_interests(data: Dict[str, Any]) -> List[WeightedInterest]:
        """
        Парсинг interests из ответа LLM с fallback на legacy формат.
        """
        raw_interests = data.get("interests")
        if isinstance(raw_interests, list):
            parsed: List[WeightedInterest] = []
            for item in raw_interests:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", "")).strip()
                if not name:
                    continue
                try:
                    weight = float(item.get("weight", 0.0))
                except (TypeError, ValueError):
                    weight = 0.0

                if weight < 0.0:
                    weight = 0.0
                if weight > 1.0:
                    weight = 1.0

                parsed.append(WeightedInterest(name=name, weight=weight))

            total_weight = sum(interest.weight for interest in parsed)
            if parsed and total_weight > 0:
                return [
                    WeightedInterest(
                        name=interest.name,
                        weight=round(interest.weight / total_weight, 4)
                    )
                    for interest in parsed
                ]

        # Fallback: преобразуем старый список user_interests в равновесный формат
        legacy_items = [
            str(item).strip()
            for item in (data.get("user_interests") or [])
            if item and str(item).strip()
        ]
        if not legacy_items:
            return []

        uniform_weight = round(1.0 / len(legacy_items), 4)
        return [
            WeightedInterest(name=name, weight=uniform_weight)
            for name in legacy_items
        ]
    
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
        
        normalized_state_images = [
            str(path).strip()
            for path in (state.images or [])
            if path and str(path).strip()
        ]

        # Если есть изображения в посте, используем их для всех событий
        if normalized_state_images:
            logger.info(f"Используем изображения из поста: {len(normalized_state_images)} шт.")
            for event in state.events:
                event.images = normalized_state_images.copy()
                event.poster_generated = False
        
        else:
            # Генерация афиш для событий без изображений
            logger.info("Изображения отсутствуют, генерируем афиши")
            
            for event in state.events:
                try:
                    event.images = [
                        str(path).strip()
                        for path in (event.images or [])
                        if path and str(path).strip()
                    ]
                    logger.info(f"Генерация афиши для: {event.title[:50]}")
                    poster_path = await self.image_handler.generate_event_poster(
                        event_title=event.title,
                        event_description=event.description
                    )
                    
                    if poster_path:
                        event.images = [str(poster_path).strip()]
                        event.poster_generated = True
                        logger.info(f"✅ Афиша сгенерирована: {poster_path}")
                    else:
                        event.poster_generated = False
                        logger.warning(f"⚠️  Не удалось сгенерировать афишу")
                
                except Exception as e:
                    event.poster_generated = False
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
            raw_result = await self.graph.ainvoke(initial_state)

            # LangGraph может вернуть dict; нормализуем результат к модели состояния
            if isinstance(raw_result, ExtractionState):
                result_state = raw_result
            elif isinstance(raw_result, dict):
                try:
                    result_state = ExtractionState.model_validate(raw_result)
                except Exception as e:
                    logger.error(f"Некорректный формат состояния графа: {e}", exc_info=True)
                    return []
            else:
                logger.error(f"Неожиданный тип результата графа: {type(raw_result).__name__}")
                return []
            
            logger.info("=" * 60)
            logger.info("РЕЗУЛЬТАТ ИЗВЛЕЧЕНИЯ:")
            logger.info(f"  Событий извлечено: {len(result_state.events)}")
            logger.info(f"  Ошибок: {len(result_state.errors)}")
            if result_state.errors:
                for error in result_state.errors:
                    logger.warning(f"    - {error}")
            logger.info("=" * 60)
            
            return result_state.events
        
        except Exception as e:
            logger.error(f"Критическая ошибка в графе: {e}", exc_info=True)
            return []
