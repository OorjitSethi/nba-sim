from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from nba_sim.web import DashboardService


class RosterOperationsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        database = Path(__file__).parents[1] / "ETL" / "nba_universe.db"
        self.service = DashboardService(
            database,
            warehouse_path=Path(self.temporary.name) / "warehouse.sqlite",
        )
        self.created = self.service.create_franchise(
            {"name": "Rotation Test", "user_team": "LAL", "seed": 310}
        )
        self.save_id = self.created["save"]["save_id"]

    def test_new_save_has_complete_persistent_league_rotations(self) -> None:
        operations = self.created["roster_operations"]
        self.assertTrue(operations["ready"])
        self.assertEqual(self.created["coverage"]["roster_plans"]["records"], 30)
        self.assertEqual(operations["metrics"]["starters"], 5)
        self.assertEqual(operations["metrics"]["target_minutes"], 240.0)
        replay = self.service.load_franchise({"save_id": self.save_id})
        self.assertTrue(replay["integrity"]["verified"])
        self.assertEqual(
            replay["roster_operations"]["assignments"],
            operations["assignments"],
        )

    def test_manual_assignments_and_role_promises_are_saved(self) -> None:
        assignments = self.created["roster_operations"]["assignments"]
        payload_rows = [dict(item) for item in assignments]
        payload_rows[-1]["designation"] = "g_league"
        payload_rows[0]["role_promise"] = "star"
        updated = self.service.save_roster_plan(
            {
                "save_id": self.save_id,
                "delegation": "manual",
                "objective": "development",
                "assignments": payload_rows,
            }
        )
        operations = updated["roster_operations"]
        self.assertEqual(operations["delegation"], "manual")
        self.assertEqual(operations["objective"], "development")
        self.assertEqual(operations["metrics"]["target_minutes"], 240.0)
        self.assertEqual(operations["metrics"]["g_league_assignments"], 1)
        self.assertEqual(operations["metrics"]["role_promises"], 1)

    def test_automatic_staff_sits_and_then_reactivates_out_player(self) -> None:
        automatic = self.service.optimize_roster_plan(
            {
                "save_id": self.save_id,
                "delegation": "automatic",
                "objective": "win_now",
            }
        )
        player = automatic["roster_operations"]["assignments"][0]
        out = self.service.update_franchise_health(
            {
                "save_id": self.save_id,
                "player_id": player["player_id"],
                "availability": "out",
                "body_area": "lower body",
            }
        )
        out_row = next(
            item for item in out["roster_operations"]["assignments"]
            if item["player_id"] == player["player_id"]
        )
        self.assertEqual(out_row["designation"], "inactive")
        self.assertEqual(out_row["target_minutes"], 0.0)
        available = self.service.update_franchise_health(
            {
                "save_id": self.save_id,
                "player_id": player["player_id"],
                "availability": "available",
            }
        )
        available_row = next(
            item for item in available["roster_operations"]["assignments"]
            if item["player_id"] == player["player_id"]
        )
        self.assertEqual(available_row["designation"], "standard")
        self.assertGreater(available_row["target_minutes"], 0.0)

    def test_saved_rotation_conditions_matchup_and_two_way_limit_is_enforced(self) -> None:
        assignments = [dict(item) for item in self.created["roster_operations"]["assignments"]]
        excluded_id = assignments[-1]["player_id"]
        assignments[-1]["designation"] = "inactive"
        saved = self.service.save_roster_plan(
            {
                "save_id": self.save_id,
                "delegation": "manual",
                "objective": "balanced",
                "assignments": assignments,
            }
        )
        game = self.service.run_matchup(
            {
                "mode": "single",
                "home": "LAL",
                "away": "BOS",
                "seed": 311,
                "include_events": False,
                "franchise_save_id": saved["save"]["save_id"],
            }
        )
        self.assertNotIn(excluded_id, {item["player_id"] for item in game["box_scores"]})

        invalid = [dict(item) for item in saved["roster_operations"]["assignments"]]
        for item in invalid[:4]:
            item["designation"] = "two_way"
        with self.assertRaisesRegex(ValueError, "at most three two-way"):
            self.service.save_roster_plan(
                {
                    "save_id": self.save_id,
                    "delegation": "manual",
                    "objective": "balanced",
                    "assignments": invalid,
                }
            )


if __name__ == "__main__":
    unittest.main()
