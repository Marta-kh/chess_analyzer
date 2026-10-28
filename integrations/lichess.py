"""
Official Lichess REST API integration (Section 10).
Supports public game export via https://lichess.org/api/games/user/{username}
with bounded count/date filters, NDJSON + raw PGN parsing, and rate-limit/error handling.
"""
from datetime import datetime, timezone
import json
from typing import Any, Callable, Dict, List, Optional
import requests
from chess_analyzer.domain.game_session import GameSession
from .chesscom import ExternalGameSummary, IntegrationError, RateLimitError, validate_username
from .pgn_importer import PGNImporter


class LichessClient:
    """Read-only client for the official Lichess public game export API."""

    BASE_URL = "https://lichess.org/api"
    USER_AGENT = "PythonChessAnalyzerMobile/1.0 (Contact: local-chess-analyzer; Python/requests)"

    def __init__(
        self,
        http_get: Optional[Callable[..., requests.Response]] = None,
        timeout: float = 12.0,
    ) -> None:
        self._get = http_get or requests.get
        self._timeout = timeout

    def fetch_user_games(
        self,
        username: str,
        max_games: int = 20,
        since_ms: Optional[int] = None,
        until_ms: Optional[int] = None,
        perf_type: Optional[str] = None,
    ) -> List[ExternalGameSummary]:
        """
        Retrieve public games for `username` using NDJSON (`Accept: application/x-ndjson` with `pgnInJson=true`),
        with automatic fallback to multi-game PGN parsing if raw PGN is returned.
        """
        clean = validate_username(username)
        params: Dict[str, Any] = {
            "max": max(1, min(50, max_games)),
            "pgnInJson": "true",
            "clocks": "false",
            "evals": "false",
            "opening": "true",
        }
        if since_ms is not None:
            params["since"] = int(since_ms)
        if until_ms is not None:
            params["until"] = int(until_ms)
        if perf_type:
            params["perfType"] = perf_type

        url = f"{self.BASE_URL}/games/user/{clean}"
        try:
            resp = self._get(
                url,
                params=params,
                headers={
                    "User-Agent": self.USER_AGENT,
                    "Accept": "application/x-ndjson",
                },
                timeout=self._timeout,
            )
        except requests.Timeout as exc:
            raise IntegrationError("Lichess API request timed out. Please check your internet connection and retry.") from exc
        except requests.RequestException as exc:
            raise IntegrationError(f"Network error contacting Lichess: {exc}") from exc

        if resp.status_code == 404:
            raise IntegrationError(f"Lichess user '{clean}' not found (HTTP 404).")
        if resp.status_code == 429:
            raise RateLimitError("Lichess API rate limit reached (HTTP 429). Please wait before retrying.")
        if resp.status_code >= 400:
            raise IntegrationError(f"Lichess API returned HTTP {resp.status_code}.")

        text = (resp.text or "").strip()
        if not text:
            return []

        summaries: List[ExternalGameSummary] = []
        for line in text.splitlines():
            line_s = line.strip()
            if not line_s or not line_s.startswith("{"):
                continue
            try:
                obj = json.loads(line_s)
            except ValueError:
                continue
            pgn = obj.get("pgn")
            if not pgn:
                # Reconstruct minimal PGN if moves field is present without pgn
                moves_str = obj.get("moves", "")
                if not moves_str:
                    continue
                pgn = f'[Event "Lichess Game"]\n\n{moves_str} *'

            game_id = obj.get("id", "")
            players = obj.get("players", {})
            w_info = players.get("white", {})
            b_info = players.get("black", {})
            w_user = w_info.get("user", {}).get("name") or w_info.get("user", {}).get("id") or "White"
            b_user = b_info.get("user", {}).get("name") or b_info.get("user", {}).get("id") or "Black"
            is_white = w_user.lower() == clean.lower()
            player_color = "white" if is_white else "black"
            opponent = b_user if is_white else w_user

            winner = obj.get("winner")
            if winner == "white":
                result_str = "1-0"
            elif winner == "black":
                result_str = "0-1"
            elif obj.get("status") in ("draw", "stalemate", "outoftime", "repetition"):
                result_str = "1/2-1/2"
            else:
                result_str = "*"

            created_at = obj.get("createdAt")
            played_iso = (
                datetime.fromtimestamp(created_at / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
                if isinstance(created_at, (int, float))
                else "Recent"
            )
            clock = obj.get("clock", {})
            tc_str = (
                f"{clock.get('initial', 0) // 60}+{clock.get('increment', 0)}"
                if clock
                else str(obj.get("speed", "-"))
            )

            summaries.append(
                ExternalGameSummary(
                    external_id=game_id,
                    source="lichess",
                    url=f"https://lichess.org/{game_id}",
                    white_username=w_user,
                    black_username=b_user,
                    white_rating=w_info.get("rating"),
                    black_rating=b_info.get("rating"),
                    player_username=clean,
                    player_color=player_color,
                    opponent_username=opponent,
                    result=result_str,
                    played_at_iso=played_iso,
                    time_control=tc_str,
                    time_class=str(obj.get("perf", obj.get("speed", "standard"))),
                    rules=str(obj.get("variant", "standard")),
                    pgn=pgn,
                )
            )

        # Fallback: if response was multi-game PGN text rather than NDJSON
        if not summaries and "[Event " in text:
            try:
                parsed_games = PGNImporter.parse_pgn_text(text)
                for idx, pg in enumerate(parsed_games):
                    h = pg.headers
                    w_user = h.get("White", "White")
                    b_user = h.get("Black", "Black")
                    is_white = w_user.lower() == clean.lower()
                    summaries.append(
                        ExternalGameSummary(
                            external_id=h.get("Site", f"lichess_{idx}").split("/")[-1],
                            source="lichess",
                            url=h.get("Site", "https://lichess.org"),
                            white_username=w_user,
                            black_username=b_user,
                            white_rating=int(h["WhiteElo"]) if h.get("WhiteElo", "").isdigit() else None,
                            black_rating=int(h["BlackElo"]) if h.get("BlackElo", "").isdigit() else None,
                            player_username=clean,
                            player_color="white" if is_white else "black",
                            opponent_username=b_user if is_white else w_user,
                            result=h.get("Result", "*"),
                            played_at_iso=h.get("UTCDate", "Recent"),
                            time_control=h.get("TimeControl", "-"),
                            time_class=h.get("Event", "standard"),
                            rules=h.get("Variant", "standard"),
                            pgn=pg.raw_pgn,
                        )
                    )
            except Exception:
                pass

        return summaries

    def import_selected_game(
        self,
        summary: ExternalGameSummary,
        global_imported_classification_default: bool = True,
    ) -> GameSession:
        return PGNImporter.import_to_session(
            pgn_text=summary.pgn,
            source="lichess",
            external_id=summary.external_id,
            external_url=summary.url,
            player_username=summary.player_username,
            time_control=summary.time_control,
            game_type=f"{summary.time_class} ({summary.rules})",
            global_imported_classification_default=global_imported_classification_default,
        )
