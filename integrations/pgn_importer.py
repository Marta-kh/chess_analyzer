"""Robust PGN parser converting PGN strings into ParsedPGNGame and GameSession instances."""
from dataclasses import dataclass
import io
from typing import Dict, List, Optional
import chess
import chess.pgn
from chess_analyzer.domain.game_session import GameSession, SessionMetadata


@dataclass
class ParsedPGNGame:
    initial_fen: str
    uci_moves: List[str]
    headers: Dict[str, str]
    raw_pgn: str
    errors: List[str]


class PGNImporter:
    """Parses standard and custom-FEN PGN strings with strict validation."""

    @staticmethod
    def parse_pgn_text(pgn_text: str) -> List[ParsedPGNGame]:
        if not pgn_text or not pgn_text.strip():
            raise ValueError("PGN input is empty.")

        stream = io.StringIO(pgn_text.strip())
        results: List[ParsedPGNGame] = []

        while True:
            game = chess.pgn.read_game(stream)
            if game is None:
                break

            headers = dict(game.headers)
            errors = [str(e) for e in game.errors]
            try:
                board = game.board()
                initial_fen = board.fen()
            except ValueError as exc:
                raise ValueError(f"Invalid FEN in PGN header: {exc}") from exc

            uci_moves: List[str] = []
            for move in game.mainline_moves():
                if move not in board.legal_moves:
                    raise ValueError(f"Illegal move '{move.uci()}' encountered in PGN.")
                uci_moves.append(move.uci())
                board.push(move)

            # Validate that non-header PGN actually contained recognizable chess content or headers
            if not uci_moves and not headers.get("FEN") and len(headers) <= 1:
                raise ValueError("Malformed or unrecognizable PGN content.")

            exporter = chess.pgn.StringExporter(headers=True, variations=True, comments=True)
            raw_game_pgn = game.accept(exporter).strip()

            results.append(
                ParsedPGNGame(
                    initial_fen=initial_fen,
                    uci_moves=uci_moves,
                    headers=headers,
                    raw_pgn=raw_game_pgn,
                    errors=errors,
                )
            )

        if not results:
            raise ValueError("No valid PGN game found in input.")
        return results

    @classmethod
    def import_to_session(
        cls,
        pgn_text: str,
        source: str = "pgn",
        external_id: Optional[str] = None,
        external_url: Optional[str] = None,
        player_username: Optional[str] = None,
        time_control: Optional[str] = None,
        game_type: str = "standard",
        global_imported_classification_default: bool = True,
    ) -> GameSession:
        parsed_list = cls.parse_pgn_text(pgn_text)
        parsed = parsed_list[0]
        h = parsed.headers

        white_name = h.get("White", "White")
        black_name = h.get("Black", "Black")
        player_color = None
        if player_username:
            u_low = player_username.strip().lower()
            if white_name.lower() == u_low:
                player_color = "white"
            elif black_name.lower() == u_low:
                player_color = "black"

        def _parse_int(val: Optional[str]) -> Optional[int]:
            if not val:
                return None
            try:
                return int(val)
            except ValueError:
                return None

        meta = SessionMetadata(
            title=f"{white_name} vs {black_name}",
            white_player=white_name,
            black_player=black_name,
            white_elo=_parse_int(h.get("WhiteElo")),
            black_elo=_parse_int(h.get("BlackElo")),
            event=h.get("Event", "Imported Game"),
            site=h.get("Site", source),
            date=h.get("UTCDate") or h.get("Date", "????.??.??"),
            result=h.get("Result", "*"),
            time_control=time_control or h.get("TimeControl", "-"),
            game_type=game_type or h.get("Variant", "standard"),
            source=source,
            external_id=external_id,
            external_url=external_url or h.get("Link") or h.get("Site"),
            player_username=player_username,
            player_color=player_color,
        )

        return GameSession.create_imported(
            initial_fen=parsed.initial_fen,
            uci_moves=parsed.uci_moves,
            metadata=meta,
            original_pgn=pgn_text.strip(),
            global_imported_classification_default=global_imported_classification_default,
        )
