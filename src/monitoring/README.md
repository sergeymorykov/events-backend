# Monitoring Module - Prometheus Metrics

## Описание

Модуль предоставляет Prometheus метрики для мониторинга системы обработки событий.

## Возможности

- ✅ 8 метрик для Event Extraction
- ✅ 4 метрики для Telegram Parser
- ✅ Автоматическая запись при обработке
- ✅ Singleton pattern для глобальных экземпляров
- ✅ Histogram для latency анализа
- ✅ Counter для счётчиков
- ✅ Gauge для текущего состояния
- ✅ Summary для статистики

## Структура

```
src/monitoring/
├── __init__.py        # Экспорты
└── prometheus.py      # Метрики
```

## Метрики

### Event Extraction

| Имя | Тип | Описание | Метки |
|-----|-----|----------|-------|
| `event_extraction_events_created_total` | Counter | Созданные события | - |
| `event_extraction_duplicates_found_total` | Counter | Найденные дубликаты | - |
| `event_extraction_posters_generated_total` | Counter | Сгенерированные афиши | - |
| `event_extraction_errors_total` | Counter | Ошибки | `type` |
| `event_extraction_duration_seconds` | Histogram | Время обработки поста | - |
| `event_extraction_poster_generation_seconds` | Histogram | Время генерации афиши | - |
| `event_extraction_new_posts_pending` | Gauge | Необработанные посты | - |
| `event_extraction_langgraph_step_seconds` | Summary | Время шагов LangGraph | `step` |

### Telegram Parser

| Имя | Тип | Описание | Метки |
|-----|-----|----------|-------|
| `telegram_parser_posts_processed_total` | Counter | Обработанные посты | `channel`, `status` |
| `telegram_parser_images_downloaded_total` | Counter | Скачанные изображения | `channel` |
| `telegram_parser_duration_seconds` | Histogram | Время парсинга канала | `channel` |
| `telegram_parser_errors_total` | Counter | Ошибки парсинга | `channel`, `error_type` |

## API

### Event Extraction

```python
from src.monitoring import get_event_metrics

metrics = get_event_metrics()

# Запись события
metrics.record_event_created()

# Запись дубликата
metrics.record_duplicate_found()

# Запись афиши
metrics.record_poster_generated()

# Запись ошибки
metrics.record_error("quota")  # quota, llm, dedup, processing

# Время обработки
import time
start = time.time()
# ... обработка
metrics.processing_duration.observe(time.time() - start)

# Установка новых постов
metrics.set_pending_posts(25)
```

### Telegram Parser

```python
from src.monitoring import get_parser_metrics

metrics = get_parser_metrics()

# Запись поста
metrics.record_post("kazankay", "saved")  # saved, filtered, duplicate

# Запись изображения
metrics.record_image("kazankay")

# Время парсинга (context manager)
with metrics.parsing_duration.labels(channel="kazankay").time():
    # ... парсинг
    pass

# Ошибка
metrics.record_error("kazankay", "flood_wait")  # flood_wait, channel_private, other
```

## Интеграция

### Автоматическая интеграция

Метрики автоматически записываются в `PostProcessor`:

```python
# В post_processor.py
from src.monitoring import get_event_metrics

metrics = get_event_metrics() if METRICS_AVAILABLE else None

# При создании события
if metrics:
    metrics.record_event_created()
    
# При дубликате
if metrics:
    metrics.record_duplicate_found()

# При ошибке
except InsufficientQuotaError:
    if metrics:
        metrics.record_error("quota")
    raise
```

### Опциональная зависимость

Модуль работает без мониторинга:
```python
try:
    from src.monitoring import get_event_metrics
    METRICS_AVAILABLE = True
except ImportError:
    METRICS_AVAILABLE = False
    # Продолжаем работу без метрик
```

## Prometheus Setup

### Конфигурация

`prometheus.yml`:
```yaml
scrape_configs:
  - job_name: 'event_system'
    static_configs:
      - targets: ['localhost:8080']
    metrics_path: '/metrics'
    scrape_interval: 10s
```

### Запуск

```bash
# Docker
docker run -p 9090:9090 \
  -v $(pwd)/prometheus.yml:/etc/prometheus/prometheus.yml \
  prom/prometheus

# Проверка
curl http://localhost:9090/targets
```

## Grafana Integration

### Импорт dashboard

1. Открыть Grafana (http://localhost:3000)
2. **Dashboards → Import**
3. Загрузить `grafana/dashboard.json`
4. Выбрать Prometheus data source
5. Import

### Alerts

Dashboard содержит alert:
- **Условие:** `event_extraction_errors_total{type="quota"} > 0`
- **Действие:** Уведомление при quota error

## Примеры запросов

### PromQL queries

```promql
# События в секунду
rate(event_extraction_events_created_total[5m])

# Процент ошибок
rate(event_extraction_errors_total[5m]) / 
  rate(event_extraction_events_created_total[5m]) * 100

# p95 latency
histogram_quantile(0.95, 
  rate(event_extraction_duration_seconds_bucket[5m])
)

# Новые посты
event_extraction_new_posts_pending
```

## Версия

**1.0.0** - Первый релиз
- Event Extraction метрики
- Telegram Parser метрики
- Singleton pattern
- Автоматическая интеграция
