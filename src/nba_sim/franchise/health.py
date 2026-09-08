from __future__ import annotations

import math
import random
from dataclasses import replace
from datetime import date, timedelta
from typing import Iterable, Mapping

from nba_sim.franchise.models import (
    InjuryRecord,
    PlayerHealthRecord,
    PlayerLifecycleRecord,
    PlayerRecord,
)


HEALTH_MODEL_VERSION = "nba-health-workload.v2"
INJURY_MODEL_VERSION = "nba-injury-occurrence.v1"
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
    availability = record.availability
    body_area = record.body_area
    detail = record.detail
    expected_return = record.expected_return
    minute_limit = record.minute_limit
    source = record.source
    if (
        source == "simulated-injury"
        and expected_return is not None
        and target >= expected_return
    ):
        availability = "managed"
        detail = f"Return-to-play ramp after {detail}".strip()
        minute_limit = 24.0
        expected_return = expected_return + timedelta(days=5)
        source = "simulated-return-to-play"
    if (
        source == "simulated-return-to-play"
        and expected_return is not None
        and target >= expected_return
    ):
        availability = "available"
        body_area = ""
        detail = ""
        expected_return = None
        minute_limit = None
        source = "simulated-recovery"
    acute = record.acute_load * math.exp(-days / 7.0)
    chronic = record.chronic_load * math.exp(-days / 28.0)
    fatigue = record.fatigue * math.exp(-days / 2.5)
    readiness = _readiness(
        fatigue=fatigue,
        availability=availability,
    )
    return replace(
        record,
        as_of_date=target,
        availability=availability,
        body_area=body_area,
        detail=detail,
        expected_return=expected_return,
        minute_limit=minute_limit,
        acute_load=acute,
        chronic_load=chronic,
        fatigue=fatigue,
        readiness=readiness,
        load_concern=load_concern_index(
            acute_load=acute,
            chronic_load=chronic,
            fatigue=fatigue,
            availability=availability,
        ),
        source=source,
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
    source: str = "user-health-scenario",
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
        source=source,
    )


def sample_game_injuries(
    *,
    game_id: str,
    occurred_on: date,
    player_minutes: Mapping[int, float],
    players: Mapping[int, PlayerRecord],
    lifecycles: Mapping[int, PlayerLifecycleRecord],
    health: Mapping[int, PlayerHealthRecord],
    injury_history: Iterable[InjuryRecord],
    seed: int,
) -> tuple[tuple[PlayerHealthRecord, ...], tuple[InjuryRecord, ...]]:
    """Sample auditable postgame injuries without changing possession RNG."""
    histories: dict[int, int] = {}
    active_ids = set()
    for injury in injury_history:
        histories[injury.player_id] = histories.get(injury.player_id, 0) + 1
        if injury.status in {"active", "recovering"}:
            active_ids.add(injury.player_id)
    updated: list[PlayerHealthRecord] = []
    injuries: list[InjuryRecord] = []
    for player_id in sorted(player_minutes):
        minutes = float(player_minutes[player_id])
        record = health.get(player_id)
        player = players.get(player_id)
        if (
            record is None
            or player is None
            or minutes <= 0
            or player_id in active_ids
            or record.availability not in {"available", "managed"}
        ):
            continue
        lifecycle = lifecycles.get(player_id)
        age = lifecycle.age if lifecycle and lifecycle.age is not None else 27.0
        age_factor = max(0.82, min(1.7, 0.9 + max(0.0, age - 24.0) * 0.035))
        exposure = max(0.18, min(1.65, minutes / 28.0))
        load_factor = 0.85 + 1.45 * record.load_concern
        fatigue_factor = 1.0 + record.fatigue / 190.0
        history_factor = min(1.45, 1.0 + 0.08 * histories.get(player_id, 0))
        return_factor = 1.28 if record.availability == "managed" else 1.0
        probability = min(
            0.028,
            0.0044 * exposure * age_factor * load_factor * fatigue_factor
            * history_factor * return_factor,
        )
        rng = random.Random(f"{seed}:{game_id}:{player_id}:injury")
        if rng.random() >= probability:
            continue
        severity_roll = rng.random()
        if severity_roll < 0.43:
            severity, minimum, maximum = "day_to_day", 1, 3
        elif severity_roll < 0.74:
            severity, minimum, maximum = "minor", 4, 10
        elif severity_roll < 0.93:
            severity, minimum, maximum = "moderate", 11, 30
        elif severity_roll < 0.992:
            severity, minimum, maximum = "major", 31, 90
        else:
            severity, minimum, maximum = "severe", 91, 210
        body_roll = rng.random()
        body_areas = (
            (0.24, "ankle", "ankle sprain"),
            (0.40, "knee", "knee injury"),
            (0.53, "hamstring", "hamstring strain"),
            (0.63, "back", "lower-back injury"),
            (0.72, "foot", "foot injury"),
            (0.80, "hand/wrist", "hand or wrist injury"),
            (0.87, "shoulder", "shoulder injury"),
            (0.93, "calf", "calf strain"),
            (0.97, "head", "concussion protocol"),
            (1.00, "other", "soft-tissue injury"),
        )
        _, body_area, description = next(item for item in body_areas if body_roll <= item[0])
        duration = rng.randint(minimum, maximum)
        expected_return = occurred_on + timedelta(days=duration)
        injury = InjuryRecord(
            injury_id=f"inj-{game_id.lower()}-{player_id}",
            player_id=player_id,
            team=player.team,
            status="active",
            description=description,
            started_on=occurred_on,
            expected_return=expected_return,
            source="simulation",
            severity=severity,
            body_area=body_area,
            games_missed=0,
            model_version=INJURY_MODEL_VERSION,
        )
        injuries.append(injury)
        updated.append(update_health_status(
            record,
            occurred_on=occurred_on,
            availability="out",
            body_area=body_area,
            detail=description,
            expected_return=expected_return,
            minute_limit=0.0,
            source="simulated-injury",
        ))
    return tuple(updated), tuple(injuries)


def reconcile_injury_history(
    injuries: Iterable[InjuryRecord],
    *,
    health: Mapping[int, PlayerHealthRecord],
    games: Iterable[object],
) -> tuple[InjuryRecord, ...]:
    """Update recovery status and missed-game counts for a completed batch."""
    result = []
    games = tuple(games)
    for injury in injuries:
        current = health.get(injury.player_id)
        status = injury.status
        resolved_on = injury.resolved_on
        if (
            current is not None
            and injury.status != "cleared"
            and injury.source == "simulation"
        ):
            if current.source == "simulated-return-to-play":
                status = "recovering"
            elif current.availability == "available":
                status = "cleared"
                resolved_on = current.as_of_date
        missed = injury.games_missed + sum(
            injury.team in {getattr(game, "home_team", ""), getattr(game, "away_team", "")}
            and getattr(game, "game_date", injury.started_on) > injury.started_on
            and not any(
                getattr(box, "player_id", None) == injury.player_id
                for box in getattr(game, "box_scores", ())
            )
            for game in games
        )
        result.append(replace(
            injury,
            status=status,
            resolved_on=resolved_on,
            games_missed=missed,
        ))
    return tuple(result)


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
