"""
FastAPI приложение для MVP-сервиса мероприятий.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pathlib import Path
from fastapi import FastAPI, HTTPException, status, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from motor.motor_asyncio import AsyncIOMotorDatabase
from openai import AsyncOpenAI
from qdrant_client import QdrantClient
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
from src.event_extraction.config import EventExtractionConfig
from src.event_extraction.normalization import TagNormalizer

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


def _coerce_to_datetime(value: Any) -> Optional[datetime]:
    """Преобразует строку/дату в datetime, если это возможно."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _extract_event_datetime(event_data: Dict[str, Any]) -> Optional[datetime]:
    """Извлекает дату события из legacy/new форматов."""
    direct_date = _coerce_to_datetime(event_data.get("date"))
    if direct_date:
        return direct_date

    schedule = event_data.get("schedule") or {}
    if isinstance(schedule, dict):
        for key in ("date_start", "valid_from", "approximate_start"):
            extracted = _coerce_to_datetime(schedule.get(key))
            if extracted:
                return extracted

    processed_at = _coerce_to_datetime(event_data.get("processed_at"))
    if processed_at:
        return processed_at

    return None


def _serialize_nested_datetimes(value: Any) -> Any:
    """Рекурсивно сериализует datetime в ISO-строки."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _serialize_nested_datetimes(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize_nested_datetimes(item) for item in value]
    return value


def _normalize_event_document(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Нормализует документ события из event_extraction под EventResponse API.
    """
    normalized = dict(event_data)

    event_dt = _extract_event_datetime(normalized)
    if event_dt and not normalized.get("date"):
        normalized["date"] = event_dt.isoformat()

    image_urls = normalized.get("image_urls")
    if not image_urls and isinstance(normalized.get("images"), list):
        normalized["image_urls"] = normalized.get("images", [])

    if not normalized.get("source_post_url"):
        sources = normalized.get("sources") or []
        if isinstance(sources, list) and sources:
            first_source = sources[0] or {}
            if isinstance(first_source, dict):
                normalized["source_post_url"] = first_source.get("post_url")

    if normalized.get("raw_post_id") is None:
        sources = normalized.get("sources") or []
        if isinstance(sources, list) and sources:
            first_source = sources[0] or {}
            if isinstance(first_source, dict):
                normalized["raw_post_id"] = first_source.get("post_id")

    if not normalized.get("user_interests") and isinstance(normalized.get("interests"), list):
        normalized["user_interests"] = [
            item.get("name")
            for item in normalized["interests"]
            if isinstance(item, dict) and item.get("name")
        ]

    if isinstance(normalized.get("schedule"), dict):
        normalized["schedule"] = _serialize_nested_datetimes(normalized["schedule"])

    return normalized


# ===== Lifecycle events =====

@app.on_event("startup")
async def startup_event():
    """Инициализация при запуске."""
    await connect_to_mongo()
    
    # Создание индексов
    db = get_database()
    # Индекс для курсорной пагинации событий
    await db.events.create_index([("date", -1), ("_id", -1)])
    # Индекс для обратной сортировки (asc)
    await db.events.create_index([("date", 1), ("_id", 1)])
    await db.events.create_index([("schedule.date_start", -1), ("_id", -1)])
    await db.events.create_index([("schedule.date_start", 1), ("_id", 1)])
    # Текстовый индекс для поиска по title
    await db.events.create_index(
        [("title", "text")],
        name="title_text_index"
    )
    # Уникальный индекс для nickname пользователей
    await db.users.create_index("nickname", unique=True)

    # Инициализация нормализатора тегов для фильтрации категорий через канонические ID.
    app.state.tag_normalizer = None
    try:
        llm_keys = EventExtractionConfig.get_api_keys()
        llm_client = None
        if llm_keys:
            llm_client = AsyncOpenAI(
                base_url=EventExtractionConfig.LLM_BASE_URL,
                api_key=llm_keys[0],
            )
        qdrant_client = QdrantClient(
            host=EventExtractionConfig.QDRANT_HOST,
            port=EventExtractionConfig.QDRANT_PORT,
            api_key=EventExtractionConfig.QDRANT_API_KEY or None,
        )
        app.state.tag_normalizer = TagNormalizer(
            llm_client=llm_client,
            model_name=EventExtractionConfig.LLM_MODEL_NAME,
            qdrant_client=qdrant_client,
            vector_size=EventExtractionConfig.QDRANT_VECTOR_SIZE,
        )
    except Exception:
        app.state.tag_normalizer = None


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
    
    # Построение базового фильтра (без даты/курсора)
    base_filter_query: Dict[str, Any] = {}
    
    # Поиск по title (MongoDB text search)
    if search:
        base_filter_query["$text"] = {"$search": search}
    
    if categories:
        category_ids: List[str] = []
        normalizer = getattr(app.state, "tag_normalizer", None)
        if normalizer:
            for category in categories:
                _, slug = await normalizer.resolve_tag(
                    category,
                    allow_llm_fallback=True,
                    kind="category",
                )
                if slug:
                    category_ids.append(slug)

        if category_ids:
            category_condition = {"category_ids": {"$all": category_ids}}
            if base_filter_query:
                base_filter_query = {"$and": [base_filter_query, category_condition]}
            else:
                base_filter_query = category_condition
        else:
            base_filter_query["categories"] = {"$all": categories}
    
    if min_price is not None or max_price is not None:
        price_filter = {}
        if min_price is not None:
            price_filter["$gte"] = min_price
        if max_price is not None:
            price_filter["$lte"] = max_price
        if price_filter:
            base_filter_query["price.amount"] = price_filter
    
    # Фильтр по вычисленной дате события
    event_date_filter: Dict[str, Any] = {}
    
    # Применяем фильтр по дате только если явно указаны параметры
    if date_from:
        event_date_filter["$gte"] = date_from.replace(tzinfo=None)
    
    if date_to:
        event_date_filter["$lte"] = date_to.replace(tzinfo=None)
    
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
            cursor_date_str, cursor_id_str = decoded.split('|')
            cursor_date = datetime.fromisoformat(cursor_date_str)
            if not ObjectId.is_valid(cursor_id_str):
                raise ValueError("Invalid ObjectId in cursor")
            cursor_id = ObjectId(cursor_id_str)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Неверный формат курсора: {str(e)}"
            )
    
    # Стадии агрегации: нормализуем дату события в поле _event_date
    event_date_expr: Dict[str, Any] = {
        "$ifNull": [
            {"$convert": {"input": "$date", "to": "date", "onError": None, "onNull": None}},
            {
                "$ifNull": [
                    {"$convert": {"input": "$schedule.date_start", "to": "date", "onError": None, "onNull": None}},
                    {
                        "$ifNull": [
                            {"$convert": {"input": "$schedule.valid_from", "to": "date", "onError": None, "onNull": None}},
                            {
                                "$ifNull": [
                                    {"$convert": {"input": "$schedule.approximate_start", "to": "date", "onError": None, "onNull": None}},
                                    {
                                        "$ifNull": [
                                            {"$convert": {"input": "$processed_at", "to": "date", "onError": None, "onNull": None}},
                                            {"$toDate": "$_id"}
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]
    }

    pipeline: List[Dict[str, Any]] = []
    if base_filter_query:
        pipeline.append({"$match": base_filter_query})

    pipeline.append({"$addFields": {"_event_date": event_date_expr}})

    if event_date_filter:
        pipeline.append({"$match": {"_event_date": event_date_filter}})

    if cursor_date and cursor_id:
        if sort_direction == -1:  # desc - новые первые
            cursor_condition = {
                "$or": [
                    {"_event_date": {"$lt": cursor_date}},
                    {"_event_date": cursor_date, "_id": {"$lt": cursor_id}}
                ]
            }
        else:  # asc - старые первые
            cursor_condition = {
                "$or": [
                    {"_event_date": {"$gt": cursor_date}},
                    {"_event_date": cursor_date, "_id": {"$gt": cursor_id}}
                ]
            }
        pipeline.append({"$match": cursor_condition})

    pipeline.extend([
        {"$sort": {"_event_date": sort_direction, "_id": sort_direction}},
        {"$limit": limit + 1}
    ])

    mongo_cursor = db.events.aggregate(pipeline)
    
    # Сбор данных в исходном порядке
    raw_events = []  # Для генерации курсоров (исходный порядок)
    events = []      # Для отображения (будет пересортирован при необходимости)
    async for event_data in mongo_cursor:
        # Сохраняем исходные данные для курсора
        raw_events.append({
            "_event_date": event_data.get("_event_date"),
            "_id": event_data["_id"]
        })

        event_data.pop("_event_date", None)
        event_data = _normalize_event_document(event_data)

        # Преобразуем в EventResponse
        event_data["id"] = str(event_data.pop("_id"))
        if "processed_at" in event_data and isinstance(event_data["processed_at"], datetime):
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
            # Суммируем сигнал из категорий
            if event.categories:
                for cat in event.categories:
                    score += user_scores.get(cat, 0)

            # Основной сигнал: weighted interests
            if event.interests:
                for interest in event.interests:
                    score += user_scores.get(interest.name, 0) * float(interest.weight)
            # Fallback для legacy-данных
            elif event.user_interests:
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
        cursor_str = f"{last_raw['_event_date'].isoformat()}|{str(last_raw['_id'])}"
        next_cursor = base64.urlsafe_b64encode(cursor_str.encode('utf-8')).decode('utf-8')
    
    prev_cursor = None
    if raw_events and cursor:  # Не первая страница
        first_raw = raw_events[0]  # Первый в исходном порядке
        cursor_str = f"{first_raw['_event_date'].isoformat()}|{str(first_raw['_id'])}"
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
    """Получение деталей мероприятия из коллекции events."""
    if not ObjectId.is_valid(event_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверный формат ID мероприятия"
        )
    
    event_data = await db.events.find_one({"_id": ObjectId(event_id)})
    
    if not event_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Мероприятие не найдено"
        )
    
    event_data = _normalize_event_document(event_data)

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
    categories = await db.events.distinct("categories")
    
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
    event_data = await db.events.find_one({"_id": ObjectId(event_id)})
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
    event_data = await db.events.find_one({"_id": ObjectId(event_id)})
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
    event_data = await db.events.find_one({"_id": ObjectId(event_id)})
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
    event_data = await db.events.find_one({"_id": ObjectId(event_id)})
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
    event_data = await db.events.find_one({"_id": ObjectId(event_id)})
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
    event_data = await db.events.find_one({"_id": ObjectId(event_id)})
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

