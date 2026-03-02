# events-backend

Бэкенд-система для сбора событий из Telegram, извлечения структурированных данных и публикации API для клиентских приложений.

## Быстрая навигация

- Подробный старт проекта: `docs/START.md`
- Что делает проект и как устроен: `docs/PROJECT_OVERVIEW.md`
- Swagger и работа с API: `docs/SWAGGER_API.md`
- Индекс документации: `docs/README.md`

## Основные компоненты

- `src/telegram_parser` — парсинг постов из Telegram в `raw_posts`.
- `src/event_extraction` — извлечение событий из сырых постов и сохранение в `processed_events`.
- `api` — FastAPI-приложение с JWT-авторизацией и выдачей событий.
- `src/monitoring` и `src/webui` — метрики Prometheus и WebUI мониторинга.

## Быстрый запуск

1. Установи зависимости: `pip install -r requirements.txt`
2. Создай `.env`: `copy env.example .env` (Windows) или `cp env.example .env` (Linux/macOS)
3. Запусти API: `python run_api.py`
4. Открой Swagger: `http://localhost:8000/docs`

## Лицензия

`LICENSE`
