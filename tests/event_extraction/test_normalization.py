"""
Тесты для канонизации категорий и интересов.
"""

import pytest
from unittest.mock import AsyncMock, Mock

from src.event_extraction.models import WeightedInterest
from src.event_extraction.normalization import TagNormalizer


@pytest.mark.asyncio
async def test_normalize_categories_with_aliases():
    """Синонимы категорий приводятся к каноническим значениям."""
    normalizer = TagNormalizer(llm_client=None)
    categories = ["Концерт", "живая музыка", "ТЕАТР", "спектакль", "  "]

    normalized = await normalizer.normalize_categories(categories)

    assert normalized == ["музыка", "театр"]


@pytest.mark.asyncio
async def test_normalize_weighted_interests_merges_duplicates():
    """Дубликаты после канонизации объединяются, веса нормализуются."""
    normalizer = TagNormalizer(llm_client=None)
    raw_interests = [
        WeightedInterest(name="концерт", weight=0.6),
        WeightedInterest(name="живая музыка", weight=0.2),
        WeightedInterest(name="театр", weight=0.2),
    ]

    normalized = await normalizer.normalize_weighted_interests(raw_interests)

    assert len(normalized) == 2
    assert normalized[0].name == "музыка"
    assert normalized[1].name == "театр"
    assert normalized[0].weight > normalized[1].weight
    assert round(sum(item.weight for item in normalized), 4) == 1.0


@pytest.mark.asyncio
async def test_limited_llm_fallback_returns_only_allowed_canonical():
    """LLM fallback может вернуть только канон из taxonomy."""
    llm_client = Mock()
    llm_response = Mock()
    llm_response.choices = [Mock(message=Mock(content='{"canonical":"музыка"}'))]
    llm_client.chat.completions.create = AsyncMock(return_value=llm_response)

    normalizer = TagNormalizer(llm_client=llm_client, model_name="gpt-4o-mini")
    normalized = await normalizer.normalize_tag("рок-концерт")

    assert normalized == "музыка"


@pytest.mark.asyncio
async def test_limited_llm_fallback_rejects_unknown_canonical():
    """Если LLM вернул неразрешенный канон, используется исходный нормализованный тег."""
    llm_client = Mock()
    llm_response = Mock()
    llm_response.choices = [Mock(message=Mock(content='{"canonical":"неизвестный_канон"}'))]
    llm_client.chat.completions.create = AsyncMock(return_value=llm_response)

    normalizer = TagNormalizer(llm_client=llm_client, model_name="gpt-4o-mini")
    normalized = await normalizer.normalize_tag("редкий жанр")

    assert normalized == "редкий жанр"


def test_infer_category_hierarchy():
    normalizer = TagNormalizer(llm_client=None)
    primary, secondary = normalizer.infer_category_hierarchy(["музыка", "театр"])

    assert primary == "культура"
    assert "музыка" in secondary
