"""
Миграция событий к weighted interests и каноническим тегам.

Запуск:
    venv/Scripts/python.exe scripts/migrate_weighted_interests.py --dry-run
"""

import asyncio
import argparse
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from openai import AsyncOpenAI
from qdrant_client import QdrantClient

# Добавляем корень проекта в PYTHONPATH для импорта src.*
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.event_extraction.models import WeightedInterest
from src.event_extraction.normalization import TagNormalizer

load_dotenv()


def parse_weighted_interests(document: Dict[str, Any]) -> List[WeightedInterest]:
    """Построение weighted interests из нового или legacy формата."""
    raw_interests = document.get("interests")
    if isinstance(raw_interests, list):
        parsed: List[WeightedInterest] = []
        for item in raw_interests:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            try:
                weight = float(item.get("weight", 0.0))
            except (TypeError, ValueError):
                weight = 0.0
            if weight < 0:
                weight = 0.0
            if weight > 1:
                weight = 1.0
            parsed.append(WeightedInterest(name=name, weight=weight))
        if parsed:
            return parsed

    legacy = [
        str(item).strip()
        for item in (document.get("user_interests") or [])
        if item and str(item).strip()
    ]
    if not legacy:
        return []

    uniform_weight = round(1.0 / len(legacy), 4)
    return [WeightedInterest(name=name, weight=uniform_weight) for name in legacy]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Миграция weighted interests + taxonomy")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только показать статистику, без записи в MongoDB",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Ограничение на количество документов (0 = без лимита)",
    )
    return parser


def _documents_are_different(original: Dict[str, Any], updated: Dict[str, Any]) -> bool:
    for key, value in updated.items():
        if original.get(key) != value:
            return True
    return False


async def migrate_collection(
    db,
    collection_name: str,
    normalizer: TagNormalizer,
    dry_run: bool = False,
    limit: int = 0,
) -> Dict[str, int]:
    """Миграция одной коллекции со статистикой изменений."""
    collection = db[collection_name]
    stats = {
        "total_docs": 0,
        "changed_docs": 0,
        "updated_docs": 0,
    }
    before_normalizer_stats = normalizer.get_stats()

    cursor = collection.find({})
    if limit and limit > 0:
        cursor = cursor.limit(limit)

    async for doc in cursor:
        stats["total_docs"] += 1
        weighted = parse_weighted_interests(doc)
        normalized_interests, interest_ids = await normalizer.normalize_weighted_interests_with_ids(weighted)
        normalized_categories, category_ids = await normalizer.normalize_categories_with_ids(doc.get("categories", []))
        category_primary, category_secondary = normalizer.infer_category_hierarchy(normalized_categories)
        legacy_interests = [item.name for item in normalized_interests]

        update_payload = {
            "categories": normalized_categories,
            "category_ids": category_ids,
            "category_primary": category_primary,
            "category_secondary": category_secondary,
            "interests": [item.model_dump(mode="json") for item in normalized_interests],
            "interest_ids": interest_ids,
            "user_interests": legacy_interests,
        }

        if not _documents_are_different(doc, update_payload):
            continue

        stats["changed_docs"] += 1
        if dry_run:
            continue

        await collection.update_one({"_id": doc["_id"]}, {"$set": update_payload})
        stats["updated_docs"] += 1

    after_normalizer_stats = normalizer.get_stats()
    stats["dictionary_hits"] = after_normalizer_stats["dictionary_hits"] - before_normalizer_stats["dictionary_hits"]
    stats["llm_hits"] = after_normalizer_stats["llm_hits"] - before_normalizer_stats["llm_hits"]
    stats["passthrough_hits"] = after_normalizer_stats["passthrough_hits"] - before_normalizer_stats["passthrough_hits"]
    return stats

def _print_collection_stats(collection_name: str, stats: Dict[str, int], dry_run: bool):
    mode = "DRY-RUN" if dry_run else "WRITE"
    print(f"\n[{collection_name}] mode={mode}")
    print(f"  total_docs: {stats['total_docs']}")
    print(f"  changed_docs: {stats['changed_docs']}")
    print(f"  updated_docs: {stats['updated_docs']}")
    print(f"  dictionary_hits: {stats['dictionary_hits']}")
    print(f"  llm_hits: {stats['llm_hits']}")
    print(f"  passthrough_hits: {stats['passthrough_hits']}")


async def main():
    args = _build_parser().parse_args()
    mongodb_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
    db_name = os.getenv("MONGODB_DB_NAME", "events_db")

    llm_client = None
    api_key = os.getenv("LLM_API_KEY")
    if api_key:
        llm_client = AsyncOpenAI(
            base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
            api_key=api_key
        )

    normalizer = TagNormalizer(
        llm_client=llm_client,
        model_name=os.getenv("LLM_MODEL_NAME", "gpt-4o-mini"),
        qdrant_client=QdrantClient(
            host=os.getenv("QDRANT_HOST", "localhost"),
            port=int(os.getenv("QDRANT_PORT", "6333")),
            api_key=os.getenv("QDRANT_API_KEY") or None,
        ),
        vector_size=int(os.getenv("QDRANT_VECTOR_SIZE", "1536")),
    )

    client = AsyncIOMotorClient(mongodb_uri)
    db = client[db_name]

    try:
        existing_collections = await db.list_collection_names()
        targets = [name for name in ("events", "processed_events") if name in existing_collections]

        if not targets:
            print("Не найдено коллекций для миграции (events/processed_events).")
            return

        total_updated = 0
        total_changed = 0
        total_dictionary_hits = 0
        total_llm_hits = 0
        total_passthrough_hits = 0
        for collection_name in targets:
            collection_stats = await migrate_collection(
                db=db,
                collection_name=collection_name,
                normalizer=normalizer,
                dry_run=args.dry_run,
                limit=args.limit,
            )
            _print_collection_stats(collection_name, collection_stats, dry_run=args.dry_run)

            total_updated += collection_stats["updated_docs"]
            total_changed += collection_stats["changed_docs"]
            total_dictionary_hits += collection_stats["dictionary_hits"]
            total_llm_hits += collection_stats["llm_hits"]
            total_passthrough_hits += collection_stats["passthrough_hits"]

        print("\nИтог:")
        print(f"  changed_docs: {total_changed}")
        print(f"  updated_docs: {total_updated}")
        print(f"  dictionary_hits: {total_dictionary_hits}")
        print(f"  llm_hits: {total_llm_hits}")
        print(f"  passthrough_hits: {total_passthrough_hits}")
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
