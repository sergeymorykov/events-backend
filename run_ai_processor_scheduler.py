"""
Планировщик запуска event_extraction каждые 4 часа.

Скрипт сохраняет старую точку входа `run_ai_processor_scheduler.py`,
но работает через новый модуль event_extraction.
"""

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.common.logging_utils import get_log_path
from run_event_extraction import main as run_event_extraction_main

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(get_log_path("event_extraction_scheduler.log"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

logger = logging.getLogger(__name__)


async def extraction_job() -> None:
    """Задача планировщика: единичный запуск extraction."""
    logger.info("Запуск event_extraction по расписанию")
    try:
        await run_event_extraction_main()
        logger.info("Запуск event_extraction завершен")
    except Exception as exc:
        logger.error("Ошибка в scheduled extraction: %s", exc, exc_info=True)


async def main() -> None:
    """Точка входа планировщика."""
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        extraction_job,
        trigger=IntervalTrigger(hours=4),
        id="event_extraction_job",
        replace_existing=True,
    )
    scheduler.start()

    logger.info("Планировщик event_extraction запущен (каждые 4 часа)")
    logger.info("Нажмите Ctrl+C для остановки")

    await extraction_job()
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())

