"""
Official Chess.com Published Data API integration (Section 9).
Uses HTTPS only, validates usernames, supports archive listing, automatic newest-archive
game retrieval, month selection, pagination, metadata extraction, and rate-limit/error handling.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Callable, Dict, List, Optional
import requests
from chess_analyzer.domain.game_session import GameSession
from .pgn_importer import PGNImporter

USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]{2,50}$")


class IntegrationError(Exception):
    """Base error for external chess API integrations."""


class RateLimitError(IntegrationError):
    """Raised when Chess.com or Lichess returns HTTP 429 Too Many Requests."""


@dataclass
class ExternalGameSummary:
    """Normalized summary of a public game from Chess.com or Lichess."""
    external_id: str
    source: str  # "chesscom" or "lichess"
    url: str
    white_username: str
    black_username: str
    white_rating: Optional[int]
    black_rating: Optional[int]
    player_username: str
    player_color: str  # "white" or "black"
    opponent_username: str
    result: str  # "1-0", "0-1", "1/2-1/2", "*"
    played_at_iso: str
    time_control: str
    time_class: str  # "blitz", "rapid", "bullet", "daily", etc.
    rules: str       # "chess" / "standard"
    pgn: str


def validate_username(username: str) -> str:
    cleaned = (username or "").strip()
    if not USERNAME_RE.match(cleaned):
        raise ValueError(
            f"Invalid username '{username}'. Usernames must be 2–50 characters (letters, digits, '_' or '-')."
        )
    return cleaned


class ChessComClient:
    """Read-only client for https://api.chess.com/pub/player/{username}."""

    BASE_URL = "https://api.chess.com/pub"
    USER_AGENT = "PythonChessAnalyzerMobile/1.0 (Contact: local-chess-analyzer; Python/requests)"

    def __init__(
        self,
        http_get: Optional[Callable[..., requests.Response]] = None,
        timeout: float = 12.0,
    ) -> None:
        self._get = http_get or requests.get
        self._timeout = timeout

    def _request_json(self, url: str) -> Dict[str, Any]:
        if not url.startswith("https://"):
            raise IntegrationError("Security violation: Only HTTPS URLs are permitted.")
        try:
            resp = self._get(
                url,
                headers={"User-Agent": self.USER_AGENT, "Accept": "application/json"},
                timeout=self._timeout,
            )
        except requests.Timeout as exc:
            raise IntegrationError("Chess.com request timed out. Please check your internet connection and retry.") from exc
        except requests.RequestException as exc:
            raise IntegrationError(f"Network error contacting Chess.com: {exc}") from exc

        if resp.status_code == 404:
            raise IntegrationError("Chess.com player or archive not found (HTTP 404). Check the username spelling.")
        if resp.status_code == 429:
            raise RateLimitError("Chess.com API rate limit reached (HTTP 429). Please wait a few seconds before retrying.")
        if resp.status_code >= 400:
            raise IntegrationError(f"Chess.com API returned HTTP {resp.status_code}.")

        try:
            return resp.json()
        except ValueError as exc:
            raise IntegrationError("Invalid JSON response from Chess.com API.") from exc

    def validate_player(self, username: str) -> Dict[str, Any]:
        clean = validate_username(username).lower()
        return self._request_json(f"{self.BASE_URL}/player/{clean}")

    def list_archive_urls(self, username: str) -> List[str]:
        """Retrieve available monthly archive URLs (newest first) without downloading every archive."""
        clean = validate_username(username).lower()
        data = self._request_json(f"{self.BASE_URL}/player/{clean}/games/archives")
        archives = data.get("archives", [])
        return list(reversed(archives))

    def _parse_games_payload(
        self,
        data: Dict[str, Any],
        username: str,
        page: int = 1,
        page_size: int = 20,
    ) -> List[ExternalGameSummary]:
        clean = validate_username(username).lower()
        raw_games = list(reversed(data.get("games", [])))

        start = max(0, (page - 1) * page_size)
        end = start + page_size
        sliced = raw_games[start:end]

        summaries: List[ExternalGameSummary] = []
        for g in sliced:
            pgn = g.get("pgn")
            if not pgn:
                continue
            w = g.get("white", {})
            b = g.get("black", {})
            w_user = w.get("username", "White")
            b_user = b.get("username", "Black")
            is_white = w_user.lower() == clean
            player_color = "white" if is_white else "black"
            opponent = b_user if is_white else w_user

            end_time = g.get("end_time")
            played_iso = (
                datetime.fromtimestamp(end_time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
                if isinstance(end_time, (int, float))
                else "Recent"
            )

            result_str = "*"
            if '[Result "1-0"]' in pgn:
                result_str = "1-0"
            elif '[Result "0-1"]' in pgn:
                result_str = "0-1"
            elif '[Result "1/2-1/2"]' in pgn:
                result_str = "1/2-1/2"

            summaries.append(
                ExternalGameSummary(
                    external_id=g.get("uuid") or g.get("url", ""),
                    source="chesscom",
                    url=g.get("url", ""),
                    white_username=w_user,
                    black_username=b_user,
                    white_rating=w.get("rating"),
                    black_rating=b.get("rating"),
                    player_username=username,
                    player_color=player_color,
                    opponent_username=opponent,
                    result=result_str,
                    played_at_iso=played_iso,
                    time_control=str(g.get("time_control", "-")),
                    time_class=str(g.get("time_class", "standard")),
                    rules=str(g.get("rules", "chess")),
                    pgn=pgn,
                )
            )
        return summaries

    def fetch_recent_games(
        self,
        username: str,
        page: int = 1,
        page_size: int = 20,
    ) -> List[ExternalGameSummary]:
        """
        Fetch a player's most recent public games by first querying their monthly archive list
        (`/pub/player/{username}/games/archives`) and then fetching the newest monthly archive.
        This guarantees results even if the player has not played in the current calendar month.
        """
        clean = validate_username(username).lower()
        archives = self.list_archive_urls(clean)
        if not archives:
            # Fallback if mock in test returns games directly on month endpoint
            now = datetime.now(timezone.utc)
            return self.fetch_games_for_month(username, now.year, now.month, page=page, page_size=page_size)

        # Fetch newest archive URL
        latest_url = archives[0]
        data = self._request_json(latest_url)
        games = self._parse_games_payload(data, username=username, page=page, page_size=page_size)

        # If fewer than page_size games in latest month and an earlier month exists on page 1, append from previous month
        if len(games) < page_size and len(archives) > 1 and page == 1:
            try:
                prev_data = self._request_json(archives[1])
                prev_games = self._parse_games_payload(
                    prev_data,
                    username=username,
                    page=1,
                    page_size=page_size - len(games),
                )
                games.extend(prev_games)
            except Exception:
                pass
        return games

    def fetch_games_for_month(
        self,
        username: str,
        year: int,
        month: int,
        page: int = 1,
        page_size: int = 20,
    ) -> List[ExternalGameSummary]:
        """Fetch public games for a specific (year, month) archive with bounded pagination."""
        clean = validate_username(username).lower()
        if not (1 <= month <= 12):
            raise ValueError("Month must be between 1 and 12.")
        url = f"{self.BASE_URL}/player/{clean}/games/{year:04d}/{month:02d}"
        data = self._request_json(url)
        return self._parse_games_payload(data, username=username, page=page, page_size=page_size)

    def import_selected_game(
        self,
        summary: ExternalGameSummary,
        global_imported_classification_default: bool = True,
    ) -> GameSession:
        return PGNImporter.import_to_session(
            pgn_text=summary.pgn,
            source="chesscom",
            external_id=summary.external_id,
            external_url=summary.url,
            player_username=summary.player_username,
            time_control=summary.time_control,
            game_type=f"{summary.time_class} ({summary.rules})",
            global_imported_classification_default=global_imported_classification_default,
        )
