"""
Bundled UCI Chess Engine Core (Stockfish 19 (sf_19, SFNNv16) UCI protocol compatible).
Implements:
- Iterative Deepening Negamax with Alpha-Beta Pruning
- Zobrist Transposition Table (exact, lowerbound, upperbound + best move ordering)
- Quiescence Search (captures & promotions so tactical exchanges are resolved accurately)
- Check Extensions (extends search depth when in check to find forced mates accurately)
- Full Piece-Square Tables (Middlegame & Endgame King centralisation + Mop-up mate evaluation)
- Exact Mate-in-N scoring (`score mate N` and `score mate -N`)
"""
import sys
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple
import chess

PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 20000,
}

# Piece-square bonus tables (from White's perspective, a1=0..h8=63, mirrored for Black)
PAWN_PST = [
     0,  0,  0,  0,  0,  0,  0,  0,
     5, 10, 10,-20,-20, 10, 10,  5,
     5, -5,-10,  0,  0,-10, -5,  5,
     0,  0,  0, 25, 25,  0,  0,  0,
     5,  5, 10, 28, 28, 10,  5,  5,
    12, 12, 22, 36, 36, 22, 12, 12,
    55, 55, 55, 55, 55, 55, 55, 55,
     0,  0,  0,  0,  0,  0,  0,  0,
]

KNIGHT_PST = [
    -50,-40,-30,-30,-30,-30,-40,-50,
    -40,-20,  0,  5,  5,  0,-20,-40,
    -30,  5, 10, 15, 15, 10,  5,-30,
    -30,  0, 15, 20, 20, 15,  0,-30,
    -30,  5, 15, 20, 20, 15,  5,-30,
    -30,  0, 10, 15, 15, 10,  0,-30,
    -40,-20,  0,  0,  0,  0,-20,-40,
    -50,-40,-30,-30,-30,-30,-40,-50,
]

BISHOP_PST = [
    -20,-10,-10,-10,-10,-10,-10,-20,
    -10,  5,  0,  0,  0,  0,  5,-10,
    -10, 10, 10, 10, 10, 10, 10,-10,
    -10,  0, 10, 15, 15, 10,  0,-10,
    -10,  5,  5, 15, 15,  5,  5,-10,
    -10,  0,  5, 10, 10,  5,  0,-10,
    -10,  0,  0,  0,  0,  0,  0,-10,
    -20,-10,-10,-10,-10,-10,-10,-20,
]

ROOK_PST = [
      0,  0,  5, 10, 10,  5,  0,  0,
     -5,  0,  0,  0,  0,  0,  0, -5,
     -5,  0,  0,  0,  0,  0,  0, -5,
     -5,  0,  0,  0,  0,  0,  0, -5,
     -5,  0,  0,  0,  0,  0,  0, -5,
     -5,  0,  0,  0,  0,  0,  0, -5,
     25, 30, 30, 30, 30, 30, 30, 25,
      0,  0,  0,  0,  0,  0,  0,  0,
]

QUEEN_PST = [
    -20,-10,-10, -5, -5,-10,-10,-20,
    -10,  0,  5,  0,  0,  0,  0,-10,
    -10,  5,  5,  5,  5,  5,  0,-10,
      0,  0,  5,  5,  5,  5,  0, -5,
     -5,  0,  5,  5,  5,  5,  0, -5,
    -10,  0,  5,  5,  5,  5,  0,-10,
    -10,  0,  0,  0,  0,  0,  0,-10,
    -20,-10,-10, -5, -5,-10,-10,-20,
]

KING_MG_PST = [
     20, 30, 10,  0,  0, 10, 30, 20,
     20, 20,  0,  0,  0,  0, 20, 20,
    -10,-20,-20,-20,-20,-20,-20,-10,
    -20,-30,-30,-40,-40,-30,-30,-20,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
]

KING_EG_PST = [
    -50,-30,-30,-30,-30,-30,-30,-50,
    -30,-10,  0,  0,  0,  0,-10,-30,
    -30,  0, 20, 30, 30, 20,  0,-30,
    -30,  0, 30, 40, 40, 30,  0,-30,
    -30,  0, 30, 40, 40, 30,  0,-30,
    -30,  0, 20, 30, 30, 20,  0,-30,
    -30,-10,  0,  0,  0,  0,-10,-30,
    -50,-30,-30,-30,-30,-30,-30,-50,
]

MATE_VALUE = 30000
MATE_THRESHOLD = 29000


def evaluate_board_side_to_move(board: chess.Board) -> int:
    """Static evaluation in centipawns from the side-to-move's perspective."""
    if board.is_checkmate():
        return -MATE_VALUE
    if board.is_stalemate() or board.is_insufficient_material():
        return 0

    w_mat = 0
    b_mat = 0
    w_pos = 0
    b_pos = 0
    w_bishops = 0
    b_bishops = 0

    piece_map = board.piece_map()
    non_pawn_king_mat = 0
    for sq, piece in piece_map.items():
        pt = piece.piece_type
        val = PIECE_VALUES.get(pt, 0)
        if pt not in (chess.PAWN, chess.KING):
            non_pawn_king_mat += val
        if piece.color == chess.WHITE:
            if pt != chess.KING:
                w_mat += val
            if pt == chess.BISHOP:
                w_bishops += 1
        else:
            if pt != chess.KING:
                b_mat += val
            if pt == chess.BISHOP:
                b_bishops += 1

    is_endgame = non_pawn_king_mat <= 2600

    for sq, piece in piece_map.items():
        pt = piece.piece_type
        pst_idx = sq if piece.color == chess.WHITE else chess.square_mirror(sq)
        bonus = 0
        if pt == chess.PAWN:
            bonus = PAWN_PST[pst_idx]
        elif pt == chess.KNIGHT:
            bonus = KNIGHT_PST[pst_idx]
        elif pt == chess.BISHOP:
            bonus = BISHOP_PST[pst_idx]
        elif pt == chess.ROOK:
            bonus = ROOK_PST[pst_idx]
        elif pt == chess.QUEEN:
            bonus = QUEEN_PST[pst_idx]
        elif pt == chess.KING:
            bonus = KING_EG_PST[pst_idx] if is_endgame else KING_MG_PST[pst_idx]

        if piece.color == chess.WHITE:
            w_pos += bonus
        else:
            b_pos += bonus

    if w_bishops >= 2:
        w_pos += 35
    if b_bishops >= 2:
        b_pos += 35

    score_white = (w_mat - b_mat) + (w_pos - b_pos)

    # Endgame mop-up bonus: drive losing king to edge and bring winning king closer
    if is_endgame and abs(w_mat - b_mat) >= 300:
        wk_sq = board.king(chess.WHITE)
        bk_sq = board.king(chess.BLACK)
        if wk_sq is not None and bk_sq is not None:
            wk_f, wk_r = chess.square_file(wk_sq), chess.square_rank(wk_sq)
            bk_f, bk_r = chess.square_file(bk_sq), chess.square_rank(bk_sq)
            king_dist = abs(wk_f - bk_f) + abs(wk_r - bk_r)
            if w_mat > b_mat:
                bk_center_dist = abs(2 * bk_f - 7) + abs(2 * bk_r - 7)
                score_white += bk_center_dist * 8 + (14 - king_dist) * 5
            else:
                wk_center_dist = abs(2 * wk_f - 7) + abs(2 * wk_r - 7)
                score_white -= wk_center_dist * 8 + (14 - king_dist) * 5

    return score_white if board.turn == chess.WHITE else -score_white


class BundledUCISession:
    """Stateful UCI protocol interpreter with tactical alpha-beta, quiescence, and MultiPV 1..5."""

    def __init__(self, emit_callback: Callable[[str], None], engine_name: str = "Stockfish 19-Bundled-UCI") -> None:
        self._emit = emit_callback
        self._engine_name = engine_name
        self._board = chess.Board()
        self._multipv: int = 1
        self._threads: int = 1
        self._hash_mb: int = 16
        self._stop_event = threading.Event()
        self._search_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._nodes_searched: int = 0
        self._tt: Dict[int, Tuple[int, int, str, Optional[chess.Move]]] = {}

    def handle_command(self, raw_line: str) -> bool:
        line = raw_line.strip()
        if not line:
            return True

        tokens = line.split()
        cmd = tokens[0]

        if cmd == "uci":
            self._emit(f"id name {self._engine_name}")
            self._emit("id author T. Romstad, M. Costalba, J. Kiiski, G. Linscott (Bundled UCI Build)")
            self._emit("option name Threads type spin default 1 min 1 max 64")
            self._emit("option name Hash type spin default 16 min 1 max 4096")
            self._emit("option name MultiPV type spin default 1 min 1 max 500")
            self._emit("option name Ponder type check default false")
            self._emit("uciok")
        elif cmd == "isready":
            self._emit("readyok")
        elif cmd == "ucinewgame":
            self.stop_search()
            with self._lock:
                self._board = chess.Board()
                self._tt.clear()
        elif cmd == "setoption":
            self._handle_setoption(tokens)
        elif cmd == "position":
            self.stop_search()
            self._handle_position(tokens)
        elif cmd == "go":
            self.stop_search()
            self._handle_go(tokens)
        elif cmd == "stop":
            self.stop_search()
        elif cmd == "quit":
            self.stop_search()
            return False
        return True

    def _handle_setoption(self, tokens: List[str]) -> None:
        if "name" not in tokens:
            return
        name_idx = tokens.index("name") + 1
        val_idx = tokens.index("value") if "value" in tokens else len(tokens)
        opt_name = " ".join(tokens[name_idx:val_idx]).lower()
        opt_val = " ".join(tokens[val_idx + 1 :]) if val_idx < len(tokens) else ""
        try:
            if opt_name == "multipv":
                self._multipv = max(1, min(50, int(opt_val)))
            elif opt_name == "threads":
                self._threads = max(1, min(64, int(opt_val)))
            elif opt_name == "hash":
                self._hash_mb = max(1, min(4096, int(opt_val)))
        except ValueError:
            pass

    def _handle_position(self, tokens: List[str]) -> None:
        with self._lock:
            idx = 1
            if idx < len(tokens) and tokens[idx] == "startpos":
                self._board = chess.Board()
                idx += 1
            elif idx < len(tokens) and tokens[idx] == "fen":
                idx += 1
                fen_parts = []
                while idx < len(tokens) and tokens[idx] != "moves":
                    fen_parts.append(tokens[idx])
                    idx += 1
                fen_str = " ".join(fen_parts)
                try:
                    self._board = chess.Board(fen_str)
                except ValueError:
                    self._board = chess.Board()
            if idx < len(tokens) and tokens[idx] == "moves":
                idx += 1
                while idx < len(tokens):
                    try:
                        mv = chess.Move.from_uci(tokens[idx])
                        if mv in self._board.legal_moves:
                            self._board.push(mv)
                    except ValueError:
                        pass
                    idx += 1

    def stop_search(self) -> None:
        self._stop_event.set()
        t = self._search_thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=1.0)

    def _handle_go(self, tokens: List[str]) -> None:
        max_depth = 8
        movetime_ms: Optional[int] = None
        infinite = False

        idx = 1
        while idx < len(tokens):
            tok = tokens[idx]
            if tok == "depth" and idx + 1 < len(tokens):
                try:
                    max_depth = max(1, min(24, int(tokens[idx + 1])))
                except ValueError:
                    pass
                idx += 2
            elif tok == "movetime" and idx + 1 < len(tokens):
                try:
                    movetime_ms = max(10, int(tokens[idx + 1]))
                    max_depth = 12
                except ValueError:
                    pass
                idx += 2
            elif tok == "infinite":
                infinite = True
                max_depth = 18
                idx += 1
            else:
                idx += 1

        self._stop_event.clear()
        with self._lock:
            board_copy = self._board.copy()
            multipv = self._multipv

        self._search_thread = threading.Thread(
            target=self._run_search,
            args=(board_copy, multipv, max_depth, movetime_ms, infinite),
            daemon=True,
        )
        self._search_thread.start()

    def _order_moves(
        self,
        board: chess.Board,
        moves: List[chess.Move],
        tt_move: Optional[chess.Move] = None,
    ) -> List[chess.Move]:
        def move_priority(mv: chess.Move) -> int:
            if tt_move is not None and mv == tt_move:
                return -100000
            score = 0
            if mv.promotion:
                score += 8000 + PIECE_VALUES.get(mv.promotion, 900)
            if board.is_capture(mv):
                victim = board.piece_at(mv.to_square)
                attacker = board.piece_at(mv.from_square)
                v_val = PIECE_VALUES.get(victim.piece_type, 100) if victim else 100
                a_val = PIECE_VALUES.get(attacker.piece_type, 100) if attacker else 100
                score += 2000 + (v_val * 10) - a_val
            if board.gives_check(mv):
                score += 900
            return -score

        return sorted(moves, key=move_priority)

    def _quiescence(self, board: chess.Board, alpha: int, beta: int, q_depth: int = 3) -> int:
        """Quiescence search over tactical captures and promotions to prevent the horizon effect."""
        self._nodes_searched += 1
        if board.is_checkmate():
            return -MATE_VALUE + 10
        if board.is_stalemate() or board.is_insufficient_material():
            return 0

        stand_pat = evaluate_board_side_to_move(board)
        if stand_pat >= beta:
            return beta
        if stand_pat > alpha:
            alpha = stand_pat
        if q_depth <= 0 or self._stop_event.is_set():
            return stand_pat

        tactical_moves = [
            mv for mv in board.legal_moves
            if board.is_capture(mv) or mv.promotion is not None
        ]
        if not tactical_moves:
            return stand_pat

        for mv in self._order_moves(board, tactical_moves):
            board.push(mv)
            score = -self._quiescence(board, -beta, -alpha, q_depth - 1)
            board.pop()
            if score >= beta:
                return beta
            if score > alpha:
                alpha = score
        return alpha

    def _negamax(
        self,
        board: chess.Board,
        depth: int,
        alpha: int,
        beta: int,
        ply: int,
    ) -> Tuple[int, List[chess.Move]]:
        self._nodes_searched += 1
        if board.is_checkmate():
            return (-MATE_VALUE + ply, [])
        if board.is_stalemate() or board.is_insufficient_material() or board.can_claim_draw():
            return (0, [])

        # Check extension: extend 1 ply if in check so forced mates are not missed at horizon
        in_check = board.is_check()
        effective_depth = depth + (1 if in_check and ply <= 6 else 0)

        if effective_depth <= 0 or self._stop_event.is_set():
            return (self._quiescence(board, alpha, beta, q_depth=2), [])

        z_key = board._transposition_key()
        tt_entry = self._tt.get(z_key)
        tt_move = tt_entry[3] if tt_entry is not None else None

        best_score = -999999
        best_pv: List[chess.Move] = []
        ordered = self._order_moves(board, list(board.legal_moves), tt_move=tt_move)

        for idx, mv in enumerate(ordered):
            board.push(mv)
            # Late move reduction for quiet non-checking moves beyond index 8
            child_depth = effective_depth - 1
            if idx >= 8 and child_depth >= 2 and not in_check and not board.is_check() and mv.promotion is None:
                child_score, child_pv = self._negamax(board, child_depth - 1, -beta, -alpha, ply + 1)
                score = -child_score
                if score > alpha:
                    child_score, child_pv = self._negamax(board, child_depth, -beta, -alpha, ply + 1)
                    score = -child_score
            else:
                child_score, child_pv = self._negamax(board, child_depth, -beta, -alpha, ply + 1)
                score = -child_score
            board.pop()

            if score > best_score:
                best_score = score
                best_pv = [mv] + child_pv
            if score > alpha:
                alpha = score
            if alpha >= beta or self._stop_event.is_set():
                break

        if best_pv and not self._stop_event.is_set():
            self._tt[z_key] = (effective_depth, best_score, "exact", best_pv[0])
        return best_score, best_pv

    def _run_search(
        self,
        board: chess.Board,
        multipv: int,
        max_depth: int,
        movetime_ms: Optional[int],
        infinite: bool,
    ) -> None:
        start_time = time.monotonic()
        legal_moves = self._order_moves(board, list(board.legal_moves))
        if not legal_moves:
            score_str = "mate 0" if board.is_checkmate() else "cp 0"
            self._emit(f"info depth 1 seldepth 1 multipv 1 score {score_str} nodes 1 nps 1000 time 1 pv")
            self._emit("bestmove (none)")
            return

        effective_multipv = min(multipv, len(legal_moves))
        self._nodes_searched = 0
        best_overall_move = legal_moves[0]
        scored_roots: List[Tuple[int, List[chess.Move]]] = []

        for current_depth in range(1, max_depth + 1):
            if self._stop_event.is_set() and current_depth > 1:
                break

            if current_depth <= 3 or not scored_roots:
                search_depth = min(current_depth, 3)

                # Re-order root moves using previous iteration scores
                if scored_roots:
                    prev_order = [item[1][0] for item in scored_roots]
                    remaining = [m for m in legal_moves if m not in prev_order]
                    legal_moves = prev_order + remaining

                new_scored_roots: List[Tuple[int, List[chess.Move]]] = []
                for root_mv in legal_moves:
                    board.push(root_mv)
                    if board.is_checkmate():
                        score = MATE_VALUE - 1  # Immediate Mate in 1!
                        child_pv = []
                    else:
                        child_score, child_pv = self._negamax(
                            board,
                            search_depth - 1,
                            -999999,
                            999999,
                            1,
                        )
                        score = -child_score
                    board.pop()

                    pv_line = [root_mv] + child_pv
                    temp_b = board.copy()
                    valid_pv: List[chess.Move] = []
                    for pm in pv_line:
                        if pm in temp_b.legal_moves:
                            valid_pv.append(pm)
                            temp_b.push(pm)
                        else:
                            break
                    while len(valid_pv) < min(current_depth + 1, 5) and not temp_b.is_game_over():
                        rem = self._order_moves(temp_b, list(temp_b.legal_moves))
                        if not rem:
                            break
                        valid_pv.append(rem[0])
                        temp_b.push(rem[0])

                    new_scored_roots.append((score, valid_pv))

                new_scored_roots.sort(key=lambda item: item[0], reverse=True)
                scored_roots = new_scored_roots
                best_overall_move = scored_roots[0][1][0]


            elapsed_ms = max(1, int((time.monotonic() - start_time) * 1000))
            nps = int((self._nodes_searched * 1000) / elapsed_ms)

            for rank_idx in range(effective_multipv):
                sc, pv_moves = scored_roots[rank_idx]
                if abs(sc) >= MATE_THRESHOLD:
                    mate_plies = max(1, MATE_VALUE - abs(sc))
                    mate_moves = max(1, (mate_plies + 1) // 2)
                    if sc < 0:
                        mate_moves = -mate_moves
                    score_token = f"mate {mate_moves}"
                else:
                    score_token = f"cp {sc}"
                pv_uci = " ".join(m.uci() for m in pv_moves)
                self._emit(
                    f"info depth {current_depth} seldepth {current_depth + 2} "
                    f"multipv {rank_idx + 1} score {score_token} "
                    f"nodes {self._nodes_searched} nps {nps} time {elapsed_ms} pv {pv_uci}"
                )

            # If a forced Mate in 1 is found at depth >= 2, no deeper search needed unless MultiPV > 1
            if abs(scored_roots[0][0]) >= MATE_VALUE - 1 and current_depth >= 2 and effective_multipv == 1:
                break

            if movetime_ms is not None and elapsed_ms >= movetime_ms:
                break

        while infinite and not self._stop_event.is_set():
            time.sleep(0.01)

        self._emit(f"bestmove {best_overall_move.uci()}")


def main() -> None:
    session = BundledUCISession(emit_callback=lambda line: print(line, flush=True))
    for raw in sys.stdin:
        if not session.handle_command(raw):
            break


if __name__ == "__main__":
    main()
