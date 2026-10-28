"""Background queue and worker for full-game or continuation move classification with position reuse and caching."""
from dataclasses import dataclass
import threading
from typing import Callable, Dict, List, Optional
import chess
from chess_analyzer.domain.game_session import GameSession
from chess_analyzer.engines.engine_models import CandidateVariation, EngineDefinition, EngineScore
from chess_analyzer.engines.uci_process import UCIProcessClient
from .evaluator import PositionEvaluator
from .expected_points import ExpectedPointsModel
from .game_report import GameAnalysisReport, PositionAnalysis, build_game_report
from .move_classifier import MoveClassification, MoveClassifier
from .opening_recognizer import OpeningRecognizer


@dataclass
class GameAnalysisProgress:
    session_id: str
    completed_plies: int
    total_plies: int
    is_running: bool
    is_cancelled: bool
    is_completed: bool
    error: Optional[str] = None

    @property
    def ratio(self) -> float:
        if self.total_plies <= 0:
            return 1.0
        return min(1.0, self.completed_plies / float(self.total_plies))


class GameAnalyzer:
    """
    Executes game-wide move classification on a background thread with:
    - Single Stockfish process reused across the entire game
    - Position reuse (each ply's `fen_after` evaluation is reused from the next ply's `fen_before` evaluation,
      evaluating N+1 unique positions instead of 2N)
    - Horizon-effect clamping so non-best moves evaluated 1 ply deeper do not receive artificial 0-loss scores
    - Opening book & transposition recognition (ECO code + opening name)
    - Safe cancellation and progress callbacks
    """

    def __init__(self, classifier: Optional[MoveClassifier] = None) -> None:
        self.classifier = classifier or MoveClassifier()
        self.opening_recognizer = OpeningRecognizer()
        self.ep_model = ExpectedPointsModel()
        self._cancel_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._progress: Optional[GameAnalysisProgress] = None
        self._eval_cache: Dict[str, List[CandidateVariation]] = {}

    @property
    def progress(self) -> Optional[GameAnalysisProgress]:
        with self._lock:
            return self._progress

    def cancel(self) -> None:
        self._cancel_event.set()
        t = self._worker_thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=1.5)

    def analyze_session_sync(
        self,
        session: GameSession,
        engine_def: EngineDefinition,
        search_depth: int = 4,
        multipv: int = 2,
        on_progress: Optional[Callable[[GameAnalysisProgress], None]] = None,
        force_reanalyze: bool = False,
    ) -> Optional[GameAnalysisReport]:
        """
        Run move classification across all recorded mainline moves in `session`.
        Enforces Section 8 activation policy: refuses to classify if `session.classification_enabled` is False.
        """
        if not session.classification_enabled:
            raise PermissionError(
                f"Move classification is disabled for session '{session.session_id}' (mode={session.mode.value}). "
                "For manual and custom-position sessions, finish the game and opt in first."
            )

        if force_reanalyze:
            self._eval_cache.clear()

        nodes = session.board_manager.history.mainline_nodes
        total = len(nodes)
        self._cancel_event.clear()

        white_rating = getattr(session.metadata, "white_elo", None)
        black_rating = getattr(session.metadata, "black_elo", None)

        with self._lock:
            self._progress = GameAnalysisProgress(
                session_id=session.session_id,
                completed_plies=0,
                total_plies=total,
                is_running=True,
                is_cancelled=False,
                is_completed=False,
            )
        if on_progress and self._progress:
            on_progress(self._progress)

        if total == 0:
            with self._lock:
                self._progress.is_running = False
                self._progress.is_completed = True
            if on_progress and self._progress:
                on_progress(self._progress)
            session.mark_classifications_computed()
            return build_game_report(
                session.session_id,
                engine_def.engine_id,
                engine_def.version_build,
                [],
                white_rating=white_rating,
                black_rating=black_rating,
            )

        initial_fen = session.board_manager.history.initial_fen
        uci_moves = [n.uci for n in nodes]
        fens_after = [n.fen_after for n in nodes]
        eco_code, opening_name, book_flags = self.opening_recognizer.analyze_opening_sequence(
            initial_fen=initial_fen,
            uci_moves=uci_moves,
            fens_after_moves=fens_after,
        )

        client = UCIProcessClient(
            engine_id=f"{engine_def.engine_id}_batch",
            display_name=engine_def.display_name,
            binary_path=engine_def.binary_path,
            transport_type=engine_def.transport_type,
        )
        classifications: List[MoveClassification] = []
        position_analyses: List[PositionAnalysis] = []

        try:
            client.start(timeout=5.0)
            search_seq = 0
            mpv_count = max(2, multipv)

            def evaluate_fen(fen: str, mpv: int) -> List[CandidateVariation]:
                cache_key = f"{fen}|{engine_def.version_build}|d{search_depth}|mpv{mpv}"
                if cache_key in self._eval_cache:
                    return self._eval_cache[cache_key]
                higher_key = f"{fen}|{engine_def.version_build}|d{search_depth}|mpv{mpv_count}"
                if mpv == 1 and higher_key in self._eval_cache:
                    return self._eval_cache[higher_key]
                nonlocal search_seq
                search_seq += 1
                client.start_search(
                    search_id=search_seq,
                    fen=fen,
                    multipv=mpv,
                    threads=1,
                    hash_mb=16,
                    max_depth=search_depth,
                )
                vars_map = client.wait_for_search_completion(timeout=5.0)
                ordered = [vars_map[k] for k in sorted(vars_map.keys())]
                self._eval_cache[cache_key] = ordered
                return ordered

            def build_pos_analysis(ply_idx: int, fen_str: str, vars_list: List[CandidateVariation]) -> PositionAnalysis:
                b = chess.Board(fen_str)
                turn_col = "white" if b.turn == chess.WHITE else "black"
                if b.is_checkmate():
                    sc = EngineScore(raw_cp_pov=None, raw_mate_pov=0, pov_color=turn_col)
                elif b.is_game_over():
                    sc = EngineScore(raw_cp_pov=0, raw_mate_pov=None, pov_color=turn_col)
                elif vars_list:
                    sc = vars_list[0].score
                else:
                    sc = EngineScore(raw_cp_pov=0, raw_mate_pov=None, pov_color=turn_col)

                w_cp = PositionEvaluator.score_to_mover_cp(sc, "white")
                outcomes_w = self.ep_model.from_score(
                    sc,
                    "white",
                    rating=white_rating,
                    is_terminal_draw=(b.is_game_over() and not b.is_checkmate()),
                )
                top_v = vars_list[0] if vars_list else None
                return PositionAnalysis(
                    ply=ply_idx,
                    fen=fen_str,
                    turn_color=turn_col,
                    score_white_pov=sc,
                    white_cp=max(-1000, min(1000, w_cp)),
                    expected_points_white=outcomes_w.expected_points,
                    win_prob_white=outcomes_w.win_prob,
                    draw_prob=outcomes_w.draw_prob,
                    loss_prob_white=outcomes_w.loss_prob,
                    best_move_uci=top_v.best_move_uci if top_v else None,
                    best_move_san=top_v.best_move_san if top_v else None,
                    pv_uci=list(top_v.pv_uci) if top_v else [],
                    depth=top_v.depth if top_v else search_depth,
                )

            prev_ep_white = 0.5
            prev_ep_black = 0.5
            next_vars_cached: Optional[List[CandidateVariation]] = None

            for idx, node in enumerate(nodes):
                if self._cancel_event.is_set():
                    with self._lock:
                        if self._progress:
                            self._progress.is_running = False
                            self._progress.is_cancelled = True
                    if on_progress and self._progress:
                        on_progress(self._progress)
                    return None

                board_before = chess.Board(node.fen_before)
                legal_count = board_before.legal_moves.count()
                vars_before = next_vars_cached if next_vars_cached is not None else evaluate_fen(node.fen_before, mpv_count)
                if idx == 0:
                    position_analyses.append(build_pos_analysis(0, node.fen_before, vars_before))

                board_after = chess.Board(node.fen_after)
                is_draw_after = board_after.is_game_over() and not board_after.is_checkmate()
                mover_col = node.turn_before

                if board_after.is_checkmate():
                    pov = "white" if board_after.turn == chess.WHITE else "black"
                    score_after = EngineScore(raw_cp_pov=None, raw_mate_pov=0, pov_color=pov)
                    next_vars_cached = []
                elif is_draw_after:
                    pov = "white" if board_after.turn == chess.WHITE else "black"
                    score_after = EngineScore(raw_cp_pov=0, raw_mate_pov=None, pov_color=pov)
                    next_vars_cached = []
                else:
                    req_mpv_after = mpv_count if idx + 1 < total else 1
                    vars_after = evaluate_fen(node.fen_after, req_mpv_after)
                    next_vars_cached = vars_after
                    score_after = vars_after[0].score if vars_after else None

                    # Guard against +1 ply search-horizon inflation on non-best moves:
                    if vars_before and score_after is not None and not score_after.is_mate and not vars_before[0].score.is_mate:
                        best_before_cp = PositionEvaluator.score_to_mover_cp(vars_before[0].score, mover_col)
                        after_cp = PositionEvaluator.score_to_mover_cp(score_after, mover_col)
                        if node.uci != vars_before[0].best_move_uci:
                            matched_cand = next((v for v in vars_before if v.best_move_uci == node.uci), None)
                            if matched_cand is not None and not matched_cand.score.is_mate:
                                cand_cp = PositionEvaluator.score_to_mover_cp(matched_cand.score, mover_col)
                                if after_cp > cand_cp:
                                    score_after = matched_cand.score
                            else:
                                # Played move wasn't in top MultiPV lines at root: cannot be better than the lowest MultiPV line
                                worst_mpv_cp = PositionEvaluator.score_to_mover_cp(vars_before[-1].score, mover_col)
                                ceiling_cp = min(best_before_cp - 12, worst_mpv_cp - 5)
                                if after_cp > ceiling_cp:
                                    opp_col = "black" if mover_col == "white" else "white"
                                    score_after = EngineScore(raw_cp_pov=-ceiling_cp, raw_mate_pov=None, pov_color=opp_col)

                position_analyses.append(
                    build_pos_analysis(node.ply, node.fen_after, next_vars_cached or [])
                )

                mover_rating = white_rating if mover_col == "white" else black_rating
                prev_ep_mover = prev_ep_white if mover_col == "white" else prev_ep_black
                is_book = book_flags[idx] if idx < len(book_flags) else False

                cls_item = self.classifier.classify_move(
                    ply=node.ply,
                    played_uci=node.uci,
                    played_san=node.san,
                    mover_color=mover_col,
                    legal_moves_count=legal_count,
                    variations_before=vars_before,
                    score_after=score_after,
                    engine_id=engine_def.engine_id,
                    engine_version=engine_def.version_build,
                    fen_before=node.fen_before,
                    is_book_line=is_book,
                    previous_ep_for_mover=prev_ep_mover,
                    player_rating=mover_rating,
                    is_terminal_draw_after=is_draw_after,
                )
                classifications.append(cls_item)

                if mover_col == "white":
                    prev_ep_white = cls_item.expected_points_after
                    prev_ep_black = 1.0 - prev_ep_white
                else:
                    prev_ep_black = cls_item.expected_points_after
                    prev_ep_white = 1.0 - prev_ep_black

                with self._lock:
                    if self._progress:
                        self._progress.completed_plies = idx + 1
                if on_progress and self._progress:
                    on_progress(self._progress)

            with self._lock:
                if self._progress:
                    self._progress.is_running = False
                    self._progress.is_completed = True
            if on_progress and self._progress:
                on_progress(self._progress)

            session.mark_classifications_computed()
            return build_game_report(
                session_id=session.session_id,
                engine_id=engine_def.engine_id,
                engine_version=engine_def.version_build,
                classifications=classifications,
                system_label=self.classifier.SYSTEM_LABEL,
                opening_eco=eco_code,
                opening_name=opening_name,
                positions=position_analyses,
                white_rating=white_rating,
                black_rating=black_rating,
            )
        finally:
            client.stop_process()

    def start_background_analysis(
        self,
        session: GameSession,
        engine_def: EngineDefinition,
        search_depth: int = 4,
        on_progress: Optional[Callable[[GameAnalysisProgress], None]] = None,
        on_complete: Optional[Callable[[Optional[GameAnalysisReport]], None]] = None,
        force_reanalyze: bool = False,
    ) -> None:
        self.cancel()

        def _runner() -> None:
            try:
                rep = self.analyze_session_sync(
                    session=session,
                    engine_def=engine_def,
                    search_depth=search_depth,
                    on_progress=on_progress,
                    force_reanalyze=force_reanalyze,
                )
                if on_complete:
                    on_complete(rep)
            except Exception as exc:
                with self._lock:
                    if self._progress:
                        self._progress.is_running = False
                        self._progress.error = str(exc)
                if on_progress and self._progress:
                    on_progress(self._progress)
                if on_complete:
                    on_complete(None)

        self._worker_thread = threading.Thread(target=_runner, daemon=True)
        self._worker_thread.start()
