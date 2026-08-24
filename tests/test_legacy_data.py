from __future__ import annotations

import unittest
from pathlib import Path

from nba_sim.data.legacy import LegacySQLiteRepository


class LegacyDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        database = Path(__file__).parents[1] / "ETL" / "nba_universe.db"
        cls.repository = LegacySQLiteRepository(database)

    def test_repository_exposes_all_teams(self) -> None:
        teams = self.repository.available_teams()
        self.assertEqual(len(teams), 30)
        self.assertIn("UTA", teams)
        self.assertIn("MEM", teams)

    def test_team_translation_is_coherent(self) -> None:
        team = self.repository.load_team("UTA")
        self.assertEqual(len(team.roster), 10)
        self.assertAlmostEqual(
            sum(player.expected_minutes for player in team.rotation),
            240.0,
            places=6,
        )
        for player in team.roster:
            self.assertTrue(player.shot_zones)
            self.assertGreater(player.usage_rate, 0)


if __name__ == "__main__":
    unittest.main()
