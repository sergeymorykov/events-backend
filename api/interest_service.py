"""
Сервис для обновления интересов пользователя на основе действий.
"""

from typing import Dict, Optional
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
# Коэффициент влияния категорий относительно explicit interests
CATEGORY_SIGNAL_WEIGHT = 0.35


def build_event_tag_weights(event: Event) -> Dict[str, float]:
    """
    Сбор весов тегов события для обновления интересов пользователя.

    Источники:
    1) event.interests (основной weighted формат)
    2) event.user_interests (legacy fallback)
    3) event.categories (дополнительный ослабленный сигнал)
    """
    tag_weights: Dict[str, float] = {}

    # Основной формат: weighted interests
    if event.interests:
        for item in event.interests:
            name = (item.name or "").strip()
            if not name:
                continue
            weight = float(item.weight or 0.0)
            if weight <= 0:
                continue
            tag_weights[name] = tag_weights.get(name, 0.0) + weight

    # Legacy fallback: если weighted отсутствуют
    elif event.user_interests:
        legacy = [tag.strip() for tag in event.user_interests if tag and tag.strip()]
        if legacy:
            uniform = 1.0 / len(legacy)
            for tag in legacy:
                tag_weights[tag] = tag_weights.get(tag, 0.0) + uniform

    # Дополнительный сигнал от категорий
    categories = [cat.strip() for cat in (event.categories or []) if cat and cat.strip()]
    if categories:
        per_category_weight = CATEGORY_SIGNAL_WEIGHT / len(categories)
        for category in categories:
            tag_weights[category] = tag_weights.get(category, 0.0) + per_category_weight

    return tag_weights


def apply_action_delta(
    interest_scores: Dict[str, float],
    tag_weights: Dict[str, float],
    action_weight: float
) -> Dict[str, float]:
    """
    Применение дельты действия к interest_scores по weighted тегам события.
    """
    updated = dict(interest_scores)
    for tag, tag_weight in tag_weights.items():
        if not tag:
            continue
        current_score = updated.get(tag, 0.0)
        updated[tag] = current_score + (action_weight * tag_weight)
    return updated


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
    
    # Взвешенное обновление интересов
    weight = ACTION_WEIGHTS.get(action, 0.0)
    tag_weights = build_event_tag_weights(event)
    interest_scores = apply_action_delta(interest_scores, tag_weights, weight)
    
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
    
    tag_weights = build_event_tag_weights(event)

    # Сначала отменяем старое действие (если есть)
    if old_action and old_action in ACTION_WEIGHTS:
        old_weight = ACTION_WEIGHTS[old_action]
        interest_scores = apply_action_delta(interest_scores, tag_weights, -old_weight)
    
    # Затем применяем новое действие
    new_weight = ACTION_WEIGHTS.get(new_action, 0.0)
    interest_scores = apply_action_delta(interest_scores, tag_weights, new_weight)
    
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
    
    tag_weights = build_event_tag_weights(event)
    # Вычитаем эффект действия
    interest_scores = apply_action_delta(interest_scores, tag_weights, -weight)
    
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

