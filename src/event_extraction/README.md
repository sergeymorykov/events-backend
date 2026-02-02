# Event Extraction Module

## Описание

Модуль для идемпотентной обработки Telegram постов с использованием LangGraph агента, семантической дедупликации через Qdrant и генерации афиш через LLM API.

## Архитектура

```
src/event_extraction/
├── __init__.py              # Экспорты модуля
├── config.py                # Конфигурация из .env
├── models.py                # Pydantic модели
├── langgraph_agent.py       # LangGraph агент для извлечения
├── post_processor.py        # Главный оркестратор
├── deduplicator.py          # Дедупликация через Qdrant
└── image_handler.py         # Генерация афиш
```

## Основные компоненты

### 1. PostProcessor
Главный оркестратор обработки постов:
- Проверка обработки поста по `(post_id, channel)`
- Вызов LangGraph агента для извлечения
- Дедупликация через Qdrant
- Сохранение результатов в MongoDB

**API:**
```python
processor = PostProcessor(db_client, qdrant_client, llm_client, image_handler)
events = await processor.process_post(raw_post_dict)
stats = await processor.process_new_posts_batch(limit=10)
```

### 2. EventExtractionGraph
LangGraph агент для многошагового извлечения:
- **split_into_events**: разделение поста на отдельные события
- **extract_event_data**: структурирование через LLM
- **process_images**: скачивание/генерация афиш

**API:**
```python
agent = EventExtractionGraph(llm_client, image_handler)
events = await agent.run_extraction_graph(text, message_date, channel, post_id)
```

### 3. EventDeduplicator
Семантическая дедупликация через Qdrant:
- Быстрый фильтр по каноническому хэшу (SHA256)
- Векторный поиск с порогом сходства (0.92)
- Обновление источников при обнаружении дубля

**API:**
```python
deduplicator = EventDeduplicator(qdrant_client, "events")
is_duplicate, original_id = await deduplicator.is_duplicate_event(event, embedding)
await deduplicator.add_event_to_index(event, embedding, event_id)
```

### 4. ImageHandler
Генерация афиш только через LLM API:
- OpenAI-совместимый API (Bothub/ZenMux/OpenAI)
- Ротация API ключей при rate limit
- Скачивание изображений из Telegram

**API:**
```python
handler = ImageHandler(images_dir, image_llm_base_url, image_llm_api_keys, image_llm_model)
poster_path = await handler.generate_event_poster(title, description)
```

## Модели данных

### StructuredEvent
Основная модель события:
```python
{
    "title": "Концерт в филармонии",
    "description": "Классическая музыка",
    "schedule": ScheduleExact(date_start=datetime(...)),
    "location": "Казанская филармония",
    "price": PriceInfo(amount=500, currency="RUB"),
    "categories": ["концерт", "музыка"],
    "user_interests": ["классика"],
    "images": ["poster.png"],
    "sources": [EventSource(channel="kazankay", post_id=123)]
}
```

### Типы расписаний

**ScheduleExact** - конкретная дата/время:
```python
ScheduleExact(
    date_start=datetime(2025, 12, 15, 19, 0),
    date_end=datetime(2025, 12, 15, 22, 0)
)
```

**ScheduleRecurringWeekly** - повторяющееся по дням недели:
```python
ScheduleRecurringWeekly(
    schedule={
        "monday": ["19:00", "21:00"],
        "friday": ["20:00"]
    },
    valid_from=datetime(2025, 12, 1),
    valid_until=datetime(2026, 1, 31)
)
```

**ScheduleFuzzy** - нечёткое расписание:
```python
ScheduleFuzzy(
    description="Каждые выходные в декабре",
    approximate_start=datetime(2025, 12, 1)
)
```

## Workflow обработки

1. **Проверка дубликата**: проверка `(post_id, channel)` в MongoDB
2. **Извлечение событий**: запуск LangGraph агента
   - Разделение на отдельные события
   - Структурирование данных
   - Обработка изображений
3. **Дедупликация**: для каждого события
   - Генерация эмбеддинга
   - Проверка по хэшу (быстрый фильтр)
   - Векторный поиск в Qdrant
4. **Сохранение**:
   - Если дубликат → обновление источников
   - Если новое → сохранение в MongoDB + Qdrant
5. **Отметка поста**: запись в `processed_posts`

## Конфигурация

Все настройки через переменные окружения (см. `.env`):

```env
# LLM
LLM_BASE_URL=https://api.mapleai.de/v1
LLM_MODEL_NAME=gpt-4o
LLM_API_KEYS=key1,key2

# Генерация изображений
IMAGE_LLM_BASE_URL=https://bothub.chat/api/v2/openai/v1
IMAGE_LLM_MODEL=dall-e-3
IMAGE_LLM_API_KEYS=key1,key2

# Qdrant
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_COLLECTION=events
QDRANT_SIMILARITY_THRESHOLD=0.92

# MongoDB
MONGODB_URI=mongodb://localhost:27017/
MONGODB_DB_NAME=events_db
```

## Использование

### Базовый пример
```python
from motor.motor_asyncio import AsyncIOMotorClient
from qdrant_client import QdrantClient
from openai import AsyncOpenAI
from src.event_extraction import PostProcessor, EventExtractionConfig, ImageHandler

# Инициализация
db_client = AsyncIOMotorClient(EventExtractionConfig.MONGODB_URI)
qdrant_client = QdrantClient(host=EventExtractionConfig.QDRANT_HOST)
llm_client = AsyncOpenAI(base_url=EventExtractionConfig.LLM_BASE_URL, api_key="...")
image_handler = ImageHandler(...)

processor = PostProcessor(db_client, qdrant_client, llm_client, image_handler)

# Обработка новых постов
stats = await processor.process_new_posts_batch(limit=10)
```

### Через скрипт
```bash
# Обработка всех новых постов
python run_event_extraction.py

# Обработка с лимитом
python run_event_extraction.py 50
```

## Тестирование

```bash
# Все тесты
pytest tests/event_extraction/ -v

# Конкретный модуль
pytest tests/event_extraction/test_post_processor.py -v

# С покрытием
pytest tests/event_extraction/ --cov=src.event_extraction
```

## Производительность

**Метрики:**
- Обработка 100 постов: < 60 сек (при доступности LLM)
- Извлечение 1 события: 2-5 сек
- Генерация афиши: 5-10 сек
- Дедупликация: < 100ms

**Оптимизация:**
- Используйте batch обработку
- Настройте ротацию API ключей
- Мониторьте Qdrant индексирование

## Миграция с ai_processor

**Основные изменения:**
- ❌ Удалён: `ai_processor/` модуль
- ✅ Новый: `src/event_extraction/` модуль
- ❌ Kandinsky API удалён
- ✅ Только LLM API для генерации афиш
- ✅ LangGraph для многошагового извлечения
- ✅ Qdrant для дедупликации
- ✅ Гибкие расписания (exact/recurring/fuzzy)

**Обновление импортов:**
```python
# Было
from ai_processor.processor import AIProcessor

# Стало
from src.event_extraction import PostProcessor
```

## Troubleshooting

### Qdrant не подключается
```bash
# Запуск через Docker
docker run -p 6333:6333 qdrant/qdrant
```

### Rate limit при генерации
- Добавьте больше ключей в `IMAGE_LLM_API_KEYS`
- Проверьте лимиты аккаунта

### Дубликаты не детектируются
- Уменьшите `QDRANT_SIMILARITY_THRESHOLD` (< 0.92)
- Проверьте работу Qdrant
- Проверьте логи эмбеддинга

## Документация

- **Полное руководство**: `GUIDE_EVENT_EXTRACTION.md`
- **API Reference**: См. docstrings в модулях
- **Примеры**: `tests/event_extraction/`

## Версия

**1.0.0** - Первый релиз
- LangGraph агент для извлечения
- Семантическая дедупликация через Qdrant
- Генерация афиш через LLM API
- Гибкие типы расписаний
