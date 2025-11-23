"""
Скрипт для проверки конфигурации перед запуском парсера.
Проверяет наличие всех необходимых переменных окружения и подключений.
"""

import os
import sys
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo import errors as mongo_errors

# Загрузка переменных окружения
load_dotenv()


def check_env_vars():
    """Проверка наличия обязательных переменных окружения."""
    print("🔍 Проверка переменных окружения...")
    
    required_vars = {
        'TELEGRAM_API_ID': 'Telegram API ID',
        'TELEGRAM_API_HASH': 'Telegram API Hash',
        'TELEGRAM_CHANNEL_USERNAME': 'Username канала для парсинга'
    }
    
    missing_vars = []
    for var, description in required_vars.items():
        value = os.getenv(var)
        if not value:
            print(f"  ❌ {var} ({description}) - не найдена")
            missing_vars.append(var)
        else:
            # Скрываем чувствительные данные
            if 'HASH' in var or 'ID' in var:
                display_value = value[:4] + '*' * (len(value) - 4)
            else:
                display_value = value
            print(f"  ✅ {var} = {display_value}")
    
    # Опциональные переменные
    optional_vars = {
        'POSTS_LIMIT': os.getenv('POSTS_LIMIT', '100'),
        'MONGODB_URI': os.getenv('MONGODB_URI', 'mongodb://localhost:27017/'),
        'MONGODB_DB_NAME': os.getenv('MONGODB_DB_NAME', 'events_db'),
        'TELEGRAM_SESSION_NAME': os.getenv('TELEGRAM_SESSION_NAME', 'telegram_parser_session')
    }
    
    print("\n📝 Опциональные переменные (значения по умолчанию):")
    for var, value in optional_vars.items():
        print(f"  ℹ️  {var} = {value}")
    
    if missing_vars:
        print(f"\n❌ Отсутствуют обязательные переменные: {', '.join(missing_vars)}")
        print("💡 Создайте файл .env на основе env.example и заполните все поля")
        return False
    
    print("\n✅ Все обязательные переменные окружения установлены")
    return True


def check_mongodb_connection():
    """Проверка подключения к MongoDB."""
    print("\n🔍 Проверка подключения к MongoDB...")
    
    mongo_uri = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/')
    db_name = os.getenv('MONGODB_DB_NAME', 'events_db')
    
    try:
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        # Проверка подключения
        client.server_info()
        
        # Проверка базы данных
        db = client[db_name]
        collections = db.list_collection_names()
        
        print(f"  ✅ Подключение к MongoDB успешно")
        print(f"  📂 База данных: {db_name}")
        print(f"  📚 Существующие коллекции: {collections if collections else 'нет'}")
        
        # Проверка коллекции raw_posts
        if 'raw_posts' in collections:
            count = db['raw_posts'].count_documents({})
            print(f"  📊 Постов в коллекции raw_posts: {count}")
        else:
            print(f"  ℹ️  Коллекция raw_posts будет создана при первом запуске")
        
        client.close()
        return True
        
    except mongo_errors.ServerSelectionTimeoutError:
        print(f"  ❌ Не удалось подключиться к MongoDB: timeout")
        print(f"  💡 Проверьте, что MongoDB запущен и доступен по адресу: {mongo_uri}")
        return False
    except Exception as e:
        print(f"  ❌ Ошибка подключения к MongoDB: {e}")
        return False


def check_telethon_session():
    """Проверка наличия сессии Telethon."""
    print("\n🔍 Проверка сессии Telethon...")
    
    session_name = os.getenv('TELEGRAM_SESSION_NAME', 'telegram_parser_session')
    session_file = f"{session_name}.session"
    
    if os.path.exists(session_file):
        print(f"  ✅ Файл сессии найден: {session_file}")
        print(f"  ℹ️  Повторная авторизация не потребуется")
    else:
        print(f"  ℹ️  Файл сессии не найден: {session_file}")
        print(f"  💡 При первом запуске потребуется авторизация через Telegram")
        print(f"      1. Введите номер телефона")
        print(f"      2. Введите код из Telegram")
        print(f"      3. Если включена 2FA — введите пароль")
    
    return True


def main():
    """Основная функция проверки."""
    print("=" * 60)
    print("🚀 Проверка конфигурации Telegram Parser")
    print("=" * 60)
    print()
    
    # Проверка переменных окружения
    env_ok = check_env_vars()
    
    if not env_ok:
        print("\n" + "=" * 60)
        print("❌ Конфигурация не пройдена")
        print("=" * 60)
        sys.exit(1)
    
    # Проверка MongoDB
    mongo_ok = check_mongodb_connection()
    
    # Проверка сессии Telethon
    session_ok = check_telethon_session()
    
    print("\n" + "=" * 60)
    if env_ok and mongo_ok and session_ok:
        print("✅ Все проверки пройдены успешно!")
        print("🎯 Можно запускать парсер: python telegram_parser.py")
    else:
        print("⚠️  Некоторые проверки не пройдены")
        print("💡 Исправьте указанные проблемы перед запуском парсера")
    print("=" * 60)


if __name__ == '__main__':
    main()

