"""
FastAPI приложение для MVP-сервиса мероприятий.
"""

from datetime import datetime
from typing import List, Optional
from pathlib import Path
from fastapi import FastAPI, HTTPException, status, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId
import base64
from api.database import connect_to_mongo, close_mongo_connection, get_database
from api.models import (
    UserRegister, UserLogin, Token, EventResponse, EventFilters,
    UserResponse, MessageResponse, UserActionResponse, Event,
    PaginatedEventsResponse
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

# Раздача статических файлов (изображения)
# Путь к папке images относительно корня проекта
images_dir = Path(__file__).parent.parent / "images"
images_dir.mkdir(exist_ok=True)  # Создаем папку, если её нет

app.mount("/images", StaticFiles(directory=str(images_dir)), name="images")


# ===== Helper functions =====

async def enrich_events_with_user_actions(
    events: List[EventResponse],
    user_id: Optional[str],
    db: AsyncIOMotorDatabase
) -> List[EventResponse]:
    """Добавляет информацию о действиях пользователя к событиям."""
    if not user_id or not events:
        return events
    
    # Получаем все действия пользователя за один запрос
    event_ids = [event.id for event in events]
    user_actions_cursor = db.user_actions.find({
        "user_id": user_id,
        "event_id": {"$in": event_ids}
    })
    
    # Создаем словарь event_id -> список действий
    actions_map = {}
    async for action in user_actions_cursor:
        event_id = action["event_id"]
        if event_id not in actions_map:
            actions_map[event_id] = []
        actions_map[event_id].append(action["action"])
    
    # Добавляем user_actions к каждому событию
    for event in events:
        event.user_actions = actions_map.get(event.id, [])
    
    return events


# ===== Lifecycle events =====

@app.on_event("startup")
async def startup_event():
    """Инициализация при запуске."""
    await connect_to_mongo()
    
    # Создание индексов
    db = get_database()
    # Индекс для курсорной пагинации событий
    await db.processed_events.create_index([("date", -1), ("_id", -1)])
    # Индекс для обратной сортировки (asc)
    await db.processed_events.create_index([("date", 1), ("_id", 1)])
    # Текстовый индекс для поиска по title
    await db.processed_events.create_index(
        [("title", "text")],
        name="title_text_index"
    )
    # Уникальный индекс для nickname пользователей
    await db.users.create_index("nickname", unique=True)


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
            nickname=user_data.nickname,
            name=user_data.name,
            db=db
        )
        return UserResponse(
            id=str(user.id),
            nickname=user.nickname,
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
    user = await authenticate_user(user_data.nickname, db)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный nickname"
        )
    
    # Создание токена с nickname и интересами в payload
    access_token = create_access_token(
        data={
            "sub": str(user.id),
            "nickname": user.nickname,
            "interests": user.interests
        }
    )
    
    return Token(access_token=access_token)


# ===== Мероприятия =====

@app.get("/events", response_model=PaginatedEventsResponse)
async def get_events(
    cursor: Optional[str] = Query(None, description="Курсор для пагинации (base64-закодированная строка)"),
    limit: int = Query(20, ge=1, le=50, description="Количество событий на страницу"),
    search: Optional[str] = Query(None, description="Поиск по названию мероприятия"),
    sort_date: str = Query("desc", pattern="^(asc|desc)$", description="Сортировка по дате: asc | desc"),
    categories: Optional[List[str]] = Query(None, description="Фильтр по категориям (можно указать несколько через запятую)"),
    min_price: Optional[int] = Query(None, description="Минимальная цена"),
    max_price: Optional[int] = Query(None, description="Максимальная цена"),
    date_from: Optional[datetime] = Query(None, description="Дата начала периода"),
    date_to: Optional[datetime] = Query(None, description="Дата окончания периода"),
    for_my_interests: bool = Query(False, description="Фильтр по интересам пользователя"),
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Получение списка мероприятий с курсорной пагинацией и ранжированием по релевантности (при for_my_interests=True)."""
    
    # Построение фильтра
    filter_query = {}
    
    # Поиск по title (MongoDB text search)
    if search:
        filter_query["$text"] = {"$search": search}
    
    if categories:
        filter_query["categories"] = {"$all": categories}
    
    if min_price is not None or max_price is not None:
        price_filter = {}
        if min_price is not None:
            price_filter["$gte"] = min_price
        if max_price is not None:
            price_filter["$lte"] = max_price
        if price_filter:
            filter_query["price.amount"] = price_filter
    
    # Фильтр по дате (показываем все события, если не указаны конкретные даты)
    date_filter = {}
    
    # Применяем фильтр по дате только если явно указаны параметры
    if date_from:
        date_filter["$gte"] = date_from.replace(tzinfo=None)
    
    if date_to:
        date_filter["$lte"] = date_to.replace(tzinfo=None)
    
    if date_filter:
        filter_query["date"] = date_filter
    
    # Проверка авторизации для for_my_interests (фильтр не применяется в БД, только ранжирование)
    user_scores = {}
    if for_my_interests:
        if not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Требуется авторизация для фильтрации по интересам"
            )
        # Сохраняем веса для ранжирования ПОСЛЕ извлечения страницы
        user_scores = current_user.interest_scores or {}
    
    # Определение направления сортировки
    sort_direction = -1 if sort_date == "desc" else 1
    
    # Декодирование курсора
    cursor_date = None
    cursor_id = None
    if cursor:
        try:
            decoded = base64.urlsafe_b64decode(cursor).decode('utf-8')
            cursor_date, cursor_id_str = decoded.split('|')
            if not ObjectId.is_valid(cursor_id_str):
                raise ValueError("Invalid ObjectId in cursor")
            cursor_id = ObjectId(cursor_id_str)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Неверный формат курсора: {str(e)}"
            )
    
    # Добавление условия для курсорной пагинации
    if cursor_date and cursor_id:
        # Логика курсора зависит от направления сортировки
        if sort_direction == -1:  # desc - новые первые
            cursor_condition = {
                "$or": [
                    {"date": {"$lt": cursor_date}},
                    {"date": cursor_date, "_id": {"$lt": cursor_id}}
                ]
            }
        else:  # asc - старые первые
            cursor_condition = {
                "$or": [
                    {"date": {"$gt": cursor_date}},
                    {"date": cursor_date, "_id": {"$gt": cursor_id}}
                ]
            }
        
        if filter_query:
            filter_query = {"$and": [filter_query, cursor_condition]}
        else:
            filter_query = cursor_condition
    
    # Запрос: сортировка по дате и _id (направление зависит от sort_date)
    mongo_cursor = db.processed_events.find(filter_query).sort([
        ("date", sort_direction),
        ("_id", sort_direction)
    ]).limit(limit + 1)
    
    # Сбор данных в исходном порядке
    raw_events = []  # Для генерации курсоров (исходный порядок)
    events = []      # Для отображения (будет пересортирован при необходимости)
    async for event_data in mongo_cursor:
        # Сохраняем исходные данные для курсора
        raw_events.append({
            "date": event_data["date"],
            "_id": event_data["_id"]
        })
        
        # Преобразуем в EventResponse
        event_data["id"] = str(event_data.pop("_id"))
        if "processed_at" in event_data:
            event_data["processed_at"] = event_data["processed_at"].isoformat()
        events.append(EventResponse(**event_data))
    
    # Проверка наличия следующей страницы
    has_more = len(events) > limit
    if has_more:
        events = events[:limit]
        raw_events = raw_events[:limit]  # Только для курсора — порядок сохранён
    
    # === РАНЖИРОВАНИЕ ПО РЕЛЕВАНТНОСТИ (только внутри текущей страницы) ===
    if for_my_interests and user_scores and events:
        def calculate_relevance(event: EventResponse) -> float:
            score = 0.0
            # Суммируем веса из categories
            if event.categories:
                for cat in event.categories:
                    score += user_scores.get(cat, 0)
            # Суммируем веса из user_interests
            if event.user_interests:
                for interest in event.user_interests:
                    score += user_scores.get(interest, 0)
            return score

        # Сортируем: сначала по релевантности (убывание), затем по дате (убывание)
        events.sort(
            key=lambda e: (
                -calculate_relevance(e), 
                -datetime.fromisoformat(e.date).timestamp() if e.date else 0
            )
        )
        # ⚠️ raw_events НЕ трогаем — он нужен для курсоров в исходном порядке
    
    # Добавляем информацию о действиях пользователя
    if current_user:
        events = await enrich_events_with_user_actions(events, str(current_user.id), db)
    
    # === ГЕНЕРАЦИЯ КУРСОРОВ (по исходному порядку из raw_events) ===
    next_cursor = None
    if has_more and raw_events:
        last_raw = raw_events[-1]  # Последний в исходном порядке
        cursor_str = f"{last_raw['date']}|{str(last_raw['_id'])}"
        next_cursor = base64.urlsafe_b64encode(cursor_str.encode('utf-8')).decode('utf-8')
    
    prev_cursor = None
    if raw_events and cursor:  # Не первая страница
        first_raw = raw_events[0]  # Первый в исходном порядке
        cursor_str = f"{first_raw['date']}|{str(first_raw['_id'])}"
        prev_cursor = base64.urlsafe_b64encode(cursor_str.encode('utf-8')).decode('utf-8')
    
    return PaginatedEventsResponse(
        items=events,
        next_cursor=next_cursor,
        prev_cursor=prev_cursor
    )


@app.get("/events/{event_id}", response_model=EventResponse)
async def get_event(
    event_id: str,
    current_user: Optional[User] = Depends(get_current_user_optional),
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
    
    event_response = EventResponse(**event_data)
    
    # Добавляем информацию о действии пользователя
    if current_user:
        enriched = await enrich_events_with_user_actions([event_response], str(current_user.id), db)
        event_response = enriched[0]
    
    return event_response


@app.get("/categories", response_model=List[str])
async def get_categories(
    db: AsyncIOMotorDatabase = Depends(get_database)
):
    """Получение уникального списка категорий из всех мероприятий."""
    # Используем distinct для получения уникальных категорий
    categories = await db.processed_events.distinct("categories")
    
    # Удаляем пустые значения и сортируем
    categories = [cat for cat in categories if cat]
    categories.sort()
    
    return categories


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
        nickname=current_user.nickname,
        name=current_user.name,
        interests=current_user.interests
    )


# ===== Health check =====

@app.get("/health")
async def health_check():
    """Проверка работоспособности API."""
    return {"status": "ok"}

