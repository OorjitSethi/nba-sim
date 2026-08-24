from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timezone
from math import log
from typing import Mapping, Protocol

import numpy as np

from nba_sim.data.point_in_time import HistoricalGame, MarketQuote
from nba_sim.domain.profiles import TeamProfile
from nba_sim.forecast.distributions import CalibrationObservation, GameDistribution
from nba_sim.forecast.ratings import DynamicTeamStrengthModel, GameObservation
from nba_sim.validation.probabilistic import (
    BootstrapDifference,
    ProbabilisticMetrics,
    evaluate_probabilistic_forecasts,
    paired_bootstrap_difference,
)


class OnlineForecastModel(Protocol):
    name: str
    version: str

    def predict(
        self,
        *,
        home_team: TeamProfile,
        away_team: TeamProfile,
    ) -> GameDistribution:
        ...

    def update(self, observation: GameObservation) -> None:
        ...


@dataclass(frozen=True)
class ForecastAuditRecord:
    game_id: str
    game_date: date
    forecast_cutoff: datetime
    model_name: str
    model_version: str
    distribution: GameDistribution
    observed_margin: int
    observed_total: int

    def as_dict(self) -> dict[str, object]:
        return {
            "game_id": self.game_id,
            "game_date": self.game_date.isoformat(),
            "forecast_cutoff": self.forecast_cutoff.isoformat(),
            "model_name": self.model_name,
            "model_version": self.model_version,
            "distribution": self.distribution.as_dict(),
            "observed_margin": self.observed_margin,
            "observed_total": self.observed_total,
        }


@dataclass(frozen=True)
class BacktestComparison:
    baseline: str
    candidate_minus_baseline_log_loss: BootstrapDifference
    candidate_minus_baseline_margin_absolute_error: BootstrapDifference

    def as_dict(self) -> dict[str, object]:
        return {
            "baseline": self.baseline,
            "candidate_minus_baseline_log_loss": asdict(
                self.candidate_minus_baseline_log_loss
            ),
            "candidate_minus_baseline_margin_absolute_error": asdict(
                self.candidate_minus_baseline_margin_absolute_error
            ),
        }


@dataclass(frozen=True)
class ChronologicalBacktestReport:
    evaluation_start: date
    evaluation_end: date
    games: int
    candidate: str
    metrics: Mapping[str, ProbabilisticMetrics]
    comparisons: tuple[BacktestComparison, ...]
    records: tuple[ForecastAuditRecord, ...]

    @property
    def promotion_passed(self) -> bool:
        return all(
            comparison.candidate_minus_baseline_log_loss.upper_95 < 0
            and (
                comparison.candidate_minus_baseline_margin_absolute_error.upper_95
                < 0
            )
            for comparison in self.comparisons
        )

    def as_dict(self, *, include_records: bool = False) -> dict[str, object]:
        result: dict[str, object] = {
            "evaluation_start": self.evaluation_start.isoformat(),
            "evaluation_end": self.evaluation_end.isoformat(),
            "games": self.games,
            "candidate": self.candidate,
            "promotion_passed": self.promotion_passed,
            "promotion_rule": (
                "candidate 95% paired-bootstrap upper bound must be below zero "
                "for log loss and margin absolute error against every baseline"
            ),
            "metrics": {
                name: metrics.as_dict() for name, metrics in self.metrics.items()
            },
            "comparisons": [
                comparison.as_dict() for comparison in self.comparisons
            ],
        }
        if include_records:
            result["records"] = [record.as_dict() for record in self.records]
        return result


class LeagueAverageBaseline:
    name = "rolling-league-average"
    version = "1.0.0"

    def __init__(self, *, prior_total: float = 224.0, prior_home_margin: float = 2.2):
        self._margins = [float(prior_home_margin)] * 50
        self._totals = [float(prior_total)] * 50

    def predict(
        self,
        *,
        home_team: TeamProfile,
        away_team: TeamProfile,
    ) -> GameDistribution:
        return GameDistribution(
            home_team=home_team.abbreviation,
            away_team=away_team.abbreviation,
            mean_margin=float(np.mean(self._margins)),
            margin_standard_deviation=max(10.0, float(np.std(self._margins, ddof=1))),
            mean_total=float(np.mean(self._totals)),
            total_standard_deviation=max(14.0, float(np.std(self._totals, ddof=1))),
            model_name=self.name,
            model_version=self.version,
        )

    def update(self, observation: GameObservation) -> None:
        self._margins.append(float(observation.home_points - observation.away_points))
        self._totals.append(float(observation.home_points + observation.away_points))
        # A three-season window adapts to league scoring without peeking ahead.
        self._margins = self._margins[-3_690:]
        self._totals = self._totals[-3_690:]


class EloForecastBaseline:
    name = "margin-aware-elo"
    version = "1.0.0"

    def __init__(
        self,
        teams: tuple[str, ...],
        *,
        initial_rating: float = 1_500.0,
        home_advantage_elo: float = 65.0,
        k_factor: float = 18.0,
    ) -> None:
        self.ratings = {team: float(initial_rating) for team in teams}
        self.home_advantage_elo = home_advantage_elo
        self.k_factor = k_factor
        self._totals = [224.0] * 50

    def predict(
        self,
        *,
        home_team: TeamProfile,
        away_team: TeamProfile,
    ) -> GameDistribution:
        difference = (
            self.ratings[home_team.abbreviation]
            + self.home_advantage_elo
            - self.ratings[away_team.abbreviation]
        )
        return GameDistribution(
            home_team=home_team.abbreviation,
            away_team=away_team.abbreviation,
            mean_margin=difference / 28.0,
            margin_standard_deviation=13.5,
            mean_total=float(np.mean(self._totals)),
            total_standard_deviation=max(16.0, float(np.std(self._totals, ddof=1))),
            model_name=self.name,
            model_version=self.version,
        )

    def update(self, observation: GameObservation) -> None:
        home = observation.home_team
        away = observation.away_team
        difference = self.ratings[home] + self.home_advantage_elo - self.ratings[away]
        expected = 1.0 / (1.0 + 10.0 ** (-difference / 400.0))
        actual = 1.0 if observation.home_points > observation.away_points else 0.0
        margin = abs(observation.home_points - observation.away_points)
        multiplier = log(max(1.0, margin + 1.0)) * (
            2.2 / (0.001 * abs(difference) + 2.2)
        )
        adjustment = self.k_factor * multiplier * (actual - expected)
        self.ratings[home] += adjustment
        self.ratings[away] -= adjustment
        self._totals.append(
            float(observation.home_points + observation.away_points)
        )
        self._totals = self._totals[-3_690:]


class CalibratedDynamicTeamModel:
    """Dynamic margin ratings plus an independently calibrated league total.

    Margin and total are different forecasting problems. The state-space
    offense/defense model captures relative team strength, while its raw score
    sum is over-responsive to noisy observations. This wrapper preserves the
    dynamic margin distribution and estimates the scoring environment online
    using only results available before each forecast cutoff.
    """

    name = "calibrated-dynamic-team-strength"
    version = "0.2.0"

    def __init__(
        self,
        teams: tuple[str, ...],
        *,
        prior_total: float = 224.0,
        prior_total_weight: int = 50,
        home_court_points: float = 1.5,
        process_standard_deviation_per_day: float = 0.18,
        observation_standard_deviation: float = 9.0,
    ) -> None:
        if prior_total_weight < 2:
            raise ValueError("prior_total_weight must be at least two")
        self.strength = DynamicTeamStrengthModel(
            teams,
            home_court_points=home_court_points,
            process_standard_deviation_per_day=(
                process_standard_deviation_per_day
            ),
            observation_standard_deviation=observation_standard_deviation,
        )
        self._totals = [float(prior_total)] * prior_total_weight

    def predict(
        self,
        *,
        home_team: TeamProfile,
        away_team: TeamProfile,
    ) -> GameDistribution:
        strength = self.strength.predict(
            home_team=home_team,
            away_team=away_team,
        )
        return GameDistribution(
            home_team=strength.home_team,
            away_team=strength.away_team,
            mean_margin=strength.mean_margin,
            margin_standard_deviation=strength.margin_standard_deviation,
            mean_total=float(np.mean(self._totals)),
            total_standard_deviation=max(
                16.0,
                float(np.std(self._totals, ddof=1)),
            ),
            margin_total_correlation=0.0,
            model_name=self.name,
            model_version=self.version,
        )

    def update(self, observation: GameObservation) -> None:
        self.strength.update(observation)
        self._totals.append(
            float(observation.home_points + observation.away_points)
        )
        self._totals = self._totals[-3_690:]


class ChronologicalBacktester:
    """Rolling-origin evaluator that respects result availability timestamps."""

    def __init__(
        self,
        *,
        profiles: Mapping[str, TeamProfile],
        models: Mapping[str, OnlineForecastModel],
        candidate: str,
        bootstrap_samples: int = 2_000,
        bootstrap_seed: int = 0,
    ) -> None:
        self.profiles = dict(profiles)
        self.models = dict(models)
        if candidate not in self.models:
            raise KeyError(candidate)
        if len(self.models) < 2:
            raise ValueError("backtest requires a candidate and at least one baseline")
        if bootstrap_samples <= 0:
            raise ValueError("bootstrap_samples must be positive")
        self.candidate = candidate
        self.bootstrap_samples = bootstrap_samples
        self.bootstrap_seed = bootstrap_seed

    def run(
        self,
        games: tuple[HistoricalGame, ...],
        *,
        evaluation_start: date,
        evaluation_end: date | None = None,
    ) -> ChronologicalBacktestReport:
        if not games:
            raise ValueError("backtest requires historical games")
        ordered = tuple(sorted(games, key=lambda game: (game.game_date, game.game_id)))
        if len({game.game_id for game in ordered}) != len(ordered):
            raise ValueError("historical game IDs must be unique")
        end = evaluation_end or ordered[-1].game_date
        if evaluation_start > end:
            raise ValueError("evaluation_start cannot follow evaluation_end")
        for game in ordered:
            if game.home_team not in self.profiles:
                raise KeyError(game.home_team)
            if game.away_team not in self.profiles:
                raise KeyError(game.away_team)

        records: list[ForecastAuditRecord] = []
        updated: set[str] = set()
        game_dates = sorted({game.game_date for game in ordered if game.game_date <= end})
        for game_date in game_dates:
            cutoff = datetime.combine(
                game_date,
                time(hour=17),
                tzinfo=timezone.utc,
            )
            available = [
                game
                for game in ordered
                if game.game_id not in updated
                and game.result_available_at <= cutoff
            ]
            for completed in available:
                observation = _rating_observation(completed)
                for model in self.models.values():
                    model.update(observation)
                updated.add(completed.game_id)

            if not evaluation_start <= game_date <= end:
                continue
            for game in (
                candidate for candidate in ordered if candidate.game_date == game_date
            ):
                for model_key, model in self.models.items():
                    distribution = model.predict(
                        home_team=self.profiles[game.home_team],
                        away_team=self.profiles[game.away_team],
                    )
                    records.append(
                        ForecastAuditRecord(
                            game_id=game.game_id,
                            game_date=game.game_date,
                            forecast_cutoff=cutoff,
                            model_name=model_key,
                            model_version=model.version,
                            distribution=distribution,
                            observed_margin=game.margin,
                            observed_total=game.total,
                        )
                    )

        evaluation_games = len({record.game_id for record in records})
        if evaluation_games < 2:
            raise ValueError("evaluation window must contain at least two games")
        metrics = {
            model_name: evaluate_probabilistic_forecasts(
                CalibrationObservation(
                    predicted=record.distribution,
                    observed_margin=record.observed_margin,
                    observed_total=record.observed_total,
                )
                for record in records
                if record.model_name == model_name
            )
            for model_name in self.models
        }
        comparisons = self._comparisons(tuple(records))
        return ChronologicalBacktestReport(
            evaluation_start=evaluation_start,
            evaluation_end=end,
            games=evaluation_games,
            candidate=self.candidate,
            metrics=metrics,
            comparisons=comparisons,
            records=tuple(records),
        )

    def _comparisons(
        self,
        records: tuple[ForecastAuditRecord, ...],
    ) -> tuple[BacktestComparison, ...]:
        by_model = {
            model_name: {
                record.game_id: record
                for record in records
                if record.model_name == model_name
            }
            for model_name in self.models
        }
        candidate = by_model[self.candidate]
        result = []
        for index, baseline_name in enumerate(
            name for name in self.models if name != self.candidate
        ):
            baseline = by_model[baseline_name]
            game_ids = sorted(set(candidate) & set(baseline))
            candidate_log = np.asarray(
                [_binary_log_loss(candidate[game_id]) for game_id in game_ids]
            )
            baseline_log = np.asarray(
                [_binary_log_loss(baseline[game_id]) for game_id in game_ids]
            )
            candidate_margin = np.asarray(
                [
                    abs(
                        candidate[game_id].observed_margin
                        - candidate[game_id].distribution.mean_margin
                    )
                    for game_id in game_ids
                ]
            )
            baseline_margin = np.asarray(
                [
                    abs(
                        baseline[game_id].observed_margin
                        - baseline[game_id].distribution.mean_margin
                    )
                    for game_id in game_ids
                ]
            )
            result.append(
                BacktestComparison(
                    baseline=baseline_name,
                    candidate_minus_baseline_log_loss=paired_bootstrap_difference(
                        candidate_log,
                        baseline_log,
                        samples=self.bootstrap_samples,
                        seed=self.bootstrap_seed + 2 * index,
                    ),
                    candidate_minus_baseline_margin_absolute_error=(
                        paired_bootstrap_difference(
                            candidate_margin,
                            baseline_margin,
                            samples=self.bootstrap_samples,
                            seed=self.bootstrap_seed + 2 * index + 1,
                        )
                    ),
                )
            )
        return tuple(result)


def default_backtester(
    profiles: Mapping[str, TeamProfile],
    *,
    bootstrap_samples: int = 2_000,
    bootstrap_seed: int = 0,
) -> ChronologicalBacktester:
    teams = tuple(sorted(profiles))
    # Selected on the 2024-25 validation season, then frozen before the 2025-26
    # test-season evaluation.
    dynamic = CalibratedDynamicTeamModel(
        teams,
        home_court_points=1.5,
        process_standard_deviation_per_day=0.18,
        observation_standard_deviation=9.0,
    )
    models: dict[str, OnlineForecastModel] = {
        dynamic.name: dynamic,
        EloForecastBaseline.name: EloForecastBaseline(teams),
        LeagueAverageBaseline.name: LeagueAverageBaseline(),
    }
    return ChronologicalBacktester(
        profiles=profiles,
        models=models,
        candidate=dynamic.name,
        bootstrap_samples=bootstrap_samples,
        bootstrap_seed=bootstrap_seed,
    )


def market_distribution(
    *,
    game: HistoricalGame,
    quote: MarketQuote,
    margin_standard_deviation: float = 13.5,
    total_standard_deviation: float = 18.5,
) -> GameDistribution:
    if quote.game_id != game.game_id:
        raise ValueError("market quote does not match game")
    return GameDistribution(
        home_team=game.home_team,
        away_team=game.away_team,
        # A home spread of -3 means the market expects the home team by three.
        mean_margin=-quote.home_spread,
        margin_standard_deviation=margin_standard_deviation,
        mean_total=quote.total,
        total_standard_deviation=total_standard_deviation,
        model_name=f"market:{quote.source}",
        model_version="point-in-time-v1",
    )


def _rating_observation(game: HistoricalGame) -> GameObservation:
    return GameObservation(
        game_date=game.game_date,
        home_team=game.home_team,
        away_team=game.away_team,
        home_points=game.home_points,
        away_points=game.away_points,
        possessions=game.possessions,
        neutral_site=game.neutral_site,
    )


def _binary_log_loss(record: ForecastAuditRecord) -> float:
    probability = float(
        np.clip(record.distribution.home_win_probability, 1e-9, 1.0 - 1e-9)
    )
    outcome = 1.0 if record.observed_margin > 0 else 0.0
    return -(outcome * log(probability) + (1.0 - outcome) * log(1.0 - probability))
