# 🕐 Руководство по планировщику

## Автоматический парсинг каждые 24 часа

### 🚀 Быстрый старт

```bash
# Установите зависимости (если еще не установлены)
pip install -r requirements.txt

# Настройте .env
cp env.example .env
# Отредактируйте .env

# Запустите планировщик
python run_scheduler.py
```

Планировщик запустится и будет работать постоянно:
- ✅ Первый парсинг — сразу при запуске
- ⏰ Далее — каждые 24 часа автоматически
- 📝 Логи в `telegram_scheduler.log`
- ⏹️  Остановка — Ctrl+C

---

## 📋 Режимы работы

Планировщик поддерживает несколько режимов работы. По умолчанию используется режим "каждые 24 часа".

### Режим 1: Каждые N часов (по умолчанию)

```python
# В telegram_parser/scheduler.py, функция main()

scheduler.start(immediate=True, interval_hours=24)
```

**Параметры:**
- `immediate=True` — запустить парсинг сразу при старте
- `interval_hours=24` — интервал между запусками (в часах)

**Примеры:**
```python
# Каждые 12 часов
scheduler.start(immediate=True, interval_hours=12)

# Каждые 6 часов
scheduler.start(immediate=True, interval_hours=6)

# Каждый час
scheduler.start(immediate=True, interval_hours=1)

# Без немедленного запуска (первый через 24 часа)
scheduler.start(immediate=False, interval_hours=24)
```

### Режим 2: Ежедневно в конкретное время

```python
# В telegram_parser/scheduler.py, функция main()

scheduler.start_daily(hour=9, minute=0, immediate=False)
```

**Параметры:**
- `hour` — час запуска (0-23)
- `minute` — минута запуска (0-59)
- `immediate` — запустить ли сразу при старте

**Примеры:**
```python
# Каждый день в 9:00
scheduler.start_daily(hour=9, minute=0, immediate=False)

# Каждый день в 3:00 ночи (+ сразу при старте)
scheduler.start_daily(hour=3, minute=0, immediate=True)

# Каждый день в 15:30
scheduler.start_daily(hour=15, minute=30, immediate=False)

# Каждый день в полночь
scheduler.start_daily(hour=0, minute=0, immediate=False)
```

---

## ⚙️ Настройка режима

Откройте `telegram_parser/scheduler.py` и найдите функцию `main()`:

```python
async def main():
    # ...
    scheduler = TelegramScheduler(Config)
    
    # Раскомментируйте нужный вариант:
    
    # Вариант 1: Каждые 24 часа (сразу + потом каждые 24ч)
    scheduler.start(immediate=True, interval_hours=24)
    
    # Вариант 2: Каждый день в 9:00 (без немедленного запуска)
    # scheduler.start_daily(hour=9, minute=0, immediate=False)
    
    # Вариант 3: Каждый день в 9:00 (с немедленным первым запуском)
    # scheduler.start_daily(hour=9, minute=0, immediate=True)
    
    # Вариант 4: Каждые 6 часов
    # scheduler.start(immediate=True, interval_hours=6)
    
    await scheduler.run_forever()
```

---

## 📊 Примеры использования

### Пример 1: Круглосуточный мониторинг (каждые 6 часов)

**Задача**: Постоянно отслеживать новые посты, проверяя каждые 6 часов

```python
# telegram_parser/scheduler.py
scheduler.start(immediate=True, interval_hours=6)
```

**Результат**:
- 00:00 — парсинг при запуске
- 06:00 — автоматический парсинг
- 12:00 — автоматический парсинг
- 18:00 — автоматический парсинг
- 00:00 — и так далее...

### Пример 2: Ежедневный парсинг в рабочее время

**Задача**: Парсить один раз в день утром в 9:00

```python
# telegram_parser/scheduler.py
scheduler.start_daily(hour=9, minute=0, immediate=False)
```

**Результат**:
- Каждый день ровно в 9:00 утра
- Без немедленного запуска

### Пример 3: Ночной парсинг + ручной при запуске

**Задача**: Парсить каждую ночь в 3:00, плюс сразу при запуске

```python
# telegram_parser/scheduler.py
scheduler.start_daily(hour=3, minute=0, immediate=True)
```

**Результат**:
- Сразу при запуске скрипта
- Каждый день в 3:00 ночи

---

## 🔍 Логирование

Планировщик ведет два лог-файла:

### 1. `telegram_scheduler.log`
Логи планировщика:
- Время запуска/остановки
- Расписание выполнения
- Информация о каждом запланированном запуске

### 2. `telegram_parser.log`
Логи парсера (как при ручном запуске):
- Подключение к каналам
- Статистика постов
- Ошибки парсинга

**Просмотр логов в реальном времени:**

```bash
# Windows (PowerShell)
Get-Content telegram_scheduler.log -Wait -Tail 50

# Linux/Mac
tail -f telegram_scheduler.log
```

---

## 🖥️ Запуск в фоне

### Windows

**Вариант 1: Task Scheduler**

1. Откройте Task Scheduler
2. Create Basic Task
3. Name: "Telegram Parser Scheduler"
4. Trigger: At startup (или At log on)
5. Action: Start a program
   - Program: `python`
   - Arguments: `G:\events-backend\run_scheduler.py`
   - Start in: `G:\events-backend`

**Вариант 2: PowerShell в фоне**

```powershell
Start-Process python -ArgumentList "run_scheduler.py" -WindowStyle Hidden
```

### Linux/Mac

**Вариант 1: systemd (рекомендуется)**

Создайте `/etc/systemd/system/telegram-parser.service`:

```ini
[Unit]
Description=Telegram Events Parser Scheduler
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/events-backend
ExecStart=/path/to/python /path/to/events-backend/run_scheduler.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Запуск:
```bash
sudo systemctl daemon-reload
sudo systemctl enable telegram-parser
sudo systemctl start telegram-parser
sudo systemctl status telegram-parser
```

**Вариант 2: screen/tmux**

```bash
# screen
screen -S telegram-parser
python run_scheduler.py
# Ctrl+A, D для отсоединения

# tmux
tmux new -s telegram-parser
python run_scheduler.py
# Ctrl+B, D для отсоединения
```

**Вариант 3: nohup**

```bash
nohup python run_scheduler.py > scheduler.out 2>&1 &
```

---

## 📦 Docker (опционально)

### Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Копирование зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование кода
COPY telegram_parser telegram_parser/
COPY run_scheduler.py .
COPY .env .

# Запуск планировщика
CMD ["python", "run_scheduler.py"]
```

### docker-compose.yml

```yaml
version: '3.8'

services:
  telegram-parser-scheduler:
    build: .
    container_name: telegram-parser-scheduler
    restart: unless-stopped
    env_file:
      - .env
    volumes:
      - ./telegram_parser_session.session:/app/telegram_parser_session.session
      - ./logs:/app/logs
    depends_on:
      - mongodb

  mongodb:
    image: mongo:latest
    container_name: mongodb
    restart: unless-stopped
    ports:
      - "27017:27017"
    volumes:
      - mongodb_data:/data/db

volumes:
  mongodb_data:
```

**Запуск:**

```bash
docker-compose up -d
```

**Просмотр логов:**

```bash
docker-compose logs -f telegram-parser-scheduler
```

---

## ❓ FAQ

### Q: Как проверить, что планировщик работает?

**A:** Посмотрите лог-файл `telegram_scheduler.log`:

```bash
# Последние 20 строк
tail -n 20 telegram_scheduler.log

# Или в реальном времени
tail -f telegram_scheduler.log
```

### Q: Можно ли запустить парсинг вручную, не дожидаясь расписания?

**A:** Да, запустите разовый парсинг параллельно:

```bash
python run_parser.py
```

Это не помешает работе планировщика.

### Q: Что делать, если планировщик упал?

**A:** Проверьте логи для диагностики:

```bash
grep "ERROR\|CRITICAL" telegram_scheduler.log
```

Перезапустите:

```bash
python run_scheduler.py
```

### Q: Можно ли изменить расписание без остановки?

**A:** Нет, нужно:
1. Остановить планировщик (Ctrl+C)
2. Отредактировать `telegram_parser/scheduler.py`
3. Запустить снова: `python run_scheduler.py`

### Q: Сколько ресурсов потребляет планировщик?

**A:** В режиме ожидания — минимум (несколько МБ RAM). Во время парсинга зависит от количества каналов и постов.

---

## 🛠️ Расширенная настройка

### Изменение интервала в коде

Можно создать свой скрипт с кастомным расписанием:

```python
# my_custom_scheduler.py
import asyncio
from telegram_parser.scheduler import TelegramScheduler
from telegram_parser.config import Config

async def main():
    scheduler = TelegramScheduler(Config)
    
    # Каждые 2 часа
    scheduler.start(immediate=True, interval_hours=2)
    
    await scheduler.run_forever()

if __name__ == '__main__':
    asyncio.run(main())
```

### Уведомления при ошибках

Добавьте отправку уведомлений в `scheduler.py`:

```python
async def parse_job(self):
    try:
        # ... парсинг ...
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        # Отправить email/Telegram уведомление
        send_error_notification(str(e))
```

---

**Готово!** Планировщик настроен и работает автоматически! 🎉

