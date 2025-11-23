"""
Скрипт для получения ID всех ваших каналов и чатов.
Используйте этот ID вместо invite hash для надежного парсинга.
"""

import asyncio
import os
from dotenv import load_dotenv
from telethon import TelegramClient

load_dotenv()


async def main():
    """Получение списка всех каналов с их ID."""
    api_id = int(os.getenv('TG_API_ID'))
    api_hash = os.getenv('TG_API_HASH')
    session_name = os.getenv('TG_SESSION_NAME', 'telegram_parser_session')
    
    print("\n🔐 Подключение к Telegram...")
    client = TelegramClient(session_name, api_id, api_hash)
    await client.start()
    
    print("\n" + "="*70)
    print("📋 ВАШИ КАНАЛЫ И ЧАТЫ")
    print("="*70 + "\n")
    
    channels_found = 0
    
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        
        # Показываем только каналы и супергруппы
        if hasattr(entity, 'broadcast') or hasattr(entity, 'megagroup'):
            title = getattr(entity, 'title', 'Без названия')
            entity_id = getattr(entity, 'id', 'unknown')
            username = getattr(entity, 'username', None)
            
            # Определяем тип
            if hasattr(entity, 'broadcast') and entity.broadcast:
                type_str = "📢 Канал"
            elif hasattr(entity, 'megagroup') and entity.megagroup:
                type_str = "👥 Супергруппа"
            else:
                type_str = "💬 Группа"
            
            # Приватный или публичный
            if username:
                access_str = f"@{username} (публичный)"
            else:
                access_str = "🔒 Приватный"
            
            print(f"{type_str}: {title}")
            print(f"  ID: {entity_id}")
            print(f"  Доступ: {access_str}")
            
            # Показываем пример использования
            if not username:  # Для приватных
                # Убираем -100 из ID для переменных фильтров
                clean_id = str(abs(entity_id))[3:] if str(abs(entity_id)).startswith('100') else str(abs(entity_id))
                print(f"  💡 В .env используйте:")
                print(f"     CHANNEL_USERNAME={entity_id}")
                print(f"     CHANNEL_{clean_id}_WHITELIST=...")
            
            print()
            channels_found += 1
    
    print("="*70)
    if channels_found == 0:
        print("⚠️  Каналы не найдены. Присоединитесь к каналам в Telegram.")
    else:
        print(f"✅ Найдено каналов/групп: {channels_found}")
        print("\n💡 Как использовать:")
        print("   1. Скопируйте ID нужного канала (например: -1001234567890)")
        print("   2. Добавьте в .env:")
        print("      CHANNEL_USERNAME=-1001234567890")
        print("   3. Для фильтров используйте ID без минуса и без 100:")
        print("      CHANNEL_1234567890_WHITELIST=событие,мероприятие")
    print("="*70)
    
    await client.disconnect()
    print("\n✅ Готово!\n")


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⏹️  Прервано пользователем")
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")

