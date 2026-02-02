# 📖 Настройка и использование: Telegram Post Event Extractor

## Описание

Модуль **Event Extraction** предназначен для идемпотентной обработки Telegram постов с использованием:
- **LangGraph агента** для многошагового извлечения событий
- **Qdrant** для семантической дедупликации
- **LLM API** (Bothub/ZenMux) для генерации афиш
- Гибкого парсинга расписаний (exact, recurring_weekly, fuzzy)

## 1. Установка зависимостей

```bash
pip install -r requirements.txt
```

Основные зависимости:
- `langgraph==0.1.8` - для многошагового извлечения
- `qdrant-client==1.10.0` - для семантической дедупликации
- `python-dateutil==2.9.0` - для парсинга дат
- `pydantic==2.9.2` - для валидации данных
- `openai>=1.52.0` - для LLM API

## 2. Конфигурация

### 2.1. Переменные окружения

Создайте файл `.env` со следующими переменными:

```env
# ===== LLM API =====
LLM_BASE_URL=https://api.mapleai.de/v1
LLM_MODEL_NAME=gpt-4o
LLM_API_KEY=your_api_key_here
# Или несколько ключей для ротации:
# LLM_API_KEYS=key1,key2,key3

LLM_TEMPERATURE=0.7
LLM_MAX_TOKENS=2000

# ===== Генерация изображений =====
# Если не указано, используются основные LLM настройки
IMAGE_LLM_BASE_URL=https://bothub.chat/api/v2/openai/v1
IMAGE_LLM_MODEL=dall-e-3
IMAGE_LLM_API_KEYS=your_image_api_key

# ===== Qdrant Vector Database =====
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_API_KEY=
QDRANT_COLLECTION=events
QDRANT_VECTOR_SIZE=1536
QDRANT_SIMILARITY_THRESHOLD=0.92

# ===== MongoDB =====
MONGODB_URI=mongodb://localhost:27017/
MONGODB_DB_NAME=events_db

# ===== Telegram (для скачивания фото) =====
TG_API_ID=your_api_id
TG_API_HASH=your_api_hash
TG_SESSION_NAME=telegram_parser_session

# ===== Настройки обработки =====
IMAGES_DIR=images
MAX_EVENTS_PER_POST=5
BATCH_SIZE=10
```

### 2.2. Запуск Qdrant

#### Docker (рекомендуется):
```bash
docker run -p 6333:6333 -p 6334:6334 \
    -v $(pwd)/qdrant_storage:/qdrant/storage:z \
    qdrant/qdrant
```

#### Локально:
```bash
# Скачать с https://github.com/qdrant/qdrant/releases
./qdrant
```

## 3. Использование

### 3.1. Базовый пример

```python
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from qdrant_client import QdrantClient
from openai import AsyncOpenAI

from src.event_extraction import (
    PostProcessor,
    EventExtractionConfig,
    ImageHandler
)

async def main():
    # Валидация конфигурации
    valid, message = EventExtractionConfig.validate()
    if not valid:
        print(f"Ошибка конфигурации: {message}")
        return
    
    if message:
        print(f"Предупреждения:\n{message}")
    
    EventExtractionConfig.print_config()
    
    # Инициализация клиентов
    db_client = AsyncIOMotorClient(EventExtractionConfig.MONGODB_URI)
    
    qdrant_client = QdrantClient(
        host=EventExtractionConfig.QDRANT_HOST,
        port=EventExtractionConfig.QDRANT_PORT,
        api_key=EventExtractionConfig.QDRANT_API_KEY or None
    )
    
    llm_client = AsyncOpenAI(
        base_url=EventExtractionConfig.LLM_BASE_URL,
        api_key=EventExtractionConfig.get_api_keys()[0]
    )
    
    image_handler = ImageHandler(
        images_dir=EventExtractionConfig.IMAGES_DIR,
        image_llm_base_url=EventExtractionConfig.IMAGE_LLM_BASE_URL,
        image_llm_api_keys=EventExtractionConfig.get_image_api_keys(),
        image_llm_model=EventExtractionConfig.IMAGE_LLM_MODEL
    )
    
    # Инициализация процессора
    processor = PostProcessor(
        db_client=db_client,
        qdrant_client=qdrant_client,
        llm_client=llm_client,
        image_handler=image_handler,
        db_name=EventExtractionConfig.MONGODB_DB_NAME,
        qdrant_collection=EventExtractionConfig.QDRANT_COLLECTION,
        llm_model=EventExtractionConfig.LLM_MODEL_NAME,
        similarity_threshold=EventExtractionConfig.QDRANT_SIMILARITY_THRESHOLD
    )
    
    # Обработка новых постов
    stats = await processor.process_new_posts_batch(limit=10)
    
    print("\n=== Статистика обработки ===")
    print(f"Всего постов: {stats['total']}")
    print(f"Успешно: {stats['success']}")
    print(f"Ошибок: {stats['errors']}")
    print(f"Событий извлечено: {stats['events_extracted']}")

if __name__ == "__main__":
    asyncio.run(main())
```

### 3.2. Обработка одного поста

```python
# Пример raw_post из MongoDB
raw_post = {
    "text": "Концерт в Казани 15 декабря в 19:00. Филармония. Вход 500 руб.",
    "photo_urls": ["images/photo1.jpg"],
    "hashtags": ["#концерт", "#музыка"],
    "post_id": 12345,
    "channel": "kazankay",
    "message_date": datetime(2025, 12, 1, 10, 0, 0),
    "post_url": "https://t.me/kazankay/12345"
}

events = await processor.process_post(raw_post)

for event in events:
    print(f"Событие: {event.title}")
    print(f"Дата: {event.schedule.date_start if event.schedule else 'не указана'}")
    print(f"Категории: {', '.join(event.categories)}")
    print(f"Афиша сгенерирована: {event.poster_generated}")
```

### 3.3. Прямой вызов LangGraph агента

```python
from src.event_extraction import EventExtractionGraph

agent = EventExtractionGraph(
    llm_client=llm_client,
    image_handler=image_handler,
    model_name="gpt-4o"
)

events = await agent.run_extraction_graph(
    text="Концерт в Казани 15 декабря в 19:00",
    message_date=datetime(2025, 12, 1, 10, 0, 0),
    channel="kazankay",
    post_id=12345
)
```

### 3.4. Дедупликация вручную

```python
from src.event_extraction import EventDeduplicator

deduplicator = EventDeduplicator(
    qdrant_client=qdrant_client,
    collection_name="events",
    similarity_threshold=0.92
)

# Проверка дубликата
embedding = await llm_client.embeddings.create(
    model="text-embedding-ada-002",
    input=f"{event.title} {event.description}"
)

is_duplicate, original_id = await deduplicator.is_duplicate_event(
    event,
    embedding.data[0].embedding
)

if is_duplicate:
    print(f"Найден дубликат: {original_id}")
else:
    print("Новое событие")
```

## 4. Интеграция в основной проект

### 4.1. Замена старого модуля

1. **Удалить** старый модуль:
```bash
rm -rf ai_processor/
```

2. **Обновить** импорты в существующих скриптах:

```python
# Старый импорт
from ai_processor.processor import AIProcessor

# Новый импорт
from src.event_extraction import PostProcessor
```

### 4.2. Интеграция в scheduler

Файл: `run_event_extraction_scheduler.py`

```python
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from motor.motor_asyncio import AsyncIOMotorClient
from qdrant_client import QdrantClient
from openai import AsyncOpenAI

from src.event_extraction import (
    PostProcessor,
    EventExtractionConfig,
    ImageHandler
)

async def run_event_extraction_task():
    """Задача для периодической обработки постов."""
    try:
        # Инициализация клиентов
        db_client = AsyncIOMotorClient(EventExtractionConfig.MONGODB_URI)
        qdrant_client = QdrantClient(
            host=EventExtractionConfig.QDRANT_HOST,
            port=EventExtractionConfig.QDRANT_PORT
        )
        llm_client = AsyncOpenAI(
            base_url=EventExtractionConfig.LLM_BASE_URL,
            api_key=EventExtractionConfig.get_api_keys()[0]
        )
        image_handler = ImageHandler(
            images_dir=EventExtractionConfig.IMAGES_DIR,
            image_llm_base_url=EventExtractionConfig.IMAGE_LLM_BASE_URL,
            image_llm_api_keys=EventExtractionConfig.get_image_api_keys(),
            image_llm_model=EventExtractionConfig.IMAGE_LLM_MODEL
        )
        
        processor = PostProcessor(
            db_client=db_client,
            qdrant_client=qdrant_client,
            llm_client=llm_client,
            image_handler=image_handler
        )
        
        # Обработка новых постов (по 10 за раз)
        stats = await processor.process_new_posts_batch(limit=10)
        print(f"Обработано: {stats['success']}/{stats['total']}")
        
    except Exception as e:
        print(f"Ошибка: {e}")

def main():
    scheduler = AsyncIOScheduler()
    
    # Запуск каждые 30 минут
    scheduler.add_job(
        run_event_extraction_task,
        'interval',
        minutes=30
    )
    
    scheduler.start()
    print("Scheduler запущен. Нажмите Ctrl+C для остановки.")
    
    # Блокировка
    try:
        asyncio.get_event_loop().run_forever()
    except (KeyboardInterrupt, SystemExit):
        pass

if __name__ == "__main__":
    main()
```

## 5. Тестирование

```bash
# Запуск всех тестов
pytest tests/event_extraction/ -v --tb=short

# Запуск конкретного теста
pytest tests/event_extraction/test_post_processor.py -v

# С покрытием
pytest tests/event_extraction/ --cov=src.event_extraction --cov-report=html
```

## 6. Troubleshooting

### 6.1. Ошибка подключения к Qdrant

**Симптом**: `Connection refused` при подключении к Qdrant

**Решение**:
```bash
# Проверить, запущен ли Qdrant
curl http://localhost:6333/collections

# Перезапустить Qdrant
docker restart qdrant
```

### 6.2. Rate limit при генерации изображений

**Симптом**: Ошибки 429 от Image LLM API

**Решение**:
- Добавить больше API ключей в `IMAGE_LLM_API_KEYS`
- Увеличить задержки между запросами
- Проверить лимиты на аккаунте

### 6.3. Дубликаты событий не детектируются

**Симптом**: Создаются дубликаты событий

**Решение**:
- Проверить `QDRANT_SIMILARITY_THRESHOLD` (уменьшить для более строгой проверки)
- Убедиться, что Qdrant работает корректно
- Проверить логи на наличие ошибок эмбеддинга

## 7. Мониторинг и логирование

### 7.1. Уровни логирования

```python
import logging

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Для отладки
logging.getLogger('src.event_extraction').setLevel(logging.DEBUG)
```

### 7.2. Метрики

```python
# Статистика Qdrant
stats = deduplicator.get_statistics()
print(f"Всего событий в индексе: {stats['total_events']}")

# Статистика MongoDB
db = db_client[EventExtractionConfig.MONGODB_DB_NAME]
total_events = await db.events.count_documents({})
total_processed = await db.processed_posts.count_documents({})
print(f"Событий в БД: {total_events}")
print(f"Обработано постов: {total_processed}")
```

## 8. Производительность

### Ожидаемая производительность

- **Обработка 100 постов**: < 60 сек (при доступности LLM)
- **Генерация афиши**: 5-10 сек
- **Дедупликация**: < 100ms
- **Извлечение 1 события**: 2-5 сек

### Оптимизация

1. **Используйте batch обработку** с `process_new_posts_batch(limit=50)`
2. **Настройте ротацию ключей** для избежания rate limits
3. **Мониторьте Qdrant** - индексирование должно быть < 1сек
4. **Кэшируйте эмбеддинги** для повторяющихся текстов

## 9. Миграция с старого модуля

### 9.1. Различия в API

| Старый модуль | Новый модуль |
|--------------|--------------|
| `AIProcessor.process_raw_post()` | `PostProcessor.process_post()` |
| `ImageHandler.generate_image_kandinsky()` | `ImageHandler.generate_event_poster()` |
| Нет дедупликации | `EventDeduplicator` |
| Простое извлечение | LangGraph агент |

### 9.2. Миграция данных

```python
# Скрипт миграции существующих событий в Qdrant
async def migrate_events_to_qdrant():
    events = await db.events.find({}).to_list(length=None)
    
    for event in events:
        # Генерация эмбеддинга
        text = f"{event['title']} {event.get('description', '')}"
        embedding = await get_embedding(text)
        
        # Создание StructuredEvent
        structured = StructuredEvent(**event)
        
        # Добавление в Qdrant
        await deduplicator.add_event_to_index(
            structured, embedding, str(event['_id'])
        )
    
    print(f"Мигрировано событий: {len(events)}")
```

## 10. FAQ

**Q: Можно ли использовать без Qdrant?**  
A: Да, но дедупликация будет недоступна. Установите `QDRANT_HOST=""` для отключения.

**Q: Поддерживаются ли другие LLM провайдеры?**  
A: Да, любой OpenAI-совместимый API. Укажите `LLM_BASE_URL` и `LLM_API_KEY`.

**Q: Как обрабатываются повторяющиеся события?**  
A: Используйте `ScheduleRecurringWeekly` для событий с расписанием по дням недели.

**Q: Можно ли отключить генерацию афиш?**  
A: Да, не указывайте `IMAGE_LLM_MODEL` в конфигурации.

## Контакты и поддержка

- GitHub Issues: [ссылка на репозиторий]
- Документация API: см. docstrings в модулях
- Примеры: см. `tests/event_extraction/`
