from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nba_sim.franchise.events import LeagueEventType
from nba_sim.franchise.trading import front_office_profile
from nba_sim.web import DashboardService


class GeneralManagerIntelligenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.service = DashboardService(
            Path(__file__).parents[1] / "ETL" / "nba_universe.db",
            warehouse_path=Path(self.temporary.name) / "warehouse.sqlite",
        )
        self.created = self.service.create_franchise(
            {"name": "Front Office League", "user_team": "LAL", "seed": 2028}
        )
        self.save_id = self.created["save"]["save_id"]

    def test_new_league_has_thirty_persistent_explainable_plans(self) -> None:
        gm = self.created["general_manager"]
        self.assertTrue(gm["ready"])
        self.assertEqual(len(gm["league"]), 30)
        self.assertEqual(sum(gm["direction_counts"].values()), 30)
        self.assertEqual(gm["automatic_teams"], 30)
        for plan in gm["league"]:
            self.assertAlmostEqual(sum(plan["priorities"].values()), 1.0, places=5)
            self.assertTrue(plan["rationale"])
            self.assertTrue(plan["triggers"])
            self.assertFalse(
                set(plan["core_player_ids"]) & set(plan["trade_block_player_ids"])
            )

    def test_manual_mandate_persists_and_drives_trade_ai(self) -> None:
        result = self.service.update_user_gm_plan(
            {
                "save_id": self.save_id,
                "automation_enabled": False,
                "direction": "rebuild",
                "evaluation_horizon": 5,
                "priorities": {
                    "win_now": 5,
                    "development": 45,
                    "flexibility": 20,
                    "draft_capital": 30,
                },
            }
        )
        plan = result["general_manager"]["user_plan"]
        self.assertEqual(plan["direction"], "rebuild")
        self.assertFalse(plan["automation_enabled"])
        self.assertEqual(plan["evaluation_horizon"], 5)
        loaded = self.service.franchise_repository.load(self.save_id)
        profile = front_office_profile(loaded.state, "LAL")
        self.assertEqual(profile.strategy, "rebuilding")
        self.assertEqual(profile.untouchable_player_ids, tuple(plan["core_player_ids"]))

        reviewed = self.service.review_gm_intelligence(
            {"save_id": self.save_id, "reason": "test review"}
        )
        self.assertEqual(
            reviewed["general_manager"]["user_plan"]["direction"],
            "rebuild",
        )
        self.assertTrue(reviewed["integrity"]["verified"])

    def test_older_save_can_initialize_without_changing_rosters(self) -> None:
        loaded = self.service.franchise_repository.load(self.save_id)
        old_shape = replace(loaded.state, gm_plans=(), head_hash="")
        legacy = self.service.franchise_repository.create_save(
            old_shape,
            name="Legacy branch",
        )
        before = [item.as_dict() for item in legacy.state.players]
        initialized = self.service.initialize_gm_intelligence(
            {"save_id": legacy.metadata.save_id}
        )
        replay = self.service.franchise_repository.load(legacy.metadata.save_id)
        self.assertEqual(before, [item.as_dict() for item in replay.state.players])
        self.assertEqual(len(initialized["general_manager"]["league"]), 30)
        self.assertEqual(
            replay.events[-1].event_type,
            LeagueEventType.GM_INTELLIGENCE_INITIALIZED,
        )

    def test_front_office_ai_ui_exposes_guided_and_advanced_modes(self) -> None:
        assets = Path(__file__).parents[1] / "src" / "nba_sim" / "web_assets"
        html = (assets / "index.html").read_text(encoding="utf-8")
        javascript = (assets / "app.js").read_text(encoding="utf-8")
        self.assertIn('data-franchise-tab="gm"', html)
        self.assertIn('id="gm-league-table"', html)
        self.assertIn('id="gm-plan-form"', html)
        self.assertIn('/api/franchise/initialize-gm', javascript)
        self.assertIn('/api/franchise/review-gm', javascript)
        self.assertIn('/api/franchise/update-gm-plan', javascript)


if __name__ == "__main__":
    unittest.main()
