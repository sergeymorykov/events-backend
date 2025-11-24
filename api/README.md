# FastAPI Events API

MVP-сервис мероприятий с системой рекомендаций на основе интересов пользователей.

## Установка

1. Установите зависимости:
```bash
pip install -r requirements.txt
```

2. Создайте файл `.env` в папке `api/` на основе `api/.env.example`:
```bash
cp api/.env.example api/.env
```

3. Отредактируйте `.env` и укажите:
   - `MONGODB_URI` - строка подключения к MongoDB
   - `MONGODB_DB_NAME` - имя базы данных
   - `JWT_SECRET_KEY` - секретный ключ для JWT (минимум 32 символа)

## Запуск

```bash
# Из корневой директории проекта
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

Или используйте скрипт:
```bash
python -m uvicorn api.main:app --reload
```

API будет доступен по адресу: http://localhost:8000

## Документация

После запуска доступна автоматическая документация:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## API Endpoints

### Авторизация

- `POST /auth/register` - Регистрация нового пользователя
- `POST /auth/login` - Вход и получение JWT токена

### Мероприятия

- `GET /events` - Список мероприятий с курсорной пагинацией
  - Query параметры:
    - `cursor` (optional) - курсор для пагинации (base64-закодированная строка с датой и ID последнего события)
    - `limit` (optional, default=20, max=50) - количество событий на страницу
    - `categories` - фильтр по категориям (можно указать несколько через запятую, например: `?categories=концерт&categories=театр`)
    - `min_price`, `max_price` - фильтр по цене
    - `date_from`, `date_to` - фильтр по дате
    - `for_my_interests` - фильтр по интересам пользователя (требует авторизации)
  - Ответ:
    ```json
    {
      "items": [EventResponse, ...],
      "next_cursor": "base64_encoded_cursor",  // или null, если больше нет данных
      "prev_cursor": "base64_encoded_cursor"   // или null, если это первая страница
    }
    ```
  - Пример использования:
    ```bash
    # Первая страница
    GET /events?limit=20
    
    # Следующая страница (используя next_cursor из предыдущего ответа)
    GET /events?limit=20&cursor=MjAyNS0xMS0yOFQxOTozMDowMHw2NzQyZjEyM2FiY2RlZjEyMzQ1Njc4OTA
    
    # С фильтрами
    GET /events?limit=10&categories=концерт&min_price=500&cursor=...
    ```
- `GET /events/{event_id}` - Детали мероприятия

### Действия с мероприятиями

- `POST /events/{event_id}/like` - Поставить лайк (требует авторизации)
- `POST /events/{event_id}/dislike` - Поставить дизлайк (требует авторизации)
- `POST /events/{event_id}/participate` - Зарегистрироваться на мероприятие (требует авторизации)
- `DELETE /events/{event_id}/like` - Отменить лайк (требует авторизации)
- `DELETE /events/{event_id}/dislike` - Отменить дизлайк (требует авторизации)
- `DELETE /events/{event_id}/participate` - Отменить участие (требует авторизации)

### Профиль

- `GET /me` - Информация о текущем пользователе (требует авторизации)

## Использование JWT токена

После успешного входа вы получите JWT токен:
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "token_type": "bearer"
}
```

Используйте его в заголовке запросов:
```
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc...
```

## Система интересов

Система автоматически обновляет интересы пользователя на основе действий:

- **Лайк** → +1.0 к каждому тегу из `categories` и `user_interests`
- **Дизлайк** → -0.8 к каждому тегу
- **Участие** → +2.0 к каждому тегу

Интересы пересчитываются автоматически: теги со score > 0.5 попадают в список `interests`.

## Курсорная пагинация

Эндпоинт `GET /events` использует **cursor-based pagination** для эффективной работы с большими наборами данных.

### Преимущества курсорной пагинации:

- **Консистентность**: нет дубликатов или пропущенных элементов при добавлении/удалении данных
- **Производительность**: использует составной индекс `{"date": -1, "_id": -1}` для быстрых запросов
- **Двунаправленная навигация**: поддержка `next_cursor` и `prev_cursor` для перемещения вперёд и назад
- **Простота**: клиент просто передает курсор из предыдущего ответа

### Принцип работы:

1. **Первый запрос** (без `cursor`):
   - Возвращает первые N событий, отсортированных по `date DESC, _id DESC`
   - Если есть еще данные, возвращает `next_cursor`
   - `prev_cursor` будет `null` (первая страница)

2. **Последующие запросы** (с `cursor`):
   - Курсор декодируется из base64 в `date|_id`
   - Возвращаются события **строго раньше** указанной позиции
   - Фильтры применяются вместе с курсором
   - Возвращает `next_cursor` (если есть ещё данные) и `prev_cursor` (для возврата назад)

3. **Конец данных**:
   - Когда `next_cursor = null`, больше событий нет

### Формат курсора:

```
base64_encode("ISO_date|event_id")
```

Пример: `"2025-11-28T19:30:00|6742f123abcdef1234567890"` → `"MjAyNS0xMS0yOFQxOTozMDowMHw2NzQyZjEyM2FiY2RlZjEyMzQ1Njc4OTA="`

### Исправленные проблемы:

**Проблема**: При передаче `next_cursor` возвращалась та же самая страница.

**Причина**: Курсор генерировался из обработанных данных `EventResponse`, где поле `date` могло быть преобразовано, а `_id` уже был переименован в `id` (строка). Это приводило к несоответствию форматов при сравнении.

**Решение**: Теперь оригинальные значения `date` и `_id` сохраняются в отдельном массиве `raw_events` **до** преобразования, и используются для генерации курсоров. Это гарантирует, что курсор содержит точно такие же значения, как в базе данных.

### Использование prev_cursor:

`prev_cursor` позволяет реализовать навигацию назад. Он генерируется на основе **первого** элемента текущей страницы и возвращается только для страниц, которые не являются первыми.

**Важно**: Для перехода назад необходимо изменить логику запроса на клиенте: использовать `$gt` вместо `$lt` и сортировать в обратном порядке. Текущая реализация `prev_cursor` служит маркером для клиента, что можно вернуться назад.

### Пример использования:

```python
# Python example
import requests

base_url = "http://localhost:8000"
events = []
cursor = None

while True:
    params = {"limit": 20}
    if cursor:
        params["cursor"] = cursor
    
    response = requests.get(f"{base_url}/events", params=params)
    data = response.json()
    
    events.extend(data["items"])
    cursor = data.get("next_cursor")
    
    if not cursor:
        break  # Все данные получены

print(f"Всего событий: {len(events)}")
```

## Структура проекта

```
api/
├── __init__.py
├── main.py              # Точка входа, маршруты
├── models.py            # Pydantic модели
├── auth.py              # JWT, хеширование, middleware
├── interest_service.py  # Логика обновления интересов
├── database.py          # Инициализация MongoDB
├── .env.example         # Пример переменных окружения
└── README.md            # Документация
```

## MongoDB коллекции

### users
```json
{
  "_id": ObjectId,
  "email": "user@example.com",
  "password_hash": "...",
  "name": "Имя",
  "interests": ["музыка", "театр"],
  "interest_scores": {"музыка": 2.5, "театр": 1.8}
}
```

### processed_events
```json
{
  "_id": ObjectId,
  "title": "Концерт",
  "description": "...",
  "date": "2025-11-28T19:30:00",  // ISO 8601 строка
  "price": {"amount": 1000, "currency": "RUB"},
  "categories": ["концерт"],
  "user_interests": ["музыка"],
  "image_url": "...",  // DEPRECATED
  "image_urls": ["..."],
  "image_caption": "...",
  "source_post_url": "...",
  "processed_at": ISODate,
  "raw_post_id": 12345
}
```

**Важно:** API читает данные из коллекции `processed_events`, которая создается модулем `ai_processor`.

### user_actions
```json
{
  "_id": ObjectId,
  "user_id": "user_id",
  "event_id": "event_id",
  "action": "like|dislike|participate",
  "created_at": ISODate
}
```

## Безопасность

- Пароли хешируются через bcrypt
- JWT токены с алгоритмом HS256, срок действия 24 часа
- Валидация всех входных данных через Pydantic
- Middleware для проверки токена на защищенных эндпоинтах

## Обработка ошибок

- `400` - Неверный запрос
- `401` - Не авторизован
- `404` - Ресурс не найден
- `409` - Конфликт (повторное действие)

