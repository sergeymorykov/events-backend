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
    user_interests: List[str] = Field(default_factory=list, description="Интересы пользователей")
    
    # Изображения
    images: List[str] = Field(default_factory=list, description="Пути к изображениям события")
    poster_generated: bool = Field(default=False, description="Была ли сгенерирована афиша")
    
    # Источники
    sources: List[EventSource] = Field(default_factory=list, description="Источники информации")
    
    # Метаданные
    canonical_hash: Optional[str] = Field(None, description="Канонический хэш для дедупликации")
    embedding_vector: Optional[List[float]] = Field(None, description="Вектор эмбеддинга для семантического поиска")
    processed_at: datetime = Field(default_factory=datetime.utcnow, description="Время обработки")
    
    @field_validator('categories', 'user_interests')
    @classmethod
    def validate_lists(cls, v: List[str]) -> List[str]:
        """Удаление пустых строк из списков."""
        return [item.strip() for item in v if item and item.strip()]


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
