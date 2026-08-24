from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Iterable

import numpy as np

from nba_sim.data.point_in_time import PlayerSeasonStat
from nba_sim.domain.profiles import PlayerProfile
from nba_sim.franchise.models import PlayerLifecycleRecord, PlayerRecord
from nba_sim.randomness import RandomStreamFactory


LIFECYCLE_MODEL_VERSION = "nba-lifecycle-nonlinear.v1"
DEVELOPMENT_FOCUSES = (
    "balanced",
    "offense",
    "playmaking",
    "defense",
    "athleticism",
)
_ATTRIBUTE_NAMES = ("offense", "playmaking", "defense", "athleticism")
_ATTRIBUTE_WEIGHTS = {
    "offense": 0.38,
    "playmaking": 0.22,
    "defense": 0.28,
    "athleticism": 0.12,
}
_ATTRIBUTE_PEAK_AGES = {
    "offense": 28.5,
    "playmaking": 29.5,
    "defense": 28.5,
    "athleticism": 25.5,
}


@dataclass(frozen=True)
class LifecycleProjectionConfig:
    focus: str = "balanced"
    planned_minutes: float = 1_800.0
    injury_burden: float = 0.0
    seasons: int = 5
    paths: int = 400

    def __post_init__(self) -> None:
        if self.focus not in DEVELOPMENT_FOCUSES:
            raise ValueError(
                f"development focus must be one of: {', '.join(DEVELOPMENT_FOCUSES)}"
            )
        if not 0 <= self.planned_minutes <= 3_500:
            raise ValueError("planned minutes must be between 0 and 3,500")
        if not 0 <= self.injury_burden <= 1:
            raise ValueError("injury burden must be between 0 and 1")
        if not 1 <= self.seasons <= 8:
            raise ValueError("projection horizon must be between 1 and 8 seasons")
        if not 50 <= self.paths <= 2_000:
            raise ValueError("projection paths must be between 50 and 2,000")


def build_lifecycle_record(
    player: PlayerRecord,
    *,
    profile: PlayerProfile | None,
    statistics: PlayerSeasonStat | None,
    season: str,
) -> PlayerLifecycleRecord:
    age = (
        statistics.age + 1.0
        if statistics is not None and statistics.age is not None
        else None
    )
    age_source = (
        f"official-{statistics.season}-season-age+1"
        if age is not None and statistics is not None
        else "not_available"
    )
    stage = lifecycle_stage(age)
    attributes = _initial_attributes(player, profile)
    overall = _overall(attributes)
    observed = statistics is not None and statistics.games_played > 0
    confidence = (
        "high"
        if observed and player.profile_source.startswith("official-")
        else "moderate"
        if profile is not None and player.profile_source != "replacement-prior"
        else "low"
    )
    uncertainty = {
        "high": 3.0,
        "moderate": 4.75,
        "low": 7.5,
    }[confidence]
    if age is None:
        uncertainty += 2.0
    growth_room = (
        max(0.0, 28.0 - age) * 0.95
        if age is not None
        else 3.0
    )
    potential_mean = _clamp(
        overall + growth_room,
        overall,
        99.0,
    )
    workload = (
        statistics.minutes * statistics.games_played
        if statistics is not None
        else max(0.0, player.expected_minutes * 72.0)
    )
    games = statistics.games_played if statistics is not None else 0
    return PlayerLifecycleRecord(
        player_id=player.player_id,
        as_of_season=season,
        age=age,
        age_source=age_source,
        stage=stage,
        offense=attributes["offense"],
        playmaking=attributes["playmaking"],
        defense=attributes["defense"],
        athleticism=attributes["athleticism"],
        overall=overall,
        potential_mean=potential_mean,
        potential_sd=uncertainty,
        workload_minutes=workload,
        games_played=games,
        confidence=confidence,
        model_version=LIFECYCLE_MODEL_VERSION,
    )


def project_lifecycle(
    record: PlayerLifecycleRecord,
    *,
    seed: int,
    config: LifecycleProjectionConfig,
) -> dict[str, object]:
    streams = RandomStreamFactory(seed)
    paths: list[list[PlayerLifecycleRecord | None]] = []
    career_highs: list[float] = []
    retired_by_horizon = 0
    for path_index in range(config.paths):
        rng = streams.generator(
            f"lifecycle:{record.player_id}:path:{path_index}"
        )
        current: PlayerLifecycleRecord | None = record
        trajectory: list[PlayerLifecycleRecord | None] = [current]
        career_high = record.overall
        for _ in range(config.seasons):
            if current is None:
                trajectory.append(None)
                continue
            next_record = _advance_one_season(
                current,
                rng=rng,
                config=config,
            )
            retirement_probability = _retirement_probability(
                age=next_record.age,
                overall=next_record.overall,
                injury_burden=config.injury_burden,
            )
            if retirement_probability is not None and rng.random() < retirement_probability:
                current = None
            else:
                current = next_record
                career_high = max(career_high, current.overall)
            trajectory.append(current)
        if current is None:
            retired_by_horizon += 1
        career_highs.append(career_high)
        paths.append(trajectory)

    seasons = [_advance_season(record.as_of_season, offset) for offset in range(config.seasons + 1)]
    annual = []
    for season_index, season in enumerate(seasons):
        active = [
            path[season_index]
            for path in paths
            if path[season_index] is not None
        ]
        overalls = [item.overall for item in active if item is not None]
        age_values = [item.age for item in active if item is not None and item.age is not None]
        annual.append(
            {
                "season": season,
                "years_out": season_index,
                "age": (
                    round(float(np.median(age_values)), 2)
                    if age_values
                    else None
                ),
                "stage": lifecycle_stage(
                    float(np.median(age_values)) if age_values else None
                ),
                "active_probability": round(len(active) / config.paths, 6),
                "retired_probability": round(
                    1.0 - len(active) / config.paths,
                    6,
                ),
                "overall": _quantiles(overalls),
                "attributes": {
                    name: _quantiles(
                        [
                            float(getattr(item, name))
                            for item in active
                            if item is not None
                        ]
                    )
                    for name in _ATTRIBUTE_NAMES
                },
            }
        )

    breakout = sum(
        high >= record.overall + 5.0 for high in career_highs
    ) / config.paths
    return {
        "kind": "player_lifecycle_projection",
        "seed": seed,
        "model_version": LIFECYCLE_MODEL_VERSION,
        "player_id": record.player_id,
        "baseline": record.as_dict(),
        "config": {
            "focus": config.focus,
            "planned_minutes": config.planned_minutes,
            "injury_burden": config.injury_burden,
            "seasons": config.seasons,
            "paths": config.paths,
        },
        "trajectory": annual,
        "career_high_overall": _quantiles(career_highs),
        "breakout_probability": round(breakout, 6),
        "retirement_probability_by_horizon": round(
            retired_by_horizon / config.paths,
            6,
        ),
        "age_known": record.age is not None,
        "interpretation": (
            "Official season age anchors the nonlinear curve."
            if record.age is not None
            else "Age is unavailable, so age-specific growth and retirement effects are withheld and uncertainty is wider."
        ),
        "limitations": [
            "Projection bands describe model uncertainty, not guaranteed ratings.",
            "Planned minutes are opportunity and workload, not a promise of playing time.",
            "Injury burden is a scenario input until longitudinal medical history is available.",
            "No exact birth date is inferred from a season-level age.",
        ],
    }


def lifecycle_stage(age: float | None) -> str:
    if age is None:
        return "unknown"
    if age < 23:
        return "prospect"
    if age < 26:
        return "developing"
    if age < 30:
        return "prime"
    if age < 34:
        return "veteran"
    if age < 37:
        return "decline"
    return "late_career"


def _initial_attributes(
    player: PlayerRecord,
    profile: PlayerProfile | None,
) -> dict[str, float]:
    if profile is None:
        role = _clamp(player.expected_minutes, 0.0, 38.0)
        baseline = 42.0 + 0.78 * role
        return {
            "offense": _clamp(baseline, 25.0, 88.0),
            "playmaking": _clamp(baseline - 2.0, 25.0, 86.0),
            "defense": _clamp(baseline - 1.0, 25.0, 88.0),
            "athleticism": 55.0,
        }

    expected_points_per_shot = sum(
        zone.frequency * zone.make_probability * shot_zone.point_value
        for shot_zone, zone in profile.shot_zones.items()
    )
    minutes_signal = profile.expected_minutes - 18.0
    offense = (
        50.0
        + 31.0 * (expected_points_per_shot - 1.02)
        + 32.0 * (profile.usage_rate - 0.18)
        + 0.34 * minutes_signal
    )
    playmaking = (
        48.0
        + 54.0 * (profile.assist_probability - 0.43)
        - 52.0 * (profile.turnover_probability - 0.12)
        + 0.26 * minutes_signal
    )
    defense = (
        49.0
        + 95.0 * profile.defensive_impact
        + 55.0 * profile.block_probability
        + 0.22 * minutes_signal
    )
    athleticism = (
        48.0
        + 38.0 * (profile.speed - 0.60)
        + 0.18 * minutes_signal
    )
    return {
        "offense": _clamp(offense, 25.0, 98.0),
        "playmaking": _clamp(playmaking, 25.0, 98.0),
        "defense": _clamp(defense, 25.0, 98.0),
        "athleticism": _clamp(athleticism, 25.0, 98.0),
    }


def _advance_one_season(
    record: PlayerLifecycleRecord,
    *,
    rng: np.random.Generator,
    config: LifecycleProjectionConfig,
) -> PlayerLifecycleRecord:
    next_age = record.age + 1.0 if record.age is not None else None
    shared_shock = float(rng.normal(0.0, 0.42 + 0.06 * record.potential_sd))
    updated: dict[str, float] = {}
    for name in _ATTRIBUTE_NAMES:
        current = float(getattr(record, name))
        age_delta = _age_curve_delta(name, next_age)
        focus_delta = _focus_delta(name, config.focus)
        opportunity_delta = _opportunity_delta(
            age=next_age,
            planned_minutes=config.planned_minutes,
        )
        injury_delta = _injury_delta(name, config.injury_burden)
        independent_shock = float(rng.normal(0.0, 0.28 + 0.035 * record.potential_sd))
        raw_delta = (
            age_delta
            + focus_delta
            + opportunity_delta
            + injury_delta
            + 0.68 * shared_shock
            + independent_shock
        )
        if raw_delta > 0:
            remaining = max(0.0, record.potential_mean - record.overall)
            raw_delta *= min(1.0, 0.28 + remaining / 8.0)
        updated[name] = _clamp(current + raw_delta, 20.0, 99.0)

    overall = _overall(updated)
    next_potential = record.potential_mean
    if next_age is not None and next_age >= 30:
        next_potential = max(overall, next_potential - 0.45 * (next_age - 29.0))
    return replace(
        record,
        as_of_season=_advance_season(record.as_of_season, 1),
        age=next_age,
        stage=lifecycle_stage(next_age),
        offense=updated["offense"],
        playmaking=updated["playmaking"],
        defense=updated["defense"],
        athleticism=updated["athleticism"],
        overall=overall,
        potential_mean=_clamp(next_potential, overall, 99.0),
        potential_sd=max(1.5, record.potential_sd * 0.92),
        workload_minutes=config.planned_minutes,
        games_played=min(82, max(0, round(config.planned_minutes / 26.5))),
    )


def _age_curve_delta(attribute: str, age: float | None) -> float:
    if age is None:
        return 0.0
    peak = _ATTRIBUTE_PEAK_AGES[attribute]
    if age < peak:
        return min(1.45, 0.32 + 0.13 * (peak - age))
    years_after = age - peak
    if years_after <= 1.0:
        return -0.08 * years_after
    multiplier = 1.28 if attribute == "athleticism" else 0.92
    return -multiplier * (0.22 * years_after ** 1.22)


def _focus_delta(attribute: str, focus: str) -> float:
    if focus == "balanced":
        return 0.10
    return 0.48 if attribute == focus else -0.08


def _opportunity_delta(
    *,
    age: float | None,
    planned_minutes: float,
) -> float:
    if age is None:
        return 0.0
    if age < 26:
        if planned_minutes < 650:
            return -0.38
        if 1_200 <= planned_minutes <= 2_450:
            return 0.20
    if age >= 30 and planned_minutes > 2_700:
        return -0.18 - 0.00022 * (planned_minutes - 2_700)
    return 0.0


def _injury_delta(attribute: str, burden: float) -> float:
    if attribute == "athleticism":
        return -1.45 * burden
    if attribute == "defense":
        return -0.72 * burden
    return -0.42 * burden


def _retirement_probability(
    *,
    age: float | None,
    overall: float,
    injury_burden: float,
) -> float | None:
    if age is None:
        return None
    age_component = 1.0 / (1.0 + math.exp(-(age - 38.0) / 1.45))
    ability_multiplier = _clamp(1.24 - (overall - 50.0) / 85.0, 0.55, 1.35)
    return _clamp(
        age_component * ability_multiplier + 0.11 * injury_burden,
        0.0,
        0.96,
    )


def _overall(attributes: dict[str, float]) -> float:
    return _clamp(
        sum(
            _ATTRIBUTE_WEIGHTS[name] * attributes[name]
            for name in _ATTRIBUTE_NAMES
        ),
        20.0,
        99.0,
    )


def _quantiles(values: Iterable[float]) -> dict[str, float] | None:
    materialized = np.asarray(tuple(values), dtype=float)
    if materialized.size == 0:
        return None
    return {
        "p10": round(float(np.quantile(materialized, 0.10)), 3),
        "p50": round(float(np.quantile(materialized, 0.50)), 3),
        "p90": round(float(np.quantile(materialized, 0.90)), 3),
    }


def _advance_season(season: str, years: int) -> str:
    try:
        start_text, end_text = season.split("-", 1)
        start = int(start_text) + years
        end = (int(start_text) + years + 1) % 100
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid season: {season}") from error
    return f"{start}-{end:02d}"


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, float(value)))
