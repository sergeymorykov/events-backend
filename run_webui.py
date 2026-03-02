"""
Скрипт для запуска WebUI мониторинга.
"""

import os
import sys

# Установка DEBUG режима из аргументов
if len(sys.argv) > 1 and sys.argv[1] == "--debug":
    os.environ["DEBUG"] = "true"
    print("Starting in DEBUG mode (WebUI enabled)")
else:
    print("Starting in PRODUCTION mode (WebUI disabled, only /metrics)")
    print("To enable WebUI run: python run_webui.py --debug")

print("""
============================================================
  Event System WebUI - Monitoring
  Version: 1.0.0
============================================================

Endpoints:
  - http://localhost:8080/         (WebUI, only in DEBUG mode)
  - http://localhost:8080/metrics  (Prometheus metrics)
  - http://localhost:8080/health   (Health check)

Press Ctrl+C to stop
""")

# Импорт и запуск будет выполнен через uvicorn
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.webui.app:create_web_app",
        factory=True,
        host="0.0.0.0",
        port=8080,
        reload=os.getenv("DEBUG") == "true"
    )
