"""
Скрипт запуска планировщика Telegram Parser из корневой директории.
Запускает парсинг каждые 4 часа; первый запуск — за 3 последних месяца.
"""

import asyncio
from src.telegram_parser.scheduler import main

if __name__ == '__main__':
    asyncio.run(main())

