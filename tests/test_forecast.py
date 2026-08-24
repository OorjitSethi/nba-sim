from __future__ import annotations

import unittest

import numpy as np

from nba_sim.forecast.distributions import GameDistribution
from nba_sim.forecast.macro import HeuristicMacroModel
from nba_sim.forecast.reconcile import MomentReconciler
from nba_sim.simulation.game import GameResult
from nba_sim.domain.events import EventLog
from tests.factories import make_team


def mock_results(count: int = 600) -> tuple[GameResult, ...]:
    home = make_team("HOM", id_offset=100)
    away = make_team("AWY", id_offset=200)
    rng = np.random.default_rng(123)
    covariance = np.asarray(((13.0**2, 15.0), (15.0, 19.0**2)))
    values = rng.multivariate_normal((0.0, 218.0), covariance, size=count)
    results = []
    for margin, total in values:
        home_score = max(1, int(round((total + margin) / 2.0)))
        away_score = max(1, int(round((total - margin) / 2.0)))
        if home_score == away_score:
            home_score += 1
        results.append(
            GameResult(
                home_team=home,
                away_team=away,
                home_score=home_score,
                away_score=away_score,
                periods=4,
                seed=len(results),
                events=EventLog(),
                box_scores={},
            )
        )
    return tuple(results)


class MacroForecastTests(unittest.TestCase):
    def test_distribution_and_transparent_prior(self) -> None:
        home = make_team("HOM", id_offset=100)
        away = make_team("AWY", id_offset=200)
        distribution = HeuristicMacroModel().predict(
            home_team=home,
            away_team=away,
        )
        self.assertGreater(distribution.home_win_probability, 0.5)
        self.assertGreater(distribution.mean_total, 180)
        self.assertEqual(distribution.covariance.shape, (2, 2))


class ReconciliationTests(unittest.TestCase):
    def test_exponential_tilting_moves_moments_without_breaking_games(self) -> None:
        results = mock_results()
        target = GameDistribution(
            home_team="HOM",
            away_team="AWY",
            mean_margin=4.0,
            margin_standard_deviation=13.0,
            mean_total=226.0,
            total_standard_deviation=19.0,
            margin_total_correlation=0.05,
            model_name="test",
            model_version="1",
        )
        reconciled = MomentReconciler().reconcile(results, target)
        summary = reconciled.as_dict()
        raw_margin = np.mean([result.margin for result in results])
        raw_total = np.mean([result.total for result in results])
        self.assertLess(
            abs(float(summary["mean_margin"]) - target.mean_margin),
            abs(raw_margin - target.mean_margin),
        )
        self.assertLess(
            abs(float(summary["mean_total"]) - target.mean_total),
            abs(raw_total - target.mean_total),
        )
        self.assertAlmostEqual(reconciled.weights.sum(), 1.0)
        self.assertGreater(reconciled.effective_sample_size, 50)
        self.assertEqual(reconciled.results, results)

    def test_matchup_mismatch_is_rejected(self) -> None:
        target = GameDistribution(
            home_team="XXX",
            away_team="AWY",
            mean_margin=0.0,
            margin_standard_deviation=13.0,
            mean_total=220.0,
            total_standard_deviation=18.0,
        )
        with self.assertRaisesRegex(ValueError, "matchup"):
            MomentReconciler().reconcile(mock_results(30), target)


if __name__ == "__main__":
    unittest.main()
