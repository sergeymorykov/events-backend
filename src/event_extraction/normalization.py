"""
Канонизация интересов и категорий через taxonomy + ограниченный LLM fallback.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from openai import AsyncOpenAI
from qdrant_client import QdrantClient

from .models import WeightedInterest
from .tag_catalog import TagCatalogService, build_slug

logger = logging.getLogger(__name__)

DEFAULT_TAXONOMY_PATH = Path(__file__).resolve().parent / "taxonomy.json"


def _sanitize_tag(tag: str) -> str:
    return (tag or "").strip().lower()


class TagNormalizer:
    """Нормализатор тегов: deterministic alias->canonical, затем ограниченный fallback."""

    def __init__(
        self,
        llm_client: Optional[AsyncOpenAI] = None,
        model_name: str = "gpt-4o-mini",
        taxonomy_path: Optional[Path] = None,
        qdrant_client: Optional[QdrantClient] = None,
        tag_catalog_collection: str = "tag_catalog",
        vector_size: int = 1536,
        category_similarity_threshold: float = 0.86,
        interest_similarity_threshold: float = 0.84,
    ):
        self.llm_client = llm_client
        self.model_name = model_name
        self.taxonomy_path = taxonomy_path or DEFAULT_TAXONOMY_PATH
        self._cache: Dict[str, Tuple[str, str]] = {}
        self._stats = {"dictionary_hits": 0, "llm_hits": 0, "passthrough_hits": 0}
        self.category_similarity_threshold = category_similarity_threshold
        self.interest_similarity_threshold = interest_similarity_threshold
        self.tag_catalog: Optional[TagCatalogService] = None
        if qdrant_client:
            self.tag_catalog = TagCatalogService(
                qdrant_client=qdrant_client,
                collection_name=tag_catalog_collection,
                vector_size=vector_size,
            )

        taxonomy = self._load_taxonomy(self.taxonomy_path)
        self.canonical_terms = set(taxonomy.get("canonical_terms", []))
        aliases = taxonomy.get("aliases", {})
        self.aliases = {
            _sanitize_tag(alias): _sanitize_tag(canonical)
            for alias, canonical in aliases.items()
            if _sanitize_tag(alias) and _sanitize_tag(canonical)
        }
        self.category_hierarchy = taxonomy.get("category_hierarchy", {})

        # Канонические термины должны также корректно резолвиться сами в себя.
        for canonical in self.canonical_terms:
            self.aliases.setdefault(canonical, canonical)

    @staticmethod
    def _load_taxonomy(path: Path) -> Dict[str, object]:
        if not path.exists():
            logger.warning(f"taxonomy файл не найден: {path}")
            return {"canonical_terms": [], "aliases": {}, "category_hierarchy": {}}
        try:
            with path.open("r", encoding="utf-8") as fp:
                loaded = json.load(fp)
            if not isinstance(loaded, dict):
                logger.warning("taxonomy должен быть JSON object, используем пустой fallback")
                return {"canonical_terms": [], "aliases": {}, "category_hierarchy": {}}
            return loaded
        except Exception as exc:
            logger.warning(f"Не удалось загрузить taxonomy: {exc}")
            return {"canonical_terms": [], "aliases": {}, "category_hierarchy": {}}

    def get_stats(self) -> Dict[str, int]:
        return dict(self._stats)

    async def normalize_tag(
        self,
        tag: str,
        allow_llm_fallback: bool = True,
        kind: str = "interest",
    ) -> str:
        canonical_name, _ = await self.resolve_tag(
            tag=tag,
            allow_llm_fallback=allow_llm_fallback,
            kind=kind,
        )
        return canonical_name

    async def resolve_tag(
        self,
        tag: str,
        allow_llm_fallback: bool = True,
        kind: str = "interest",
    ) -> Tuple[str, str]:
        """Нормализует тег и возвращает (canonical_name, canonical_slug)."""
        normalized = _sanitize_tag(tag)
        if not normalized:
            return "", ""

        cache_key = f"{kind}:{normalized}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        if normalized in self.aliases:
            canonical = self.aliases[normalized]
            self._stats["dictionary_hits"] += 1
        else:
            if not allow_llm_fallback or not self.llm_client or not self.canonical_terms:
                canonical = normalized
                self._stats["passthrough_hits"] += 1
            else:
                canonical = await self._normalize_with_llm_limited(normalized)
                if canonical != normalized:
                    self._stats["llm_hits"] += 1
                else:
                    self._stats["passthrough_hits"] += 1

        slug = build_slug(kind, canonical)
        if self.tag_catalog and self.llm_client:
            embedding = await self._embed_text(normalized)
            if embedding:
                similarity_threshold = (
                    self.category_similarity_threshold
                    if kind == "category"
                    else self.interest_similarity_threshold
                )
                canonical, slug = self.tag_catalog.resolve_with_embedding(
                    kind=kind,
                    raw_tag=normalized,
                    embedding=embedding,
                    proposed_canonical=canonical,
                    similarity_threshold=similarity_threshold,
                )
            else:
                existing_slug = self.tag_catalog.get_slug_by_canonical(kind=kind, canonical_name=canonical)
                if existing_slug:
                    slug = existing_slug

        resolved = (canonical, slug)
        self._cache[cache_key] = resolved
        return resolved

    async def _embed_text(self, text: str) -> Optional[List[float]]:
        if not self.llm_client or not text:
            return None
        try:
            response = await self.llm_client.embeddings.create(
                model="text-embedding-ada-002",
                input=text[:512],
            )
            return response.data[0].embedding
        except Exception as exc:
            logger.warning(f"Не удалось получить embedding для тега '{text}': {exc}")
            return None

    async def normalize_categories(
        self,
        categories: List[str],
        allow_llm_fallback: bool = True,
    ) -> List[str]:
        """Канонизация категорий с удалением дублей и пустых значений."""
        result: List[str] = []
        seen = set()
        for category in categories or []:
            canonical = await self.normalize_tag(
                category,
                allow_llm_fallback=allow_llm_fallback,
                kind="category",
            )
            if canonical and canonical not in seen:
                seen.add(canonical)
                result.append(canonical)
        return result

    async def normalize_categories_with_ids(
        self,
        categories: List[str],
        allow_llm_fallback: bool = True,
    ) -> Tuple[List[str], List[str]]:
        result_names: List[str] = []
        result_ids: List[str] = []
        seen_slugs = set()
        for category in categories or []:
            canonical, slug = await self.resolve_tag(
                category,
                allow_llm_fallback=allow_llm_fallback,
                kind="category",
            )
            if not canonical or not slug or slug in seen_slugs:
                continue
            seen_slugs.add(slug)
            result_names.append(canonical)
            result_ids.append(slug)
        return result_names, result_ids

    async def normalize_weighted_interests(
        self,
        interests: List[WeightedInterest],
        min_weight: float = 0.05,
        allow_llm_fallback: bool = True,
    ) -> List[WeightedInterest]:
        """Канонизация weighted interests с merge дублей и нормализацией весов."""
        if not interests:
            return []

        accumulator: Dict[str, float] = {}
        for interest in interests:
            canonical = await self.normalize_tag(
                interest.name,
                allow_llm_fallback=allow_llm_fallback,
                kind="interest",
            )
            if not canonical:
                continue
            accumulator[canonical] = accumulator.get(canonical, 0.0) + float(interest.weight)

        filtered = {name: weight for name, weight in accumulator.items() if weight >= min_weight}
        if not filtered:
            return []

        total_weight = sum(filtered.values())
        if total_weight <= 0:
            return []

        return [
            WeightedInterest(name=name, weight=round(weight / total_weight, 4))
            for name, weight in sorted(filtered.items(), key=lambda item: item[1], reverse=True)
        ]

    async def normalize_weighted_interests_with_ids(
        self,
        interests: List[WeightedInterest],
        min_weight: float = 0.05,
        allow_llm_fallback: bool = True,
    ) -> Tuple[List[WeightedInterest], List[str]]:
        if not interests:
            return [], []

        by_slug: Dict[str, Tuple[str, float]] = {}
        for interest in interests:
            canonical, slug = await self.resolve_tag(
                interest.name,
                allow_llm_fallback=allow_llm_fallback,
                kind="interest",
            )
            if not canonical or not slug:
                continue
            prev_name, prev_weight = by_slug.get(slug, (canonical, 0.0))
            by_slug[slug] = (prev_name or canonical, prev_weight + float(interest.weight))

        filtered = {
            slug: (name, weight)
            for slug, (name, weight) in by_slug.items()
            if weight >= min_weight
        }
        if not filtered:
            return [], []

        total_weight = sum(weight for _, weight in filtered.values())
        if total_weight <= 0:
            return [], []

        sorted_items = sorted(filtered.items(), key=lambda item: item[1][1], reverse=True)
        normalized_interests = [
            WeightedInterest(name=name, weight=round(weight / total_weight, 4))
            for _, (name, weight) in sorted_items
        ]
        interest_ids = [slug for slug, _ in sorted_items]
        return normalized_interests, interest_ids

    def infer_category_hierarchy(self, categories: List[str]) -> Tuple[Optional[str], List[str]]:
        """
        Возвращает category_primary и category_secondary на основе taxonomy.
        """
        if not categories:
            return None, []

        primary: Optional[str] = None
        secondary: List[str] = []
        seen_secondary = set()

        for category in categories:
            mapping = self.category_hierarchy.get(category, {})
            mapped_primary = _sanitize_tag(str(mapping.get("primary", "")))
            mapped_secondary = _sanitize_tag(str(mapping.get("secondary", "")))

            if not primary and mapped_primary:
                primary = mapped_primary

            if mapped_secondary and mapped_secondary not in seen_secondary:
                seen_secondary.add(mapped_secondary)
                secondary.append(mapped_secondary)

        if not secondary:
            secondary = [category for category in categories if category]

        return primary, secondary

    async def _normalize_with_llm_limited(self, tag: str) -> str:
        """
        Fallback-канонизация через LLM, но только в пределах canonical_terms.
        """
        canonical_sorted = sorted(self.canonical_terms)
        system_prompt = (
            "Ты нормализуешь теги для афиши событий. "
            "Выбери один наиболее близкий canonical ТОЛЬКО из переданного списка. "
            "Если корректного соответствия нет, верни пустую строку. "
            "Ответ строго JSON: {\"canonical\": \"...\"}."
        )
        user_prompt = (
            f"tag: {tag}\n"
            f"allowed_canonicals: {', '.join(canonical_sorted)}"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            completion = await self.llm_client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=0.0,
                max_tokens=60,
            )
            content = completion.choices[0].message.content or ""
            parsed = json.loads(content.strip())
            canonical = _sanitize_tag(str(parsed.get("canonical", "")))
            return canonical if canonical in self.canonical_terms else tag
        except Exception as exc:
            logger.warning(f"Не удалось нормализовать тег через LLM fallback: {tag} ({exc})")
            return tag
