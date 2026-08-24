from __future__ import annotations

from dataclasses import asdict, dataclass
from math import erf, sqrt

import numpy as np


@dataclass(frozen=True)
class GameDistribution:
    home_team: str
    away_team: str
    mean_margin: float
    margin_standard_deviation: float
    mean_total: float
    total_standard_deviation: float
    margin_total_correlation: float = 0.0
    model_name: str = "unknown"
    model_version: str = "unversioned"

    def __post_init__(self) -> None:
        if self.home_team == self.away_team:
            raise ValueError("distribution requires two different teams")
        if self.margin_standard_deviation <= 0:
            raise ValueError("margin standard deviation must be positive")
        if self.total_standard_deviation <= 0:
            raise ValueError("total standard deviation must be positive")
        if not -0.99 < self.margin_total_correlation < 0.99:
            raise ValueError("correlation must be strictly between -0.99 and 0.99")

    @property
    def home_win_probability(self) -> float:
        z = self.mean_margin / self.margin_standard_deviation
        return 0.5 * (1.0 + erf(z / sqrt(2.0)))

    @property
    def covariance(self) -> np.ndarray:
        margin_variance = self.margin_standard_deviation**2
        total_variance = self.total_standard_deviation**2
        covariance = (
            self.margin_total_correlation
            * self.margin_standard_deviation
            * self.total_standard_deviation
        )
        return np.asarray(
            (
                (margin_variance, covariance),
                (covariance, total_variance),
            ),
            dtype=np.float64,
        )

    def as_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["home_win_probability"] = round(self.home_win_probability, 6)
        return result


@dataclass(frozen=True)
class CalibrationObservation:
    predicted: GameDistribution
    observed_margin: float
    observed_total: float
