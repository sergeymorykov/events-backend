"""
Сервис векторного каталога тегов (categories/interests) в Qdrant.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import List, Optional, Tuple
from uuid import uuid4

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

logger = logging.getLogger(__name__)


def _normalize(value: str) -> str:
    return (value or "").strip().lower()


def build_slug(kind: str, canonical_name: str) -> str:
    sanitized = re.sub(r"[^\w\s-]", " ", _normalize(canonical_name))
    sanitized = re.sub(r"\s+", "-", sanitized).strip("-")
    sanitized = sanitized or "unknown"
    return f"{kind}:{sanitized}"


class TagCatalogService:
    """Работа с каталогом канонических тегов в Qdrant."""

    def __init__(
        self,
        qdrant_client: QdrantClient,
        collection_name: str = "tag_catalog",
        vector_size: int = 1536,
    ):
        self.client = qdrant_client
        self.collection_name = collection_name
        self.vector_size = vector_size
        self._init_collection()

    def _init_collection(self):
        collections = self.client.get_collections().collections
        if any(col.name == self.collection_name for col in collections):
            return
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(size=self.vector_size, distance=Distance.COSINE),
        )
        logger.info(f"Создана коллекция каталога тегов: {self.collection_name}")

    def resolve_with_embedding(
        self,
        *,
        kind: str,
        raw_tag: str,
        embedding: List[float],
        proposed_canonical: str,
        similarity_threshold: float,
    ) -> Tuple[str, str]:
        """
        Возвращает (canonical_name, slug), дополняя каталог при необходимости.
        """
        normalized_kind = _normalize(kind)
        normalized_raw = _normalize(raw_tag)
        proposed = _normalize(proposed_canonical) or normalized_raw
        if not normalized_kind or not normalized_raw:
            return proposed, build_slug(normalized_kind or "tag", proposed or "unknown")

        query_filter = Filter(
            must=[
                FieldCondition(key="kind", match=MatchValue(value=normalized_kind)),
            ]
        )
        search_results = self.client.search(
            collection_name=self.collection_name,
            query_vector=embedding,
            query_filter=query_filter,
            limit=1,
            with_payload=True,
        )
        if search_results and search_results[0].score >= similarity_threshold:
            best = search_results[0]
            payload = best.payload or {}
            canonical_name = _normalize(str(payload.get("canonical_name", proposed))) or proposed
            slug = _normalize(str(payload.get("slug", build_slug(normalized_kind, canonical_name))))
            aliases = payload.get("aliases", []) if isinstance(payload.get("aliases"), list) else []
            if normalized_raw not in aliases:
                aliases.append(normalized_raw)
                self.client.set_payload(
                    collection_name=self.collection_name,
                    payload={
                        "aliases": aliases,
                        "updated_at": datetime.utcnow().isoformat(),
                    },
                    points=[best.id],
                )
            return canonical_name, slug

        canonical_name = proposed
        slug = build_slug(normalized_kind, canonical_name)
        now = datetime.utcnow().isoformat()
        payload = {
            "kind": normalized_kind,
            "canonical_name": canonical_name,
            "slug": slug,
            "aliases": [normalized_raw] if normalized_raw != canonical_name else [canonical_name],
            "usage_count": 1,
            "created_at": now,
            "updated_at": now,
        }
        point = PointStruct(id=str(uuid4()), vector=embedding, payload=payload)
        self.client.upsert(collection_name=self.collection_name, points=[point])
        return canonical_name, slug

    def get_slug_by_canonical(self, kind: str, canonical_name: str) -> Optional[str]:
        normalized_kind = _normalize(kind)
        canonical = _normalize(canonical_name)
        query_filter = Filter(
            must=[
                FieldCondition(key="kind", match=MatchValue(value=normalized_kind)),
                FieldCondition(key="canonical_name", match=MatchValue(value=canonical)),
            ]
        )
        results = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=query_filter,
            with_payload=True,
            limit=1,
        )
        if not results or not results[0]:
            return None
        payload = results[0][0].payload or {}
        return str(payload.get("slug")) if payload.get("slug") else None
