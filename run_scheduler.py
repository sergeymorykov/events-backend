"""
Скрипт запуска планировщика Telegram Parser из корневой директории.
Автоматически запускает парсинг каждые 24 часа.
"""

import asyncio
from telegram_parser.scheduler import main

if __name__ == '__main__':
    asyncio.run(main())

