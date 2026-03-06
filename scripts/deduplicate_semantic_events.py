"""
Скрипт дедупликации семантически одинаковых событий в MongoDB.

Логика:
- Сканирует события из коллекции (по умолчанию `events`);
- Строит embedding по ключевым полям события;
- Ищет семантический дубликат в временной коллекции Qdrant;
- Оставляет одну каноническую запись, дубли удаляет;
- Перед удалением объединяет `sources` и `images` в канонической записи;
- Переназначает `user_actions.event_id` с дублей на каноническое событие.

Запуск:
    venv/Scripts/python.exe scripts/deduplicate_semantic_events.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple
from uuid import uuid4

from bson import ObjectId
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from openai import AsyncOpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

# Добавляем корень проекта в PYTHONPATH для импорта src.*
PROJECT_ROOT = Path(__file__).resolve().parent.parent
import sys

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.event_extraction.config import EventExtractionConfig

load_dotenv()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Семантическая дедупликация событий в MongoDB")
    parser.add_argument("--collection", default="events", help="Коллекция MongoDB для дедупликации")
    parser.add_argument("--dry-run", action="store_true", help="Без записи изменений в БД")
    parser.add_argument("--limit", type=int, default=0, help="Лимит документов (0 = без лимита)")
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.92,
        help="Порог семантического сходства для дубликатов",
    )
    return parser


def _normalize_text(text: str) -> str:
    compact = re.sub(r"[^\w\s]", " ", (text or "").lower())
    compact = re.sub(r"\s+", " ", compact).strip()
    return compact


def _build_embedding_text(event_doc: Dict[str, Any], top_interests: int = 5) -> str:
    interests = event_doc.get("interests") or []
    weighted = []
    for item in interests:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        try:
            weight = float(item.get("weight", 0.0))
        except (TypeError, ValueError):
            weight = 0.0
        if name:
            weighted.append((name, weight))
    weighted.sort(key=lambda x: x[1], reverse=True)
    top_interest_names = [name for name, _ in weighted[:top_interests]]

    categories = [str(x).strip() for x in (event_doc.get("categories") or []) if str(x).strip()]
    category_secondary = [str(x).strip() for x in (event_doc.get("category_secondary") or []) if str(x).strip()]
    parts = [
        str(event_doc.get("title", "")),
        str(event_doc.get("description", "")),
        str(event_doc.get("location", "")),
        str(event_doc.get("address", "")),
        " ".join(categories),
        " ".join(top_interest_names),
        str(event_doc.get("category_primary", "")),
        " ".join(category_secondary),
    ]
    return _normalize_text(" ".join(part for part in parts if part).strip())


async def _get_embedding(llm_client: AsyncOpenAI, text: str) -> List[float]:
    response = await llm_client.embeddings.create(
        model="text-embedding-ada-002",
        input=text[:8000],
    )
    return response.data[0].embedding


def _unique_dict_list(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    result: List[Dict[str, Any]] = []
    for item in items:
        key = tuple(sorted(item.items()))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _unique_str_list(items: List[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


async def deduplicate_events(
    *,
    mongo_db,
    qdrant_client: QdrantClient,
    llm_client: AsyncOpenAI,
    collection_name: str,
    threshold: float,
    dry_run: bool,
    limit: int,
) -> Dict[str, int]:
    collection = mongo_db[collection_name]
    temp_collection = f"dedup_tmp_{collection_name}_{int(datetime.utcnow().timestamp())}"

    stats = {
        "scanned": 0,
        "kept": 0,
        "duplicates_found": 0,
        "mongo_deleted": 0,
        "mongo_updated": 0,
        "actions_relinked": 0,
    }

    duplicates_by_keeper: Dict[str, List[str]] = defaultdict(list)
    merge_sources: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    merge_images: Dict[str, List[str]] = defaultdict(list)

    qdrant_client.create_collection(
        collection_name=temp_collection,
        vectors_config=VectorParams(
            size=EventExtractionConfig.QDRANT_VECTOR_SIZE,
            distance=Distance.COSINE,
        ),
    )

    try:
        cursor = collection.find({})
        if limit and limit > 0:
            cursor = cursor.limit(limit)

        async for event_doc in cursor:
            stats["scanned"] += 1
            current_id = str(event_doc["_id"])
            embedding_text = _build_embedding_text(event_doc)
            if not embedding_text:
                stats["kept"] += 1
                continue

            embedding = await _get_embedding(llm_client, embedding_text)
            search_results = qdrant_client.search(
                collection_name=temp_collection,
                query_vector=embedding,
                limit=1,
                score_threshold=threshold,
                with_payload=True,
            )

            if search_results:
                keeper_id = str((search_results[0].payload or {}).get("mongo_id", ""))
                if keeper_id:
                    duplicates_by_keeper[keeper_id].append(current_id)
                    stats["duplicates_found"] += 1
                    merge_sources[keeper_id].extend(event_doc.get("sources") or [])
                    merge_images[keeper_id].extend(event_doc.get("images") or [])
                    continue

            point = PointStruct(
                id=str(uuid4()),
                vector=embedding,
                payload={"mongo_id": current_id},
            )
            qdrant_client.upsert(collection_name=temp_collection, points=[point])
            stats["kept"] += 1

        for keeper_id, duplicate_ids in duplicates_by_keeper.items():
            keeper_object_id = ObjectId(keeper_id)
            keeper_doc = await collection.find_one({"_id": keeper_object_id})
            if not keeper_doc:
                continue

            combined_sources = _unique_dict_list((keeper_doc.get("sources") or []) + merge_sources[keeper_id])
            combined_images = _unique_str_list((keeper_doc.get("images") or []) + merge_images[keeper_id])
            duplicate_object_ids = [ObjectId(x) for x in duplicate_ids]

            if dry_run:
                continue

            await collection.update_one(
                {"_id": keeper_object_id},
                {
                    "$set": {
                        "sources": combined_sources,
                        "images": combined_images,
                        "merged_duplicate_ids": duplicate_ids,
                        "deduplicated_at": datetime.utcnow(),
                    }
                },
            )
            stats["mongo_updated"] += 1

            update_actions_result = await mongo_db.user_actions.update_many(
                {"event_id": {"$in": duplicate_ids}},
                {"$set": {"event_id": keeper_id}},
            )
            stats["actions_relinked"] += int(update_actions_result.modified_count or 0)

            delete_result = await collection.delete_many({"_id": {"$in": duplicate_object_ids}})
            stats["mongo_deleted"] += int(delete_result.deleted_count or 0)

        return stats
    finally:
        qdrant_client.delete_collection(temp_collection)


async def main():
    args = _build_parser().parse_args()

    mongodb_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
    db_name = os.getenv("MONGODB_DB_NAME", "events_db")
    llm_base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    llm_api_keys = EventExtractionConfig.get_api_keys()
    if not llm_api_keys:
        raise RuntimeError("Не найден LLM API ключ в окружении (LLM_API_KEY/LLM_API_KEYS)")

    mongo_client = AsyncIOMotorClient(mongodb_uri)
    mongo_db = mongo_client[db_name]
    llm_client = AsyncOpenAI(base_url=llm_base_url, api_key=llm_api_keys[0])
    qdrant_client = QdrantClient(
        host=os.getenv("QDRANT_HOST", "localhost"),
        port=int(os.getenv("QDRANT_PORT", "6333")),
        api_key=os.getenv("QDRANT_API_KEY") or None,
    )

    try:
        stats = await deduplicate_events(
            mongo_db=mongo_db,
            qdrant_client=qdrant_client,
            llm_client=llm_client,
            collection_name=args.collection,
            threshold=args.threshold,
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
