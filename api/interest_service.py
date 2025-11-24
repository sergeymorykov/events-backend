"""
Сервис для обновления интересов пользователя на основе действий.
"""

from typing import List, Dict, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from api.models import Event


# Веса для разных действий
ACTION_WEIGHTS = {
    "like": 1.0,
    "dislike": -0.8,
    "participate": 2.0
}

# Порог для включения интереса в список
INTEREST_THRESHOLD = 0.5


async def update_user_interests(
    user_id: str,
    event: Event,
    action: str,
    db: AsyncIOMotorDatabase
) -> Dict[str, float]:
    """
    Обновление interest_scores пользователя на основе действия.
    
    Args:
        user_id: ID пользователя
        event: Объект мероприятия
        action: Действие (like, dislike, participate)
        
    Returns:
        Обновленный словарь interest_scores
    """
    from bson import ObjectId
    
    # Получение текущих interest_scores пользователя
    if not ObjectId.is_valid(user_id):
        raise ValueError(f"Неверный формат ID пользователя: {user_id}")
    
    user_data = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user_data:
        raise ValueError(f"Пользователь {user_id} не найден")
    
    interest_scores: Dict[str, float] = user_data.get("interest_scores", {})
    
    # Вес действия
    weight = ACTION_WEIGHTS.get(action, 0.0)
    
    # Получение всех тегов из мероприятия
    tags = set(event.categories or [])
    tags.update(event.user_interests or [])
    
    # Обновление scores для каждого тега
    for tag in tags:
        if tag:
            current_score = interest_scores.get(tag, 0.0)
            interest_scores[tag] = current_score + weight
    
    # Пересчет interests на основе порога
    interests = [
        tag for tag, score in interest_scores.items()
        if score > INTEREST_THRESHOLD
    ]
    
    # Обновление в БД
    await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {
            "$set": {
                "interest_scores": interest_scores,
                "interests": interests
            }
        }
    )
    
    return interest_scores


async def check_user_action_exists(
    user_id: str,
    event_id: str,
    action: str,
    db: AsyncIOMotorDatabase
) -> bool:
    """
    Проверка существования действия пользователя.
    
    Args:
        user_id: ID пользователя
        event_id: ID мероприятия
        action: Действие (like, dislike, participate)
        
    Returns:
        True если действие уже существует
    """
    existing_action = await db.user_actions.find_one({
        "user_id": user_id,
        "event_id": event_id,
        "action": action
    })
    
    return existing_action is not None


async def get_user_action(
    user_id: str,
    event_id: str,
    db: AsyncIOMotorDatabase
) -> str:
    """
    Получение текущего действия пользователя для мероприятия (like/dislike).
    
    Args:
        user_id: ID пользователя
        event_id: ID мероприятия
        
    Returns:
        Действие ("like", "dislike") или None если действия нет
    """
    action_data = await db.user_actions.find_one({
        "user_id": user_id,
        "event_id": event_id,
        "action": {"$in": ["like", "dislike"]}
    })
    
    return action_data.get("action") if action_data else None


async def remove_user_action(
    user_id: str,
    event_id: str,
    action: str,
    db: AsyncIOMotorDatabase
) -> bool:
    """
    Удаление действия пользователя.
    
    Args:
        user_id: ID пользователя
        event_id: ID мероприятия
        action: Действие для удаления
        
    Returns:
        True если действие было удалено
    """
    result = await db.user_actions.delete_one({
        "user_id": user_id,
        "event_id": event_id,
        "action": action
    })
    
    return result.deleted_count > 0


async def update_user_interests_with_reversal(
    user_id: str,
    event: Event,
    new_action: str,
    old_action: Optional[str],
    db: AsyncIOMotorDatabase
) -> Dict[str, float]:
    """
    Обновление interest_scores с учетом переключения между лайком и дизлайком.
    Сначала отменяет старое действие, затем применяет новое.
    
    Args:
        user_id: ID пользователя
        event: Объект мероприятия
        new_action: Новое действие (like, dislike)
        old_action: Старое действие (like, dislike) или None
        
    Returns:
        Обновленный словарь interest_scores
    """
    from bson import ObjectId
    
    # Получение текущих interest_scores пользователя
    if not ObjectId.is_valid(user_id):
        raise ValueError(f"Неверный формат ID пользователя: {user_id}")
    
    user_data = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user_data:
        raise ValueError(f"Пользователь {user_id} не найден")
    
    interest_scores: Dict[str, float] = user_data.get("interest_scores", {})
    
    # Получение всех тегов из мероприятия
    tags = set(event.categories or [])
    tags.update(event.user_interests or [])
    
    # Сначала отменяем старое действие (если есть)
    if old_action and old_action in ACTION_WEIGHTS:
        old_weight = ACTION_WEIGHTS[old_action]
        for tag in tags:
            if tag:
                current_score = interest_scores.get(tag, 0.0)
                interest_scores[tag] = current_score - old_weight
    
    # Затем применяем новое действие
    new_weight = ACTION_WEIGHTS.get(new_action, 0.0)
    for tag in tags:
        if tag:
            current_score = interest_scores.get(tag, 0.0)
            interest_scores[tag] = current_score + new_weight
    
    # Пересчет interests на основе порога
    interests = [
        tag for tag, score in interest_scores.items()
        if score > INTEREST_THRESHOLD
    ]
    
    # Обновление в БД
    await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {
            "$set": {
                "interest_scores": interest_scores,
                "interests": interests
            }
        }
    )
    
    return interest_scores


async def cancel_user_action_effect(
    user_id: str,
    event: Event,
    action: str,
    db: AsyncIOMotorDatabase
) -> Dict[str, float]:
    """
    Отмена эффекта действия пользователя (обратный пересчет интересов).
    
    Args:
        user_id: ID пользователя
        event: Объект мероприятия
        action: Действие для отмены (like, dislike, participate)
        
    Returns:
        Обновленный словарь interest_scores
    """
    from bson import ObjectId
    
    # Получение текущих interest_scores пользователя
    if not ObjectId.is_valid(user_id):
        raise ValueError(f"Неверный формат ID пользователя: {user_id}")
    
    user_data = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user_data:
        raise ValueError(f"Пользователь {user_id} не найден")
    
    interest_scores: Dict[str, float] = user_data.get("interest_scores", {})
    
    # Вес действия (отрицательный для отмены)
    weight = ACTION_WEIGHTS.get(action, 0.0)
    
    # Получение всех тегов из мероприятия
    tags = set(event.categories or [])
    tags.update(event.user_interests or [])
    
    # Отмена эффекта действия для каждого тега
    for tag in tags:
        if tag:
            current_score = interest_scores.get(tag, 0.0)
            interest_scores[tag] = current_score - weight  # Вычитаем вес действия
    
    # Пересчет interests на основе порога
    interests = [
        tag for tag, score in interest_scores.items()
        if score > INTEREST_THRESHOLD
    ]
    
    # Обновление в БД
    await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {
            "$set": {
                "interest_scores": interest_scores,
                "interests": interests
            }
        }
    )
    
    return interest_scores

