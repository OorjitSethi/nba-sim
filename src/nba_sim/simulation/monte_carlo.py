from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
import os

import numpy as np

from nba_sim.randomness import RandomStreamFactory
from nba_sim.simulation.game import GameResult, GameSimulator


@dataclass(frozen=True)
class MonteCarloSummary:
    home_team: str
    away_team: str
    trials: int
    seed: int
    home_win_probability: float
    away_win_probability: float
    mean_home_score: float
    mean_away_score: float
    mean_margin: float
    mean_total: float
    margin_quantiles: dict[str, float]
    total_quantiles: dict[str, float]
    overtime_probability: float

    def as_dict(self) -> dict[str, object]:
        return {
            "home_team": self.home_team,
            "away_team": self.away_team,
            "trials": self.trials,
            "seed": self.seed,
            "home_win_probability": self.home_win_probability,
            "away_win_probability": self.away_win_probability,
            "mean_home_score": self.mean_home_score,
            "mean_away_score": self.mean_away_score,
            "mean_margin": self.mean_margin,
            "mean_total": self.mean_total,
            "margin_quantiles": self.margin_quantiles,
            "total_quantiles": self.total_quantiles,
            "overtime_probability": self.overtime_probability,
        }


def run_monte_carlo(
    simulator: GameSimulator,
    *,
    trials: int,
    seed: int = 0,
    workers: int = 1,
) -> MonteCarloSummary:
    if trials <= 0:
        raise ValueError("trials must be positive")
    workers = _resolve_workers(workers)
    streams = RandomStreamFactory(seed)
    trial_seeds = tuple(
        streams.seed_for(f"trial:{trial}") for trial in range(trials)
    )
    home_scores = np.empty(trials, dtype=np.int32)
    away_scores = np.empty(trials, dtype=np.int32)
    periods = np.empty(trials, dtype=np.int16)
    if workers == 1:
        outputs = (
            _simulate_score((simulator, trial_seed))
            for trial_seed in trial_seeds
        )
        for trial, output in enumerate(outputs):
            home_scores[trial], away_scores[trial], periods[trial] = output
    else:
        chunksize = max(1, trials // (workers * 8))
        try:
            with ProcessPoolExecutor(max_workers=workers) as executor:
                outputs = executor.map(
                    _simulate_score,
                    ((simulator, trial_seed) for trial_seed in trial_seeds),
                    chunksize=chunksize,
                )
                for trial, output in enumerate(outputs):
                    home_scores[trial], away_scores[trial], periods[trial] = output
        except PermissionError:
            # Some managed runtimes prohibit POSIX semaphore inspection. Preserve
            # exact seeds and results through a deterministic serial fallback.
            for trial, trial_seed in enumerate(trial_seeds):
                output = _simulate_score((simulator, trial_seed))
                home_scores[trial], away_scores[trial], periods[trial] = output

    return summarize_simulations(
        home_team=simulator.home_team.abbreviation,
        away_team=simulator.away_team.abbreviation,
        seed=seed,
        home_scores=home_scores,
        away_scores=away_scores,
        periods=periods,
        regulation_periods=simulator.rules.regulation_periods,
    )


def summarize_simulations(
    *,
    home_team: str,
    away_team: str,
    seed: int,
    home_scores: np.ndarray,
    away_scores: np.ndarray,
    periods: np.ndarray,
    regulation_periods: int = 4,
) -> MonteCarloSummary:
    """Summarize score arrays produced by fixed or scenario-varying trials."""

    if not (
        home_scores.ndim == away_scores.ndim == periods.ndim == 1
        and len(home_scores) == len(away_scores) == len(periods)
    ):
        raise ValueError("simulation score arrays must be aligned vectors")
    if len(home_scores) == 0:
        raise ValueError("at least one simulation is required")
    margins = home_scores - away_scores
    totals = home_scores + away_scores
    quantile_levels = (0.05, 0.25, 0.50, 0.75, 0.95)

    def quantiles(values: np.ndarray) -> dict[str, float]:
        return {
            f"{level:.2f}": round(float(value), 3)
            for level, value in zip(
                quantile_levels,
                np.quantile(values, quantile_levels),
            )
        }

    home_win_probability = float(np.mean(margins > 0))
    return MonteCarloSummary(
        home_team=home_team,
        away_team=away_team,
        trials=len(home_scores),
        seed=seed,
        home_win_probability=round(home_win_probability, 6),
        away_win_probability=round(1.0 - home_win_probability, 6),
        mean_home_score=round(float(np.mean(home_scores)), 3),
        mean_away_score=round(float(np.mean(away_scores)), 3),
        mean_margin=round(float(np.mean(margins)), 3),
        mean_total=round(float(np.mean(totals)), 3),
        margin_quantiles=quantiles(margins),
        total_quantiles=quantiles(totals),
        overtime_probability=round(
            float(np.mean(periods > regulation_periods)),
            6,
        ),
    )


def simulate_ensemble(
    simulator: GameSimulator,
    *,
    trials: int,
    seed: int = 0,
    workers: int = 1,
) -> tuple[GameResult, ...]:
    if trials <= 0:
        raise ValueError("trials must be positive")
    workers = _resolve_workers(workers)
    streams = RandomStreamFactory(seed)
    trial_seeds = tuple(
        streams.seed_for(f"trial:{trial}") for trial in range(trials)
    )
    if workers == 1:
        return tuple(
            simulator.simulate(seed=trial_seed) for trial_seed in trial_seeds
        )
    chunksize = max(1, trials // (workers * 8))
    try:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            return tuple(
                executor.map(
                    _simulate_full_game,
                    ((simulator, trial_seed) for trial_seed in trial_seeds),
                    chunksize=chunksize,
                )
            )
    except PermissionError:
        return tuple(
            simulator.simulate(seed=trial_seed) for trial_seed in trial_seeds
        )


def _resolve_workers(workers: int) -> int:
    if workers < 0:
        raise ValueError("workers cannot be negative")
    if workers == 0:
        return max(1, min(os.cpu_count() or 1, 8))
    return workers


def _simulate_score(arguments: tuple[GameSimulator, int]) -> tuple[int, int, int]:
    simulator, seed = arguments
    result = simulator.simulate(seed=seed)
    return result.home_score, result.away_score, result.periods


def _simulate_full_game(arguments: tuple[GameSimulator, int]) -> GameResult:
    simulator, seed = arguments
    return simulator.simulate(seed=seed)
