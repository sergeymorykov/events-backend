"""
Скрипт запуска планировщика Telegram Parser из корневой директории.
Автоматически запускает парсинг каждые 24 часа.
"""

import asyncio
from telegram_parser.scheduler import main

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.create_task(main())
    loop.run_forever()

