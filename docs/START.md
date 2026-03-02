# Старт проекта

Документ описывает полный запуск проекта локально и через Docker.

## 1) Требования

- Python `3.11+`
- MongoDB `6+` (локально или удалённо)
- (Опционально) Qdrant для `event_extraction`
- (Опционально) Docker и Docker Compose

## 2) Установка

1. Установить зависимости:
   - `pip install -r requirements.txt`
2. Создать рабочий `.env`:
   - Windows: `copy env.example .env`
   - Linux/macOS: `cp env.example .env`
3. Заполнить минимум обязательных параметров:
   - `MONGODB_URI`
   - `MONGODB_DB_NAME`
   - `JWT_SECRET_KEY`
   - `TG_API_ID`
   - `TG_API_HASH`
   - `CHANNEL_USERNAME`

## 3) Что запускать в первую очередь

Рекомендуемая последовательность:

1. Telegram-парсер (наполнить `raw_posts`)
   - `python run_parser.py`
2. Event extraction (получить `processed_events`)
   - `python run_event_extraction.py`
3. API для клиентов
   - `python run_api.py`
4. Swagger UI
   - `http://localhost:8000/docs`

## 4) Режимы запуска

### Telegram Parser

- Разовый запуск: `python run_parser.py`
- Планировщик (альтернативно): `python -m src.telegram_parser.scheduler`

Выходные данные:
- коллекция `raw_posts`
- логи `telegram_parser.log` / `telegram_scheduler.log`

### Event Extraction

- Запуск: `python run_event_extraction.py`
- С лимитом постов: `python run_event_extraction.py 50`

Выходные данные:
- коллекция `processed_events`
- отметки в `processed_posts`
- сгенерированные файлы в `images/` (при включённой обработке изображений)

### API

- Запуск: `python run_api.py`
- Альтернатива: `uvicorn api.main:app --reload --host 0.0.0.0 --port 8000`

Проверка:
- `GET http://localhost:8000/health` -> `{"status":"ok"}`

### Мониторинг

- WebUI + метрики: `python run_webui.py --debug`
- Только endpoint метрик: `python run_webui.py`

Адреса:
- `http://localhost:8080/metrics`
- `http://localhost:8080/health`
- `http://localhost:8080/` (только при `--debug`)

## 5) Docker запуск

### API в контейнере

- `docker compose up --build`

Проверь:
- `http://localhost:8000/docs`

### Мониторинг стек (Prometheus + Grafana)

- `docker compose -f docker-compose.monitoring.yml up -d`

Проверь:
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000`

## 6) Частые проблемы на старте

- `401` на защищённых endpoint:
  - не передан `Authorization: Bearer <token>`
- `500` при чтении событий:
  - отсутствует/пустая коллекция `processed_events`
- парсер не стартует:
  - не заполнены `TG_API_ID`, `TG_API_HASH`, `CHANNEL_USERNAME`
- extraction падает на LLM:
  - не настроены `LLM_BASE_URL` и ключи (`LLM_API_KEYS`)

## 7) Минимальный smoke-test

1. `python run_api.py`
2. `POST /auth/register`
3. `POST /auth/login`
4. `GET /events`
5. `GET /categories`

Если шаги 2-5 проходят, API готово к интеграции.
