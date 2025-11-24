"""
Модуль авторизации: JWT, хеширование паролей, middleware.
"""

import os
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
import bcrypt
from motor.motor_asyncio import AsyncIOMotorDatabase
from api.database import get_database
from api.models import User

# Настройки JWT
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

# HTTP Bearer для извлечения токена
security = HTTPBearer()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Проверка пароля."""
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8")
    )

def get_password_hash(password: str) -> str:
    """Хеширование пароля."""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Создание JWT токена."""
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_user_by_email(email: str, db: AsyncIOMotorDatabase) -> Optional[User]:
    """Получение пользователя по email."""
    from bson import ObjectId
    user_data = await db.users.find_one({"email": email})
    if user_data:
        user_data["_id"] = str(user_data["_id"])
        return User(**user_data)
    return None


async def create_user(email: str, password: str, name: str, db: AsyncIOMotorDatabase) -> User:
    """Создание нового пользователя."""
    # Проверка существования пользователя
    existing_user = await get_user_by_email(email, db)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пользователь с таким email уже существует"
        )
    
    # Создание пользователя
    password_hash = get_password_hash(password)
    user_data = {
        "email": email,
        "password_hash": password_hash,
        "name": name,
        "interests": [],
        "interest_scores": {}
    }
    
    result = await db.users.insert_one(user_data)
    user_data["_id"] = str(result.inserted_id)
    return User(**user_data)


async def authenticate_user(email: str, password: str, db: AsyncIOMotorDatabase) -> Optional[User]:
    """Аутентификация пользователя."""
    user = await get_user_by_email(email, db)
    if not user:
        return None
    
    if not verify_password(password, user.password_hash):
        return None
    
    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncIOMotorDatabase = Depends(get_database)
) -> User:
    """Получение текущего пользователя из JWT токена."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Не удалось подтвердить учетные данные",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        token = credentials.credentials
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    # Получение пользователя из БД
    from bson import ObjectId
    if not ObjectId.is_valid(user_id):
        raise credentials_exception
    
    user_data = await db.users.find_one({"_id": ObjectId(user_id)})
    if user_data is None:
        raise credentials_exception
    
    user_data["_id"] = str(user_data["_id"])
    return User(**user_data)


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
    db: AsyncIOMotorDatabase = Depends(get_database)
) -> Optional[User]:
    """Получение текущего пользователя из JWT токена (опционально, не требует токена)."""
    if not credentials:
        return None
    
    try:
        return await get_current_user(credentials, db)
    except HTTPException:
        return None


def get_user_interests_from_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> List[str]:
    """Получение интересов пользователя из JWT токена."""
    try:
        token = credentials.credentials
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        interests: List[str] = payload.get("interests", [])
        return interests
    except JWTError:
        return []

