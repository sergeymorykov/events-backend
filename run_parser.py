"""
Скрипт запуска Telegram Parser из корневой директории.
"""

import asyncio
from telegram_parser.main import main

if __name__ == '__main__':
    asyncio.run(main())

