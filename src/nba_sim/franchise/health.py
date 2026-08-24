from __future__ import annotations

import math
from dataclasses import replace
from datetime import date
from typing import Iterable

from nba_sim.franchise.models import (
    PlayerHealthRecord,
    PlayerLifecycleRecord,
    PlayerRecord,
)


HEALTH_MODEL_VERSION = "nba-health-workload.v1"
AVAILABILITY_STATES = (
    "available",
    "managed",
    "questionable",
    "doubtful",
    "out",
)


def build_health_record(
    player: PlayerRecord,
    *,
    lifecycle: PlayerLifecycleRecord | None,
    as_of: date,
) -> PlayerHealthRecord:
    if lifecycle is not None and lifecycle.games_played > 0:
        average_game_minutes = (
            lifecycle.workload_minutes / lifecycle.games_played
        )
        weekly_game_load = average_game_minutes * 3.4
        confidence = lifecycle.confidence
        source = "prior-season-game-minutes"
    else:
        weekly_game_load = max(0.0, player.expected_minutes * 3.4)
        confidence = "low"
        source = "projected-role-prior"
    acute = weekly_game_load
    chronic = weekly_game_load * 4.0
    concern = load_concern_index(
        acute_load=acute,
        chronic_load=chronic,
        fatigue=0.0,
        availability="available",
    )
    return PlayerHealthRecord(
        player_id=player.player_id,
        as_of_date=as_of,
        availability="available",
        body_area="",
        detail="",
        expected_return=None,
        minute_limit=None,
        acute_load=acute,
        chronic_load=chronic,
        fatigue=0.0,
        readiness=100.0,
        load_concern=concern,
        last_load_date=None,
        confidence=confidence,
        source=source,
        model_version=HEALTH_MODEL_VERSION,
    )


def advance_health_record(
    record: PlayerHealthRecord,
    *,
    target: date,
) -> PlayerHealthRecord:
    days = (target - record.as_of_date).days
    if days < 0:
        raise ValueError("health state cannot move backward")
    if days == 0:
        return record
    acute = record.acute_load * math.exp(-days / 7.0)
    chronic = record.chronic_load * math.exp(-days / 28.0)
    fatigue = record.fatigue * math.exp(-days / 2.5)
    readiness = _readiness(
        fatigue=fatigue,
        availability=record.availability,
    )
    return replace(
        record,
        as_of_date=target,
        acute_load=acute,
        chronic_load=chronic,
        fatigue=fatigue,
        readiness=readiness,
        load_concern=load_concern_index(
            acute_load=acute,
            chronic_load=chronic,
            fatigue=fatigue,
            availability=record.availability,
        ),
    )


def advance_health_records(
    records: Iterable[PlayerHealthRecord],
    *,
    target: date,
) -> tuple[PlayerHealthRecord, ...]:
    return tuple(
        advance_health_record(record, target=target)
        for record in records
    )


def apply_workload(
    record: PlayerHealthRecord,
    *,
    occurred_on: date,
    minutes: float,
    intensity: float,
) -> PlayerHealthRecord:
    if not 0 <= minutes <= 80:
        raise ValueError("workload minutes must be between 0 and 80")
    if not 0.25 <= intensity <= 2.0:
        raise ValueError("workload intensity must be between 0.25 and 2.0")
    current = advance_health_record(record, target=occurred_on)
    load = minutes * intensity
    acute = current.acute_load + load
    chronic = current.chronic_load + load
    fatigue = min(100.0, current.fatigue + load * 0.72)
    readiness = _readiness(
        fatigue=fatigue,
        availability=current.availability,
    )
    return replace(
        current,
        acute_load=acute,
        chronic_load=chronic,
        fatigue=fatigue,
        readiness=readiness,
        load_concern=load_concern_index(
            acute_load=acute,
            chronic_load=chronic,
            fatigue=fatigue,
            availability=current.availability,
        ),
        last_load_date=occurred_on,
    )


def update_health_status(
    record: PlayerHealthRecord,
    *,
    occurred_on: date,
    availability: str,
    body_area: str = "",
    detail: str = "",
    expected_return: date | None = None,
    minute_limit: float | None = None,
) -> PlayerHealthRecord:
    if availability not in AVAILABILITY_STATES:
        raise ValueError("invalid availability state")
    current = advance_health_record(record, target=occurred_on)
    if availability == "available":
        body_area = ""
        detail = ""
        expected_return = None
        minute_limit = None
    elif availability == "managed" and minute_limit is None:
        minute_limit = 28.0
    elif availability in {"doubtful", "out"}:
        minute_limit = 0.0
    if expected_return is not None and expected_return < occurred_on:
        raise ValueError("expected return cannot precede the league date")
    readiness = _readiness(
        fatigue=current.fatigue,
        availability=availability,
    )
    return replace(
        current,
        availability=availability,
        body_area=body_area.strip(),
        detail=detail.strip(),
        expected_return=expected_return,
        minute_limit=minute_limit,
        readiness=readiness,
        load_concern=load_concern_index(
            acute_load=current.acute_load,
            chronic_load=current.chronic_load,
            fatigue=current.fatigue,
            availability=availability,
        ),
        source="user-health-scenario",
    )


def load_concern_index(
    *,
    acute_load: float,
    chronic_load: float,
    fatigue: float,
    availability: str,
) -> float:
    prepared_week = max(chronic_load / 4.0, 1.0)
    ratio = acute_load / prepared_week
    rapid_spike = max(0.0, ratio - 1.3)
    detraining = max(0.0, 0.65 - ratio)
    status = {
        "available": 0.0,
        "managed": 0.10,
        "questionable": 0.20,
        "doubtful": 0.36,
        "out": 0.45,
    }[availability]
    value = (
        0.08
        + 0.22 * rapid_spike
        + 0.16 * detraining
        + 0.0032 * fatigue
        + status
    )
    return min(1.0, max(0.0, value))


def availability_policy(
    records: Iterable[PlayerHealthRecord],
) -> tuple[tuple[int, ...], dict[int, float]]:
    inactive: list[int] = []
    limits: dict[int, float] = {}
    for record in records:
        if record.availability in {"out", "doubtful"}:
            inactive.append(record.player_id)
        elif record.minute_limit is not None:
            limits[record.player_id] = record.minute_limit
    return tuple(sorted(inactive)), limits


def _readiness(*, fatigue: float, availability: str) -> float:
    status_ceiling = {
        "available": 100.0,
        "managed": 82.0,
        "questionable": 68.0,
        "doubtful": 35.0,
        "out": 10.0,
    }[availability]
    return min(status_ceiling, max(0.0, 100.0 - 0.62 * fatigue))
