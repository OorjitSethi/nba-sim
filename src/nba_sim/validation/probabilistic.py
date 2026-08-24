from __future__ import annotations

from dataclasses import asdict, dataclass
from math import exp, log, pi, sqrt
from statistics import NormalDist
from typing import Iterable

import numpy as np

from nba_sim.forecast.distributions import CalibrationObservation


_NORMAL = NormalDist()


def _normal_pdf(value: float) -> float:
    return exp(-0.5 * value * value) / sqrt(2.0 * pi)


def _normal_cdf(value: float) -> float:
    return _NORMAL.cdf(value)


def _normal_crps(observed: float, mean: float, standard_deviation: float) -> float:
    z = (observed - mean) / standard_deviation
    return standard_deviation * (
        z * (2.0 * _normal_cdf(z) - 1.0)
        + 2.0 * _normal_pdf(z)
        - 1.0 / sqrt(pi)
    )


@dataclass(frozen=True)
class ProbabilisticMetrics:
    observations: int
    brier_score: float
    log_loss: float
    expected_calibration_error: float
    margin_mae: float
    total_mae: float
    margin_rmse: float
    total_rmse: float
    joint_gaussian_nll: float
    margin_crps: float
    total_crps: float
    interval_coverage: dict[str, dict[str, float]]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def evaluate_probabilistic_forecasts(
    observations: Iterable[CalibrationObservation],
    *,
    calibration_bins: int = 10,
) -> ProbabilisticMetrics:
    rows = tuple(observations)
    if not rows:
        raise ValueError("probabilistic evaluation requires observations")
    if calibration_bins < 2:
        raise ValueError("calibration_bins must be at least two")

    probabilities = np.asarray(
        [row.predicted.home_win_probability for row in rows],
        dtype=float,
    )
    outcomes = np.asarray(
        [float(row.observed_margin > 0) for row in rows],
        dtype=float,
    )
    clipped = np.clip(probabilities, 1e-9, 1.0 - 1e-9)
    brier = float(np.mean((probabilities - outcomes) ** 2))
    log_loss = float(
        -np.mean(outcomes * np.log(clipped) + (1.0 - outcomes) * np.log(1.0 - clipped))
    )
    calibration_error = _expected_calibration_error(
        probabilities,
        outcomes,
        bins=calibration_bins,
    )

    margin_errors = np.asarray(
        [row.observed_margin - row.predicted.mean_margin for row in rows],
        dtype=float,
    )
    total_errors = np.asarray(
        [row.observed_total - row.predicted.mean_total for row in rows],
        dtype=float,
    )
    joint_nll = np.mean(
        [
            _bivariate_gaussian_nll(
                observed=np.asarray((row.observed_margin, row.observed_total)),
                mean=np.asarray(
                    (row.predicted.mean_margin, row.predicted.mean_total)
                ),
                covariance=row.predicted.covariance,
            )
            for row in rows
        ]
    )
    margin_crps = np.mean(
        [
            _normal_crps(
                row.observed_margin,
                row.predicted.mean_margin,
                row.predicted.margin_standard_deviation,
            )
            for row in rows
        ]
    )
    total_crps = np.mean(
        [
            _normal_crps(
                row.observed_total,
                row.predicted.mean_total,
                row.predicted.total_standard_deviation,
            )
            for row in rows
        ]
    )
    coverage = {
        f"{level:.2f}": {
            "margin": _interval_coverage(rows, level=level, field="margin"),
            "total": _interval_coverage(rows, level=level, field="total"),
        }
        for level in (0.50, 0.80, 0.90)
    }
    return ProbabilisticMetrics(
        observations=len(rows),
        brier_score=round(brier, 8),
        log_loss=round(log_loss, 8),
        expected_calibration_error=round(calibration_error, 8),
        margin_mae=round(float(np.mean(np.abs(margin_errors))), 8),
        total_mae=round(float(np.mean(np.abs(total_errors))), 8),
        margin_rmse=round(float(sqrt(np.mean(margin_errors**2))), 8),
        total_rmse=round(float(sqrt(np.mean(total_errors**2))), 8),
        joint_gaussian_nll=round(float(joint_nll), 8),
        margin_crps=round(float(margin_crps), 8),
        total_crps=round(float(total_crps), 8),
        interval_coverage=coverage,
    )


def _expected_calibration_error(
    probabilities: np.ndarray,
    outcomes: np.ndarray,
    *,
    bins: int,
) -> float:
    boundaries = np.linspace(0.0, 1.0, bins + 1)
    result = 0.0
    for index in range(bins):
        if index == bins - 1:
            selected = (
                (probabilities >= boundaries[index])
                & (probabilities <= boundaries[index + 1])
            )
        else:
            selected = (
                (probabilities >= boundaries[index])
                & (probabilities < boundaries[index + 1])
            )
        count = int(selected.sum())
        if count == 0:
            continue
        result += (
            count
            / len(probabilities)
            * abs(float(probabilities[selected].mean() - outcomes[selected].mean()))
        )
    return result


def _bivariate_gaussian_nll(
    *,
    observed: np.ndarray,
    mean: np.ndarray,
    covariance: np.ndarray,
) -> float:
    sign, log_determinant = np.linalg.slogdet(covariance)
    if sign <= 0:
        raise ValueError("forecast covariance must be positive definite")
    residual = observed - mean
    solved = np.linalg.solve(covariance, residual)
    mahalanobis = float(np.dot(residual, solved))
    return 0.5 * (2.0 * log(2.0 * pi) + log_determinant + mahalanobis)


def _interval_coverage(
    rows: tuple[CalibrationObservation, ...],
    *,
    level: float,
    field: str,
) -> float:
    z = _NORMAL.inv_cdf(0.5 + level / 2.0)
    covered = 0
    for row in rows:
        if field == "margin":
            observed = row.observed_margin
            mean = row.predicted.mean_margin
            standard_deviation = row.predicted.margin_standard_deviation
        elif field == "total":
            observed = row.observed_total
            mean = row.predicted.mean_total
            standard_deviation = row.predicted.total_standard_deviation
        else:
            raise ValueError(field)
        covered += abs(observed - mean) <= z * standard_deviation
    return round(covered / len(rows), 8)


@dataclass(frozen=True)
class BootstrapDifference:
    observed_difference: float
    lower_95: float
    upper_95: float
    probability_below_zero: float


def paired_bootstrap_difference(
    candidate_losses: np.ndarray,
    baseline_losses: np.ndarray,
    *,
    samples: int = 10_000,
    seed: int = 0,
) -> BootstrapDifference:
    candidate = np.asarray(candidate_losses, dtype=np.float64)
    baseline = np.asarray(baseline_losses, dtype=np.float64)
    if candidate.shape != baseline.shape or candidate.ndim != 1:
        raise ValueError("paired loss vectors must be one-dimensional and aligned")
    if len(candidate) < 2:
        raise ValueError("bootstrap requires at least two paired observations")
    if samples <= 0:
        raise ValueError("bootstrap samples must be positive")
    differences = candidate - baseline
    rng = np.random.default_rng(seed)
    bootstrap = np.empty(samples, dtype=np.float64)
    for index in range(samples):
        draw = rng.integers(0, len(differences), size=len(differences))
        bootstrap[index] = differences[draw].mean()
    return BootstrapDifference(
        observed_difference=float(differences.mean()),
        lower_95=float(np.quantile(bootstrap, 0.025)),
        upper_95=float(np.quantile(bootstrap, 0.975)),
        probability_below_zero=float(np.mean(bootstrap < 0)),
    )
