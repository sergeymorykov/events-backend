# WebUI Module - Monitoring Dashboard

## Описание

WebUI модуль предоставляет визуальный интерфейс для мониторинга системы обработки событий.

## Возможности

- ✅ Реал-тайм статистика (посты, события)
- ✅ Последние запуски парсера и extractor
- ✅ Процент обработки постов
- ✅ Prometheus метрики endpoint
- ✅ Health check endpoint
- ✅ Защита в production (DEBUG=false)
- ✅ Автообновление каждые 30 сек

## Структура

```
src/webui/
├── __init__.py       # Экспорты
├── app.py            # FastAPI приложение
└── templates/
    └── index.html    # Jinja2 шаблон
```

## API

### Endpoints

**`GET /`** - главная страница
- Требует: `DEBUG=true` в `.env`
- Возвращает: HTML страница со статистикой
- Автообновление: каждые 30 сек

**`GET /metrics`** - Prometheus метрики
- Доступ: без ограничений (для Prometheus)
- Формат: Prometheus text format
- Содержит: все метрики `event_extraction_*` и `telegram_parser_*`

**`GET /health`** - health check
- Доступ: без ограничений
- Формат: JSON `{"status": "ok", "timestamp": "..."}`

## Использование

### Запуск

```bash
# Production режим (только metrics)
uvicorn src.webui.app:create_web_app --factory --port 8080

# Debug режим (с WebUI)
DEBUG=true uvicorn src.webui.app:create_web_app --factory --port 8080 --reload

# Через скрипт
python run_webui.py --debug
```

### Программный вызов

```python
from src.webui.app import create_web_app

app = create_web_app()

# Запуск через uvicorn
import uvicorn
uvicorn.run(app, host="0.0.0.0", port=8080)
```

## Конфигурация

### Переменные окружения

```env
# MongoDB (обязательно)
MONGODB_URI=mongodb://localhost:27017/
MONGODB_DB_NAME=events_db

# Режим отладки (опционально)
DEBUG=true  # Включает доступ к WebUI
```

## Безопасность

### Production deployment

**Рекомендации:**
- ✅ `DEBUG=false` в production
- ✅ Ограничить доступ к WebUI (nginx auth)
- ✅ Metrics endpoint доступен только для Prometheus
- ✅ Использовать HTTPS

### Пример nginx

```nginx
server {
    listen 80;
    
    # WebUI - с аутентификацией
    location / {
        auth_basic "Monitoring";
        auth_basic_user_file /etc/nginx/.htpasswd;
        proxy_pass http://localhost:8080;
    }
    
    # Metrics - только для Prometheus
    location /metrics {
        allow 10.0.0.0/8;
        deny all;
        proxy_pass http://localhost:8080/metrics;
    }
}
```

## Статистика

### Отображаемые данные

| Метрика | Источник | Обновление |
|---------|----------|------------|
| Всего постов | `raw_posts.count()` | При загрузке |
| Обработано | `processed_posts.count()` | При загрузке |
| Новые посты | вычисляется | При загрузке |
| События | `events.count()` | При загрузке |
| Последний парсинг | `processed_posts` (max date) | При загрузке |
| Последнее событие | `events` (max date) | При загрузке |
| Процент | вычисляется | При загрузке |

## Troubleshooting

### WebUI возвращает 403

**Решение:**
```bash
export DEBUG=true
# или в .env
DEBUG=true
```

### Статистика не обновляется

**Решение:**
- Проверить подключение к MongoDB
- Проверить логи: `docker logs events_webui`

### Metrics пустые

**Решение:**
- Убедиться, что event_extraction запускался
- Проверить: `curl http://localhost:8080/metrics`

## Версия

**1.0.0** - Первый релиз
- WebUI dashboard
- Prometheus metrics
- Health check
- Production security
