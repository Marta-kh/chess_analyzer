"""Reusable UI widgets for engine comparison, evaluation graph, and Chess.com-style Game Review scorecard."""
from .engine_panel import EngineComparisonPanel, EngineInstancePanel
from .game_review_card import (
    CUSTOM_EVAL_ICONS,
    EvaluationGraphWidget,
    GameReviewScorecardWidget,
    get_classification_badge_spec,
)

__all__ = [
    "CUSTOM_EVAL_ICONS",
    "EngineComparisonPanel",
    "EngineInstancePanel",
    "EvaluationGraphWidget",
    "GameReviewScorecardWidget",
    "get_classification_badge_spec",
]
