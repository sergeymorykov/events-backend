"""
Инициализация MongoDB клиента для FastAPI приложения.
"""

import os
from motor.motor_asyncio import AsyncIOMotorClient
from typing import Optional

# Глобальный клиент MongoDB
mongodb_client: Optional[AsyncIOMotorClient] = None
database = None


async def connect_to_mongo():
    """Подключение к MongoDB."""
    global mongodb_client, database
    
    mongodb_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    db_name = os.getenv("MONGODB_DB_NAME", "events_db")
    
    mongodb_client = AsyncIOMotorClient(mongodb_uri)
    database = mongodb_client[db_name]
    
    # Проверка подключения
    try:
        await mongodb_client.admin.command('ping')
        print(f"✅ Подключение к MongoDB успешно: {db_name}")
    except Exception as e:
        print(f"❌ Ошибка подключения к MongoDB: {e}")
        raise


async def close_mongo_connection():
    """Закрытие подключения к MongoDB."""
    global mongodb_client
    
    if mongodb_client:
        mongodb_client.close()
        print("MongoDB соединение закрыто")


def get_database():
    """Получение объекта базы данных."""
    return database

