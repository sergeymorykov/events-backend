"""
Тесты weighted-механики пересчета интересов пользователя.
"""

from api.interest_service import build_event_tag_weights, apply_action_delta
from api.models import Event, WeightedInterest


def build_event(**kwargs):
    base = {
        "_id": "64b8c2f5e8a1b5d7c3f1a123",
        "title": "Тест",
        "categories": [],
        "user_interests": [],
        "interests": [],
    }
    base.update(kwargs)
    return Event(**base)


def test_build_event_tag_weights_from_weighted_interests():
    event = build_event(
        categories=["концерт", "выставка"],
        interests=[
            WeightedInterest(name="музыка", weight=0.7),
            WeightedInterest(name="искусство", weight=0.3),
        ],
    )

    weights = build_event_tag_weights(event)

    assert weights["музыка"] == 0.7
    assert weights["искусство"] == 0.3
    # Категории добавляются как ослабленный сигнал
    assert weights["концерт"] > 0
    assert weights["выставка"] > 0


def test_build_event_tag_weights_legacy_fallback():
    event = build_event(
        user_interests=["музыка", "театр"],
        interests=[],
    )

    weights = build_event_tag_weights(event)

    assert round(weights["музыка"], 2) == 0.5
    assert round(weights["театр"], 2) == 0.5


def test_apply_action_delta_uses_weight():
    scores = {"музыка": 1.0}
    tag_weights = {"музыка": 0.8, "театр": 0.2}

    updated = apply_action_delta(scores, tag_weights, action_weight=2.0)

    assert updated["музыка"] == 2.6  # 1.0 + 2.0 * 0.8
    assert updated["театр"] == 0.4   # 0.0 + 2.0 * 0.2
