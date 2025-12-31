"""
Скрипт запуска планировщика AI процессора из корневой директории.
Автоматически запускает обработку постов каждые 4 часа.
"""

import asyncio
from ai_processor.scheduler import main

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.create_task(main())
    loop.run_forever()

