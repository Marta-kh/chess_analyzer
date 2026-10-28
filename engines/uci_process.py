"""Low-level UCI engine transport supporting both OS subprocesses (Desktop/Android) and In-Process queues (iOS)."""
from abc import ABC, abstractmethod
import queue
import subprocess
import threading
import time
from typing import Callable, Dict, List, Optional
import chess
from .bundled_uci_core import BundledUCISession
from .engine_models import CandidateVariation, EngineScore


class UCITransport(ABC):
    """Abstract transport layer for sending UCI commands and receiving lines."""

    @abstractmethod
    def start(self) -> None:
        pass

    @abstractmethod
    def send_line(self, command: str) -> None:
        pass

    @abstractmethod
    def is_alive(self) -> bool:
        pass

    @abstractmethod
    def close(self) -> None:
        pass


class SubprocessUCITransport(UCITransport):
    """
    OS Subprocess transport (`subprocess.Popen` without shell=True to prevent command injection).
    Used on Linux, macOS, Windows, and Android (`nativeLibraryDir/libstockfish.so`).
    """

    def __init__(self, binary_path: str, on_line: Callable[[str], None], on_exit: Callable[[int], None]) -> None:
        self._binary_path = binary_path
        self._on_line = on_line
        self._on_exit = on_exit
        self._proc: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._closed = False
        self._write_lock = threading.Lock()

    def start(self) -> None:
        import os
        import sys
        from pathlib import Path
        from .engine_registry import is_binary_compatible_with_host

        self._closed = False
        path_obj = Path(self._binary_path)
        if path_obj.suffix.lower() == ".py" or not is_binary_compatible_with_host(path_obj):
            py_core = Path(__file__).resolve().parent / "bundled_uci_core.py"
            target_script = str(path_obj) if path_obj.suffix.lower() == ".py" and path_obj.exists() else str(py_core)
            cmd = [sys.executable, "-u", target_script]
        else:
            cmd = [self._binary_path]

        popen_kwargs = {}
        if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        # Security requirement (Section 17): Never use shell=True
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            **popen_kwargs,
        )
        self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._reader_thread.start()

    def _read_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for raw_line in proc.stdout:
                if self._closed:
                    break
                self._on_line(raw_line.rstrip("\r\n"))
        except Exception:
            pass
        finally:
            rc = proc.poll()
            if rc is None and not self._closed:
                rc = proc.wait()
            if not self._closed:
                self._on_exit(rc if rc is not None else -1)

    def send_line(self, command: str) -> None:
        with self._write_lock:
            if self._proc is None or self._proc.stdin is None or self._proc.poll() is not None:
                raise RuntimeError("UCI subprocess is not running.")
            self._proc.stdin.write(command + "\n")
            self._proc.stdin.flush()

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None and not self._closed

    def close(self) -> None:
        self._closed = True
        proc = self._proc
        if proc is not None:
            try:
                if proc.poll() is None and proc.stdin:
                    proc.stdin.write("quit\n")
                    proc.stdin.flush()
                    proc.wait(timeout=0.5)
            except Exception:
                pass
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=0.5)
                for stream in (proc.stdin, proc.stdout, proc.stderr):
                    if stream is not None:
                        try:
                            stream.close()
                        except Exception:
                            pass
        self._proc = None


class InProcessUCITransport(UCITransport):
    """
    In-process UCI transport for iOS (where Apple's App Sandbox blocks fork/execve)
    and deterministic unit testing.
    """

    def __init__(self, engine_name: str, on_line: Callable[[str], None], on_exit: Callable[[int], None]) -> None:
        self._engine_name = engine_name
        self._on_line = on_line
        self._on_exit = on_exit
        self._cmd_queue: "queue.Queue[Optional[str]]" = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._session: Optional[BundledUCISession] = None
        self._alive = False

    def start(self) -> None:
        self._alive = True
        self._session = BundledUCISession(emit_callback=self._on_line, engine_name=self._engine_name)
        self._worker = threading.Thread(target=self._loop, daemon=True)
        self._worker.start()

    def _loop(self) -> None:
        while self._alive:
            cmd = self._cmd_queue.get()
            if cmd is None:
                break
            if self._session is not None:
                cont = self._session.handle_command(cmd)
                if not cont:
                    break
        self._alive = False

    def send_line(self, command: str) -> None:
        if not self._alive:
            raise RuntimeError("In-process UCI engine is not running.")
        if command.strip() == "stop" and self._session is not None:
            self._session.stop_search()
            return
        self._cmd_queue.put(command)

    def is_alive(self) -> bool:
        return self._alive

    def close(self) -> None:
        self._alive = False
        if self._session is not None:
            self._session.stop_search()
        self._cmd_queue.put(None)
        if self._worker is not None and self._worker.is_alive():
            self._worker.join(timeout=0.5)


def parse_uci_info_line(line: str, root_board: chess.Board) -> Optional[CandidateVariation]:
    """
    Parse a Stockfish `info ...` line into a `CandidateVariation`, normalizing the score
    and converting the UCI principal variation into SAN moves on `root_board`.
    """
    if not line.startswith("info ") or " score " not in line or " pv " not in line:
        return None
    if "upperbound" in line or "lowerbound" in line:
        # Ignore aspiration window partial bounds unless main pv
        pass

    tokens = line.split()
    depth = 1
    seldepth = 1
    multipv = 1
    nodes = 0
    nps = 0
    time_ms = 0
    raw_cp: Optional[int] = None
    raw_mate: Optional[int] = None
    pv_uci: List[str] = []

    i = 1
    while i < len(tokens):
        tok = tokens[i]
        if tok == "depth" and i + 1 < len(tokens):
            depth = int(tokens[i + 1])
            i += 2
        elif tok == "seldepth" and i + 1 < len(tokens):
            seldepth = int(tokens[i + 1])
            i += 2
        elif tok == "multipv" and i + 1 < len(tokens):
            multipv = int(tokens[i + 1])
            i += 2
        elif tok == "nodes" and i + 1 < len(tokens):
            nodes = int(tokens[i + 1])
            i += 2
        elif tok == "nps" and i + 1 < len(tokens):
            nps = int(tokens[i + 1])
            i += 2
        elif tok == "time" and i + 1 < len(tokens):
            time_ms = int(tokens[i + 1])
            i += 2
        elif tok == "score" and i + 2 < len(tokens):
            kind = tokens[i + 1]
            val = int(tokens[i + 2])
            if kind == "cp":
                raw_cp = val
            elif kind == "mate":
                raw_mate = val
            i += 3
        elif tok == "pv":
            pv_uci = tokens[i + 1 :]
            break
        else:
            i += 1

    pov_color = "white" if root_board.turn == chess.WHITE else "black"
    score = EngineScore(raw_cp_pov=raw_cp, raw_mate_pov=raw_mate, pov_color=pov_color)

    # Convert pv_uci to SAN safely
    pv_san: List[str] = []
    b_copy = root_board.copy()
    valid_uci: List[str] = []
    for uci_mv in pv_uci:
        try:
            mv = chess.Move.from_uci(uci_mv)
            if mv in b_copy.legal_moves:
                pv_san.append(b_copy.san(mv))
                valid_uci.append(uci_mv)
                b_copy.push(mv)
            else:
                break
        except ValueError:
            break

    return CandidateVariation(
        multipv_index=multipv,
        score=score,
        depth=depth,
        seldepth=seldepth,
        pv_uci=valid_uci,
        pv_san=pv_san,
        nodes=nodes,
        nps=nps,
        time_ms=time_ms,
    )


class UCIProcessClient:
    """
    Manages the full lifecycle of a single Stockfish UCI engine instance:
    - Handshake (`uci` -> `uciok`, `isready` -> `readyok`)
    - Option detection and configuration (`MultiPV`, `Threads`, `Hash`)
    - Position setup and `go` search execution
    - Generation-tagged result callbacks so stale searches never overwrite current position results
    - Automatic crash recovery
    """

    def __init__(
        self,
        engine_id: str,
        display_name: str,
        binary_path: str,
        transport_type: str = "subprocess",
        on_update: Optional[Callable[[str, int, Dict[int, CandidateVariation], bool, Optional[str]], None]] = None,
    ) -> None:
        self.engine_id = engine_id
        self.display_name = display_name
        self.binary_path = binary_path
        self.transport_type = transport_type
        self._on_update = on_update

        self._transport: Optional[UCITransport] = None
        self._uci_ok_event = threading.Event()
        self._ready_ok_event = threading.Event()
        self._bestmove_event = threading.Event()
        self._lock = threading.Lock()

        self.detected_name: str = display_name
        self.supported_options: Dict[str, str] = {}
        self._current_search_id: int = 0
        self._active_board: chess.Board = chess.Board()
        self._variations_by_idx: Dict[int, CandidateVariation] = {}
        self._last_bestmove: Optional[str] = None
        self._crashed_count: int = 0

    def start(self, timeout: float = 5.0) -> bool:
        """Start transport and perform UCI handshake."""
        if self._transport is not None and self._transport.is_alive():
            return True

        self._uci_ok_event.clear()
        self._ready_ok_event.clear()

        if self.transport_type == "subprocess":
            self._transport = SubprocessUCITransport(
                binary_path=self.binary_path,
                on_line=self._handle_stdout_line,
                on_exit=self._handle_process_exit,
            )
        else:
            self._transport = InProcessUCITransport(
                engine_name=self.display_name,
                on_line=self._handle_stdout_line,
                on_exit=self._handle_process_exit,
            )

        self._transport.start()
        self._transport.send_line("uci")
        if not self._uci_ok_event.wait(timeout=timeout):
            self.stop_process()
            raise TimeoutError(f"Engine '{self.display_name}' failed UCI handshake within {timeout}s.")

        self._transport.send_line("isready")
        if not self._ready_ok_event.wait(timeout=timeout):
            self.stop_process()
            raise TimeoutError(f"Engine '{self.display_name}' failed isready check.")
        return True

    def _handle_stdout_line(self, line: str) -> None:
        if line == "uciok":
            self._uci_ok_event.set()
            return
        if line == "readyok":
            self._ready_ok_event.set()
            return
        if line.startswith("id name "):
            self.detected_name = line[len("id name ") :].strip()
            return
        if line.startswith("option name "):
            parts = line.split()
            if "type" in parts:
                t_idx = parts.index("type")
                opt_name = " ".join(parts[2:t_idx])
                opt_type = parts[t_idx + 1] if t_idx + 1 < len(parts) else "string"
                self.supported_options[opt_name] = opt_type
            return

        if line.startswith("info "):
            with self._lock:
                search_id = self._current_search_id
                board_copy = self._active_board.copy()
            cand = parse_uci_info_line(line, board_copy)
            if cand is not None:
                with self._lock:
                    if search_id != self._current_search_id:
                        return  # Ignore stale info line
                    self._variations_by_idx[cand.multipv_index] = cand
                    snapshot = dict(self._variations_by_idx)
                if self._on_update:
                    self._on_update(self.engine_id, search_id, snapshot, False, None)
            return

        if line.startswith("bestmove "):
            parts = line.split()
            bm = parts[1] if len(parts) > 1 else "(none)"
            with self._lock:
                search_id = self._current_search_id
                self._last_bestmove = bm
                for v in self._variations_by_idx.values():
                    v.is_complete = True
                snapshot = dict(self._variations_by_idx)
            self._bestmove_event.set()
            if self._on_update:
                self._on_update(self.engine_id, search_id, snapshot, True, bm)

    def _handle_process_exit(self, return_code: int) -> None:
        self._crashed_count += 1
        self._bestmove_event.set()

    def ensure_ready(self, timeout: float = 3.0) -> None:
        if self._transport is None or not self._transport.is_alive():
            self.start(timeout=timeout)
            return
        self._ready_ok_event.clear()
        self._transport.send_line("isready")
        if not self._ready_ok_event.wait(timeout=timeout):
            # Restart failed process safely (Section 7.3 item 9)
            self.stop_process()
            self.start(timeout=timeout)

    def cancel_search(self, wait_timeout: float = 0.5) -> None:
        """Stop an ongoing search cleanly."""
        if self._transport is not None and self._transport.is_alive():
            try:
                self._transport.send_line("stop")
                self._bestmove_event.wait(timeout=wait_timeout)
            except Exception:
                pass

    def start_search(
        self,
        search_id: int,
        fen: str,
        multipv: int = 1,
        threads: int = 1,
        hash_mb: int = 16,
        max_depth: Optional[int] = 10,
        movetime_ms: Optional[int] = None,
        infinite: bool = False,
    ) -> None:
        """Configure UCI options, send position, and start an asynchronous search."""
        self.cancel_search(wait_timeout=0.3)
        self.ensure_ready()
        assert self._transport is not None

        board = chess.Board(fen)
        legal_count = board.legal_moves.count()

        with self._lock:
            self._current_search_id = search_id
            self._active_board = board
            self._variations_by_idx.clear()
            self._last_bestmove = None
            self._bestmove_event.clear()

        if legal_count == 0:
            # Terminal position (checkmate or stalemate): no legal moves exist
            self._bestmove_event.set()
            if self._on_update:
                self._on_update(self.engine_id, search_id, {}, True, "(none)")
            return

        effective_multipv = max(1, min(multipv, legal_count, 5))
        self._transport.send_line(f"setoption name Threads value {max(1, threads)}")
        self._transport.send_line(f"setoption name Hash value {max(1, hash_mb)}")
        self._transport.send_line(f"setoption name MultiPV value {effective_multipv}")
        self._ready_ok_event.clear()
        self._transport.send_line("isready")
        self._ready_ok_event.wait(timeout=2.0)

        self._transport.send_line(f"position fen {fen}")

        if infinite:
            go_cmd = "go infinite"
        elif movetime_ms is not None:
            go_cmd = f"go movetime {movetime_ms}"
            if max_depth is not None:
                go_cmd += f" depth {max_depth}"
        else:
            d = max_depth or 10
            go_cmd = f"go depth {d}"

        self._transport.send_line(go_cmd)

    def wait_for_search_completion(self, timeout: float = 10.0) -> Dict[int, CandidateVariation]:
        self._bestmove_event.wait(timeout=timeout)
        with self._lock:
            return dict(self._variations_by_idx)

    def stop_process(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None
