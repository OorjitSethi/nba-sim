from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from nba_sim.forecast.distributions import GameDistribution
from nba_sim.simulation.game import GameResult


def _stable_softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.max(logits)
    weights = np.exp(shifted)
    return weights / weights.sum()


def _weighted_quantile(
    values: np.ndarray,
    weights: np.ndarray,
    quantile: float,
) -> float:
    if not 0.0 <= quantile <= 1.0:
        raise ValueError("quantile must be in [0, 1]")
    order = np.argsort(values)
    ordered_values = values[order]
    ordered_weights = weights[order]
    cumulative = np.cumsum(ordered_weights)
    index = min(
        len(values) - 1,
        int(np.searchsorted(cumulative, quantile, side="left")),
    )
    return float(ordered_values[index])


@dataclass(frozen=True)
class ReconciledEnsemble:
    results: tuple[GameResult, ...]
    weights: np.ndarray
    target: GameDistribution
    converged: bool
    iterations: int

    def __post_init__(self) -> None:
        weights = np.asarray(self.weights, dtype=np.float64).copy()
        if weights.shape != (len(self.results),):
            raise ValueError("weight vector does not align with game results")
        if np.any(weights < 0) or not np.isclose(weights.sum(), 1.0):
            raise ValueError("weights must be non-negative and sum to one")
        weights.flags.writeable = False
        object.__setattr__(self, "weights", weights)

    @property
    def margins(self) -> np.ndarray:
        return np.asarray([result.margin for result in self.results], dtype=float)

    @property
    def totals(self) -> np.ndarray:
        return np.asarray([result.total for result in self.results], dtype=float)

    @property
    def effective_sample_size(self) -> float:
        return 1.0 / float(np.sum(self.weights**2))

    def as_dict(self) -> dict[str, object]:
        margins = self.margins
        totals = self.totals
        home_win_probability = float(np.dot(self.weights, margins > 0))
        return {
            "trials": len(self.results),
            "converged": self.converged,
            "iterations": self.iterations,
            "effective_sample_size": round(self.effective_sample_size, 3),
            "home_win_probability": round(home_win_probability, 6),
            "away_win_probability": round(1.0 - home_win_probability, 6),
            "mean_margin": round(float(np.dot(self.weights, margins)), 4),
            "mean_total": round(float(np.dot(self.weights, totals)), 4),
            "margin_quantiles": {
                f"{quantile:.2f}": round(
                    _weighted_quantile(margins, self.weights, quantile),
                    3,
                )
                for quantile in (0.05, 0.25, 0.50, 0.75, 0.95)
            },
            "total_quantiles": {
                f"{quantile:.2f}": round(
                    _weighted_quantile(totals, self.weights, quantile),
                    3,
                )
                for quantile in (0.05, 0.25, 0.50, 0.75, 0.95)
            },
            "target": self.target.as_dict(),
        }


class MomentReconciler:
    """Minimum-KL exponential tilting of coherent micro simulations."""

    def __init__(
        self,
        *,
        maximum_iterations: int = 80,
        tolerance: float = 2e-3,
        ridge: float = 1e-5,
    ) -> None:
        self.maximum_iterations = maximum_iterations
        self.tolerance = tolerance
        self.ridge = ridge

    def reconcile(
        self,
        results: tuple[GameResult, ...],
        target: GameDistribution,
    ) -> ReconciledEnsemble:
        if len(results) < 25:
            raise ValueError("reconciliation requires at least 25 simulations")
        if any(
            result.home_team.abbreviation != target.home_team
            or result.away_team.abbreviation != target.away_team
            for result in results
        ):
            raise ValueError("simulation matchup does not match macro target")

        margins = np.asarray([result.margin for result in results], dtype=float)
        totals = np.asarray([result.total for result in results], dtype=float)
        raw_mean = np.asarray((margins.mean(), totals.mean()))
        raw_scale = np.asarray((margins.std(), totals.std()))
        if np.any(raw_scale < 1e-6):
            raise ValueError("simulation ensemble has degenerate variance")
        z_margin = (margins - raw_mean[0]) / raw_scale[0]
        z_total = (totals - raw_mean[1]) / raw_scale[1]
        features = np.column_stack(
            (
                z_margin,
                z_total,
                z_margin**2,
                z_total**2,
                z_margin * z_total,
            )
        )

        target_mean = np.asarray((target.mean_margin, target.mean_total))
        # Prevent impossible requests outside the finite Monte Carlo support.
        target_mean[0] = np.clip(
            target_mean[0],
            np.min(margins) + 0.25,
            np.max(margins) - 0.25,
        )
        target_mean[1] = np.clip(
            target_mean[1],
            np.min(totals) + 0.25,
            np.max(totals) - 0.25,
        )
        mean_z = (target_mean - raw_mean) / raw_scale
        margin_sd_z = np.clip(
            target.margin_standard_deviation / raw_scale[0],
            0.55,
            1.6,
        )
        total_sd_z = np.clip(
            target.total_standard_deviation / raw_scale[1],
            0.55,
            1.6,
        )
        target_moments = np.asarray(
            (
                mean_z[0],
                mean_z[1],
                margin_sd_z**2 + mean_z[0] ** 2,
                total_sd_z**2 + mean_z[1] ** 2,
                target.margin_total_correlation * margin_sd_z * total_sd_z
                + mean_z[0] * mean_z[1],
            )
        )

        theta = np.zeros(features.shape[1], dtype=float)
        weights = np.full(len(results), 1.0 / len(results))
        converged = False
        completed_iterations = 0
        for iteration in range(1, self.maximum_iterations + 1):
            completed_iterations = iteration
            weights = _stable_softmax(np.sum(features * theta, axis=1))
            current = np.sum(features * weights[:, None], axis=0)
            error = target_moments - current
            if float(np.max(np.abs(error))) < self.tolerance:
                converged = True
                break
            centered = features - current
            covariance = np.einsum(
                "ni,nj,n->ij",
                centered,
                centered,
                weights,
            )
            step = np.linalg.solve(
                covariance + self.ridge * np.eye(covariance.shape[0]),
                error,
            )

            base_error = float(np.linalg.norm(error))
            accepted = False
            for factor in (1.0, 0.5, 0.25, 0.1, 0.05):
                candidate = np.clip(theta + factor * step, -20.0, 20.0)
                candidate_weights = _stable_softmax(
                    np.sum(features * candidate, axis=1)
                )
                candidate_current = np.sum(
                    features * candidate_weights[:, None],
                    axis=0,
                )
                candidate_error = target_moments - candidate_current
                if float(np.linalg.norm(candidate_error)) < base_error:
                    theta = candidate
                    accepted = True
                    break
            if not accepted:
                break

        weights = _stable_softmax(np.sum(features * theta, axis=1))
        return ReconciledEnsemble(
            results=results,
            weights=weights,
            target=target,
            converged=converged,
            iterations=completed_iterations,
        )
