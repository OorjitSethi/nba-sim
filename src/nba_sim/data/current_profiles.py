from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Mapping

from nba_sim.data.legacy import LegacySQLiteRepository
from nba_sim.data.point_in_time import (
    PlayerSeasonStat,
    PointInTimeWarehouse,
    RosterObservation,
)
from nba_sim.domain.enums import ShotZone
from nba_sim.domain.profiles import PlayerProfile, TeamProfile, ZoneProfile
from nba_sim.domain.scenarios import _allocate_minutes


class CurrentRosterProfileRepository:
    """Overlay current membership onto the best available player priors.

    Team membership comes from the point-in-time official roster snapshot.
    Returning players retain historical simulation attributes. Players absent
    from the bundled historical artifact receive an explicit replacement prior;
    this keeps them usable without pretending that unobserved attributes are
    measured.
    """

    def __init__(
        self,
        *,
        legacy: LegacySQLiteRepository,
        warehouse: PointInTimeWarehouse,
        cutoff: datetime | None = None,
    ) -> None:
        self.legacy = legacy
        self.warehouse = warehouse
        self.cutoff = (cutoff or datetime.now(timezone.utc)).astimezone(
            timezone.utc
        )
        self.season = warehouse.current_roster_season(cutoff=self.cutoff)
        self.stat_season = warehouse.latest_player_stat_season(cutoff=self.cutoff)
        self._stats = (
            {
                row.player_id: row
                for row in warehouse.player_stats_as_of(
                    season=self.stat_season,
                    cutoff=self.cutoff,
                )
            }
            if self.stat_season is not None
            else {}
        )
        self._sources: dict[int, str] = {}

    def available_teams(self) -> tuple[str, ...]:
        return self.legacy.available_teams()

    def load_team(self, abbreviation: str) -> TeamProfile:
        abbreviation = abbreviation.upper()
        observations = tuple(
            row
            for row in self.warehouse.roster_as_of(
                team=abbreviation,
                cutoff=self.cutoff,
            )
            if row.roster_status == "active"
        )
        if len(observations) < 5:
            return self.legacy.load_team(abbreviation)
        players = tuple(
            self._player(row, team_abbreviation=abbreviation)
            for row in observations
        )
        players = _project_rotation_minutes(players)
        pace_weights = [
            (
                player.expected_minutes,
                self._stats[player.player_id].pace,
            )
            for player in players
            if player.player_id in self._stats
            and self._stats[player.player_id].minutes > 0
        ]
        pace = (
            sum(weight * value for weight, value in pace_weights)
            / sum(weight for weight, _ in pace_weights)
            if pace_weights
            else 99.0
        )
        return TeamProfile(
            abbreviation=abbreviation,
            name=abbreviation,
            roster=players,
            pace=_clamp(pace, 94.0, 106.0),
        )

    def profile_source(self, player_id: int) -> str:
        return self._sources.get(int(player_id), "legacy-2023-24")

    def player_statistics(self, player_id: int) -> PlayerSeasonStat | None:
        """Return the latest point-in-time season row used by this repository."""
        return self._stats.get(int(player_id))

    def _player(
        self,
        observation: RosterObservation,
        *,
        team_abbreviation: str,
    ) -> PlayerProfile:
        historical = self.legacy.load_player(
            observation.player_id,
            team_abbreviation=team_abbreviation,
        )
        if historical is not None:
            profile = replace(
                historical,
                name=observation.player_name,
                position=observation.position or historical.position,
            )
        else:
            profile = _replacement_profile(
                observation,
                team_abbreviation=team_abbreviation,
            )
        statistics = self._stats.get(observation.player_id)
        if statistics is not None and statistics.games_played > 0:
            self._sources[observation.player_id] = (
                f"official-{statistics.season}"
            )
            return _statistical_profile(profile, statistics)
        self._sources[observation.player_id] = (
            "historical-2023-24"
            if historical is not None
            else "replacement-prior"
        )
        return profile


def _replacement_profile(
    observation: RosterObservation,
    *,
    team_abbreviation: str,
) -> PlayerProfile:
    return PlayerProfile(
        player_id=observation.player_id,
        name=observation.player_name,
        team_abbreviation=team_abbreviation,
        position=observation.position or "Unknown",
        expected_minutes=12.0,
        usage_rate=0.20,
        free_throw_probability=0.75,
        turnover_probability=0.12,
        assist_probability=0.48,
        shooting_foul_probability=0.10,
        steal_share=0.75,
        block_probability=0.02,
        offensive_rebound_weight=45.0,
        defensive_rebound_weight=55.0,
        defensive_impact=0.0,
        speed=0.65,
        height_inches=78.0,
        shot_zones={
            ShotZone.RESTRICTED_AREA: ZoneProfile(0.42, 0.62),
            ShotZone.PAINT_NON_RA: ZoneProfile(0.13, 0.43),
            ShotZone.MID_RANGE: ZoneProfile(0.12, 0.40),
            ShotZone.LEFT_CORNER_THREE: ZoneProfile(0.06, 0.36),
            ShotZone.RIGHT_CORNER_THREE: ZoneProfile(0.06, 0.36),
            ShotZone.ABOVE_BREAK_THREE: ZoneProfile(0.21, 0.35),
        },
    )


def _statistical_profile(
    prior: PlayerProfile,
    statistics: PlayerSeasonStat,
) -> PlayerProfile:
    sample_weight = min(1.0, statistics.games_played / 20.0)
    minutes = (
        sample_weight * statistics.minutes
        + (1.0 - sample_weight) * prior.expected_minutes
    )
    possessions_ended = (
        statistics.field_goals_attempted
        + 0.44 * statistics.free_throws_attempted
        + statistics.turnovers
    )
    turnover_probability = (
        statistics.turnovers / possessions_ended
        if possessions_ended > 0
        else prior.turnover_probability
    )
    free_throw_probability = _shrunk_percentage(
        made=statistics.free_throws_made * statistics.games_played,
        attempted=statistics.free_throws_attempted * statistics.games_played,
        prior=0.77,
        prior_attempts=40.0,
    )
    foul_pressure = (
        statistics.free_throws_attempted
        / max(1.0, statistics.field_goals_attempted)
    )
    total_minutes = statistics.minutes * statistics.games_played
    defensive_signal = (
        0.7 * (114.0 - statistics.defensive_rating) / 100.0
        + 0.3 * (statistics.player_impact_estimate - 0.10)
    )
    defensive_reliability = min(1.0, total_minutes / 1_000.0)
    return replace(
        prior,
        expected_minutes=_clamp(minutes, 2.0, 38.0),
        usage_rate=_clamp(statistics.usage_rate, 0.06, 0.42),
        free_throw_probability=_clamp(
            free_throw_probability,
            0.35,
            0.96,
        ),
        turnover_probability=_clamp(
            turnover_probability,
            0.06,
            0.20,
        ),
        assist_probability=_clamp(
            0.28 + 1.65 * statistics.assist_rate,
            0.28,
            0.84,
        ),
        shooting_foul_probability=_clamp(
            0.065 + 0.16 * foul_pressure,
            0.065,
            0.17,
        ),
        steal_share=max(
            0.05,
            0.25 + 20.0 * statistics.steals / max(statistics.minutes, 1.0),
        ),
        block_probability=_clamp(
            0.88 * statistics.blocks / max(statistics.minutes, 1.0),
            0.003,
            0.055,
        ),
        offensive_rebound_weight=max(
            0.1,
            100.0 * statistics.offensive_rebound_rate
            + statistics.height_inches * 0.35,
        ),
        defensive_rebound_weight=max(
            0.1,
            100.0 * statistics.defensive_rebound_rate
            + statistics.height_inches * 0.45,
        ),
        defensive_impact=_clamp(
            defensive_reliability * defensive_signal,
            -0.10,
            0.10,
        ),
        height_inches=statistics.height_inches,
        shot_zones=_recalibrated_shot_zones(prior.shot_zones, statistics),
    )


def _project_rotation_minutes(
    players: tuple[PlayerProfile, ...],
) -> tuple[PlayerProfile, ...]:
    ordered = tuple(
        sorted(
            players,
            key=lambda player: player.expected_minutes,
            reverse=True,
        )
    )
    primary = ordered[: min(10, len(ordered))]
    allocations = _allocate_minutes(
        primary,
        {player.player_id: 40.0 for player in primary},
    )
    lowest_rotation_minutes = min(allocations.values())
    return tuple(
        replace(
            player,
            expected_minutes=(
                allocations[player.player_id]
                if player.player_id in allocations
                else min(player.expected_minutes, lowest_rotation_minutes * 0.75)
            ),
        )
        for player in players
    )


def _recalibrated_shot_zones(
    prior: Mapping[ShotZone, ZoneProfile],
    statistics: PlayerSeasonStat,
) -> dict[ShotZone, ZoneProfile]:
    zones = dict(prior)
    two_zones = tuple(zone for zone in zones if zone.point_value == 2)
    three_zones = tuple(zone for zone in zones if zone.point_value == 3)
    total_attempts = statistics.field_goals_attempted * statistics.games_played
    three_attempts = statistics.threes_attempted * statistics.games_played
    two_attempts = max(0.0, total_attempts - three_attempts)
    two_makes = max(
        0.0,
        (statistics.field_goals_made - statistics.threes_made)
        * statistics.games_played,
    )
    three_makes = statistics.threes_made * statistics.games_played
    prior_three_frequency = sum(
        zones[zone].frequency for zone in three_zones
    ) / max(1e-9, sum(item.frequency for item in zones.values()))
    observed_three_frequency = (
        three_attempts / total_attempts
        if total_attempts > 0
        else prior_three_frequency
    )
    three_frequency = (
        total_attempts * observed_three_frequency
        + 200.0 * prior_three_frequency
    ) / (total_attempts + 200.0)
    two_percentage = _shrunk_percentage(
        made=two_makes,
        attempted=two_attempts,
        prior=0.54,
        prior_attempts=75.0,
    )
    three_percentage = _shrunk_percentage(
        made=three_makes,
        attempted=three_attempts,
        prior=0.36,
        prior_attempts=75.0,
    )
    result = {}
    for group, frequency, percentage in (
        (two_zones, 1.0 - three_frequency, two_percentage),
        (three_zones, three_frequency, three_percentage),
    ):
        if not group:
            continue
        group_frequency = sum(zones[zone].frequency for zone in group)
        group_make = sum(
            zones[zone].frequency * zones[zone].make_probability
            for zone in group
        ) / max(group_frequency, 1e-9)
        for zone in group:
            share = zones[zone].frequency / max(group_frequency, 1e-9)
            make_adjustment = 0.35 * (
                zones[zone].make_probability - group_make
            )
            result[zone] = ZoneProfile(
                frequency=_clamp(frequency * share, 0.0, 1.0),
                make_probability=_clamp(
                    percentage + make_adjustment,
                    0.02,
                    0.90,
                ),
            )
    return result


def _shrunk_percentage(
    *,
    made: float,
    attempted: float,
    prior: float,
    prior_attempts: float,
) -> float:
    return (made + prior * prior_attempts) / max(
        attempted + prior_attempts,
        1e-9,
    )


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(float(value), high))


__all__ = ["CurrentRosterProfileRepository"]
