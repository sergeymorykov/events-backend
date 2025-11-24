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

- `GET /events` - Список мероприятий с фильтрацией
  - Query параметры:
    - `categories` - фильтр по категориям (можно указать несколько через запятую, например: `?categories=концерт&categories=театр`)
    - `min_price`, `max_price` - фильтр по цене
    - `date_from`, `date_to` - фильтр по дате
    - `for_my_interests` - фильтр по интересам пользователя (требует авторизации)
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

