# AI Processor - Быстрый старт

Модуль для обработки постов из Telegram через AI (извлечение событий, генерация изображений).

## 🚀 Быстрый старт

### 1. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 2. Настройка переменных окружения

Создайте файл `.env` на основе `env.example`:

```bash
cp env.example .env
```

Обязательные параметры в `.env`:

```bash
# ===== AI PROCESSOR (Новый универсальный подход) =====
# Базовый URL API (ZenMux, OpenAI, GigaChat и др.)
LLM_BASE_URL=https://api.mapleai.de/v1

# API ключи (можно несколько через запятую для ротации)
LLM_API_KEYS=ваш_ключ_1,ваш_ключ_2

# Название модели
LLM_MODEL_NAME=gpt-4o

# Параметры генерации (опционально)
LLM_TEMPERATURE=0.7
LLM_MAX_TOKENS=2000

# Kandinsky для генерации изображений (получить на https://fusionbrain.ai/)
KANDINSKY_API_KEY=ваш_ключ_kandinsky
KANDINSKY_SECRET_KEY=ваш_секретный_ключ

# MongoDB (должна быть запущена)
MONGODB_URI=mongodb://localhost:27017/
MONGODB_DB_NAME=events_db

# Telegram API (для скачивания фото, опционально)
TG_API_ID=ваш_api_id
TG_API_HASH=ваш_api_hash
```

### 3. Запуск

#### Вариант 1: Обработка всех постов

```bash
python run_ai_processor.py
```

#### Вариант 2: Тестирование на одном посте

```bash
# Обработать один пост из БД
python test_single_post.py

# Или использовать тестовые данные
python test_single_post.py --mock
```

## 📊 Что происходит?

1. **Получение постов** из MongoDB (коллекция `raw_posts`)
2. **Обработка изображения:**
   - Скачивание из Telegram (если есть)
   - Или генерация через Kandinsky 3.1
3. **AI анализ** через LLM (GigaChat/OpenAI):
   - Извлечение названия, описания, даты
   - Определение цены
   - Категоризация события
   - Определение интересов пользователей
4. **Сохранение** в MongoDB (коллекция `processed_events`)

## 🗂️ Структура данных

### Входные данные (raw_posts)

```json
{
  "post_id": 12345,
  "text": "Концерт 25 ноября в 19:00...",
  "photo_url": {...},
  "post_url": "https://t.me/channel/12345",
  "hashtags": ["концерт", "музыка"]
}
```

### Выходные данные (processed_events)

```json
{
  "title": "Концерт джазовой музыки",
  "description": "Вечер живой музыки...",
  "date": "2025-11-25T19:00:00",
  "price": {"amount": 1500, "currency": "RUB"},
  "categories": ["концерт", "музыка"],
  "user_interests": ["джаз", "живая музыка"],
  "image_url": "images/generated_20251123_120000.png",
  "source_post_url": "https://t.me/channel/12345"
}
```

## 📋 Коллекции MongoDB

После обработки в БД появятся:

- **processed_events** - обработанные события
- **categories** - уникальные категории событий
- **user_interests** - уникальные интересы пользователей

## 🔧 Настройка

### Выбор LLM провайдера

Модуль теперь поддерживает **любой OpenAI-совместимый API** через универсальный подход:

#### ZenMux / MapleAI (рекомендуется)

```bash
LLM_BASE_URL=https://api.mapleai.de/v1
LLM_API_KEYS=ключ1,ключ2,ключ3  # Поддержка ротации!
LLM_MODEL_NAME=gpt-4o
```

**Преимущества:**
- Доступ к множеству моделей
- Автоматическая ротация ключей при rate limits
- Retry механизм с экспоненциальной задержкой

#### OpenAI

```bash
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEYS=ваш_ключ
LLM_MODEL_NAME=gpt-4o
```

Получить ключ: https://platform.openai.com/api-keys

#### GigaChat

```bash
LLM_BASE_URL=https://gigachat.devices.sberbank.ru/api/v1
LLM_API_KEYS=ваш_токен
LLM_MODEL_NAME=GigaChat-Max
```

Получить токен: https://developers.sber.ru/portal/products/gigachat

#### Другие провайдеры

Любой OpenAI-совместимый API: просто укажите `LLM_BASE_URL` и API ключи

### Kandinsky (генерация изображений)

Если не настроено - модуль будет работать только с постами, у которых уже есть фото.

```bash
KANDINSKY_API_KEY=ваш_ключ
KANDINSKY_SECRET_KEY=ваш_секрет
```

Получить: https://fusionbrain.ai/

## 📝 Логи

Логи сохраняются в `ai_processor.log`:

```bash
tail -f ai_processor.log
```

## 🎯 Примеры использования

### Обработка конкретного количества постов

Отредактируйте `run_ai_processor.py`:

```python
# Обработать только 10 постов
stats = await processor.process_all_unprocessed_posts(limit=10)
```

### Программное использование

```python
import asyncio
from ai_processor import AIProcessor
from ai_processor.config import AIConfig

async def main():
    api_keys = AIConfig.get_api_keys()
    
    processor = AIProcessor(
        llm_base_url=AIConfig.LLM_BASE_URL,
        llm_api_keys=api_keys,
        llm_model_name=AIConfig.LLM_MODEL_NAME,
        kandinsky_api_key=AIConfig.KANDINSKY_API_KEY,
        kandinsky_secret_key=AIConfig.KANDINSKY_SECRET_KEY,
        mongodb_uri=AIConfig.MONGODB_URI,
        mongodb_db_name=AIConfig.MONGODB_DB_NAME
    )
    
    # Обработка
    await processor.process_all_unprocessed_posts()
    
    processor.close()

asyncio.run(main())
```

## 🐛 Troubleshooting

### "Нет необработанных постов"

Сначала запустите парсер:

```bash
python run_parser.py
```

### "Ошибка конфигурации: GIGACHAT_TOKEN должен быть указан"

Проверьте файл `.env` - все обязательные переменные заполнены?

### "Не удалось подключиться к MongoDB"

Убедитесь, что MongoDB запущена:

```bash
# Локально
mongod

# Или используйте MongoDB Atlas (облачная версия)
```

### "Kandinsky API ключи не настроены"

Это предупреждение. Модуль будет работать, но:
- Генерация изображений будет недоступна
- Обрабатываются только посты с фото

## 📚 Дополнительная документация

- [Полная документация AI Processor](ai_processor/README.md)
- [Парсер Telegram](telegram_parser/README.md)
- [Примеры использования](telegram_parser/EXAMPLES.md)

## 💡 Полезные команды

```bash
# Полная обработка
python run_ai_processor.py

# Тест на одном посте
python test_single_post.py

# Тест с mock данными
python test_single_post.py --mock

# Просмотр логов
tail -f ai_processor.log

# Проверка статистики БД (Python)
python -c "from ai_processor import AIProcessor; from ai_processor.config import AIConfig; p = AIProcessor(llm_provider=AIConfig.LLM_PROVIDER, gigachat_token=AIConfig.GIGACHAT_TOKEN, mongodb_uri=AIConfig.MONGODB_URI, mongodb_db_name=AIConfig.MONGODB_DB_NAME); print(p.db_handler.get_statistics()); p.close()"
```

## 🎉 Готово!

После настройки просто запустите:

```bash
python run_ai_processor.py
```

И наблюдайте, как AI обрабатывает ваши посты! 🚀

