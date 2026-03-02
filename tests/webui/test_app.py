"""
Тесты для WebUI приложения.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch, AsyncMock

from src.webui.app import create_web_app


@pytest.fixture
def test_client():
    """Тестовый клиент FastAPI."""
    app = create_web_app()
    return TestClient(app)


def test_health_endpoint(test_client):
    """Тест health check endpoint."""
    response = test_client.get("/health")
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "timestamp" in data


def test_metrics_endpoint(test_client):
    """Тест Prometheus metrics endpoint."""
    response = test_client.get("/metrics")
    
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    
    # Проверяем наличие основных метрик
    content = response.text
    assert "event_extraction_events_created_total" in content or "# HELP" in content


@patch.dict('os.environ', {'DEBUG': 'true'})
def test_index_endpoint_debug_mode():
    """Тест главной страницы в режиме отладки."""
    app = create_web_app()
    client = TestClient(app)
    
    response = client.get("/")
    
    # В debug режиме должна быть доступна страница
    assert response.status_code == 200
    assert "Event System Monitor" in response.text or response.headers["content-type"].startswith("text/html")


@patch.dict('os.environ', {'DEBUG': 'false'})
def test_index_endpoint_production_mode():
    """Тест главной страницы в production режиме."""
    app = create_web_app()
    client = TestClient(app)
    
    response = client.get("/")
    
    # В production режиме без debug должен быть 403
    assert response.status_code == 403
    assert "отладки" in response.text or "debug" in response.text.lower()
