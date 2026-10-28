"""Stockfish and UCI engine management subsystem."""
from .engine_models import (
    CandidateVariation,
    EngineAnalysisResult,
    EngineConfig,
    EngineDefinition,
    EngineScore,
    EngineStatus,
    SearchLimit,
)
from .resource_scheduler import ResourceBudget, ResourceScheduler
from .engine_registry import EngineRegistry, MAX_REGISTERED_ENGINES, MAX_VARIATIONS_PER_ENGINE
from .uci_process import (
    InProcessUCITransport,
    SubprocessUCITransport,
    UCIProcessClient,
    UCITransport,
)
from .engine_manager import EngineManager

__all__ = [
    "CandidateVariation",
    "EngineAnalysisResult",
    "EngineConfig",
    "EngineDefinition",
    "EngineScore",
    "EngineStatus",
    "SearchLimit",
    "ResourceBudget",
    "ResourceScheduler",
    "EngineRegistry",
    "MAX_REGISTERED_ENGINES",
    "MAX_VARIATIONS_PER_ENGINE",
    "InProcessUCITransport",
    "SubprocessUCITransport",
    "UCIProcessClient",
    "UCITransport",
    "EngineManager",
]
