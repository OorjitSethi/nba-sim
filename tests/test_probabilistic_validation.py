from __future__ import annotations

import unittest

import numpy as np

from nba_sim.forecast.distributions import CalibrationObservation, GameDistribution
from nba_sim.validation.probabilistic import (
    evaluate_probabilistic_forecasts,
    paired_bootstrap_difference,
)


class ProbabilisticValidationTests(unittest.TestCase):
    def test_metrics_are_finite_and_intervals_are_reported(self) -> None:
        rng = np.random.default_rng(44)
        rows = []
        for index in range(300):
            mean_margin = rng.normal(0, 5)
            mean_total = rng.normal(225, 4)
            observed_margin = rng.normal(mean_margin, 13)
            observed_total = rng.normal(mean_total, 18)
            rows.append(
                CalibrationObservation(
                    predicted=GameDistribution(
                        home_team="HOM",
                        away_team="AWY",
                        mean_margin=mean_margin,
                        margin_standard_deviation=13,
                        mean_total=mean_total,
                        total_standard_deviation=18,
                        model_name="synthetic",
                    ),
                    observed_margin=observed_margin,
                    observed_total=observed_total,
                )
            )
        metrics = evaluate_probabilistic_forecasts(rows)
        self.assertEqual(metrics.observations, 300)
        self.assertTrue(0 <= metrics.brier_score <= 1)
        self.assertLess(metrics.expected_calibration_error, 0.12)
        self.assertIn("0.90", metrics.interval_coverage)
        self.assertGreater(metrics.interval_coverage["0.90"]["margin"], 0.84)
        self.assertLess(metrics.interval_coverage["0.90"]["margin"], 0.96)

    def test_paired_bootstrap_detects_better_candidate(self) -> None:
        rng = np.random.default_rng(8)
        baseline = rng.normal(10.0, 2.0, size=200)
        candidate = baseline - rng.normal(0.8, 0.4, size=200)
        result = paired_bootstrap_difference(
            candidate,
            baseline,
            samples=2_000,
            seed=2,
        )
        self.assertLess(result.upper_95, 0)
        self.assertGreater(result.probability_below_zero, 0.99)

    def test_empty_evaluation_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires"):
            evaluate_probabilistic_forecasts([])


if __name__ == "__main__":
    unittest.main()
