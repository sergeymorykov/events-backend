  """
  Модуль планировщика задач для автоматической обработки постов через AI.
  Запускает AI процессор каждые 4 часа.
  """

  import asyncio
  import logging
  import sys
  from datetime import datetime
  from pathlib import Path
  from apscheduler.schedulers.asyncio import AsyncIOScheduler
  from apscheduler.triggers.interval import IntervalTrigger

  from telethon import TelegramClient

  # Добавляем корневую директорию в путь для импорта
  sys.path.insert(0, str(Path(__file__).parent.parent))

  from ai_processor import AIProcessor
  from ai_processor.config import AIConfig

  # Настройка логирования
  logging.basicConfig(
      level=logging.INFO,
      format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
      datefmt='%Y-%m-%d %H:%M:%S',
      handlers=[
          logging.FileHandler('ai_processor_scheduler.log', encoding='utf-8'),
          logging.StreamHandler()
      ]
  )

  logger = logging.getLogger(__name__)


  class AIProcessorScheduler:
      """Планировщик для автоматической обработки постов через AI."""
      
      def __init__(self):
          """Инициализация планировщика."""
          self.scheduler = AsyncIOScheduler()
          self.processor: AIProcessor = None
          self.telegram_client: TelegramClient = None
          
      async def _is_first_run(self) -> bool:
          """
          Проверяет, является ли это первым запуском (нет обработанных событий в БД).
          
          Returns:
              True если это первый запуск, False иначе
          """
          try:
              from pymongo import MongoClient
              client = MongoClient(AIConfig.MONGODB_URI, serverSelectionTimeoutMS=5000)
              db = client[AIConfig.MONGODB_DB_NAME]
              collection = db['processed_events']
              count = collection.count_documents({})
              client.close()
              return count == 0
          except Exception as e:
              logger.warning(f"Не удалось проверить первый запуск: {e}. Считаем, что это не первый запуск.")
              return False
      
      async def _init_telegram_client(self) -> TelegramClient:
          """Инициализация Telegram клиента для скачивания фото."""
          if not AIConfig.TG_API_ID or not AIConfig.TG_API_HASH:
              return None
              
          try:
              logger.info("Инициализация Telegram клиента...")
              telegram_client = TelegramClient(
                  AIConfig.TG_SESSION_NAME,
                  int(AIConfig.TG_API_ID),
                  AIConfig.TG_API_HASH
              )
              await telegram_client.start()
              
              if await telegram_client.is_user_authorized():
                  me = await telegram_client.get_me()
                  logger.info(f"Telegram клиент авторизован: {me.first_name} (@{me.username})")
                  return telegram_client
              else:
                  logger.warning("Telegram клиент не авторизован")
                  await telegram_client.disconnect()
                  return None
                  
          except Exception as e:
              logger.error(f"Ошибка инициализации Telegram клиента: {e}")
              return None
      
      async def _init_processor(self) -> AIProcessor:
          """Инициализация AI процессора."""
          # Получение API ключей
          api_keys = AIConfig.get_api_keys()
          image_api_keys = AIConfig.get_image_api_keys()
          
          processor = AIProcessor(
              llm_base_url=AIConfig.LLM_BASE_URL,
              llm_api_keys=api_keys,
              llm_model_name=AIConfig.LLM_MODEL_NAME,
              llm_vision_model=AIConfig.LLM_VISION_MODEL,
              llm_temperature=AIConfig.LLM_TEMPERATURE,
              llm_max_tokens=AIConfig.LLM_MAX_TOKENS,
              kandinsky_api_key=AIConfig.KANDINSKY_API_KEY,
              kandinsky_secret_key=AIConfig.KANDINSKY_SECRET_KEY,
              image_llm_base_url=AIConfig.IMAGE_LLM_BASE_URL or AIConfig.LLM_BASE_URL,
              image_llm_api_keys=image_api_keys if image_api_keys else None,
              image_llm_model=AIConfig.IMAGE_LLM_MODEL,
              mongodb_uri=AIConfig.MONGODB_URI,
              mongodb_db_name=AIConfig.MONGODB_DB_NAME,
              images_dir=AIConfig.IMAGES_DIR,
              telegram_client=self.telegram_client
          )
          
          return processor
      
      async def process_job(self, is_first_run: bool = False):
          """
          Задача обработки постов (вызывается по расписанию).
          
          Args:
              is_first_run: True если это первый запуск
          """
          try:
              logger.info("=" * 60)
              logger.info(f"🕐 НАЧАЛО ЗАПЛАНИРОВАННОЙ ОБРАБОТКИ ПОСТОВ")
              logger.info(f"   Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
              
              if is_first_run:
                  logger.info("   Режим: ПЕРВЫЙ ЗАПУСК (обработка всех необработанных постов)")
              else:
                  logger.info("   Режим: ОБЫЧНЫЙ ЗАПУСК (обработка новых необработанных постов)")
              logger.info("=" * 60)
              
              # Инициализация Telegram клиента (если еще не инициализирован)
              if not self.telegram_client:
                  self.telegram_client = await self._init_telegram_client()
              
              # Создание нового процессора для каждого запуска
              self.processor = await self._init_processor()
              
              # Обработка всех необработанных постов
              # В обоих случаях обрабатываем все необработанные посты
              # (при первом запуске их будет много, при последующих - только новые)
              stats = await self.processor.process_all_unprocessed_posts(limit=None)
              
              logger.info("=" * 60)
              logger.info("✅ ЗАПЛАНИРОВАННАЯ ОБРАБОТКА ЗАВЕРШЕНА")
              logger.info(f"   Обработано: {stats['success']}/{stats['total']}")
              logger.info(f"   Ошибок: {stats['errors']}")
              logger.info("=" * 60)
              
              # Закрытие процессора после обработки
              if self.processor:
                  self.processor.close()
                  self.processor = None
              
          except Exception as e:
              logger.error(f"❌ Ошибка в запланированной обработке: {e}", exc_info=True)
              if self.processor:
                  try:
                      self.processor.close()
                  except:
                      pass
                  self.processor = None
      
      def start(self, immediate: bool = True, interval_hours: int = 4):
          """
          Запуск планировщика.
          
          Args:
              immediate: Запустить обработку сразу при старте (по умолчанию True)
              interval_hours: Интервал между запусками в часах (по умолчанию 4)
          """
          logger.info("=" * 60)
          logger.info("🚀 ЗАПУСК ПЛАНИРОВЩИКА AI PROCESSOR")
          logger.info("=" * 60)
          
          # Вывод конфигурации
          AIConfig.print_config()
          
          logger.info(f"Первый запуск: обработка всех необработанных постов")
          logger.info(f"Последующие запуски: обработка новых необработанных постов")
          logger.info(f"Интервал запуска: каждые {interval_hours} часов")
          
          if immediate:
              logger.info("⏰ Первый запуск: сразу при старте")
          else:
              logger.info(f"⏰ Первый запуск: через {interval_hours} часов")
          
          logger.info("=" * 60)
          
          # Добавление задачи в планировщик
          # Запуск каждые N часов
          self.scheduler.add_job(
              self.process_job,
              trigger=IntervalTrigger(hours=interval_hours),
              id='process_posts',
              name='Обработка постов через AI',
              replace_existing=True,
              kwargs={'is_first_run': False}
          )
          
        # Запуск планировщика
        self.scheduler.start()
        
        # Если нужен немедленный первый запуск
        if immediate:
            logger.info("▶️  Запуск первой обработки...")
            # Добавляем одноразовую задачу для немедленного запуска
            # Используем scheduler.add_job вместо asyncio.create_task
            async def first_run_check():
                is_first = await self._is_first_run()
                await self.process_job(is_first_run=is_first)
            
            # Добавление одноразовой задачи с немедленным запуском
            self.scheduler.add_job(
                first_run_check,
                id='first_run',
                name='Первый запуск обработки',
                replace_existing=True
            )
        
        logger.info("✅ Планировщик запущен и работает")
        logger.info(f"   Следующий запуск: через {interval_hours} часов")
        logger.info("   Нажмите Ctrl+C для остановки")
        logger.info("=" * 60)
      
    def stop(self):
        """Остановка планировщика."""
        logger.info("Остановка планировщика...")
        
        # Закрытие процессора
        if self.processor:
            try:
                self.processor.close()
            except:
                pass
        
        # Закрытие Telegram клиента
        if self.telegram_client:
            try:
                # Получаем текущий event loop и создаём задачу на отключение
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Если loop работает, создаём задачу
                    asyncio.ensure_future(self.telegram_client.disconnect())
                else:
                    # Если loop не работает, запускаем синхронно
                    loop.run_until_complete(self.telegram_client.disconnect())
            except Exception as e:
                logger.warning(f"Не удалось отключить Telegram клиент: {e}")
        
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
          is_valid, message = AIConfig.validate()
          if not is_valid:
              logger.error(f"Ошибка конфигурации: {message}")
              logger.error("Проверьте файл .env")
              return
          
          if message:  # Предупреждения
              logger.warning(message)
          
          # Создание и запуск планировщика
          scheduler = AIProcessorScheduler()
          
          # Режим запуска
          # Первый запуск: обработка всех необработанных постов
          # Последующие запуски: каждые 4 часа, обработка новых необработанных постов
          scheduler.start(immediate=True, interval_hours=4)
          
          # Запуск вечного цикла
          await scheduler.run_forever()
          
      except KeyboardInterrupt:
          logger.info("Планировщик остановлен пользователем")
      except Exception as e:
          logger.critical(f"Критическая ошибка: {e}", exc_info=True)


  if __name__ == '__main__':
      asyncio.run(main())

