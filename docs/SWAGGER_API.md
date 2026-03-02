# Swagger документация API

Документ описывает, как использовать Swagger/OpenAPI в проекте и какие endpoint доступны.

## 1) Где открыть Swagger

После запуска API (`python run_api.py`) доступны:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

## 2) Авторизация в Swagger

API использует Bearer JWT на защищённых маршрутах.

Порядок:

1. Выполни `POST /auth/register` (один раз).
2. Выполни `POST /auth/login` и получи `access_token`.
3. Нажми `Authorize` в Swagger и вставь:
   - `Bearer <access_token>`

После этого можно вызывать защищённые endpoint.

## 3) Группы endpoint

## Auth

- `POST /auth/register`
  - регистрация пользователя по `nickname` и `name`.
- `POST /auth/login`
  - выдача JWT токена.

## Events

- `GET /events`
  - список событий с фильтрацией и курсорной пагинацией.
  - query-параметры:
    - `cursor`
    - `limit` (1..50)
    - `search`
    - `sort_date` (`asc`/`desc`)
    - `categories` (повторяемый параметр)
    - `min_price`, `max_price`
    - `date_from`, `date_to`
    - `for_my_interests` (требует авторизации)

- `GET /events/{event_id}`
  - получение карточки события по id.

- `GET /categories`
  - список уникальных категорий.

## User actions

Требуют Bearer токен:

- `POST /events/{event_id}/like`
- `POST /events/{event_id}/dislike`
- `POST /events/{event_id}/participate`
- `DELETE /events/{event_id}/like`
- `DELETE /events/{event_id}/dislike`
- `DELETE /events/{event_id}/participate`

## Profile

- `GET /me`
  - профиль текущего пользователя.

## Service

- `GET /health`
  - health-check сервиса.

## 4) Пример сценария проверки через Swagger

1. `POST /auth/register`
2. `POST /auth/login`
3. `Authorize` с полученным токеном
4. `GET /events?limit=10`
5. Выбери `event_id` и вызови `GET /events/{event_id}`
6. Вызови `POST /events/{event_id}/like`
7. Проверь `GET /me`

## 5) Коды ответов, на которые смотреть

- `200` — успешный запрос
- `201` — успешная регистрация
- `400` — ошибка формата входных данных
- `401` — отсутствует/некорректен JWT
- `404` — сущность не найдена
- `409` — конфликт действия (например, повторный like)

## 6) Что важно для фронтенда

- Pagination курсором:
  - используй `next_cursor` из `GET /events` для следующей страницы.
- Для персонализированной выдачи:
  - передавай `for_my_interests=true` только с токеном.
- Для действий пользователя:
  - учитывай, что `like` и `dislike` взаимоисключающие.
