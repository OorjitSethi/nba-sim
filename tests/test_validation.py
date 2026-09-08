from __future__ import annotations

import unittest
from pathlib import Path

from nba_sim.validation.fidelity import (
    FidelityGate,
    FidelityMetric,
    FidelityReport,
    LeaguePerTeamGameTargets,
)


class FidelityTargetTests(unittest.TestCase):
    def test_legacy_totals_reconstruct_known_league_scoring(self) -> None:
        raw = (
            Path(__file__).parents[1]
            / "ETL"
            / "raw_data"
            / "league_roster_raw.json"
        )
        targets = LeaguePerTeamGameTargets.from_legacy_player_totals(raw)
        self.assertAlmostEqual(targets.points, 114.211, places=3)
        self.assertAlmostEqual(targets.field_goals_attempted, 88.902, places=3)
        self.assertAlmostEqual(targets.turnovers, 12.900, places=3)
        self.assertEqual(len(targets.metric_values()), 12)

    def test_release_gate_checks_sample_size_mean_and_worst_metric(self) -> None:
        passing = FidelityReport(
            season="test",
            simulated_games=30,
            simulated_team_games=60,
            metrics=(
                FidelityMetric("a", 1.0, 1.03, 0.03, 0.03),
                FidelityMetric("b", 1.0, 0.91, 0.09, 0.09),
            ),
        )
        self.assertTrue(FidelityGate().evaluate(passing).passed)

        too_small = FidelityReport(
            season="test",
            simulated_games=29,
            simulated_team_games=58,
            metrics=passing.metrics,
        )
        self.assertFalse(FidelityGate().evaluate(too_small).passed)

        regression = FidelityReport(
            season="test",
            simulated_games=30,
            simulated_team_games=60,
            metrics=(FidelityMetric("a", 1.0, 1.13, 0.13, 0.13),),
        )
        result = FidelityGate().evaluate(regression)
        self.assertFalse(result.passed)
        self.assertFalse(result.maximum_error_passed)


if __name__ == "__main__":
    unittest.main()
