"""
Pydantic модели и схемы для FastAPI приложения.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any, Annotated
from pydantic import BaseModel, EmailStr, Field, BeforeValidator, field_validator
from bson import ObjectId


def validate_object_id(v: Any) -> str:
    if isinstance(v, ObjectId):
        return str(v)
    if isinstance(v, str) and ObjectId.is_valid(v):
        return v
    raise ValueError("Invalid ObjectId")


PyObjectId = Annotated[str, BeforeValidator(validate_object_id)]


# ===== Модели для авторизации =====

class UserRegister(BaseModel):
    """Модель регистрации пользователя."""
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=72, description="Пароль должен содержать 6-72 символов (и не более 72 байт)")
    name: str = Field(..., min_length=1, max_length=100)

class UserLogin(BaseModel):
    """Модель входа пользователя."""
    email: EmailStr
    password: str


class Token(BaseModel):
    """Модель JWT токена."""
    access_token: str
    token_type: str = "bearer"


# ===== Модели для мероприятий =====

class Price(BaseModel):
    """Модель цены мероприятия."""
    amount: Optional[int] = None
    currency: Optional[str] = None


class EventBase(BaseModel):
    """Базовая модель мероприятия (соответствует ProcessedEvent из ai_processor)."""
    title: Optional[str] = None
    description: Optional[str] = None
    date: Optional[str] = None  # ISO 8601 строка, как в ProcessedEvent
    price: Optional[Price] = None
    categories: List[str] = Field(default_factory=list)
    user_interests: List[str] = Field(default_factory=list)
    image_url: Optional[str] = None  # DEPRECATED, для совместимости
    image_urls: List[str] = Field(default_factory=list)
    image_caption: Optional[str] = None
    source_post_url: Optional[str] = None
    processed_at: Optional[datetime] = None
    raw_post_id: Optional[int] = None
    
    @field_validator('image_urls', 'categories', 'user_interests', mode='before')
    @classmethod
    def convert_none_to_list(cls, v):
        """Преобразует None в пустой список."""
        return v if v is not None else []


class Event(EventBase):
    """Модель мероприятия с ID."""
    id: PyObjectId = Field(alias="_id")
    
    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}


class EventResponse(EventBase):
    """Модель ответа с мероприятием (без внутренних полей)."""
    id: str  # Поле id без alias, так как мы переименовываем _id в id в коде
    
    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}


# ===== Модели для действий пользователя =====

class UserAction(BaseModel):
    """Модель действия пользователя."""
    user_id: str
    event_id: str
    action: str = Field(..., pattern="^(like|dislike|participate)$")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UserActionResponse(BaseModel):
    """Модель ответа с действием пользователя."""
    id: str
    user_id: str
    event_id: str
    action: str
    created_at: datetime


# ===== Модели для пользователя =====

class User(BaseModel):
    """Модель пользователя (для внутреннего использования)."""
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    email: EmailStr
    password_hash: str
    name: str
    interests: List[str] = Field(default_factory=list)
    interest_scores: Dict[str, float] = Field(default_factory=dict)
    
    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}


class UserResponse(BaseModel):
    """Модель ответа с пользователем (без чувствительных данных)."""
    id: str
    email: EmailStr
    name: str
    interests: List[str]


# ===== Модели для фильтров =====

class EventFilters(BaseModel):
    """Модель фильтров для поиска мероприятий."""
    category: Optional[str] = None
    min_price: Optional[int] = None
    max_price: Optional[int] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    for_my_interests: bool = False


# ===== Модели для ответов =====

class MessageResponse(BaseModel):
    """Модель простого текстового ответа."""
    message: str


class ErrorResponse(BaseModel):
    """Модель ответа с ошибкой."""
    detail: str


class PaginatedEventsResponse(BaseModel):
    """Модель ответа с пагинированным списком мероприятий."""
    items: List[EventResponse]
    next_cursor: Optional[str] = None
    prev_cursor: Optional[str] = None

