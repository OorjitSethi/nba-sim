from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from nba_sim.data.legacy import LegacySQLiteRepository
from nba_sim.randomness import RandomStreamFactory
from nba_sim.simulation.game import GameResult, GameSimulator


@dataclass(frozen=True)
class LeaguePerTeamGameTargets:
    season: str
    team_games: int
    points: float
    field_goals_made: float
    field_goals_attempted: float
    threes_made: float
    threes_attempted: float
    free_throws_made: float
    free_throws_attempted: float
    assists: float
    turnovers: float
    steals: float
    blocks: float
    personal_fouls: float

    @classmethod
    def from_legacy_player_totals(
        cls,
        path: str | Path,
        *,
        season: str = "2023-24",
        team_games: int = 2_460,
    ) -> "LeaguePerTeamGameTargets":
        with Path(path).open(encoding="utf-8") as handle:
            rows = json.load(handle)

        def total(key: str) -> float:
            return sum(float(row.get(key) or 0.0) for row in rows)

        points = 2.0 * total("FGM") + total("FG3M") + total("FTM")
        return cls(
            season=season,
            team_games=team_games,
            points=points / team_games,
            field_goals_made=total("FGM") / team_games,
            field_goals_attempted=total("FGA") / team_games,
            threes_made=total("FG3M") / team_games,
            threes_attempted=total("FG3A") / team_games,
            free_throws_made=total("FTM") / team_games,
            free_throws_attempted=total("FTA") / team_games,
            assists=total("AST") / team_games,
            turnovers=total("TOV") / team_games,
            steals=total("STL") / team_games,
            blocks=total("BLK") / team_games,
            personal_fouls=total("PF") / team_games,
        )

    def metric_values(self) -> dict[str, float]:
        values = asdict(self)
        values.pop("season")
        values.pop("team_games")
        return {name: float(value) for name, value in values.items()}


@dataclass(frozen=True)
class FidelityMetric:
    name: str
    target: float
    simulated: float
    absolute_error: float
    absolute_percentage_error: float

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class FidelityReport:
    season: str
    simulated_games: int
    simulated_team_games: int
    metrics: tuple[FidelityMetric, ...]

    @property
    def mean_absolute_percentage_error(self) -> float:
        return float(
            np.mean([metric.absolute_percentage_error for metric in self.metrics])
        )

    @property
    def maximum_absolute_percentage_error(self) -> float:
        return max(metric.absolute_percentage_error for metric in self.metrics)

    def as_dict(self) -> dict[str, object]:
        return {
            "season": self.season,
            "simulated_games": self.simulated_games,
            "simulated_team_games": self.simulated_team_games,
            "mean_absolute_percentage_error": round(
                self.mean_absolute_percentage_error,
                6,
            ),
            "maximum_absolute_percentage_error": round(
                self.maximum_absolute_percentage_error,
                6,
            ),
            "metrics": [metric.as_dict() for metric in self.metrics],
        }


@dataclass(frozen=True)
class FidelityGateResult:
    passed: bool
    enough_games: bool
    mean_error_passed: bool
    maximum_error_passed: bool
    minimum_simulated_games: int
    maximum_mean_absolute_percentage_error: float
    maximum_single_metric_percentage_error: float

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class FidelityGate:
    """A release gate for league-level statistical ecology.

    These thresholds are deliberately wider than one calibration run's observed
    error so the gate measures regressions rather than Monte Carlo noise.
    """

    minimum_simulated_games: int = 30
    maximum_mean_absolute_percentage_error: float = 0.06
    maximum_single_metric_percentage_error: float = 0.12

    def __post_init__(self) -> None:
        if self.minimum_simulated_games <= 0:
            raise ValueError("minimum_simulated_games must be positive")
        if self.maximum_mean_absolute_percentage_error <= 0:
            raise ValueError("mean-error threshold must be positive")
        if self.maximum_single_metric_percentage_error <= 0:
            raise ValueError("maximum-error threshold must be positive")

    def evaluate(self, report: FidelityReport) -> FidelityGateResult:
        enough_games = report.simulated_games >= self.minimum_simulated_games
        mean_passed = (
            report.mean_absolute_percentage_error
            <= self.maximum_mean_absolute_percentage_error
        )
        maximum_passed = (
            report.maximum_absolute_percentage_error
            <= self.maximum_single_metric_percentage_error
        )
        return FidelityGateResult(
            passed=enough_games and mean_passed and maximum_passed,
            enough_games=enough_games,
            mean_error_passed=mean_passed,
            maximum_error_passed=maximum_passed,
            minimum_simulated_games=self.minimum_simulated_games,
            maximum_mean_absolute_percentage_error=(
                self.maximum_mean_absolute_percentage_error
            ),
            maximum_single_metric_percentage_error=(
                self.maximum_single_metric_percentage_error
            ),
        )


def _aggregate_results(results: list[GameResult]) -> dict[str, float]:
    names = (
        "points",
        "field_goals_made",
        "field_goals_attempted",
        "threes_made",
        "threes_attempted",
        "free_throws_made",
        "free_throws_attempted",
        "assists",
        "turnovers",
        "steals",
        "blocks",
        "personal_fouls",
    )
    totals = {name: 0.0 for name in names}
    for result in results:
        for box in result.box_scores.values():
            for name in names:
                totals[name] += float(getattr(box, name))
    denominator = 2.0 * len(results)
    return {name: value / denominator for name, value in totals.items()}


def _report(
    *,
    targets: LeaguePerTeamGameTargets,
    results: list[GameResult],
) -> FidelityReport:
    simulated = _aggregate_results(results)
    metrics = []
    for name, target in targets.metric_values().items():
        value = simulated[name]
        absolute_error = abs(value - target)
        metrics.append(
            FidelityMetric(
                name=name,
                target=round(target, 6),
                simulated=round(value, 6),
                absolute_error=round(absolute_error, 6),
                absolute_percentage_error=round(
                    absolute_error / max(abs(target), 1e-9),
                    6,
                ),
            )
        )
    return FidelityReport(
        season=targets.season,
        simulated_games=len(results),
        simulated_team_games=2 * len(results),
        metrics=tuple(metrics),
    )


def evaluate_legacy_league_fidelity(
    repository: LegacySQLiteRepository,
    *,
    raw_player_totals_path: str | Path,
    games_per_matchup: int = 2,
    seed: int = 0,
) -> FidelityReport:
    if games_per_matchup <= 0:
        raise ValueError("games_per_matchup must be positive")
    targets = LeaguePerTeamGameTargets.from_legacy_player_totals(
        raw_player_totals_path
    )
    streams = RandomStreamFactory(seed)
    pairing_rng = streams.generator("league-pairings")
    abbreviations = list(repository.available_teams())
    pairing_rng.shuffle(abbreviations)
    if len(abbreviations) % 2:
        raise ValueError("league pairing requires an even number of teams")

    results: list[GameResult] = []
    for pair_index in range(0, len(abbreviations), 2):
        first = repository.load_team(abbreviations[pair_index])
        second = repository.load_team(abbreviations[pair_index + 1])
        for game_index in range(games_per_matchup):
            if game_index % 2:
                home, away = second, first
            else:
                home, away = first, second
            simulator = GameSimulator(home_team=home, away_team=away)
            results.append(
                simulator.simulate(
                    seed=streams.seed_for(
                        f"pair:{pair_index // 2}:game:{game_index}"
                    )
                )
            )
    return _report(targets=targets, results=results)
