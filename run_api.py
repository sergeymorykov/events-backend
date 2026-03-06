"""
Скрипт для запуска FastAPI приложения.
"""

import uvicorn
import os
from pathlib import Path

if __name__ == "__main__":
    # Загрузка переменных окружения из .env в папке api
    from dotenv import load_dotenv
    
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✅ Загружены переменные окружения из {env_path}")
    else:
        print(f"⚠️  Файл .env не найден: {env_path}")
        print("   Используются значения по умолчанию")
    
    api_reload = os.getenv("API_RELOAD", "false").strip().lower() in {"1", "true", "yes"}

    # Запуск сервера
    uvicorn.run(
        "api.main:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", "8000")),
        reload=api_reload,
        log_level="info"
    )

