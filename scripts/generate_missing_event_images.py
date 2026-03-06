"""
Скрипт генерации изображений для событий без images в MongoDB.

Запуск:
    venv/Scripts/python.exe scripts/generate_missing_event_images.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

# Добавляем корень проекта в PYTHONPATH для импорта src.*
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.event_extraction.config import EventExtractionConfig
from src.event_extraction.image_handler import ImageHandler

load_dotenv()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Генерация изображений для событий без поля images"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только показать статистику без записи в MongoDB",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Ограничение количества документов (0 = без лимита)",
    )
    parser.add_argument(
        "--collection",
        default="events",
        help="Название коллекции с событиями",
    )
    return parser


def _normalize_image_paths(image_paths: Any) -> List[str]:
    if not isinstance(image_paths, list):
        return []

    normalized: List[str] = []
    seen = set()
    for item in image_paths:
        if not item:
            continue
        path = str(item).strip()
        if not path or path in seen:
            continue
        seen.add(path)
        normalized.append(path)
    return normalized


async def generate_missing_images(
    *,
    db,
    collection_name: str,
    image_handler: ImageHandler,
    dry_run: bool,
    limit: int,
) -> Dict[str, int]:
    collection = db[collection_name]
    query = {
        "$or": [
            {"images": {"$exists": False}},
            {"images": None},
            {"images": []},
        ]
    }

    cursor = collection.find(query)
    if limit and limit > 0:
        cursor = cursor.limit(limit)

    stats = {
        "scanned": 0,
        "updated": 0,
        "generated": 0,
        "failed_generation": 0,
        "skipped_no_title": 0,
        "skipped_has_images": 0,
        "errors": 0,
    }

    async for doc in cursor:
        stats["scanned"] += 1
        try:
            existing_images = _normalize_image_paths(doc.get("images"))
            if existing_images:
                stats["skipped_has_images"] += 1
                continue

            title = str(doc.get("title", "")).strip()
            description = doc.get("description")
            if not title:
                stats["skipped_no_title"] += 1
                continue

            poster_path = await image_handler.generate_event_poster(
                event_title=title,
                event_description=str(description).strip() if description else None,
            )

            if not poster_path:
                stats["failed_generation"] += 1
                continue

            normalized_poster_path = str(poster_path).strip()
            if not normalized_poster_path:
                stats["failed_generation"] += 1
                continue

            stats["generated"] += 1
            if dry_run:
                continue

            result = await collection.update_one(
                {"_id": doc["_id"]},
                {
                    "$set": {
                        "images": [normalized_poster_path],
                        "poster_generated": True,
                    }
                },
            )
            if result.modified_count:
                stats["updated"] += 1
        except Exception:
            stats["errors"] += 1

    return stats


async def main():
    args = _build_parser().parse_args()

    mongo_client = AsyncIOMotorClient(EventExtractionConfig.MONGODB_URI)
    db = mongo_client[EventExtractionConfig.MONGODB_DB_NAME]
    image_handler = ImageHandler(
        images_dir=EventExtractionConfig.IMAGES_DIR,
        image_llm_base_url=EventExtractionConfig.IMAGE_LLM_BASE_URL,
        image_llm_api_key=EventExtractionConfig.get_image_api_key(),
        image_llm_model=EventExtractionConfig.IMAGE_LLM_MODEL,
    )

    try:
        stats = await generate_missing_images(
            db=db,
            collection_name=args.collection,
            image_handler=image_handler,
            dry_run=args.dry_run,
            limit=args.limit,
        )
        mode = "DRY-RUN" if args.dry_run else "WRITE"
        print(f"[{mode}] collection={args.collection}")
        for key, value in stats.items():
            print(f"{key}: {value}")
    finally:
        mongo_client.close()


if __name__ == "__main__":
    asyncio.run(main())
