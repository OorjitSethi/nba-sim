from __future__ import annotations

from typing import Any

from nba_sim.domain.events import Event, EventLog, EventType
from nba_sim.domain.rules import Ruleset
from nba_sim.domain.state import GameState


class EventEmitter:
    """Append an event and immediately reduce it into live game state."""

    def __init__(self, state: GameState, rules: Ruleset) -> None:
        self.state = state
        self.rules = rules
        self.log = EventLog()

    def emit(
        self,
        event_type: EventType,
        *,
        team: str | None = None,
        player_id: int | None = None,
        related_player_id: int | None = None,
        points: int = 0,
        period: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Event:
        event = Event(
            sequence=len(self.log),
            event_type=event_type,
            period=self.state.period if period is None else period,
            period_clock_ms=self.state.period_clock_ms,
            team=team,
            player_id=player_id,
            related_player_id=related_player_id,
            points=points,
            payload={} if payload is None else payload,
        )
        self.log.append(event)
        self.state.apply(event, self.rules)
        return event

    def advance_clock(self, elapsed_seconds: float) -> int:
        if elapsed_seconds < 0:
            raise ValueError("elapsed time cannot be negative")
        elapsed_ms = min(
            self.state.period_clock_ms,
            max(0, int(round(elapsed_seconds * 1_000))),
        )
        if elapsed_ms:
            self.emit(
                EventType.CLOCK_ADVANCED,
                payload={"elapsed_ms": elapsed_ms},
            )
        return elapsed_ms
