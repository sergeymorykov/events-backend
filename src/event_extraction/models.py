"""
Pydantic модели для event extraction модуля.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator
from enum import Enum


class ScheduleType(str, Enum):
    """Тип расписания события."""
    EXACT = "exact"  # Конкретная дата/время
    RECURRING_WEEKLY = "recurring_weekly"  # Повторяющееся по дням недели
    FUZZY = "fuzzy"  # Нечёткое расписание


class ScheduleExact(BaseModel):
    """Расписание с конкретной датой и временем."""
    type: ScheduleType = Field(default=ScheduleType.EXACT)
    date_start: datetime = Field(..., description="Дата и время начала события")
    date_end: Optional[datetime] = Field(None, description="Дата и время окончания (если известна)")
    timezone: str = Field(default="Europe/Moscow", description="Часовой пояс")


class ScheduleRecurringWeekly(BaseModel):
    """Повторяющееся расписание по дням недели с разным временем."""
    type: ScheduleType = Field(default=ScheduleType.RECURRING_WEEKLY)
    schedule: Dict[str, List[str]] = Field(
        ...,
        description="Расписание вида {день_недели: [время1, время2, ...]}"
    )
    valid_from: Optional[datetime] = Field(None, description="Начало действия расписания")
    valid_until: Optional[datetime] = Field(None, description="Окончание действия расписания")
    timezone: str = Field(default="Europe/Moscow")

    @field_validator('schedule')
    @classmethod
    def validate_schedule(cls, v: Dict[str, List[str]]) -> Dict[str, List[str]]:
        """Валидация дней недели и формата времени."""
        valid_days = {'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'}
        for day in v.keys():
            if day.lower() not in valid_days:
                raise ValueError(f"Некорректный день недели: {day}")
        return v


class ScheduleFuzzy(BaseModel):
    """Нечёткое расписание (например, 'каждые выходные', 'по вечерам')."""
    type: ScheduleType = Field(default=ScheduleType.FUZZY)
    description: str = Field(..., description="Текстовое описание расписания")
    approximate_start: Optional[datetime] = Field(None, description="Приблизительная дата начала")
    approximate_end: Optional[datetime] = Field(None, description="Приблизительная дата окончания")


class PriceInfo(BaseModel):
    """Информация о цене события."""
    amount: Optional[int] = Field(None, description="Стоимость в числовом формате")
    currency: Optional[str] = Field(None, description="Валюта (RUB, USD, EUR и т.д.)")
    is_free: bool = Field(default=False, description="Бесплатное событие")
    price_range: Optional[str] = Field(None, description="Диапазон цен (например, '500-1000')")


class EventSource(BaseModel):
    """Источник информации о событии."""
    channel: str = Field(..., description="Название канала/источника")
    post_id: int = Field(..., description="ID поста в источнике")
    post_url: Optional[str] = Field(None, description="Ссылка на пост")
    message_date: Optional[datetime] = Field(None, description="Дата публикации поста")


class WeightedInterest(BaseModel):
    """Интерес с весом преобладания в контексте события."""
    name: str = Field(..., description="Название интереса")
    weight: float = Field(..., ge=0.0, le=1.0, description="Вес интереса от 0 до 1")

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Нормализация названия интереса."""
        return v.strip()


class StructuredEvent(BaseModel):
    """Структурированное событие после извлечения."""
    
    # Основные поля
    title: str = Field(..., description="Название события")
    description: Optional[str] = Field(None, description="Описание события")
    
    # Расписание (union type для разных типов расписаний)
    schedule: Optional[ScheduleExact | ScheduleRecurringWeekly | ScheduleFuzzy] = Field(
        None,
        description="Расписание события"
    )
    
    # Локация
    location: Optional[str] = Field(None, description="Место проведения события")
    address: Optional[str] = Field(None, description="Адрес места проведения")
    
    # Цена
    price: Optional[PriceInfo] = Field(None, description="Информация о цене")
    
    # Категории и интересы
    categories: List[str] = Field(default_factory=list, description="Категории события")
    category_ids: List[str] = Field(default_factory=list, description="Канонические ID категорий")
    category_primary: Optional[str] = Field(None, description="Основная категория верхнего уровня")
    category_secondary: List[str] = Field(default_factory=list, description="Вторичные категории")
    interests: List[WeightedInterest] = Field(
        default_factory=list,
        description="Интересы с весами (основное поле)"
    )
    interest_ids: List[str] = Field(default_factory=list, description="Канонические ID интересов")
    user_interests: List[str] = Field(default_factory=list, description="Интересы пользователей")
    
    # Изображения
    images: List[str] = Field(default_factory=list, description="Пути к изображениям события")
    poster_generated: bool = Field(default=False, description="Была ли сгенерирована афиша")
    
    # Источники
    sources: List[EventSource] = Field(default_factory=list, description="Источники информации")
    
    # Метаданные
    canonical_hash: Optional[str] = Field(None, description="Канонический хэш для дедупликации")
    processed_at: datetime = Field(default_factory=datetime.utcnow, description="Время обработки")
    
    @field_validator('categories', 'user_interests', 'category_secondary', 'category_ids', 'interest_ids')
    @classmethod
    def validate_lists(cls, v: List[str]) -> List[str]:
        """Удаление пустых строк из списков."""
        return [item.strip() for item in v if item and item.strip()]

    @field_validator('category_primary')
    @classmethod
    def validate_primary_category(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        normalized = v.strip()
        return normalized or None

    @field_validator('interests', mode='before')
    @classmethod
    def normalize_interests(cls, v: Any) -> List[Dict[str, Any]] | Any:
        """
        Совместимость со старым форматом:
        - ["музыка", "театр"] -> [{"name": "...", "weight": 0.5}, ...]
        """
        if v is None:
            return []

        if isinstance(v, list) and all(isinstance(item, str) for item in v):
            raw_names = [item.strip() for item in v if item and item.strip()]
            if not raw_names:
                return []
            uniform_weight = round(1.0 / len(raw_names), 4)
            return [{"name": name, "weight": uniform_weight} for name in raw_names]

        return v


class RawPost(BaseModel):
    """Модель сырого поста из MongoDB."""
    text: str = Field(..., description="Текст поста")
    photo_urls: Optional[List[str]] = Field(None, description="Список путей к локальным картинкам")
    hashtags: List[str] = Field(default_factory=list, description="Хештеги поста")
    post_id: int = Field(..., description="ID поста")
    channel: str = Field(..., description="Название канала")
    message_date: Optional[datetime] = Field(None, description="Дата публикации поста в Telegram")
    post_url: Optional[str] = Field(None, description="Ссылка на пост")
    
    class Config:
        """Конфигурация Pydantic модели."""
        populate_by_name = True


class ExtractionState(BaseModel):
    """Состояние LangGraph агента для извлечения событий."""
    
    # Входные данные
    raw_text: str = Field(..., description="Исходный текст поста")
    images: List[str] = Field(default_factory=list, description="Пути к изображениям")
    hashtags: List[str] = Field(default_factory=list, description="Хештеги")
    message_date: Optional[datetime] = Field(None, description="Дата публикации поста")
    channel: str = Field(default="", description="Название канала")
    post_id: int = Field(default=0, description="ID поста")
    
    # Промежуточные данные
    raw_events: List[str] = Field(
        default_factory=list,
        description="Список текстов отдельных событий после разделения"
    )
    
    # Выходные данные
    events: List[StructuredEvent] = Field(
        default_factory=list,
        description="Извлечённые структурированные события"
    )
    
    # Метаданные
    errors: List[str] = Field(default_factory=list, description="Ошибки при обработке")
    current_step: str = Field(default="init", description="Текущий шаг обработки")
    
    class Config:
        """Конфигурация Pydantic модели."""
        arbitrary_types_allowed = True


class Category(BaseModel):
    """Модель категории в БД."""
    name: str = Field(..., description="Название категории")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    usage_count: int = Field(default=0, description="Количество использований")
    
    class Config:
        """Конфигурация Pydantic модели."""
        populate_by_name = True


class UserInterest(BaseModel):
    """Модель интереса пользователя в БД."""
    name: str = Field(..., description="Название интереса")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    usage_count: int = Field(default=0, description="Количество использований")
    
    class Config:
        """Конфигурация Pydantic модели."""
        populate_by_name = True
