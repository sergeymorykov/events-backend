"""
Утилиты для настройки путей логирования.
"""

from pathlib import Path


def get_log_path(filename: str) -> Path:
    """
    Возвращает путь к файлу лога в директории logs.

    Args:
        filename: Имя файла лога (например, event_extraction.log)

    Returns:
        Абсолютный путь к файлу лога
    """
    project_root = Path(__file__).resolve().parents[2]
    logs_dir = project_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir / filename
