from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from nba_sim.franchise.trading import TradeRulePolicy
from nba_sim.web import DashboardService


class TradingPhaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        database = Path(__file__).parents[1] / "ETL" / "nba_universe.db"
        self.service = DashboardService(
            database,
            warehouse_path=Path(self.temporary.name) / "warehouse.sqlite",
        )
        created = self.service.create_franchise(
            {"name": "Trade Test", "user_team": "LAL", "seed": 404}
        )
        self.save_id = created["save"]["save_id"]
        self.initialized = self.service.initialize_trade_center(
            {"save_id": self.save_id}
        )
        self.board = self.service.franchise_trade_board(
            {"save_id": self.save_id}
        )

    def package(self, team: str, *, players=(), assets=()):
        return {
            "team": team,
            "player_ids": list(players),
            "asset_ids": list(assets),
        }

    def test_policy_round_trip_and_future_asset_universe(self) -> None:
        self.assertEqual(
            TradeRulePolicy.from_dict(TradeRulePolicy().as_dict()),
            TradeRulePolicy(),
        )
        self.assertEqual(len(self.board["assets"]), 420)
        updated = self.service.update_trade_rules(
            {
                "save_id": self.save_id,
                "salary_matching": False,
                "stepien_rule": False,
                "injury_house_rule": True,
                "ai_to_ai_trades": False,
                "ai_aggressiveness": 0.8,
            }
        )
        policy = updated["trade_center"]["policy"]
        self.assertFalse(policy["salary_matching"])
        self.assertFalse(policy["stepien_rule"])
        self.assertTrue(policy["injury_house_rule"])
        self.assertFalse(policy["ai_to_ai_trades"])
        self.assertEqual(policy["ai_aggressiveness"], 0.8)

    def test_stepien_and_salary_rules_can_each_be_disabled(self) -> None:
        lal_firsts = [
            item for item in self.board["assets"]
            if item["current_team"] == "LAL"
            and item["original_team"] == "LAL"
            and item["round"] == 1
            and item["draft_year"] in {2027, 2028}
        ]
        bos_second = next(
            item for item in self.board["assets"]
            if item["current_team"] == "BOS" and item["round"] == 2
        )
        proposal = [
            self.package("LAL", assets=[item["asset_id"] for item in lal_firsts]),
            self.package("BOS", assets=[bos_second["asset_id"]]),
        ]
        evaluation = self.service.evaluate_franchise_trade(
            {"save_id": self.save_id, "packages": proposal}
        )["evaluation"]
        self.assertIn(
            "stepien_rule",
            {item["rule"] for item in evaluation["blockers"]},
        )
        self.service.update_trade_rules(
            {
                "save_id": self.save_id,
                "stepien_rule": False,
                "ai_acceptance": False,
            }
        )
        evaluation = self.service.evaluate_franchise_trade(
            {"save_id": self.save_id, "packages": proposal}
        )["evaluation"]
        self.assertNotIn(
            "stepien_rule",
            {item["rule"] for item in evaluation["blockers"]},
        )

        expensive = max(
            (item for item in self.board["players"] if item["team"] == "LAL"),
            key=lambda item: item["salary"],
        )
        cheap = min(
            (item for item in self.board["players"] if item["team"] == "BOS"),
            key=lambda item: item["salary"],
        )
        reverse = [
            self.package("LAL", players=[expensive["player_id"]]),
            self.package("BOS", players=[cheap["player_id"]]),
        ]
        self.service.update_trade_rules(
            {"save_id": self.save_id, "salary_matching": True}
        )
        salary_result = self.service.evaluate_franchise_trade(
            {"save_id": self.save_id, "packages": reverse}
        )["evaluation"]
        self.assertIn(
            "salary_matching",
            {item["rule"] for item in salary_result["blockers"]},
        )
        self.service.update_trade_rules(
            {"save_id": self.save_id, "salary_matching": False}
        )
        salary_result = self.service.evaluate_franchise_trade(
            {"save_id": self.save_id, "packages": reverse}
        )["evaluation"]
        self.assertNotIn(
            "salary_matching",
            {item["rule"] for item in salary_result["blockers"]},
        )

    def test_executed_trade_moves_players_and_replays(self) -> None:
        lal = min(
            (item for item in self.board["players"] if item["team"] == "LAL"),
            key=lambda item: item["trade_value"],
        )
        bos = min(
            (item for item in self.board["players"] if item["team"] == "BOS"),
            key=lambda item: abs(item["trade_value"] - lal["trade_value"]),
        )
        self.service.update_trade_rules(
            {
                "save_id": self.save_id,
                "salary_matching": False,
                "first_apron": False,
                "second_apron": False,
                "roster_limits": False,
                "ai_acceptance": False,
            }
        )
        packages = [
            self.package("LAL", players=[lal["player_id"]]),
            self.package("BOS", players=[bos["player_id"]]),
        ]
        completed = self.service.execute_franchise_trade(
            {"save_id": self.save_id, "packages": packages}
        )
        self.assertEqual(completed["trade_completed"]["transaction_type"], "trade")
        replay = self.service.load_franchise({"save_id": self.save_id})
        new_board = self.service.franchise_trade_board({"save_id": self.save_id})
        moved_lal = next(
            item for item in new_board["players"]
            if item["player_id"] == lal["player_id"]
        )
        moved_bos = next(
            item for item in new_board["players"]
            if item["player_id"] == bos["player_id"]
        )
        self.assertEqual(moved_lal["team"], "BOS")
        self.assertEqual(moved_bos["team"], "LAL")
        self.assertTrue(replay["integrity"]["verified"])
        self.assertEqual(len(replay["trade_center"]["recent_trades"]), 1)

    def test_cpu_market_excludes_user_team_and_is_event_sourced(self) -> None:
        self.service.update_trade_rules(
            {
                "save_id": self.save_id,
                "salary_matching": False,
                "first_apron": False,
                "second_apron": False,
                "roster_limits": False,
                "ai_aggressiveness": 1,
            }
        )
        result = self.service.run_ai_trade_market(
            {"save_id": self.save_id, "max_deals": 2}
        )
        self.assertGreaterEqual(result["ai_trades_made"], 1)
        self.assertLessEqual(result["ai_trades_made"], 2)
        for record in result["ai_trade_records"]:
            self.assertNotIn("LAL", record["teams"])
        replay = self.service.load_franchise({"save_id": self.save_id})
        self.assertTrue(replay["integrity"]["verified"])
        self.assertEqual(
            len(replay["trade_center"]["recent_trades"]),
            result["ai_trades_made"],
        )

    def test_injury_rule_is_optional_and_weekly_cpu_market_is_automatic(self) -> None:
        lal = next(
            item for item in self.board["players"] if item["team"] == "LAL"
        )
        bos = min(
            (item for item in self.board["players"] if item["team"] == "BOS"),
            key=lambda item: abs(item["trade_value"] - lal["trade_value"]),
        )
        self.service.update_franchise_health(
            {
                "save_id": self.save_id,
                "player_id": lal["player_id"],
                "availability": "out",
                "body_area": "lower body",
                "detail": "test restriction",
            }
        )
        packages = [
            self.package("LAL", players=[lal["player_id"]]),
            self.package("BOS", players=[bos["player_id"]]),
        ]
        self.service.update_trade_rules(
            {
                "save_id": self.save_id,
                "salary_matching": False,
                "first_apron": False,
                "second_apron": False,
                "roster_limits": False,
                "ai_acceptance": False,
                "injury_house_rule": False,
            }
        )
        allowed = self.service.evaluate_franchise_trade(
            {"save_id": self.save_id, "packages": packages}
        )["evaluation"]
        self.assertNotIn(
            "injury_house_rule",
            {item["rule"] for item in allowed["blockers"]},
        )
        self.service.update_trade_rules(
            {"save_id": self.save_id, "injury_house_rule": True}
        )
        blocked = self.service.evaluate_franchise_trade(
            {"save_id": self.save_id, "packages": packages}
        )["evaluation"]
        self.assertIn(
            "injury_house_rule",
            {item["rule"] for item in blocked["blockers"]},
        )

        self.service.update_trade_rules(
            {
                "save_id": self.save_id,
                "injury_house_rule": False,
                "ai_acceptance": True,
                "ai_aggressiveness": 1,
            }
        )
        advanced = self.service.advance_franchise_date(
            {"save_id": self.save_id, "days": 7}
        )
        self.assertEqual(len(advanced["trade_center"]["recent_trades"]), 1)
        self.assertNotIn(
            "LAL",
            advanced["trade_center"]["recent_trades"][0]["teams"],
        )


if __name__ == "__main__":
    unittest.main()
