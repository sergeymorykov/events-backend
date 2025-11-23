# LLM Провайдеры - Примеры конфигурации

AI Processor поддерживает любой OpenAI-совместимый API для обработки текста и генерации изображений. Ниже приведены примеры конфигурации для популярных провайдеров.

## Оглавление
- [Обработка текста (LLM)](#обработка-текста-llm)
- [Генерация изображений](#генерация-изображений)
- [Ротация ключей](#ротация-ключей)
- [Параметры генерации](#параметры-генерации)

---

## Обработка текста (LLM)

## ZenMux / MapleAI (рекомендуется)

**Преимущества:**
- Доступ к множеству моделей (GPT-4, Claude, Gemini и др.)
- Единый API для всех моделей
- Автоматическая ротация ключей
- Хорошая производительность

```bash
LLM_BASE_URL=https://api.mapleai.de/v1
LLM_API_KEYS=ключ1,ключ2,ключ3  # Несколько ключей для ротации
LLM_MODEL_NAME=gpt-4o
LLM_VISION_MODEL=gpt-4o
LLM_TEMPERATURE=0.7
LLM_MAX_TOKENS=2000
```

**Доступные модели:**
- `gpt-4o` - GPT-4 Omni (рекомендуется)
- `gpt-4-turbo`
- `claude-3-5-sonnet-20241022`
- `gemini-1.5-pro`

---

## OpenAI

**Для прямой работы с OpenAI API:**

```bash
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEYS=sk-...your_key_here
LLM_MODEL_NAME=gpt-4o
LLM_VISION_MODEL=gpt-4o
LLM_TEMPERATURE=0.7
LLM_MAX_TOKENS=2000
```

**Получить API ключ:** https://platform.openai.com/api-keys

**Популярные модели:**
- `gpt-4o` - GPT-4 Omni (лучшая модель)
- `gpt-4-turbo`
- `gpt-3.5-turbo` (дешевле, но менее точная)

---

## GigaChat (Sber)

**Для русскоязычных задач:**

```bash
LLM_BASE_URL=https://gigachat.devices.sberbank.ru/api/v1
LLM_API_KEYS=ваш_токен_gigachat
LLM_MODEL_NAME=GigaChat-Max
LLM_TEMPERATURE=0.7
LLM_MAX_TOKENS=2000
```

**Получить токен:** https://developers.sber.ru/portal/products/gigachat

**Доступные модели:**
- `GigaChat-Max` - самая мощная модель
- `GigaChat-Pro`
- `GigaChat`

---

## LocalAI / Ollama (локальные модели)

**Для работы с локальными моделями:**

```bash
LLM_BASE_URL=http://localhost:11434/v1  # Ollama
# или
LLM_BASE_URL=http://localhost:8080/v1   # LocalAI

LLM_API_KEYS=dummy_key  # Не требуется для локальных моделей
LLM_MODEL_NAME=llama3.1:8b
LLM_TEMPERATURE=0.7
LLM_MAX_TOKENS=2000
```

**Популярные локальные модели:**
- `llama3.1:8b`
- `mistral:7b`
- `qwen2.5:14b`

---

## Генерация изображений

AI Processor поддерживает несколько методов генерации изображений:
1. **LLM-based** (ZenMax, OpenAI DALL-E, Flux и др.) - приоритетный метод
2. **Kandinsky** - fallback метод

### Метод 1: LLM Image Generation (ZenMax, DALL-E, Flux)

**Рекомендуемый способ** для универсальности и качества.

#### ZenMax (множество моделей)

```bash
# Используем те же ключи, что и для текста
IMAGE_LLM_MODEL=flux-pro  # или dall-e-3, stable-diffusion-xl

# Опционально: отдельные настройки
IMAGE_LLM_BASE_URL=https://api.mapleai.de/v1  # По умолчанию = LLM_BASE_URL
IMAGE_LLM_API_KEYS=ключ1,ключ2  # По умолчанию = LLM_API_KEYS
```

**Доступные модели изображений в ZenMax:**
- `flux-pro` - Flux Pro (высокое качество)
- `flux-schnell` - Flux Schnell (быстрая генерация)
- `dall-e-3` - DALL-E 3 от OpenAI
- `stable-diffusion-xl` - Stable Diffusion XL

#### OpenAI DALL-E

```bash
IMAGE_LLM_BASE_URL=https://api.openai.com/v1
IMAGE_LLM_API_KEYS=sk-...your_openai_key
IMAGE_LLM_MODEL=dall-e-3
```

#### Другие OpenAI-совместимые провайдеры

```bash
# Together AI
IMAGE_LLM_BASE_URL=https://api.together.xyz/v1
IMAGE_LLM_API_KEYS=your_key
IMAGE_LLM_MODEL=stabilityai/stable-diffusion-xl-base-1.0

# Replicate
IMAGE_LLM_BASE_URL=https://api.replicate.com/v1
IMAGE_LLM_API_KEYS=your_key
IMAGE_LLM_MODEL=stability-ai/sdxl
```

### Метод 2: Kandinsky (Fallback)

Используется автоматически, если LLM генерация недоступна или не настроена.

```bash
KANDINSKY_API_KEY=ваш_api_ключ
KANDINSKY_SECRET_KEY=ваш_secret_ключ
```

**Получить ключи:** https://fusionbrain.ai/

### Как это работает

1. **Приоритет**: Если настроен `IMAGE_LLM_MODEL`, используется LLM генерация
2. **Fallback**: Если LLM генерация не удалась или не настроена, используется Kandinsky
3. **Автоматический выбор**: Процессор сам выбирает доступный метод

### Пример полной конфигурации

```bash
# Текстовая модель
LLM_BASE_URL=https://api.mapleai.de/v1
LLM_API_KEYS=key1,key2,key3
LLM_MODEL_NAME=gpt-4o
LLM_VISION_MODEL=gpt-4o

# Генерация изображений (использует те же URL и ключи)
IMAGE_LLM_MODEL=flux-pro

# Kandinsky как резервный вариант
KANDINSKY_API_KEY=ваш_ключ
KANDINSKY_SECRET_KEY=ваш_секрет
```

---

## Другие OpenAI-совместимые провайдеры

### Groq

```bash
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_API_KEYS=gsk_...your_key_here
LLM_MODEL_NAME=llama-3.1-70b-versatile
```

### Together AI

```bash
LLM_BASE_URL=https://api.together.xyz/v1
LLM_API_KEYS=your_key_here
LLM_MODEL_NAME=meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo
```

### Anthropic (через прокси)

Для работы с Claude через OpenAI-совместимый прокси:

```bash
LLM_BASE_URL=https://your-proxy.com/v1
LLM_API_KEYS=your_anthropic_key
LLM_MODEL_NAME=claude-3-5-sonnet-20241022
```

---

## Ротация ключей

AI Processor поддерживает **автоматическую ротацию API ключей** при достижении rate limits для обработки текста и генерации изображений:

```bash
# Укажите несколько ключей через запятую для текстовой модели
LLM_API_KEYS=key1,key2,key3

# И для генерации изображений (опционально, по умолчанию используются LLM_API_KEYS)
IMAGE_LLM_API_KEYS=img_key1,img_key2

# Или через точку с запятой
LLM_API_KEYS=key1;key2;key3

# Или на отдельных строках (в многострочной переменной)
LLM_API_KEYS="
key1
key2
key3
"
```

**Как это работает:**
1. При ошибке rate limit (429) модуль автоматически переключается на следующий ключ
2. Используется retry механизм с экспоненциальной задержкой (1-10 сек)
3. Максимум 3 попытки на один ключ
4. Если все ключи исчерпаны, операция завершается с ошибкой

---

## Параметры генерации

### Temperature (температура)

```bash
LLM_TEMPERATURE=0.7  # По умолчанию
```

- `0.0` - детерминированный вывод (всегда один и тот же ответ)
- `0.3-0.5` - более консервативный, точный вывод
- `0.7` - сбалансированный (рекомендуется)
- `1.0+` - более креативный, разнообразный вывод

### Max Tokens

```bash
LLM_MAX_TOKENS=2000  # По умолчанию
```

Максимальное количество токенов в ответе:
- `512-1000` - короткие ответы
- `1000-2000` - средние ответы (рекомендуется)
- `2000-4000` - длинные ответы
- `4000+` - очень длинные ответы (дорого)

---

## Vision модели

Для обработки изображений можно указать отдельную модель:

```bash
LLM_VISION_MODEL=gpt-4o  # Если не указано, используется LLM_MODEL_NAME
```

**Модели с поддержкой vision:**
- `gpt-4o` (OpenAI)
- `claude-3-5-sonnet-20241022` (Anthropic)
- `gemini-1.5-pro` (Google)

Если модель не поддерживает vision, описание изображений будет пропущено.

---

## Проверка конфигурации

После настройки запустите тест:

```bash
python -c "from ai_processor.config import AIConfig; AIConfig.print_config()"
```

Вывод покажет вашу текущую конфигурацию (без секретов).

---

## Обратная совместимость

Старые переменные окружения по-прежнему поддерживаются:

```bash
# Старый способ (deprecated, но работает)
GIGACHAT_TOKEN=your_token
OPENAI_API_KEY=your_key

# Автоматически конвертируется в:
LLM_API_KEYS=your_token  # или your_key
```

**Рекомендуется** использовать новые переменные для полного контроля.

