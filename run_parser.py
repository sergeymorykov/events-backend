"""
Скрипт запуска Telegram Parser из корневой директории.
"""

import asyncio
import sys
from telegram_parser.main import main

if __name__ == '__main__':
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

