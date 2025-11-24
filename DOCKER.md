# Docker развертывание

Инструкция по развертыванию всего функционала через Docker.

## Требования

- Docker >= 20.10
- Docker Compose >= 2.0

## Быстрый старт

### 1. Подготовка

Скопируйте `.env.example` в `.env` и заполните необходимые переменные:

```bash
cp env.example .env
```

Отредактируйте `.env` файл, указав:
- Telegram API credentials
- LLM API ключи
- MongoDB credentials (если используете внешний MongoDB)
- JWT секретный ключ

### 2. Запуск всех сервисов

```bash
# Запуск MongoDB + FastAPI + AI процессор
docker-compose up -d

# Просмотр логов
docker-compose logs -f

# Остановка
docker-compose down
```

### 3. Запуск отдельных сервисов

```bash
# Только MongoDB + FastAPI
docker-compose up -d mongodb api

# MongoDB + FastAPI + AI процессор
docker-compose up -d mongodb api ai_processor

# Telegram парсер (однократный запуск)
docker-compose --profile parser up -d telegram_parser

# AI процессор (однократная обработка)
docker-compose --profile manual up -d ai_processor

# Schedulers (планировщики задач)
docker-compose --profile scheduler up -d telegram_scheduler ai_processor_scheduler
```

## Структура сервисов

### MongoDB
- Порт: `27017` (по умолчанию)
- Данные сохраняются в volume `mongodb_data`
- Автоматический healthcheck

### FastAPI (API)
- Порт: `8000` (по умолчанию)
- Доступен по адресу: `http://localhost:8000`
- Документация API: `http://localhost:8000/docs`

### AI процессор
- Обрабатывает необработанные посты из MongoDB
- Генерирует изображения и описания
- Запускается автоматически при старте

### Telegram парсер
- Парсит посты из Telegram каналов
- Сохраняет в MongoDB
- Запускается по требованию (profile: parser)

### Telegram Parser Scheduler
- Планирует автоматический парсинг Telegram каналов
- Первый запуск: парсинг за последние 3 месяца
- Последующие запуски: каждые 4 часа, парсинг за последние 4 часа
- Запускается по требованию (profile: scheduler)

### AI Processor Scheduler
- Планирует автоматическую обработку постов через AI
- Первый запуск: обработка всех необработанных постов
- Последующие запуски: каждые 4 часа, обработка новых необработанных постов
- Запускается по требованию (profile: scheduler)

## Production развертывание

Для production используйте дополнительный файл конфигурации:

```bash
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Production конфигурация включает:
- Ограничения ресурсов
- Ротацию логов
- Автоматический перезапуск

## Переменные окружения

Основные переменные (в `.env`):

```bash
# MongoDB
MONGO_ROOT_USERNAME=admin
MONGO_ROOT_PASSWORD=admin123
MONGODB_DB_NAME=events_db
MONGODB_PORT=27017

# FastAPI
API_PORT=8000
JWT_SECRET_KEY=your-secret-key-change-in-production

# Telegram
TG_API_ID=your_api_id
TG_API_HASH=your_api_hash

# LLM
LLM_BASE_URL=https://zenmux.ai/api/v1
LLM_API_KEYS=key1,key2
LLM_MODEL_NAME=google/gemini-3-pro-preview-free

# Image Generation
IMAGE_LLM_BASE_URL=https://zenmux.ai/api/v1
IMAGE_LLM_API_KEYS=key1,key2
IMAGE_LLM_MODEL=google/gemini-3-pro-image-preview-free
```

## Volumes

Проект использует следующие volumes:

- `./images` - директория с изображениями (монтируется в контейнеры)
- `./logs` - директория с логами
- `./telegram_parser_session.session` - сессия Telegram (для авторизации)
- `mongodb_data` - данные MongoDB
- `mongodb_config` - конфигурация MongoDB

## Полезные команды

```bash
# Просмотр статуса сервисов
docker-compose ps

# Просмотр логов конкретного сервиса
docker-compose logs -f api
docker-compose logs -f ai_processor

# Перезапуск сервиса
docker-compose restart api

# Остановка и удаление контейнеров
docker-compose down

# Остановка и удаление контейнеров + volumes (ОСТОРОЖНО: удалит данные!)
docker-compose down -v

# Пересборка образов
docker-compose build --no-cache

# Выполнение команды в контейнере
docker-compose exec api python -c "print('Hello')"

# Доступ к MongoDB shell
docker-compose exec mongodb mongosh -u admin -p admin123
```

## Troubleshooting

### Проблема: MongoDB не запускается

Проверьте логи:
```bash
docker-compose logs mongodb
```

Убедитесь, что порт 27017 свободен или измените `MONGODB_PORT` в `.env`.

### Проблема: API не может подключиться к MongoDB

Проверьте:
1. MongoDB запущен: `docker-compose ps`
2. Правильные credentials в `.env`
3. MONGODB_URI в контейнере: `docker-compose exec api env | grep MONGODB`

### Проблема: Telegram парсер не авторизуется

1. Убедитесь, что файл `telegram_parser_session.session` существует
2. Если нет, запустите парсер локально один раз для создания сессии
3. Скопируйте `.session` файл в корень проекта

### Проблема: AI процессор получает rate limit

Увеличьте задержки в коде или добавьте больше API ключей в `.env`.

## Обновление

```bash
# Остановка
docker-compose down

# Получение последних изменений
git pull

# Пересборка и запуск
docker-compose build --no-cache
docker-compose up -d
```

## Мониторинг

Просмотр использования ресурсов:
```bash
docker stats
```

Просмотр логов всех сервисов:
```bash
docker-compose logs -f --tail=100
```

