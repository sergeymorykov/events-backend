"""
Совместимый скрипт запуска обработки постов.

Оставлен для обратной совместимости со старой командой:
`python run_ai_processor.py`.
Фактическая обработка выполняется модулем event_extraction.
"""

import asyncio
import sys

from run_event_extraction import main as run_event_extraction_main


if __name__ == "__main__":
    print("Внимание: ai_processor удален. Запускается event_extraction.")
    exit_code = asyncio.run(run_event_extraction_main())
    sys.exit(exit_code or 0)

