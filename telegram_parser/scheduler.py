"""
Модуль планировщика задач для автоматического парсинга.
Запускает парсер каждые 24 часа.
"""

import asyncio
import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .config import Config
from .parser import TelegramParser

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('telegram_scheduler.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


class TelegramScheduler:
    """Планировщик для автоматического парсинга каналов."""
    
    def __init__(self, config: Config):
        """
        Инициализация планировщика.
        
        Args:
            config: Объект конфигурации
        """
        self.config = config
        self.scheduler = AsyncIOScheduler()
        self.parser: TelegramParser = None
        
    async def _is_first_run(self) -> bool:
        """
        Проверяет, является ли это первым запуском (нет постов в БД).
        
        Returns:
            True если это первый запуск, False иначе
        """
        try:
            from pymongo import MongoClient
            client = MongoClient(self.config.MONGODB_URI, serverSelectionTimeoutMS=5000)
            db = client[self.config.MONGODB_DB_NAME]
            collection = db['raw_posts']
            count = collection.count_documents({})
            client.close()
            return count == 0
        except Exception as e:
            logger.warning(f"Не удалось проверить первый запуск: {e}. Считаем, что это не первый запуск.")
            return False
    
    async def parse_job(self, is_first_run: bool = False):
        """
        Задача парсинга (вызывается по расписанию).
        
        Args:
            is_first_run: True если это первый запуск (парсинг за 3 месяца)
        """
        try:
            logger.info("=" * 60)
            logger.info(f"🕐 НАЧАЛО ЗАПЛАНИРОВАННОГО ПАРСИНГА")
            logger.info(f"   Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
            if is_first_run:
                logger.info("   Режим: ПЕРВЫЙ ЗАПУСК (парсинг за последние 3 месяца)")
            else:
                logger.info("   Режим: ОБЫЧНЫЙ ЗАПУСК (парсинг за последние 4 часа)")
            logger.info("=" * 60)
            
            # Создание нового парсера для каждого запуска
            self.parser = TelegramParser(self.config)
            
            # Запуск парсинга с соответствующим периодом
            if is_first_run:
                # Первый запуск: парсинг за последние 3 месяца (используется MONTHS_BACK из конфига)
                await self.parser.run(hours_back=None)
            else:
                # Обычный запуск: парсинг за последние 4 часа
                await self.parser.run(hours_back=4)
            
            logger.info("=" * 60)
            logger.info("✅ ЗАПЛАНИРОВАННЫЙ ПАРСИНГ ЗАВЕРШЕН")
            logger.info("=" * 60)
            
        except Exception as e:
            logger.error(f"❌ Ошибка в запланированном парсинге: {e}", exc_info=True)
    
    def start(self, immediate: bool = True, interval_hours: int = 4):
        """
        Запуск планировщика.
        
        Args:
            immediate: Запустить парсинг сразу при старте (по умолчанию True)
            interval_hours: Интервал между запусками в часах (по умолчанию 4)
        """
        logger.info("=" * 60)
        logger.info("🚀 ЗАПУСК ПЛАНИРОВЩИКА TELEGRAM PARSER")
        logger.info("=" * 60)
        
        # Вывод конфигурации
        logger.info(f"Каналы: {', '.join(self.config.get_channels())}")
        logger.info(f"Первый запуск: парсинг за последние {self.config.MONTHS_BACK} месяцев")
        logger.info(f"Последующие запуски: парсинг за последние 4 часа")
        logger.info(f"Интервал запуска: каждые {interval_hours} часов")
        
        if immediate:
            logger.info("⏰ Первый запуск: сразу при старте")
        else:
            logger.info(f"⏰ Первый запуск: через {interval_hours} часов")
        
        logger.info("=" * 60)
        
        # Добавление задачи в планировщик
        # Запуск каждые N часов
        self.scheduler.add_job(
            self.parse_job,
            trigger=IntervalTrigger(hours=interval_hours),
            id='parse_channels',
            name='Парсинг Telegram каналов',
            replace_existing=True,
            kwargs={'is_first_run': False}
        )
        
        # Запуск планировщика
        self.scheduler.start()
        
        # Если нужен немедленный первый запуск
        if immediate:
            logger.info("▶️  Запуск первого парсинга...")
            # Проверяем, первый ли это запуск
            async def first_run_check():
                is_first = await self._is_first_run()
                await self.parse_job(is_first_run=is_first)
            asyncio.create_task(first_run_check())
        
        logger.info("✅ Планировщик запущен и работает")
        logger.info(f"   Следующий запуск: через {interval_hours} часов")
        logger.info("   Нажмите Ctrl+C для остановки")
        logger.info("=" * 60)
    
    def start_daily(self, hour: int = 9, minute: int = 0, immediate: bool = False):
        """
        Запуск планировщика с ежедневным расписанием в конкретное время.
        
        Args:
            hour: Час запуска (0-23, по умолчанию 9)
            minute: Минута запуска (0-59, по умолчанию 0)
            immediate: Запустить парсинг сразу при старте (по умолчанию False)
        """
        logger.info("=" * 60)
        logger.info("🚀 ЗАПУСК ПЛАНИРОВЩИКА TELEGRAM PARSER (ЕЖЕДНЕВНО)")
        logger.info("=" * 60)
        
        # Вывод конфигурации
        logger.info(f"Каналы: {', '.join(self.config.get_channels())}")
        logger.info(f"Период парсинга: последние {self.config.MONTHS_BACK} месяцев")
        logger.info(f"⏰ Расписание: каждый день в {hour:02d}:{minute:02d}")
        
        if immediate:
            logger.info("▶️  Первый запуск: сразу при старте")
        
        logger.info("=" * 60)
        
        # Добавление задачи с cron триггером
        self.scheduler.add_job(
            self.parse_job,
            trigger=CronTrigger(hour=hour, minute=minute),
            id='parse_channels_daily',
            name='Ежедневный парсинг Telegram каналов',
            replace_existing=True
        )
        
        # Запуск планировщика
        self.scheduler.start()
        
        # Если нужен немедленный первый запуск
        if immediate:
            logger.info("▶️  Запуск первого парсинга...")
            asyncio.create_task(self.parse_job())
        
        logger.info("✅ Планировщик запущен и работает")
        logger.info(f"   Следующий запуск: {hour:02d}:{minute:02d}")
        logger.info("   Нажмите Ctrl+C для остановки")
        logger.info("=" * 60)
    
    def stop(self):
        """Остановка планировщика."""
        logger.info("Остановка планировщика...")
        self.scheduler.shutdown()
        logger.info("Планировщик остановлен")
    
    async def run_forever(self):
        """
        Запуск планировщика в бесконечном цикле.
        Блокирует выполнение до получения сигнала остановки.
        """
        try:
            # Ожидание завершения (бесконечно)
            while True:
                await asyncio.sleep(3600)  # Спим по часу
        except (KeyboardInterrupt, SystemExit):
            logger.info("\n⏹️  Получен сигнал остановки")
            self.stop()


async def main():
    """Точка входа для запуска планировщика."""
    try:
        # Валидация конфигурации
        is_valid, error_message = Config.validate()
        if not is_valid:
            logger.error(f"Ошибка конфигурации: {error_message}")
            logger.error("Проверьте файл .env")
            return
        
        # Создание и запуск планировщика
        scheduler = TelegramScheduler(Config)
        
        # Режим запуска
        # Первый запуск: парсинг за последние 3 месяца
        # Последующие запуски: каждые 4 часа, парсинг за последние 4 часа
        scheduler.start(immediate=True, interval_hours=4)
        
        # Вариант 2: Каждый день в 9:00 (без немедленного запуска)
        # scheduler.start_daily(hour=9, minute=0, immediate=False)
        
        # Вариант 3: Каждый день в 9:00 (с немедленным первым запуском)
        # scheduler.start_daily(hour=9, minute=0, immediate=True)
        
        # Вариант 4: Каждые 6 часов
        # scheduler.start(immediate=True, interval_hours=6)
        
        # Запуск вечного цикла
        await scheduler.run_forever()
        
    except KeyboardInterrupt:
        logger.info("Планировщик остановлен пользователем")
    except Exception as e:
        logger.critical(f"Критическая ошибка: {e}", exc_info=True)


if __name__ == '__main__':
    asyncio.run(main())

