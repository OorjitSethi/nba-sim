from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Mapping

import numpy as np

from nba_sim.domain.enums import ShotZone


def _probability(value: float, name: str) -> float:
    value = float(value)
    if not isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be a finite probability, got {value!r}")
    return value


@dataclass(frozen=True)
class ZoneProfile:
    frequency: float
    make_probability: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "frequency", _probability(self.frequency, "frequency"))
        object.__setattr__(
            self,
            "make_probability",
            _probability(self.make_probability, "make_probability"),
        )


@dataclass(frozen=True)
class PlayerProfile:
    player_id: int
    name: str
    team_abbreviation: str
    position: str
    expected_minutes: float
    usage_rate: float
    free_throw_probability: float
    turnover_probability: float
    assist_probability: float
    shooting_foul_probability: float
    steal_share: float
    block_probability: float
    offensive_rebound_weight: float
    defensive_rebound_weight: float
    defensive_impact: float
    speed: float
    height_inches: float
    shot_zones: Mapping[ShotZone, ZoneProfile] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("player name cannot be empty")
        if self.expected_minutes < 0:
            raise ValueError("expected_minutes cannot be negative")
        for name in (
            "usage_rate",
            "free_throw_probability",
            "turnover_probability",
            "assist_probability",
            "shooting_foul_probability",
            "block_probability",
        ):
            object.__setattr__(self, name, _probability(getattr(self, name), name))
        if self.steal_share < 0:
            raise ValueError("steal_share cannot be negative")
        if self.offensive_rebound_weight < 0 or self.defensive_rebound_weight < 0:
            raise ValueError("rebound weights cannot be negative")
        if self.height_inches <= 0:
            raise ValueError("height_inches must be positive")
        if not self.shot_zones:
            raise ValueError(f"{self.name} has no shot-zone profile")
        if sum(zone.frequency for zone in self.shot_zones.values()) <= 0:
            raise ValueError(f"{self.name} has no positive shot-zone frequencies")

    def sample_zone(self, rng: np.random.Generator) -> ShotZone:
        zones = tuple(self.shot_zones)
        weights = np.asarray(
            [self.shot_zones[zone].frequency for zone in zones],
            dtype=float,
        )
        weights /= weights.sum()
        return zones[int(rng.choice(len(zones), p=weights))]

    def make_probability(self, zone: ShotZone) -> float:
        if zone in self.shot_zones:
            return self.shot_zones[zone].make_probability
        return 0.35 if zone.point_value == 3 else 0.50


@dataclass(frozen=True)
class TeamProfile:
    abbreviation: str
    name: str
    roster: tuple[PlayerProfile, ...]
    pace: float = 99.0
    home_court_points: float = 2.2
    minute_limits: Mapping[int, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if len(self.roster) < 5:
            raise ValueError("an NBA team requires at least five available players")
        ids = [player.player_id for player in self.roster]
        if len(ids) != len(set(ids)):
            raise ValueError("roster contains duplicate player IDs")
        if self.pace <= 0:
            raise ValueError("pace must be positive")
        unknown_limits = set(self.minute_limits) - set(ids)
        if unknown_limits:
            raise ValueError(
                f"minute limits reference unknown players: {sorted(unknown_limits)}"
            )
        for player_id, limit in self.minute_limits.items():
            if not 0.0 <= float(limit) <= 48.0:
                raise ValueError(
                    f"minute limit for player {player_id} must be between 0 and 48"
                )

    @property
    def rotation(self) -> tuple[PlayerProfile, ...]:
        ordered = sorted(
            self.roster,
            key=lambda player: player.expected_minutes,
            reverse=True,
        )
        return tuple(ordered[: min(10, len(ordered))])

    @property
    def starting_lineup(self) -> tuple[PlayerProfile, ...]:
        return self.rotation[:5]

    def player(self, player_id: int) -> PlayerProfile:
        for player in self.roster:
            if player.player_id == player_id:
                return player
        raise KeyError(player_id)
