"""Selective Game Review event identification (Chess.com-inspired key moments).

Identifies high-signal events (Brilliant, Great, Blunder, Mistake, Inaccuracy, Miss,
critical defensive saves, turning points, and end of opening book) while suppressing
routine Best/Excellent/Good moves so the summary stays focused and readable.
"""
from dataclasses import dataclass
from typing import List
from .move_classifier import MoveClassification, MoveQuality


@dataclass(frozen=True)
class KeyGameEvent:
    """A high-significance game review moment."""
    ply: int
    move_number: int
    mover_color: str
    played_san: str
    played_uci: str
    quality: MoveQuality
    event_type: str
    importance_score: float
    expected_points_loss: float
    best_move_san: str
    description: str


class GameEventSelector:
    """Filters and ranks important game moments without re-running Stockfish."""

    ROUTINE_QUALITIES = {
        MoveQuality.BEST,
        MoveQuality.EXCELLENT,
        MoveQuality.GOOD,
        MoveQuality.FORCED,
        MoveQuality.INSUFFICIENT_DATA,
    }

    def select_events(
        self,
        classifications: List[MoveClassification],
        player_filter: str = "both",  # "both", "white", "black"
        density: str = "standard",    # "compact" (max 8), "standard" (max 16), "detailed" (all key events)
    ) -> List[KeyGameEvent]:
        events: List[KeyGameEvent] = []
        last_book_ply = 0
        for c in classifications:
            if c.quality == MoveQuality.BOOK:
                last_book_ply = c.ply

        for c in classifications:
            mover = c.mover_color.lower()
            if player_filter == "white" and mover != "white":
                continue
            if player_filter == "black" and mover != "black":
                continue

            move_num = (c.ply + 1) // 2
            ep_loss = getattr(c, "expected_points_loss", c.win_prob_loss)
            best_san = c.best_move_san or c.best_move_uci or ""

            # End-of-book transition marker
            if last_book_ply > 0 and c.ply == last_book_ply + 1 and c.quality in self.ROUTINE_QUALITIES:
                events.append(
                    KeyGameEvent(
                        ply=c.ply,
                        move_number=move_num,
                        mover_color=mover,
                        played_san=c.played_san,
                        played_uci=c.played_uci,
                        quality=c.quality,
                        event_type="Opening Transition",
                        importance_score=0.35,
                        expected_points_loss=ep_loss,
                        best_move_san=best_san,
                        description=f"Left opening book with {c.played_san}.",
                    )
                )
                continue

            if c.quality in self.ROUTINE_QUALITIES or c.quality == MoveQuality.BOOK:
                continue

            base_importance = {
                MoveQuality.BRILLIANT: 1.00,
                MoveQuality.GREAT: 0.85,
                MoveQuality.BLUNDER: 0.95,
                MoveQuality.MISSED_WIN: 0.88,
                MoveQuality.MISTAKE: 0.72,
                MoveQuality.INACCURACY: 0.45,
            }.get(c.quality, 0.50)

            importance = min(1.0, base_importance + 0.35 * ep_loss)
            if c.quality == MoveQuality.BRILLIANT:
                ev_type = "Brilliant Sacrifice / Resource"
            elif c.quality == MoveQuality.GREAT:
                ev_type = "Critical Move / Defensive Save"
            elif c.quality == MoveQuality.BLUNDER:
                ev_type = "Turning Point (Blunder)" if ep_loss >= 0.30 else "Blunder"
            elif c.quality == MoveQuality.MISSED_WIN:
                ev_type = "Missed Tactical Opportunity"
            elif c.quality == MoveQuality.MISTAKE:
                ev_type = "Mistake"
            else:
                ev_type = "Inaccuracy"

            events.append(
                KeyGameEvent(
                    ply=c.ply,
                    move_number=move_num,
                    mover_color=mover,
                    played_san=c.played_san,
                    played_uci=c.played_uci,
                    quality=c.quality,
                    event_type=ev_type,
                    importance_score=importance,
                    expected_points_loss=ep_loss,
                    best_move_san=best_san,
                    description=c.explanation,
                )
            )

        if density == "compact":
            ranked = sorted(events, key=lambda e: (-e.importance_score, e.ply))[:8]
            return sorted(ranked, key=lambda e: e.ply)
        elif density == "standard":
            ranked = sorted(events, key=lambda e: (-e.importance_score, e.ply))[:16]
            return sorted(ranked, key=lambda e: e.ply)
        return events
