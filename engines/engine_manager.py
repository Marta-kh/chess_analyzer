"""High-level EngineManager coordinating up to 5 Stockfish engines and up to 5 MultiPV lines per engine."""
import threading
from typing import Callable, Dict, List, Optional
import chess
from .engine_models import (
    CandidateVariation,
    EngineAnalysisResult,
    EngineDefinition,
    EngineStatus,
    SearchLimit,
)
from .engine_registry import EngineRegistry, MAX_VARIATIONS_PER_ENGINE
from .resource_scheduler import ResourceBudget, ResourceScheduler
from .uci_process import UCIProcessClient


class EngineManager:
    """
    Coordinates multiple Stockfish engines (up to 5) with independent candidate-variation lists (up to 5 each).
    Enforces:
    - Engine analysis OFF by default (Section 7.1).
    - Adding/removing candidate variations per engine via UCI MultiPV (Section 7.5).
    - Resource budget across active engines (Section 7.4).
    - Generation-tagged updates so stale searches never overwrite current position results (Section 16).
    """

    def __init__(
        self,
        registry: Optional[EngineRegistry] = None,
        scheduler: Optional[ResourceScheduler] = None,
    ) -> None:
        self.registry = registry or EngineRegistry()
        self.scheduler = scheduler or ResourceScheduler()
        self._clients: Dict[str, UCIProcessClient] = {}
        self._results: Dict[str, EngineAnalysisResult] = {}
        self._listeners: List[Callable[[Dict[str, EngineAnalysisResult]], None]] = []
        self._lock = threading.Lock()
        self._global_search_id: int = 0
        self._current_fen: str = chess.STARTING_FEN
        self._analysis_active: bool = False  # OFF by default (Section 7.1)

    @property
    def is_analysis_active(self) -> bool:
        return self._analysis_active

    @property
    def current_fen(self) -> str:
        return self._current_fen

    def set_current_fen(self, fen: str) -> None:
        """Synchronize the board's current FEN even when engine analysis is OFF."""
        if fen:
            self._current_fen = fen

    def add_listener(self, listener: Callable[[Dict[str, EngineAnalysisResult]], None]) -> None:
        self._listeners.append(listener)

    def _notify_listeners(self) -> None:
        with self._lock:
            snapshot = {k: v for k, v in self._results.items()}
        for cb in self._listeners:
            try:
                cb(snapshot)
            except Exception:
                pass

    def set_analysis_active(self, active: bool, current_fen: Optional[str] = None) -> None:
        """
        Explicitly enable or disable live engine analysis.
        When enabled, if no engine is currently enabled in the registry, enables the bundled Stockfish engine.
        When disabled, immediately cancels all background searches.
        """
        if current_fen:
            self._current_fen = current_fen
        self._analysis_active = bool(active)
        if not self._analysis_active:
            self.stop_all_searches()
            self._notify_listeners()
            return

        if not self.registry.list_enabled_engines():
            # Enable the default bundled engine when user turns on analysis
            bundled = self.registry.list_engines()[0]
            self.registry.set_engine_enabled(bundled.engine_id, True)

        self.analyze_position(self._current_fen)

    def enable_engine(self, engine_id: str, enabled: bool) -> None:
        """Enable or disable a specific engine in the comparison panel."""
        self.registry.set_engine_enabled(engine_id, enabled)
        if not enabled:
            with self._lock:
                client = self._clients.pop(engine_id, None)
                self._results.pop(engine_id, None)
            if client:
                client.stop_process()
            if not self.registry.list_enabled_engines():
                self._analysis_active = False
            elif self._analysis_active:
                self.analyze_position(self._current_fen)
            self._notify_listeners()
        else:
            if self._analysis_active:
                self.analyze_position(self._current_fen)

    def add_variation(self, engine_id: str) -> int:
        """
        Critical Requirement (Section 7.5):
        Clicking 'Add variation' adds another candidate line from the selected engine (up to 5),
        NOT another engine instance. Reconfigures MultiPV and updates the search if analysis is active.
        """
        eng = self.registry.get_engine(engine_id)
        if eng.config.visible_variations >= MAX_VARIATIONS_PER_ENGINE:
            return eng.config.visible_variations
        new_count = eng.config.visible_variations + 1
        self.registry.set_visible_variations(engine_id, new_count)

        if self._analysis_active and eng.enabled:
            with self._lock:
                if engine_id in self._results:
                    self._results[engine_id].requested_variations = new_count
                    self._results[engine_id].is_calculating_additional_variation = True
            self._restart_single_engine_search(eng, self._current_fen)
        return new_count

    def remove_variation(self, engine_id: str, multipv_index: Optional[int] = None) -> int:
        """
        Remove a candidate variation line from `engine_id` (down to minimum 1 line when enabled).
        Never removes or disables the engine itself (Section 7.5).
        """
        eng = self.registry.get_engine(engine_id)
        if eng.config.visible_variations <= 1:
            return 1
        new_count = eng.config.visible_variations - 1
        self.registry.set_visible_variations(engine_id, new_count)

        with self._lock:
            res = self._results.get(engine_id)
            if res is not None:
                res.requested_variations = new_count
                if multipv_index is not None and len(res.variations) > new_count:
                    res.variations = [v for v in res.variations if v.multipv_index != multipv_index][:new_count]
                    # Renumber remaining lines 1..new_count
                    for idx, v in enumerate(res.variations):
                        v.multipv_index = idx + 1
                else:
                    res.variations = res.variations[:new_count]
                res.limited_variations_reason = self._compute_limitation_reason(
                    new_count, res.available_legal_moves
                )
        self._notify_listeners()
        return new_count

    @staticmethod
    def _compute_limitation_reason(requested: int, legal_moves_count: int) -> Optional[str]:
        if legal_moves_count == 0:
            return "No legal moves exist in this position (game over)."
        if legal_moves_count < requested:
            return (
                f"Only {legal_moves_count} legal move(s) exist in this position; "
                f"cannot produce {requested} distinct candidate lines."
            )
        return None

    def _get_or_create_client(self, eng: EngineDefinition) -> UCIProcessClient:
        with self._lock:
            if eng.engine_id not in self._clients:
                self._clients[eng.engine_id] = UCIProcessClient(
                    engine_id=eng.engine_id,
                    display_name=eng.display_name,
                    binary_path=eng.binary_path,
                    transport_type=eng.transport_type,
                    on_update=self._on_client_update,
                )
            return self._clients[eng.engine_id]

    def analyze_position(self, fen: str, search_limit_override: Optional[SearchLimit] = None) -> int:
        """
        Start or update analysis of `fen` across all enabled engines within the resource budget.
        Returns the new `search_id`.
        """
        self._current_fen = fen
        if not self._analysis_active:
            return self._global_search_id

        enabled_engines = self.registry.list_enabled_engines()
        if not enabled_engines:
            return self._global_search_id

        allocations = self.scheduler.allocate_resources(enabled_engines)
        board = chess.Board(fen)
        legal_count = board.legal_moves.count()

        with self._lock:
            self._global_search_id += 1
            search_id = self._global_search_id

        for eng in enabled_engines:
            self._start_engine_search_internal(
                eng=eng,
                fen=fen,
                search_id=search_id,
                legal_count=legal_count,
                alloc=allocations.get(eng.engine_id, {"threads": 1, "hash_mb": 16}),
                limit_override=search_limit_override,
            )
        return search_id

    def _restart_single_engine_search(self, eng: EngineDefinition, fen: str) -> None:
        enabled_engines = self.registry.list_enabled_engines()
        allocations = self.scheduler.allocate_resources(enabled_engines)
        board = chess.Board(fen)
        legal_count = board.legal_moves.count()
        with self._lock:
            self._global_search_id += 1
            search_id = self._global_search_id
        self._start_engine_search_internal(
            eng=eng,
            fen=fen,
            search_id=search_id,
            legal_count=legal_count,
            alloc=allocations.get(eng.engine_id, {"threads": 1, "hash_mb": 16}),
            limit_override=None,
        )

    def _start_engine_search_internal(
        self,
        eng: EngineDefinition,
        fen: str,
        search_id: int,
        legal_count: int,
        alloc: Dict[str, int],
        limit_override: Optional[SearchLimit],
    ) -> None:
        limit = limit_override or eng.config.search_limit
        req_vars = eng.config.visible_variations
        reason = self._compute_limitation_reason(req_vars, legal_count)

        with self._lock:
            prev_vars = (
                self._results[eng.engine_id].variations
                if eng.engine_id in self._results and self._results[eng.engine_id].fen == fen
                else []
            )
            self._results[eng.engine_id] = EngineAnalysisResult(
                engine_id=eng.engine_id,
                engine_name=eng.display_name,
                version_build=eng.version_build,
                fen=fen,
                search_id=search_id,
                status=EngineStatus.ANALYZING if legal_count > 0 else EngineStatus.IDLE,
                requested_variations=req_vars,
                available_legal_moves=legal_count,
                variations=list(prev_vars),
                current_depth=0,
                target_depth=limit.max_depth,
                progress_ratio=0.0 if legal_count > 0 else 1.0,
                is_calculating_additional_variation=len(prev_vars) < min(req_vars, legal_count),
                limited_variations_reason=reason,
            )
        self._notify_listeners()

        try:
            client = self._get_or_create_client(eng)
            client.start_search(
                search_id=search_id,
                fen=fen,
                multipv=req_vars,
                threads=alloc["threads"],
                hash_mb=alloc["hash_mb"],
                max_depth=limit.max_depth,
                movetime_ms=limit.movetime_ms,
                infinite=limit.infinite,
            )
        except Exception as exc:
            with self._lock:
                if eng.engine_id in self._results:
                    self._results[eng.engine_id].status = EngineStatus.ERROR
                    self._results[eng.engine_id].error_message = str(exc)
            self._notify_listeners()

    def _on_client_update(
        self,
        engine_id: str,
        search_id: int,
        variations_map: Dict[int, CandidateVariation],
        is_complete: bool,
        bestmove: Optional[str],
    ) -> None:
        with self._lock:
            res = self._results.get(engine_id)
            if res is None or res.search_id != search_id:
                return  # Discard stale search updates (Section 16)
            ordered = [
                variations_map[k]
                for k in sorted(variations_map.keys())
                if k <= res.requested_variations
            ]
            res.variations = ordered
            if ordered:
                res.current_depth = max(v.depth for v in ordered)
                if res.target_depth and res.target_depth > 0:
                    res.progress_ratio = min(1.0, res.current_depth / float(res.target_depth))
            expected_count = min(res.requested_variations, res.available_legal_moves)
            res.is_calculating_additional_variation = (not is_complete) and (len(ordered) < expected_count)
            if is_complete:
                res.status = EngineStatus.IDLE
                res.progress_ratio = 1.0
                res.is_calculating_additional_variation = False
        self._notify_listeners()

    def wait_for_all_engines(self, timeout: float = 10.0) -> Dict[str, EngineAnalysisResult]:
        with self._lock:
            clients = list(self._clients.values())
        for c in clients:
            c.wait_for_search_completion(timeout=timeout)
        with self._lock:
            return dict(self._results)

    def get_results(self) -> Dict[str, EngineAnalysisResult]:
        with self._lock:
            return dict(self._results)

    def stop_all_searches(self) -> None:
        with self._lock:
            clients = list(self._clients.values())
            for res in self._results.values():
                if res.status == EngineStatus.ANALYZING:
                    res.status = EngineStatus.IDLE
                    res.is_calculating_additional_variation = False
        for c in clients:
            c.cancel_search()
        self._notify_listeners()

    def shutdown(self) -> None:
        self.stop_all_searches()
        with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
        for c in clients:
            c.stop_process()
