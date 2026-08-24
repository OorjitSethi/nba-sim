from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Iterator, Mapping


class EventType(str, Enum):
    GAME_STARTED = "game_started"
    PERIOD_STARTED = "period_started"
    POSSESSION_STARTED = "possession_started"
    CLOCK_ADVANCED = "clock_advanced"
    SHOT_ATTEMPT = "shot_attempt"
    SHOT_MADE = "shot_made"
    SHOT_MISSED = "shot_missed"
    ASSIST = "assist"
    BLOCK = "block"
    FOUL = "foul"
    FREE_THROW_MADE = "free_throw_made"
    FREE_THROW_MISSED = "free_throw_missed"
    OFFENSIVE_REBOUND = "offensive_rebound"
    DEFENSIVE_REBOUND = "defensive_rebound"
    TURNOVER = "turnover"
    STEAL = "steal"
    POSSESSION_CHANGED = "possession_changed"
    SUBSTITUTION = "substitution"
    PERIOD_ENDED = "period_ended"
    GAME_ENDED = "game_ended"


class FrozenMapping(Mapping[str, Any]):
    """Small pickle-safe immutable mapping for event payloads."""

    def __init__(self, values: Mapping[str, Any] | None = None) -> None:
        self._values = dict(values or {})

    def __getitem__(self, key: str) -> Any:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __reduce__(self) -> tuple[object, tuple[dict[str, Any]]]:
        return FrozenMapping, (self._values,)


@dataclass(frozen=True)
class Event:
    sequence: int
    event_type: EventType
    period: int
    period_clock_ms: int
    team: str | None = None
    player_id: int | None = None
    related_player_id: int | None = None
    points: int = 0
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("event sequence cannot be negative")
        if self.period <= 0:
            raise ValueError("event period must be positive")
        if self.period_clock_ms < 0:
            raise ValueError("event clock cannot be negative")
        if self.points < 0:
            raise ValueError("event points cannot be negative")
        object.__setattr__(self, "payload", FrozenMapping(self.payload))

    def as_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "event_type": self.event_type.value,
            "period": self.period,
            "period_clock_ms": self.period_clock_ms,
            "team": self.team,
            "player_id": self.player_id,
            "related_player_id": self.related_player_id,
            "points": self.points,
            "payload": dict(self.payload),
        }


class EventLog:
    def __init__(self, events: Iterable[Event] = ()) -> None:
        self._events: list[Event] = []
        for event in events:
            self.append(event)

    def append(self, event: Event) -> None:
        if event.sequence != len(self._events):
            raise ValueError(
                f"expected event sequence {len(self._events)}, got {event.sequence}"
            )
        self._events.append(event)

    def __len__(self) -> int:
        return len(self._events)

    def __iter__(self) -> Iterator[Event]:
        return iter(self._events)

    def __getitem__(self, index: int) -> Event:
        return self._events[index]

    def types(self) -> tuple[EventType, ...]:
        return tuple(event.event_type for event in self._events)

    def as_records(self) -> list[dict[str, Any]]:
        return [event.as_dict() for event in self._events]
