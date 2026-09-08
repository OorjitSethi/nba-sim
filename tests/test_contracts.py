from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from nba_sim.web import DashboardService


class ContractFreeAgencyPhaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        database = Path(__file__).parents[1] / "ETL" / "nba_universe.db"
        self.service = DashboardService(
            database,
            warehouse_path=Path(self.temporary.name) / "warehouse.sqlite",
        )
        self.created = self.service.create_franchise(
            {"name": "Contract Test", "user_team": "LAL", "seed": 808}
        )
        self.save_id = self.created["save"]["save_id"]

    def test_new_league_has_complete_modeled_multi_year_ledger(self) -> None:
        market = self.created["contract_market"]
        self.assertTrue(market["ready"])
        self.assertFalse(market["official_salary_data"])
        self.assertEqual(
            self.created["summary"]["counts"]["contracts"],
            self.created["summary"]["counts"]["players"],
        )
        self.assertEqual(len(market["projections"]), 5)
        self.assertEqual(market["projections"][0]["season"], "2026-27")
        self.assertIn("not official", market["data_label"].lower())
        self.assertFalse(self.created["cap_sheet"]["official_salary_data"])

    def test_extension_negotiation_is_durable_and_cannot_repeat(self) -> None:
        target = self.created["contract_market"]["contracts"][0]
        payload = {
            "save_id": self.save_id,
            "player_id": target["player_id"],
            "years": 4,
            "annual_salary": target["asking_salary"],
            "role": "star",
        }
        evaluation = self.service.evaluate_contract_extension(payload)["evaluation"]
        self.assertTrue(evaluation["can_sign"])
        signed = self.service.sign_contract_extension(payload)
        row = next(
            item
            for item in signed["contract_market"]["contracts"]
            if item["player_id"] == target["player_id"]
        )
        self.assertFalse(row["extension_eligible"])
        self.assertEqual(
            signed["contract_decision"]["transaction_type"],
            "extension",
        )
        replay = self.service.load_franchise({"save_id": self.save_id})
        self.assertEqual(replay["summary"]["revision"], signed["summary"]["revision"])
        with self.assertRaisesRegex(ValueError, "already signed"):
            self.service.sign_contract_extension(payload)

    def test_option_decision_changes_only_the_option_year(self) -> None:
        target = next(
            item
            for item in self.created["contract_market"]["contracts"]
            if item["option"] is not None
        )
        original = {year["season"]: year for year in target["years"]}
        result = self.service.decide_contract_option(
            {
                "save_id": self.save_id,
                "player_id": target["player_id"],
                "exercise": True,
            }
        )
        updated = next(
            item
            for item in result["contract_market"]["contracts"]
            if item["player_id"] == target["player_id"]
        )
        for year in updated["years"]:
            if year["season"] == target["option"]["season"]:
                self.assertIn(year["option"], {"exercised", None})
            else:
                self.assertEqual(year, original[year["season"]])

    def test_cpu_waivers_create_market_and_signing_moves_player(self) -> None:
        market_result = self.service.run_cpu_contract_market(
            {"save_id": self.save_id, "max_moves": 3}
        )
        self.assertEqual(len(market_result["cpu_contract_moves"]), 3)
        free_agents = market_result["contract_market"]["free_agents"]
        self.assertEqual(len(free_agents), 3)
        target = min(free_agents, key=lambda item: item["asking_salary"])
        payload = {
            "save_id": self.save_id,
            "player_id": target["player_id"],
            "years": 4,
            "annual_salary": target["asking_salary"],
            "role": "star",
        }
        evaluation = self.service.evaluate_free_agent_offer(payload)["evaluation"]
        self.assertTrue(evaluation["can_sign"])
        signed = self.service.sign_free_agent(payload)
        self.assertNotIn(
            target["player_id"],
            {item["player_id"] for item in signed["contract_market"]["free_agents"]},
        )
        self.assertIn(
            target["player_id"],
            {item["player_id"] for item in signed["roster"]},
        )
        self.assertEqual(
            signed["events"][0]["event_type"],
            "free_agent_signed",
        )


if __name__ == "__main__":
    unittest.main()
