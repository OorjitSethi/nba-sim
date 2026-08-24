from __future__ import annotations

from typing import Protocol

import numpy as np

from nba_sim.domain.profiles import PlayerProfile, TeamProfile
from nba_sim.forecast.distributions import GameDistribution


class MacroForecastModel(Protocol):
    name: str
    version: str
    trained: bool

    def predict(
        self,
        *,
        home_team: TeamProfile,
        away_team: TeamProfile,
    ) -> GameDistribution:
        ...


class HeuristicMacroModel:
    """Transparent top-down prior pending time-correct historical model fitting."""

    name = "transparent-profile-prior"
    version = "0.1.0"
    trained = False

    def predict(
        self,
        *,
        home_team: TeamProfile,
        away_team: TeamProfile,
    ) -> GameDistribution:
        home_offense = self._offensive_rating(home_team)
        away_offense = self._offensive_rating(away_team)
        home_defense = self._defensive_rating_allowed(home_team)
        away_defense = self._defensive_rating_allowed(away_team)

        home_rating = (home_offense + away_defense) / 2.0
        away_rating = (away_offense + home_defense) / 2.0
        home_advantage = home_team.home_court_points
        home_rating += home_advantage / 2.0
        away_rating -= home_advantage / 2.0
        pace = (home_team.pace + away_team.pace) / 2.0
        home_points = home_rating * pace / 100.0
        away_points = away_rating * pace / 100.0
        return GameDistribution(
            home_team=home_team.abbreviation,
            away_team=away_team.abbreviation,
            mean_margin=home_points - away_points,
            margin_standard_deviation=13.2,
            mean_total=home_points + away_points,
            total_standard_deviation=18.0,
            margin_total_correlation=0.08,
            model_name=self.name,
            model_version=self.version,
        )

    @staticmethod
    def _rotation_weights(team: TeamProfile) -> np.ndarray:
        values = np.asarray(
            [player.expected_minutes for player in team.rotation],
            dtype=float,
        )
        return values / values.sum()

    def _offensive_rating(self, team: TeamProfile) -> float:
        weights = self._rotation_weights(team)
        shot_values = np.asarray(
            [self._player_shot_value(player) for player in team.rotation]
        )
        turnovers = np.asarray(
            [player.turnover_probability for player in team.rotation]
        )
        foul_pressure = np.asarray(
            [
                player.shooting_foul_probability * player.free_throw_probability
                for player in team.rotation
            ]
        )
        shot_component = float(np.dot(weights, shot_values))
        turnover_component = float(np.dot(weights, turnovers))
        foul_component = float(np.dot(weights, foul_pressure))
        return float(
            np.clip(
                114.0
                + 65.0 * (shot_component - 1.07)
                + 55.0 * (0.13 - turnover_component)
                + 20.0 * (foul_component - 0.08),
                101.0,
                126.0,
            )
        )

    def _defensive_rating_allowed(self, team: TeamProfile) -> float:
        weights = self._rotation_weights(team)
        impact = float(
            np.dot(
                weights,
                np.asarray([player.defensive_impact for player in team.rotation]),
            )
        )
        blocks = float(
            np.dot(
                weights,
                np.asarray([player.block_probability for player in team.rotation]),
            )
        )
        return float(np.clip(114.0 - 85.0 * impact - 18.0 * (blocks - 0.025), 101.0, 126.0))

    @staticmethod
    def _player_shot_value(player: PlayerProfile) -> float:
        frequency = sum(profile.frequency for profile in player.shot_zones.values())
        if frequency <= 0:
            return 1.05
        return sum(
            profile.frequency * profile.make_probability * zone.point_value
            for zone, profile in player.shot_zones.items()
        ) / frequency
