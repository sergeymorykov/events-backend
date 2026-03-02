"""
WebUI для мониторинга системы обработки событий.
FastAPI + Jinja2 templates.
"""

import os
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from motor.motor_asyncio import AsyncIOMotorClient
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

logger = logging.getLogger(__name__)


class WebUIApp:
    """WebUI приложение для мониторинга."""
    
    def __init__(self, mongodb_uri: str, db_name: str, debug: bool = False):
        """
        Инициализация WebUI.
        
        Args:
            mongodb_uri: URI подключения к MongoDB
            db_name: Имя базы данных
            debug: Режим отладки (включает UI)
        """
        self.mongodb_uri = mongodb_uri
        self.db_name = db_name
        self.debug = debug
        
        # Клиент MongoDB
        self.db_client = AsyncIOMotorClient(mongodb_uri)
        self.db = self.db_client[db_name]
        
        # Jinja2 templates
        templates_dir = Path(__file__).parent / "templates"
        self.templates = Jinja2Templates(directory=str(templates_dir))
    
    async def get_statistics(self) -> Dict[str, Any]:
        """
        Получение статистики из MongoDB.
        
        Returns:
            Словарь со статистикой
        """
        try:
            # Статистика по постам
            total_raw_posts = await self.db.raw_posts.count_documents({})
            processed_posts = await self.db.processed_posts.count_documents({})
            
            # Статистика по событиям
            total_events = await self.db.events.count_documents({})
            
            # Последний запуск парсера (из processed_posts)
            last_parser_run = await self.db.processed_posts.find_one(
                {},
                sort=[("processed_at", -1)]
            )
            
            # Последнее созданное событие
            last_event = await self.db.events.find_one(
                {},
                sort=[("processed_at", -1)]
            )
            
            # Подсчёт новых постов (не обработанных)
            new_posts_count = total_raw_posts - processed_posts
            
            return {
                "total_raw_posts": total_raw_posts,
                "processed_posts": processed_posts,
                "new_posts": max(0, new_posts_count),
                "total_events": total_events,
                "last_parser_run": last_parser_run.get("processed_at") if last_parser_run else None,
                "last_event_created": last_event.get("processed_at") if last_event else None,
                "uptime": datetime.now().isoformat()
            }
        
        except Exception as e:
            logger.error(f"Ошибка получения статистики: {e}")
            return {}


def create_web_app() -> FastAPI:
    """
    Фабрика для создания FastAPI приложения.
    
    Returns:
        Настроенное FastAPI приложение
    """
    app = FastAPI(
        title="Event System Monitor",
        description="Мониторинг системы обработки событий из Telegram",
        version="1.0.0"
    )
    
    # Получение настроек из env
    mongodb_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
    db_name = os.getenv("MONGODB_DB_NAME", "events_db")
    debug = os.getenv("DEBUG", "false").lower() == "true"
    
    webui = WebUIApp(mongodb_uri, db_name, debug)
    
    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        """Главная страница с статистикой."""
        if not debug and not webui.debug:
            return PlainTextResponse(
                "WebUI доступен только в режиме отладки (DEBUG=true)",
                status_code=403
            )
        
        stats = await webui.get_statistics()
        
        return webui.templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "stats": stats,
                "current_time": datetime.now()
            }
        )
    
    @app.get("/metrics", response_class=PlainTextResponse)
    async def metrics():
        """Endpoint для Prometheus метрик."""
        return PlainTextResponse(
            generate_latest(),
            media_type=CONTENT_TYPE_LATEST
        )
    
    @app.get("/health")
    async def health():
        """Health check endpoint."""
        return {"status": "ok", "timestamp": datetime.now().isoformat()}
    
    return app
