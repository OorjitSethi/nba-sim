from __future__ import annotations

from dataclasses import replace
from datetime import date

from nba_sim.domain.profiles import PlayerProfile, TeamProfile, ZoneProfile
from nba_sim.franchise.models import CoachingProfileRecord, TeamChemistryRecord


CHEMISTRY_MODEL_VERSION = "nba-chemistry-coaching.v1"


def default_team_chemistry(team: str, *, as_of: date) -> TeamChemistryRecord:
    return TeamChemistryRecord(
        team=team,
        as_of_date=as_of,
        cohesion=50.0,
        role_clarity=50.0,
        trust=50.0,
        system_familiarity=50.0,
        morale=50.0,
        shared_sessions=0,
        confidence="low",
        source="neutral-unobserved-prior",
        model_version=CHEMISTRY_MODEL_VERSION,
    )


def default_coaching_profile(team: str, *, as_of: date) -> CoachingProfileRecord:
    return CoachingProfileRecord(
        team=team,
        as_of_date=as_of,
        coach_name="Unassigned strategy profile",
        offensive_system="balanced",
        defensive_system="balanced",
        pace_emphasis=0.0,
        rotation_depth=10,
        development_priority="balanced",
        adaptability=50.0,
        confidence="low",
        source="user-strategy-prior",
        model_version=CHEMISTRY_MODEL_VERSION,
    )


def record_shared_session(
    record: TeamChemistryRecord,
    *,
    occurred_on: date,
    emphasis: str,
    intensity: float,
) -> TeamChemistryRecord:
    if emphasis not in {"cohesion", "roles", "system", "recovery"}:
        raise ValueError("invalid chemistry session emphasis")
    if not 0.25 <= intensity <= 2.0:
        raise ValueError("session intensity must be between 0.25 and 2")
    gains = {
        "cohesion": (0.9, 0.25, 0.65, 0.25, 0.35),
        "roles": (0.25, 1.05, 0.35, 0.45, 0.25),
        "system": (0.25, 0.35, 0.25, 1.1, 0.15),
        "recovery": (0.35, 0.20, 0.45, 0.10, 0.9),
    }[emphasis]
    values = [
        record.cohesion,
        record.role_clarity,
        record.trust,
        record.system_familiarity,
        record.morale,
    ]
    updated = [
        min(100.0, value + gain * intensity * (1.0 - value / 120.0))
        for value, gain in zip(values, gains)
    ]
    return replace(
        record,
        as_of_date=occurred_on,
        cohesion=updated[0],
        role_clarity=updated[1],
        trust=updated[2],
        system_familiarity=updated[3],
        morale=updated[4],
        shared_sessions=record.shared_sessions + 1,
        source="user-team-session",
    )


def apply_team_environment(
    team: TeamProfile,
    *,
    chemistry: TeamChemistryRecord,
    coaching: CoachingProfileRecord,
) -> TeamProfile:
    familiarity = (chemistry.system_familiarity - 50.0) / 50.0
    cohesion = (chemistry.cohesion - 50.0) / 50.0
    role_clarity = (chemistry.role_clarity - 50.0) / 50.0
    morale = (chemistry.morale - 50.0) / 50.0
    scheme_gain = 0.012 * familiarity
    defense_gain = 0.008 * cohesion
    adjusted: list[PlayerProfile] = []
    for player in team.roster:
        assist = player.assist_probability
        turnover = player.turnover_probability
        defensive_impact = player.defensive_impact
        zones = player.shot_zones
        if coaching.offensive_system in {"motion", "pace_space"}:
            assist = _clamp(assist + 0.012 + scheme_gain, 0.0, 1.0)
        elif coaching.offensive_system == "heliocentric":
            assist = _clamp(assist + 0.006, 0.0, 1.0)
        turnover = _clamp(
            turnover - 0.008 * role_clarity - 0.004 * familiarity,
            0.0,
            1.0,
        )
        if coaching.defensive_system != "balanced":
            defensive_impact += defense_gain + 0.004 * (
                coaching.adaptability - 50.0
            ) / 50.0
        shot_multiplier = 1.0 + 0.008 * cohesion + 0.006 * morale
        zones = {
            zone: ZoneProfile(
                frequency=profile.frequency,
                make_probability=_clamp(
                    profile.make_probability * shot_multiplier,
                    0.01,
                    0.99,
                ),
            )
            for zone, profile in zones.items()
        }
        adjusted.append(
            replace(
                player,
                assist_probability=assist,
                turnover_probability=turnover,
                defensive_impact=defensive_impact,
                shot_zones=zones,
            )
        )
    return replace(
        team,
        roster=tuple(adjusted),
        pace=team.pace * (1.0 + 0.03 * coaching.pace_emphasis),
    )


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, value))
