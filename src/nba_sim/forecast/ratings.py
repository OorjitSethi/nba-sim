from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from math import sqrt
from typing import Iterable, Mapping

import numpy as np

from nba_sim.domain.profiles import TeamProfile
from nba_sim.forecast.distributions import GameDistribution


@dataclass(frozen=True)
class GameObservation:
    game_date: date
    home_team: str
    away_team: str
    home_points: int
    away_points: int
    possessions: float
    neutral_site: bool = False

    def __post_init__(self) -> None:
        if self.home_team == self.away_team:
            raise ValueError("a team cannot play itself")
        if self.home_points < 0 or self.away_points < 0:
            raise ValueError("points cannot be negative")
        if self.possessions <= 0:
            raise ValueError("possessions must be positive")


@dataclass(frozen=True)
class TeamStrengthEstimate:
    team: str
    offense_per_100: float
    defense_per_100: float
    offense_standard_error: float
    defense_standard_error: float


class DynamicTeamStrengthModel:
    """Chronological Bayesian state-space offense/defense estimator."""

    name = "dynamic-bayesian-team-strength"
    version = "0.1.0"
    trained = True

    def __init__(
        self,
        teams: Iterable[str],
        *,
        league_rating: float = 114.0,
        home_court_points: float = 2.2,
        prior_standard_deviation: float = 6.0,
        process_standard_deviation_per_day: float = 0.08,
        observation_standard_deviation: float = 10.5,
    ) -> None:
        ordered = tuple(sorted(set(teams)))
        if len(ordered) < 2:
            raise ValueError("dynamic ratings require at least two teams")
        self.teams = ordered
        self.indices = {team: index for index, team in enumerate(ordered)}
        self.league_rating = league_rating
        self.home_court_points = home_court_points
        self.process_variance_per_day = process_standard_deviation_per_day**2
        self.observation_variance = observation_standard_deviation**2
        dimensions = 2 * len(ordered)
        self.mean = np.zeros(dimensions, dtype=np.float64)
        self.covariance = np.eye(dimensions, dtype=np.float64) * (
            prior_standard_deviation**2
        )
        self.last_update: date | None = None
        self.observations_seen = 0

    def fit(self, observations: Iterable[GameObservation]) -> "DynamicTeamStrengthModel":
        ordered = sorted(observations, key=lambda observation: observation.game_date)
        for observation in ordered:
            self.update(observation)
        return self

    def update(self, observation: GameObservation) -> None:
        if observation.home_team not in self.indices:
            raise KeyError(observation.home_team)
        if observation.away_team not in self.indices:
            raise KeyError(observation.away_team)
        if self.last_update is not None and observation.game_date < self.last_update:
            raise ValueError("rating updates must be chronological")
        if self.last_update is not None:
            elapsed_days = max(0, (observation.game_date - self.last_update).days)
            self.covariance += np.eye(self.covariance.shape[0]) * (
                elapsed_days * self.process_variance_per_day
            )

        home_adjustment = 0.0 if observation.neutral_site else self.home_court_points / 2.0
        home_rating = observation.home_points * 100.0 / observation.possessions
        away_rating = observation.away_points * 100.0 / observation.possessions

        home_design = self._score_design(
            offense=observation.home_team,
            defense=observation.away_team,
        )
        away_design = self._score_design(
            offense=observation.away_team,
            defense=observation.home_team,
        )
        self._scalar_update(
            home_design,
            home_rating - self.league_rating - home_adjustment,
        )
        self._scalar_update(
            away_design,
            away_rating - self.league_rating + home_adjustment,
        )
        self.last_update = observation.game_date
        self.observations_seen += 1

    def predict(
        self,
        *,
        home_team: TeamProfile,
        away_team: TeamProfile,
    ) -> GameDistribution:
        if home_team.abbreviation not in self.indices:
            raise KeyError(home_team.abbreviation)
        if away_team.abbreviation not in self.indices:
            raise KeyError(away_team.abbreviation)
        home_design = self._score_design(
            offense=home_team.abbreviation,
            defense=away_team.abbreviation,
        )
        away_design = self._score_design(
            offense=away_team.abbreviation,
            defense=home_team.abbreviation,
        )
        pace = (home_team.pace + away_team.pace) / 2.0
        home_rating = (
            self.league_rating
            + self.home_court_points / 2.0
            + float(np.dot(home_design, self.mean))
        )
        away_rating = (
            self.league_rating
            - self.home_court_points / 2.0
            + float(np.dot(away_design, self.mean))
        )
        scale = pace / 100.0
        home_points = home_rating * scale
        away_points = away_rating * scale

        score_noise_variance = self.observation_variance * scale**2
        home_variance = (
            float(
                np.einsum(
                    "i,ij,j->",
                    home_design,
                    self.covariance,
                    home_design,
                )
            )
            * scale**2
            + score_noise_variance
        )
        away_variance = (
            float(
                np.einsum(
                    "i,ij,j->",
                    away_design,
                    self.covariance,
                    away_design,
                )
            )
            * scale**2
            + score_noise_variance
        )
        score_covariance = (
            float(
                np.einsum(
                    "i,ij,j->",
                    home_design,
                    self.covariance,
                    away_design,
                )
            )
            * scale**2
        )
        margin_variance = max(
            1e-6,
            home_variance + away_variance - 2.0 * score_covariance,
        )
        total_variance = max(
            1e-6,
            home_variance + away_variance + 2.0 * score_covariance,
        )
        margin_total_covariance = home_variance - away_variance
        correlation = float(
            np.clip(
                margin_total_covariance
                / sqrt(margin_variance * total_variance),
                -0.95,
                0.95,
            )
        )
        return GameDistribution(
            home_team=home_team.abbreviation,
            away_team=away_team.abbreviation,
            mean_margin=home_points - away_points,
            margin_standard_deviation=sqrt(margin_variance),
            mean_total=home_points + away_points,
            total_standard_deviation=sqrt(total_variance),
            margin_total_correlation=correlation,
            model_name=self.name,
            model_version=self.version,
        )

    def estimates(self) -> tuple[TeamStrengthEstimate, ...]:
        count = len(self.teams)
        result = []
        for team, index in self.indices.items():
            result.append(
                TeamStrengthEstimate(
                    team=team,
                    offense_per_100=float(self.mean[index]),
                    defense_per_100=float(self.mean[count + index]),
                    offense_standard_error=sqrt(self.covariance[index, index]),
                    defense_standard_error=sqrt(
                        self.covariance[count + index, count + index]
                    ),
                )
            )
        return tuple(sorted(result, key=lambda estimate: estimate.team))

    def snapshot(self) -> dict[str, object]:
        return {
            "name": self.name,
            "version": self.version,
            "last_update": (
                self.last_update.isoformat() if self.last_update is not None else None
            ),
            "observations_seen": self.observations_seen,
            "estimates": [asdict(estimate) for estimate in self.estimates()],
        }

    def _score_design(self, *, offense: str, defense: str) -> np.ndarray:
        count = len(self.teams)
        design = np.zeros(2 * count, dtype=np.float64)
        design[self.indices[offense]] = 1.0
        # Defensive estimates are positive when they suppress opponent scoring.
        design[count + self.indices[defense]] = -1.0
        return design

    def _scalar_update(self, design: np.ndarray, observed_centered: float) -> None:
        projected = np.einsum("ij,j->i", self.covariance, design)
        innovation_variance = (
            float(np.dot(design, projected)) + self.observation_variance
        )
        gain = projected / innovation_variance
        residual = observed_centered - float(np.dot(design, self.mean))
        self.mean += gain * residual
        self.covariance = (
            self.covariance
            - np.outer(projected, projected) / innovation_variance
        )
        self.covariance = (self.covariance + self.covariance.T) / 2.0


@dataclass(frozen=True)
class StintObservation:
    offense_player_ids: tuple[int, ...]
    defense_player_ids: tuple[int, ...]
    points: int
    possessions: float

    def __post_init__(self) -> None:
        if len(self.offense_player_ids) != 5 or len(self.defense_player_ids) != 5:
            raise ValueError("RAPM stint requires two five-player lineups")
        if len(set(self.offense_player_ids)) != 5:
            raise ValueError("offensive lineup contains duplicate players")
        if len(set(self.defense_player_ids)) != 5:
            raise ValueError("defensive lineup contains duplicate players")
        if self.possessions <= 0:
            raise ValueError("stint possessions must be positive")
        if self.points < 0:
            raise ValueError("stint points cannot be negative")


@dataclass(frozen=True)
class PlayerImpactEstimate:
    player_id: int
    offense_per_100: float
    defense_per_100: float
    offense_standard_error: float
    defense_standard_error: float
    possessions: float


class BayesianRAPM:
    """Possession-weighted ridge RAPM with posterior standard errors."""

    name = "bayesian-ridge-rapm"
    version = "0.1.0"

    def __init__(
        self,
        *,
        ridge_strength: float = 800.0,
        league_rating: float = 114.0,
    ) -> None:
        if ridge_strength <= 0:
            raise ValueError("ridge_strength must be positive")
        self.ridge_strength = ridge_strength
        self.league_rating = league_rating
        self._estimates: tuple[PlayerImpactEstimate, ...] = ()

    def fit(
        self,
        stints: Iterable[StintObservation],
        *,
        prior_offense: Mapping[int, float] | None = None,
        prior_defense: Mapping[int, float] | None = None,
    ) -> "BayesianRAPM":
        observations = tuple(stints)
        if not observations:
            raise ValueError("RAPM requires at least one stint")
        players = tuple(
            sorted(
                {
                    player_id
                    for observation in observations
                    for player_id in (
                        observation.offense_player_ids
                        + observation.defense_player_ids
                    )
                }
            )
        )
        indices = {player_id: index for index, player_id in enumerate(players)}
        count = len(players)
        design = np.zeros((len(observations), 2 * count), dtype=np.float64)
        response = np.zeros(len(observations), dtype=np.float64)
        weights = np.zeros(len(observations), dtype=np.float64)
        possessions_by_player = np.zeros(count, dtype=np.float64)

        for row, observation in enumerate(observations):
            for player_id in observation.offense_player_ids:
                design[row, indices[player_id]] = 1.0
                possessions_by_player[indices[player_id]] += observation.possessions
            for player_id in observation.defense_player_ids:
                design[row, count + indices[player_id]] = -1.0
                possessions_by_player[indices[player_id]] += observation.possessions
            response[row] = (
                observation.points * 100.0 / observation.possessions
                - self.league_rating
            )
            weights[row] = observation.possessions

        prior = np.zeros(2 * count, dtype=np.float64)
        prior_offense = prior_offense or {}
        prior_defense = prior_defense or {}
        for player_id, index in indices.items():
            prior[index] = prior_offense.get(player_id, 0.0)
            prior[count + index] = prior_defense.get(player_id, 0.0)

        weighted_design = design * np.sqrt(weights)[:, None]
        weighted_response = response * np.sqrt(weights)
        precision = (
            np.einsum("ni,nj->ij", weighted_design, weighted_design)
            + self.ridge_strength * np.eye(2 * count)
        )
        right_hand_side = (
            np.einsum("ni,n->i", weighted_design, weighted_response)
            + self.ridge_strength * prior
        )
        coefficients = np.linalg.solve(precision, right_hand_side)
        residual = response - np.sum(design * coefficients, axis=1)
        degrees_of_freedom = max(1, len(observations) - min(len(observations), 2 * count))
        residual_variance = float(np.dot(weights, residual**2) / degrees_of_freedom)
        posterior_covariance = residual_variance * np.linalg.inv(precision)

        estimates = []
        for player_id, index in indices.items():
            estimates.append(
                PlayerImpactEstimate(
                    player_id=player_id,
                    offense_per_100=float(coefficients[index]),
                    defense_per_100=float(coefficients[count + index]),
                    offense_standard_error=sqrt(
                        max(0.0, posterior_covariance[index, index])
                    ),
                    defense_standard_error=sqrt(
                        max(
                            0.0,
                            posterior_covariance[
                                count + index,
                                count + index,
                            ],
                        )
                    ),
                    possessions=float(possessions_by_player[index]),
                )
            )
        self._estimates = tuple(
            sorted(estimates, key=lambda estimate: estimate.player_id)
        )
        return self

    @property
    def estimates(self) -> tuple[PlayerImpactEstimate, ...]:
        if not self._estimates:
            raise RuntimeError("RAPM model has not been fitted")
        return self._estimates
