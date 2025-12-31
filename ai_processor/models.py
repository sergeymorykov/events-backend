"""
Pydantic модели для валидации данных в AI процессоре.
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator


class PriceInfo(BaseModel):
    """Информация о цене события."""
    amount: Optional[int] = Field(None, description="Стоимость в числовом формате")
    currency: Optional[str] = Field(None, description="Валюта (RUB, USD, EUR и т.д.)")


class ProcessedEvent(BaseModel):
    """Обработанное событие после AI-анализа."""
    
    # Основные поля
    title: Optional[str] = Field(None, description="Название события")
    description: Optional[str] = Field(None, description="Описание события")
    date: Optional[str] = Field(None, description="Дата события в формате ISO 8601")
    price: Optional[PriceInfo] = Field(None, description="Информация о цене")
    
    # Категории и интересы
    categories: List[str] = Field(default_factory=list, description="Список категорий события")
    user_interests: List[str] = Field(default_factory=list, description="Список пользовательских интересов")
    
    # Дополнительные поля
    image_urls: Optional[List[str]] = Field(None, description="Список путей к исходным или сгенерированным изображениям")
    image_url: Optional[str] = Field(None, description="[DEPRECATED] Старое поле, не использовать")
    image_caption: Optional[str] = Field(None, description="Описание изображения от AI")
    source_post_url: Optional[str] = Field(None, description="Ссылка на исходный пост")
    
    # Метаданные
    processed_at: datetime = Field(default_factory=datetime.utcnow, description="Время обработки")
    raw_post_id: Optional[int] = Field(None, description="ID исходного поста из raw_posts")
    
    @field_validator('date')
    @classmethod
    def validate_date_format(cls, v: Optional[str]) -> Optional[str]:
        """Валидация формата даты ISO 8601."""
        if v is None:
            return v
        try:
            datetime.fromisoformat(v.replace('Z', '+00:00'))
            return v
        except (ValueError, AttributeError):
            # Если дата невалидна, возвращаем None
            return None
    
    @field_validator('categories', 'user_interests')
    @classmethod
    def validate_lists(cls, v: List[str]) -> List[str]:
        """Удаление пустых строк из списков."""
        return [item.strip() for item in v if item and item.strip()]


class RawPost(BaseModel):
    """Модель сырого поста из MongoDB."""
    text: str = Field(..., description="Текст поста")
    photo_urls: Optional[List[str]] = Field(None, description="Список путей к локальным картинкам")
    photo_url: Optional[str] = Field(None, description="[DEPRECATED] Старое поле, не использовать")
    hashtags: List[str] = Field(default_factory=list, description="Хештеги поста")
    post_id: Optional[int] = Field(None, description="ID поста")
    message_date: Optional[datetime] = Field(None, description="Дата публикации поста в Telegram")
    
    class Config:
        """Конфигурация Pydantic модели."""
        populate_by_name = True


class LLMResponse(BaseModel):
    """Схема ответа от LLM."""
    title: Optional[str] = None
    description: Optional[str] = None
    date: Optional[str] = None
    price: Optional[PriceInfo] = None
    categories: List[str] = Field(default_factory=list)
    user_interests: List[str] = Field(default_factory=list)


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

