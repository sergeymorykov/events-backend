# 🧪 Примеры использования

> **Навигация:** [📚 Документация](README.md) | [🏠 Главная](../README.md) | [🚀 Быстрый старт](QUICKSTART.md) | [🎯 Фильтры](FEATURE_CHANNEL_FILTERS.md)

---

## Примеры конфигураций для разных сценариев

### 1. Глобальные фильтры для всех каналов

**Задача**: Все каналы с одинаковыми фильтрами

```env
CHANNEL_USERNAME=moscowevents,spbevents,kazan_events

# Глобальные фильтры применятся ко всем каналам
HASHTAG_WHITELIST=концерт,фестиваль,выставка
HASHTAG_BLACKLIST=реклама,спам,18+
POSTS_LIMIT=200
```

### 2. Индивидуальные фильтры для каждого канала

**Задача**: Разные типы событий из разных каналов

```env
CHANNEL_USERNAME=moscowmusic,moscowtheater,moscowexpo

# Музыкальные события
CHANNEL_moscowmusic_WHITELIST=концерт,фестиваль,джаз,рок
CHANNEL_moscowmusic_BLACKLIST=детям

# Театральные события
CHANNEL_moscowtheater_WHITELIST=спектакль,премьера,театр
CHANNEL_moscowtheater_BLACKLIST=закрытое

# Выставки и экспо
CHANNEL_moscowexpo_WHITELIST=выставка,экспозиция,галерея
CHANNEL_moscowexpo_BLACKLIST=18+,реклама
```

### 3. Комбинированный подход (глобальные + специфичные)

**Задача**: Большинство каналов с общими фильтрами, один специальный

```env
CHANNEL_USERNAME=events1,events2,events3,vip_events

# Глобальные фильтры для events1, events2, events3
HASHTAG_WHITELIST=событие,мероприятие
HASHTAG_BLACKLIST=спам,реклама

# Специальные фильтры только для vip_events
CHANNEL_vip_events_WHITELIST=премиум,элитное,закрытое
CHANNEL_vip_events_BLACKLIST=массовое
```

### 4. Только blacklist без whitelist

**Задача**: Парсить всё, но исключить нежелательное

```env
CHANNEL_USERNAME=general_events

# Только blacklist - все хештеги разрешены, кроме указанных
HASHTAG_BLACKLIST=спам,реклама,18+,партнерство,pr
```

---

## Примеры текстов, которые распознаются

### ✅ Успешно распознаются:

```
1. "Концерт 23 ноября в 19:00 #концерт #москва"
   → Дата: 23.11.2025, Хештеги: [концерт, москва]

2. "Выставка современного искусства 10.12.2025 #выставка"
   → Дата: 10.12.2025, Хештеги: [выставка]

3. "Фестиваль завтра! #фестиваль #музыка"
   → Дата: {завтра}, Хештеги: [фестиваль, музыка]

4. "Театральная премьера 15 декабря 2025 года #театр"
   → Дата: 15.12.2025, Хештеги: [театр]

5. "Джазовый вечер сегодня в 20:00 #джаз #концерт"
   → Дата: {сегодня}, Хештеги: [джаз, концерт]
```

### ❌ Отфильтруются:

```
1. "Концерт был 1 января #концерт"
   → Причина: дата в прошлом (date_in_past)

2. "Мероприятие скоро! #событие #спам"
   → Причина: хештег в blacklist (если спам в HASHTAG_BLACKLIST)

3. "Интересное событие #новости"
   → Причина: нет разрешенных хештегов (если задан whitelist без 'новости')

4. "Концерт в ближайшее время"
   → Причина: дата не найдена (no_date_found)
```

---

## Тестирование фильтров

### Тест 1: Проверка глобального whitelist

**Конфигурация**:
```env
CHANNEL_USERNAME=test_channel
HASHTAG_WHITELIST=концерт,фестиваль
```

**Тестовые посты**:
```python
# ✅ Пройдет
"Концерт 23 ноября #концерт #москва"

# ✅ Пройдет
"Фестиваль завтра #фестиваль"

# ❌ Не пройдет (нет разрешенных хештегов)
"Выставка 10.12.2025 #выставка"

# ❌ Не пройдет (нет хештегов вообще)
"Мероприятие 15 декабря"
```

### Тест 2: Проверка специфичного whitelist

**Конфигурация**:
```env
CHANNEL_USERNAME=channel1,channel2

# Глобальный
HASHTAG_WHITELIST=событие

# Специфичный для channel1 (переопределяет глобальный)
CHANNEL_channel1_WHITELIST=концерт,фестиваль
```

**Результат**:
- `channel1`: пропустит только посты с #концерт или #фестиваль
- `channel2`: пропустит только посты с #событие

### Тест 3: Проверка blacklist с приоритетом

**Конфигурация**:
```env
CHANNEL_USERNAME=test_channel
HASHTAG_WHITELIST=концерт,фестиваль
HASHTAG_BLACKLIST=18+,закрытое
```

**Тестовые посты**:
```python
# ✅ Пройдет
"Концерт 23 ноября #концерт"

# ❌ Не пройдет (blacklist имеет приоритет)
"Фестиваль завтра #фестиваль #18+"

# ❌ Не пройдет (blacklist)
"Закрытое мероприятие 10.12.2025 #концерт #закрытое"
```

### Тест 3: Проверка парсинга дат

**Тестовые тексты**:
```python
test_cases = [
    # (текст, ожидаемая дата)
    ("Концерт 23 ноября", datetime(2025, 11, 23)),
    ("Мероприятие 10.12.2025", datetime(2025, 12, 10)),
    ("Выставка 2025-12-15", datetime(2025, 12, 15)),
    ("Событие завтра", datetime.now() + timedelta(days=1)),
    ("Фестиваль сегодня", datetime.now()),
]
```

**Проверка вручную**:
```python
from telegram_parser.date_parser import DateParser

parser = DateParser()

for text, expected in test_cases:
    result = parser.parse_date(text)
    print(f"Текст: {text}")
    print(f"Результат: {result}")
    print(f"Ожидалось: {expected}")
    print()
```

---

## MongoDB запросы для анализа

### Статистика по каналам

```javascript
// Количество постов по каналам
db.raw_posts.aggregate([
    { $group: { _id: "$channel", count: { $sum: 1 } } },
    { $sort: { count: -1 } }
])
```

### Топ хештегов

```javascript
// Самые популярные хештеги
db.raw_posts.aggregate([
    { $unwind: "$hashtags" },
    { $group: { _id: "$hashtags", count: { $sum: 1 } } },
    { $sort: { count: -1 } },
    { $limit: 20 }
])
```

### Валидные будущие события

```javascript
// Все валидные будущие мероприятия
db.raw_posts.find({
    filtered_reason: null,
    date_parsed: { $gte: new Date() }
}).sort({ date_parsed: 1 })
```

### Причины фильтрации

```javascript
// Статистика по причинам фильтрации
db.raw_posts.aggregate([
    { $match: { filtered_reason: { $ne: null } } },
    { $group: { _id: "$filtered_reason", count: { $sum: 1 } } },
    { $sort: { count: -1 } }
])
```

### События по дате

```javascript
// События на конкретную дату
db.raw_posts.find({
    filtered_reason: null,
    date_parsed: {
        $gte: ISODate("2025-11-23T00:00:00Z"),
        $lt: ISODate("2025-11-24T00:00:00Z")
    }
})
```

### Экспорт в JSON

```bash
# Экспорт всех валидных событий
mongoexport --db=events_db --collection=raw_posts \
  --query='{"filtered_reason": null}' \
  --out=valid_events.json
```

---

## Python скрипты для анализа

### Скрипт 1: Анализ результатов

```python
from pymongo import MongoClient
from datetime import datetime

client = MongoClient('mongodb://localhost:27017/')
db = client['events_db']

# Общая статистика
total = db.raw_posts.count_documents({})
valid = db.raw_posts.count_documents({'filtered_reason': None})
filtered = total - valid

print(f"📊 Статистика:")
print(f"  Всего постов: {total}")
print(f"  Валидных: {valid} ({valid/total*100:.1f}%)")
print(f"  Отфильтровано: {filtered} ({filtered/total*100:.1f}%)")

# Причины фильтрации
print(f"\n❌ Причины фильтрации:")
reasons = db.raw_posts.aggregate([
    {'$match': {'filtered_reason': {'$ne': None}}},
    {'$group': {'_id': '$filtered_reason', 'count': {'$sum': 1}}},
    {'$sort': {'count': -1}}
])

for reason in reasons:
    print(f"  {reason['_id']}: {reason['count']}")

# Ближайшие события
print(f"\n📅 Ближайшие 5 событий:")
events = db.raw_posts.find({
    'filtered_reason': None,
    'date_parsed': {'$gte': datetime.now()}
}).sort('date_parsed', 1).limit(5)

for event in events:
    print(f"  {event['date_parsed'].date()} - {event['channel']}")
    print(f"    {event['text'][:80]}...")
    print(f"    Хештеги: {', '.join(event['hashtags'][:5])}")
    print()
```

### Скрипт 2: Экспорт в CSV

```python
import csv
from pymongo import MongoClient
from datetime import datetime

client = MongoClient('mongodb://localhost:27017/')
db = client['events_db']

# Получение валидных событий
events = db.raw_posts.find({
    'filtered_reason': None,
    'date_parsed': {'$gte': datetime.now()}
}).sort('date_parsed', 1)

# Экспорт в CSV
with open('events.csv', 'w', encoding='utf-8', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['Дата', 'Канал', 'Текст', 'Хештеги', 'URL'])
    
    for event in events:
        writer.writerow([
            event['date_parsed'].strftime('%Y-%m-%d'),
            event['channel'],
            event['text'][:200],
            ', '.join(event['hashtags']),
            event['post_url']
        ])

print("✅ Экспорт завершен: events.csv")
```

### Скрипт 3: Календарь событий

```python
from pymongo import MongoClient
from datetime import datetime, timedelta
from collections import defaultdict

client = MongoClient('mongodb://localhost:27017/')
db = client['events_db']

# Группировка по датам
calendar = defaultdict(list)

events = db.raw_posts.find({
    'filtered_reason': None,
    'date_parsed': {
        '$gte': datetime.now(),
        '$lte': datetime.now() + timedelta(days=30)
    }
}).sort('date_parsed', 1)

for event in events:
    date_key = event['date_parsed'].date()
    calendar[date_key].append(event)

# Вывод календаря
print("📅 КАЛЕНДАРЬ СОБЫТИЙ (ближайшие 30 дней)\n")

for date in sorted(calendar.keys()):
    events_count = len(calendar[date])
    print(f"\n{date.strftime('%d.%m.%Y (%A)')} — {events_count} событий:")
    
    for event in calendar[date]:
        print(f"  • {event['text'][:60]}...")
        print(f"    Канал: {event['channel']}, Хештеги: {', '.join(event['hashtags'][:3])}")
```

---

## Отладка и логирование

### Уровни детализации логов

Отредактируйте `telegram_parser/main.py`:

```python
# Минимальные логи (только важное)
logging.basicConfig(level=logging.WARNING, ...)

# Стандартные логи (рекомендуется)
logging.basicConfig(level=logging.INFO, ...)

# Подробные логи (для отладки)
logging.basicConfig(level=logging.DEBUG, ...)
```

### Просмотр логов

```bash
# Последние 50 строк
tail -n 50 telegram_parser.log

# Следить за логами в реальном времени
tail -f telegram_parser.log

# Поиск ошибок
grep "ERROR" telegram_parser.log

# Статистика фильтрации
grep "отфильтрован" telegram_parser.log | wc -l
```

---

## Автоматизация

### Cron (Linux/Mac)

```bash
# Редактировать crontab
crontab -e

# Добавить задачу (каждый день в 9:00)
0 9 * * * cd /path/to/events-backend && /path/to/python run_parser.py >> /var/log/telegram_parser_cron.log 2>&1
```

### Windows Task Scheduler

```powershell
# PowerShell скрипт: run_parser.ps1
cd G:\events-backend
.\venv\Scripts\python.exe run_parser.py

# Создать задачу в Task Scheduler:
# Действие: Запуск программы
# Программа: powershell.exe
# Аргументы: -File "G:\events-backend\run_parser.ps1"
```

### Docker (опционально)

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY telegram_parser telegram_parser/
COPY run_parser.py .
COPY .env .

CMD ["python", "run_parser.py"]
```

```bash
# Собрать и запустить
docker build -t telegram-parser .
docker run --network host telegram-parser
```

---

## 📖 Дополнительная документация

- **[QUICKSTART.md](QUICKSTART.md)** — быстрый старт для новичков
- **[FEATURE_CHANNEL_FILTERS.md](FEATURE_CHANNEL_FILTERS.md)** — настройка фильтров
- **[SCHEDULER_GUIDE.md](SCHEDULER_GUIDE.md)** — автоматический парсинг по расписанию
- **[PRIVATE_CHANNELS.md](PRIVATE_CHANNELS.md)** — работа с приватными каналами
- **[Главный README](../README.md)** — обзор проекта и возможности

---

**Больше примеров?** Откройте Issue в репозитории!

**Telegram Parser v2.3** © 2025

