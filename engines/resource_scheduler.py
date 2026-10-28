"""CPU thread and memory budget scheduler across up to 5 concurrent Stockfish engines."""
from dataclasses import dataclass
import os
from typing import Dict, List, Optional
from .engine_models import EngineDefinition


@dataclass
class ResourceBudget:
    """Overall system budget for all active engines combined."""
    max_total_threads: int = max(1, min(4, (os.cpu_count() or 2)))
    max_total_hash_mb: int = 128
    deep_analysis_max_depth: int = 20
    deep_analysis_movetime_ms: int = 5000


class ResourceScheduler:
    """
    Prevents multiple active engines from independently consuming all CPU cores or memory
    (Section 7.4). Allocates threads and hash table sizes proportionally within the budget.
    """

    def __init__(self, budget: Optional[ResourceBudget] = None) -> None:
        self._budget = budget or ResourceBudget()

    @property
    def budget(self) -> ResourceBudget:
        return self._budget

    def update_budget(self, budget: ResourceBudget) -> None:
        if budget.max_total_threads < 1:
            raise ValueError("max_total_threads must be >= 1")
        if budget.max_total_hash_mb < 8:
            raise ValueError("max_total_hash_mb must be >= 8")
        self._budget = budget

    def allocate_resources(self, active_engines: List[EngineDefinition]) -> Dict[str, Dict[str, int]]:
        """
        Return a dict mapping `engine_id -> {"threads": int, "hash_mb": int}`
        guaranteeing that the sum across active engines respects the total budget
        (with a minimum floor of 1 thread and 8 MB hash per active engine).
        """
        if not active_engines:
            return {}

        n = len(active_engines)
        total_req_threads = sum(max(1, e.config.threads) for e in active_engines)
        total_req_hash = sum(max(8, e.config.hash_mb) for e in active_engines)

        allocations: Dict[str, Dict[str, int]] = {}
        remaining_threads = max(n, self._budget.max_total_threads)
        remaining_hash = max(n * 8, self._budget.max_total_hash_mb)

        for idx, eng in enumerate(active_engines):
            engines_left = n - idx
            if total_req_threads <= self._budget.max_total_threads:
                t_alloc = max(1, eng.config.threads)
            else:
                share = max(1, int(round((eng.config.threads / total_req_threads) * self._budget.max_total_threads)))
                t_alloc = min(share, max(1, remaining_threads - (engines_left - 1)))

            if total_req_hash <= self._budget.max_total_hash_mb:
                h_alloc = max(8, eng.config.hash_mb)
            else:
                h_share = max(8, int(round((eng.config.hash_mb / total_req_hash) * self._budget.max_total_hash_mb)))
                h_alloc = min(h_share, max(8, remaining_hash - (engines_left - 1) * 8))

            remaining_threads = max(0, remaining_threads - t_alloc)
            remaining_hash = max(0, remaining_hash - h_alloc)
            allocations[eng.engine_id] = {"threads": t_alloc, "hash_mb": h_alloc}

        return allocations
