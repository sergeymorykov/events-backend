"""
Скрипт для проверки конфигурации перед запуском парсера.
Проверяет наличие всех необходимых переменных окружения и подключений.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo import errors as mongo_errors

# Добавление родительской директории в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

# Загрузка переменных окружения
load_dotenv()


def check_env_vars():
    """Проверка наличия обязательных переменных окружения."""
    print("🔍 Проверка переменных окружения...")
    
    required_vars = {
        'TG_API_ID': 'Telegram API ID',
        'TG_API_HASH': 'Telegram API Hash',
        'CHANNEL_USERNAME': 'Username канала(ов) для парсинга'
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
                display_value = value[:4] + '*' * (len(value) - 4) if len(value) > 4 else '****'
            else:
                display_value = value
            print(f"  ✅ {var} = {display_value}")
    
    # Опциональные переменные
    optional_vars = {
        'TG_SESSION_NAME': os.getenv('TG_SESSION_NAME', 'telegram_parser_session'),
        'MONTHS_BACK': os.getenv('MONTHS_BACK', '3'),
        'HASHTAG_WHITELIST': os.getenv('HASHTAG_WHITELIST', '(не задан)'),
        'HASHTAG_BLACKLIST': os.getenv('HASHTAG_BLACKLIST', '(не задан)'),
        'MONGODB_URI': os.getenv('MONGODB_URI', 'mongodb://localhost:27017/'),
        'MONGODB_DB_NAME': os.getenv('MONGODB_DB_NAME', 'events_db')
    }
    
    print("\n📝 Опциональные переменные:")
    for var, value in optional_vars.items():
        print(f"  ℹ️  {var} = {value}")
    
    # Проверка списка каналов
    channels = [ch.strip() for ch in os.getenv('CHANNEL_USERNAME', '').split(',') if ch.strip()]
    if channels:
        print(f"\n📺 Каналы для парсинга ({len(channels)}):")
        for ch in channels:
            print(f"  • {ch}")
    
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
    
    session_name = os.getenv('TG_SESSION_NAME', 'telegram_parser_session')
    session_file = f"{session_name}.session"
    
    if os.path.exists(session_file):
        print(f"  ✅ Файл сессии найден: {session_file}")
        print(f"  ℹ️  Повторная авторизация не потребуется")
    else:
        print(f"  ℹ️  Файл сессии не найден: {session_file}")
        print(f"  💡 При первом запуске потребуется авторизация через Telegram:")
        print(f"      1. Введите номер телефона")
        print(f"      2. Введите код из Telegram")
        print(f"      3. Если включена 2FA — введите пароль")
    
    return True


def check_filters():
    """Проверка настроек фильтров."""
    print("\n🔍 Проверка настроек фильтров...")
    
    # Глобальные фильтры
    global_whitelist = os.getenv('HASHTAG_WHITELIST', '')
    global_blacklist = os.getenv('HASHTAG_BLACKLIST', '')
    
    print("\n📋 Глобальные фильтры (по умолчанию):")
    
    if global_whitelist:
        hashtags = [ht.strip().lstrip('#') for ht in global_whitelist.split(',') if ht.strip()]
        print(f"  ✅ Whitelist ({len(hashtags)}): {', '.join(f'#{ht}' for ht in hashtags)}")
    else:
        print(f"  ℹ️  Whitelist не задан (все хештеги разрешены)")
    
    if global_blacklist:
        hashtags = [ht.strip().lstrip('#') for ht in global_blacklist.split(',') if ht.strip()]
        print(f"  ✅ Blacklist ({len(hashtags)}): {', '.join(f'#{ht}' for ht in hashtags)}")
    else:
        print(f"  ℹ️  Blacklist не задан (нет запрещенных)")
    
    # Проверка специфичных фильтров для каждого канала
    channels = [ch.strip() for ch in os.getenv('CHANNEL_USERNAME', '').split(',') if ch.strip()]
    
    has_channel_filters = False
    for channel in channels:
        # Нормализуем имя канала для переменных окружения
        # Убираем + для приватных каналов
        normalized_channel = channel[1:] if channel.startswith('+') else channel
        
        channel_whitelist = os.getenv(f'CHANNEL_{normalized_channel}_WHITELIST', '')
        channel_blacklist = os.getenv(f'CHANNEL_{normalized_channel}_BLACKLIST', '')
        
        if channel_whitelist or channel_blacklist:
            if not has_channel_filters:
                print("\n📺 Специфичные фильтры для каналов:")
                has_channel_filters = True
            
            print(f"\n  Канал: {channel}")
            if channel.startswith('+'):
                print(f"    (Переменные: CHANNEL_{normalized_channel}_*)")
            
            if channel_whitelist:
                hashtags = [ht.strip().lstrip('#') for ht in channel_whitelist.split(',') if ht.strip()]
                print(f"    ✅ Whitelist: {', '.join(f'#{ht}' for ht in hashtags)}")
            else:
                print(f"    ℹ️  Whitelist: используется глобальный")
            
            if channel_blacklist:
                hashtags = [ht.strip().lstrip('#') for ht in channel_blacklist.split(',') if ht.strip()]
                print(f"    ✅ Blacklist: {', '.join(f'#{ht}' for ht in hashtags)}")
            else:
                print(f"    ℹ️  Blacklist: используется глобальный")
    
    if not has_channel_filters:
        print("\n  ℹ️  Специфичные фильтры для каналов не заданы")
        print("      Все каналы будут использовать глобальные фильтры")
    
    return True


def main():
    """Основная функция проверки."""
    print("=" * 60)
    print("🚀 Проверка конфигурации Telegram Parser v2.0")
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
    
    # Проверка фильтров
    filters_ok = check_filters()
    
    print("\n" + "=" * 60)
    if env_ok and mongo_ok and session_ok and filters_ok:
        print("✅ Все проверки пройдены успешно!")
        print("🎯 Можно запускать парсер:")
        print("   python run_parser.py")
        print("   или")
        print("   python telegram_parser/main.py")
    else:
        print("⚠️  Некоторые проверки не пройдены")
        print("💡 Исправьте указанные проблемы перед запуском парсера")
    print("=" * 60)


if __name__ == '__main__':
    main()
