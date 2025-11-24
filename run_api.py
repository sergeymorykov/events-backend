"""
Скрипт для запуска FastAPI приложения.
"""

import uvicorn
import os
from pathlib import Path

if __name__ == "__main__":
    # Загрузка переменных окружения из .env в папке api
    from dotenv import load_dotenv
    
    env_path = Path(__file__).parent / "api" / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✅ Загружены переменные окружения из {env_path}")
    else:
        print(f"⚠️  Файл .env не найден: {env_path}")
        print("   Используются значения по умолчанию")
    
    # Запуск сервера
    uvicorn.run(
        "api.main:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", "8000")),
        reload=True,
        log_level="info"
    )

