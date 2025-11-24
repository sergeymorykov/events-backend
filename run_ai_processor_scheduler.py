"""
Скрипт запуска планировщика AI процессора из корневой директории.
Автоматически запускает обработку постов каждые 4 часа.
"""

import asyncio
from ai_processor.scheduler import main

if __name__ == '__main__':
    asyncio.run(main())

