from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from nba_sim.validation.fidelity import (
    FidelityGate,
    FidelityMetric,
    FidelityReport,
    LeaguePerTeamGameTargets,
)


class FidelityTargetTests(unittest.TestCase):
    def test_legacy_totals_reconstruct_scoring(self) -> None:
        rows = [
            {
                "FGM": 40,
                "FGA": 88,
                "FG3M": 12,
                "FG3A": 34,
                "FTM": 18,
                "FTA": 22,
                "AST": 25,
                "TOV": 13,
                "STL": 7,
                "BLK": 5,
                "PF": 19,
            },
            {
                "FGM": 41,
                "FGA": 90,
                "FG3M": 13,
                "FG3A": 35,
                "FTM": 17,
                "FTA": 21,
                "AST": 26,
                "TOV": 12,
                "STL": 8,
                "BLK": 4,
                "PF": 20,
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "totals.json"
            raw.write_text(json.dumps(rows), encoding="utf-8")
            targets = LeaguePerTeamGameTargets.from_legacy_player_totals(
                raw,
                team_games=2,
            )
        self.assertAlmostEqual(targets.points, 111.0, places=3)
        self.assertAlmostEqual(targets.field_goals_attempted, 89.0, places=3)
        self.assertAlmostEqual(targets.turnovers, 12.5, places=3)
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
