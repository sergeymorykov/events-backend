"""
Исключения для event extraction модуля.
"""


class InsufficientQuotaError(Exception):
    """
    Исключение при нехватке квоты/токенов в LLM API.
    
    При возникновении этой ошибки модуль event_extraction должен
    прекратить обработку и завершить работу с чётким логом.
    """
    pass


class PostProcessingError(Exception):
    """Общая ошибка при обработке поста."""
    pass


class EventDeduplicationError(Exception):
    """Ошибка при дедупликации события."""
    pass
