"""
FastAPI приложение для MVP-сервиса мероприятий.
"""

from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, HTTPException, status, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId
from api.database import connect_to_mongo, close_mongo_connection, get_database
from api.models import (
    UserRegister, UserLogin, Token, EventResponse, EventFilters,
    UserResponse, MessageResponse, UserActionResponse, Event
)
from api.auth import (
    create_user, authenticate_user, create_access_token,
    get_current_user, get_current_user_optional, get_user_interests_from_token
)
from api.interest_service import (
    update_user_interests, 
    check_user_action_exists,
    get_user_action,
    remove_user_action,
    update_user_interests_with_reversal,
    cancel_user_action_effect
)
from api.models import User

app = FastAPI(
    title="Events API",
    description="MVP-сервис мероприятий",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===== Lifecycle events =====

@app.on_event("startup")
async def startup_event():
    """Инициализация при запуске."""
    await connect_to_mongo()


@app.on_event("shutdown")
async def shutdown_event():
    """Очистка при завершении."""
    await close_mongo_connection()


# ===== Авторизация =====

@app.post("/auth/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(user_data: UserRegister, db: AsyncIOMotorDatabase = Depends(get_database)):
    """Регистрация нового пользователя."""
    try:
        user = await create_user(
            email=user_data.email,
            password=user_data.password,
            name=user_data.name,
            db=db
        )
        return UserResponse(
            id=str(user.id),
            email=user.email,
            name=user.name,
            interests=user.interests
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ошибка регистрации: {str(e)}"
        )


@app.post("/auth/login", response_model=Token)
async def login(user_data: UserLogin, db: AsyncIOMotorDatabase = Depends(get_database)):
    """Вход пользователя и получение JWT токена."""
    user = await authenticate_user(user_data.email, user_data.password, db)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный email или пароль"
        )
    
    # Создание токена с интересами в payload
    access_token = create_access_token(
        data={
            "sub": str(user.id),
            "interests": user.interests
        }
    )
    
    return Token(access_token=access_token)


# ===== Мероприятия =====

@app.get("/events", response_model=List[EventResponse])
async def get_events(
    categories: Optional[List[str]] = Query(None, description="Фильтр по категориям (можно указать несколько через запятую)"),
    min_price: Optional[int] = Query(None, description="Минимальная цена"),
    max_price: Optional[int] = Query(None, description="Максимальная цена"),
    date_from: Optional[datetime] = Query(None, description="Дата начала периода"),
    date_to: Optional[datetime] = Query(None, description="Дата окончания периода"),
    for_my_interests: bool = Query(False, description="Фильтр по интересам пользователя"),
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Получение списка мероприятий с фильтрацией из коллекции processed_events."""
    # Построение фильтра
    filter_query = {}
    
    if categories:
        # Фильтр по нескольким категориям: событие должно содержать хотя бы одну из указанных категорий
        filter_query["categories"] = {"$in": categories}
    
    if min_price is not None or max_price is not None:
        price_filter = {}
        if min_price is not None:
            price_filter["$gte"] = min_price
        if max_price is not None:
            price_filter["$lte"] = max_price
        if price_filter:
            filter_query["price.amount"] = price_filter
    
    # Фильтр по дате (date хранится как ISO 8601 строка в processed_events)
    if date_from or date_to:
        date_filter = {}
        if date_from:
            # Конвертируем datetime в ISO 8601 строку для сравнения
            # Убираем timezone info для корректного сравнения строк
            date_from_str = date_from.replace(tzinfo=None).isoformat()
            date_filter["$gte"] = date_from_str
        if date_to:
            date_to_str = date_to.replace(tzinfo=None).isoformat()
            date_filter["$lte"] = date_to_str
        if date_filter:
            filter_query["date"] = date_filter
    
    # Фильтр по интересам пользователя
    if for_my_interests:
        if not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Требуется авторизация для фильтрации по интересам"
            )
        
        # Получение интересов из токена или из БД
        user_interests = current_user.interests
        if user_interests:
            filter_query["$or"] = [
                {"categories": {"$in": user_interests}},
                {"user_interests": {"$in": user_interests}}
            ]
    
    # Получение мероприятий из коллекции processed_events
    cursor = db.processed_events.find(filter_query).sort("processed_at", -1)
    events = []
    
    async for event_data in cursor:
        # Переименовываем _id в id для корректной сериализации
        event_data["id"] = str(event_data.pop("_id"))
        # Преобразуем processed_at из datetime в строку, если нужно
        if "processed_at" in event_data and isinstance(event_data["processed_at"], datetime):
            event_data["processed_at"] = event_data["processed_at"].isoformat()
        events.append(EventResponse(**event_data))
    
    return events


@app.get("/events/{event_id}", response_model=EventResponse)
async def get_event(
    event_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Получение деталей мероприятия из коллекции processed_events."""
    if not ObjectId.is_valid(event_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверный формат ID мероприятия"
        )
    
    event_data = await db.processed_events.find_one({"_id": ObjectId(event_id)})
    
    if not event_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Мероприятие не найдено"
        )
    
    # Переименовываем _id в id для корректной сериализации
    event_data["id"] = str(event_data.pop("_id"))
    # Преобразуем processed_at из datetime в строку, если нужно
    if "processed_at" in event_data and isinstance(event_data["processed_at"], datetime):
        event_data["processed_at"] = event_data["processed_at"].isoformat()
    return EventResponse(**event_data)


# ===== Действия с мероприятиями =====

@app.post("/events/{event_id}/like", response_model=MessageResponse)
async def like_event(
    event_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Лайк мероприятия."""
    if not ObjectId.is_valid(event_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверный формат ID мероприятия"
        )
    
    # Проверка существования мероприятия
    event_data = await db.processed_events.find_one({"_id": ObjectId(event_id)})
    if not event_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Мероприятие не найдено"
        )
    
    event = Event(**event_data)
    
    user_id_str = str(current_user.id)
    
    # Проверяем текущее действие
    current_action = await get_user_action(user_id_str, event_id, db)
    
    # Если уже есть лайк - возвращаем ошибку
    if current_action == "like":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Вы уже поставили лайк этому мероприятию"
        )
    
    # Если есть дизлайк - удаляем его
    if current_action == "dislike":
        await remove_user_action(user_id_str, event_id, "dislike", db)
    
    # Сохранение нового действия
    action_data = {
        "user_id": user_id_str,
        "event_id": event_id,
        "action": "like",
        "created_at": datetime.utcnow()
    }
    await db.user_actions.insert_one(action_data)
    
    # Обновление интересов пользователя с учетом переключения
    await update_user_interests_with_reversal(
        user_id_str, 
        event, 
        "like", 
        current_action, 
        db
    )
    
    message = "Лайк поставлен" if not current_action else "Лайк поставлен (дизлайк отменен)"
    return MessageResponse(message=message)


@app.post("/events/{event_id}/dislike", response_model=MessageResponse)
async def dislike_event(
    event_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Дизлайк мероприятия."""
    if not ObjectId.is_valid(event_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверный формат ID мероприятия"
        )
    
    # Проверка существования мероприятия
    event_data = await db.processed_events.find_one({"_id": ObjectId(event_id)})
    if not event_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Мероприятие не найдено"
        )
    
    event = Event(**event_data)
    
    user_id_str = str(current_user.id)
    
    # Проверяем текущее действие
    current_action = await get_user_action(user_id_str, event_id, db)
    
    # Если уже есть дизлайк - возвращаем ошибку
    if current_action == "dislike":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Вы уже поставили дизлайк этому мероприятию"
        )
    
    # Если есть лайк - удаляем его
    if current_action == "like":
        await remove_user_action(user_id_str, event_id, "like", db)
    
    # Сохранение нового действия
    action_data = {
        "user_id": user_id_str,
        "event_id": event_id,
        "action": "dislike",
        "created_at": datetime.utcnow()
    }
    await db.user_actions.insert_one(action_data)
    
    # Обновление интересов пользователя с учетом переключения
    await update_user_interests_with_reversal(
        user_id_str, 
        event, 
        "dislike", 
        current_action, 
        db
    )
    
    message = "Дизлайк поставлен" if not current_action else "Дизлайк поставлен (лайк отменен)"
    return MessageResponse(message=message)


@app.post("/events/{event_id}/participate", response_model=MessageResponse)
async def participate_event(
    event_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Участие в мероприятии."""
    if not ObjectId.is_valid(event_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверный формат ID мероприятия"
        )
    
    # Проверка существования мероприятия
    event_data = await db.processed_events.find_one({"_id": ObjectId(event_id)})
    if not event_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Мероприятие не найдено"
        )
    
    event = Event(**event_data)
    
    # Проверка на повторное участие (можно участвовать несколько раз, но для логики проверим)
    existing_participation = await db.user_actions.find_one({
        "user_id": str(current_user.id),
        "event_id": event_id,
        "action": "participate"
    })
    
    if existing_participation:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Вы уже зарегистрированы на это мероприятие"
        )
    
    # Сохранение действия
    action_data = {
        "user_id": str(current_user.id),
        "event_id": event_id,
        "action": "participate",
        "created_at": datetime.utcnow()
    }
    await db.user_actions.insert_one(action_data)
    
    # Обновление интересов пользователя
    await update_user_interests(str(current_user.id), event, "participate", db)
    
    return MessageResponse(message="Вы зарегистрированы на мероприятие")


@app.delete("/events/{event_id}/like", response_model=MessageResponse)
async def unlike_event(
    event_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Отмена лайка мероприятия."""
    if not ObjectId.is_valid(event_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверный формат ID мероприятия"
        )
    
    # Проверка существования мероприятия
    event_data = await db.processed_events.find_one({"_id": ObjectId(event_id)})
    if not event_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Мероприятие не найдено"
        )
    
    event = Event(**event_data)
    user_id_str = str(current_user.id)
    
    # Проверяем, есть ли лайк
    if not await check_user_action_exists(user_id_str, event_id, "like", db):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Лайк не найден"
        )
    
    # Удаление действия
    await remove_user_action(user_id_str, event_id, "like", db)
    
    # Отмена эффекта на интересы пользователя
    await cancel_user_action_effect(user_id_str, event, "like", db)
    
    return MessageResponse(message="Лайк отменен")


@app.delete("/events/{event_id}/dislike", response_model=MessageResponse)
async def undislike_event(
    event_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Отмена дизлайка мероприятия."""
    if not ObjectId.is_valid(event_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверный формат ID мероприятия"
        )
    
    # Проверка существования мероприятия
    event_data = await db.processed_events.find_one({"_id": ObjectId(event_id)})
    if not event_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Мероприятие не найдено"
        )
    
    event = Event(**event_data)
    user_id_str = str(current_user.id)
    
    # Проверяем, есть ли дизлайк
    if not await check_user_action_exists(user_id_str, event_id, "dislike", db):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Дизлайк не найден"
        )
    
    # Удаление действия
    await remove_user_action(user_id_str, event_id, "dislike", db)
    
    # Отмена эффекта на интересы пользователя
    await cancel_user_action_effect(user_id_str, event, "dislike", db)
    
    return MessageResponse(message="Дизлайк отменен")


@app.delete("/events/{event_id}/participate", response_model=MessageResponse)
async def cancel_participation(
    event_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Отмена участия в мероприятии."""
    if not ObjectId.is_valid(event_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверный формат ID мероприятия"
        )
    
    # Проверка существования мероприятия
    event_data = await db.processed_events.find_one({"_id": ObjectId(event_id)})
    if not event_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Мероприятие не найдено"
        )
    
    event = Event(**event_data)
    user_id_str = str(current_user.id)
    
    # Проверяем, есть ли участие
    if not await check_user_action_exists(user_id_str, event_id, "participate", db):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Участие не найдено"
        )
    
    # Удаление действия
    await remove_user_action(user_id_str, event_id, "participate", db)
    
    # Отмена эффекта на интересы пользователя
    await cancel_user_action_effect(user_id_str, event, "participate", db)
    
    return MessageResponse(message="Участие отменено")


# ===== Профиль пользователя =====

@app.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """Получение информации о текущем пользователе."""
    return UserResponse(
        id=str(current_user.id),
        email=current_user.email,
        name=current_user.name,
        interests=current_user.interests
    )


# ===== Health check =====

@app.get("/health")
async def health_check():
    """Проверка работоспособности API."""
    return {"status": "ok"}

