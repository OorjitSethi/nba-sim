from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from nba_sim.franchise.careers import (
    CAREER_MODEL_VERSION,
    advance_career_state,
    career_history_response,
    comeback_probability,
    retirement_probability,
)
from nba_sim.franchise.models import CareerDecisionRecord
from nba_sim.web import DashboardService


class PermanentCareerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        service = DashboardService(
            Path(__file__).parents[1] / "ETL" / "nba_universe.db",
            warehouse_path=Path(self.temporary.name) / "warehouse.sqlite",
        )
        created = service.create_franchise(
            {"name": "Career Lab", "user_team": "LAL", "seed": 44}
        )
        self.state = service.franchise_repository.load(
            created["save"]["save_id"]
        ).state

    def test_retirement_hazard_respects_age_ability_work_and_contract(self) -> None:
        elite = retirement_probability(
            age=38,
            overall=94,
            season_minutes=2_600,
            injury_burden=0.0,
            has_active_contract=True,
            roster_status="active",
        )
        fringe = retirement_probability(
            age=38,
            overall=67,
            season_minutes=240,
            injury_burden=0.7,
            has_active_contract=False,
            roster_status="free_agent",
        )
        self.assertIsNotNone(elite)
        self.assertIsNotNone(fringe)
        self.assertLess(elite, fringe)
        self.assertIsNone(retirement_probability(
            age=None,
            overall=80,
            season_minutes=2_000,
            injury_burden=0.0,
            has_active_contract=True,
            roster_status="active",
        ))

    def test_forced_late_career_retirement_is_permanent_and_deterministic(self) -> None:
        lifecycle = self.state.player_lifecycles[0]
        player = next(item for item in self.state.players if item.player_id == lifecycle.player_id)
        lifecycles = tuple(
            replace(item, age=49.0, stage="late_career")
            if item.player_id == player.player_id else item
            for item in self.state.player_lifecycles
        )
        state = replace(self.state, player_lifecycles=lifecycles)
        first = advance_career_state(
            state,
            season_minutes={player.player_id: 1_100.0},
            season_games={player.player_id: 50},
            games_missed={player.player_id: 3},
        )
        second = advance_career_state(
            state,
            season_minutes={player.player_id: 1_100.0},
            season_games={player.player_id: 50},
            games_missed={player.player_id: 3},
        )
        self.assertEqual(
            [item.as_dict() for item in first.decisions],
            [item.as_dict() for item in second.decisions],
        )
        retired = next(item for item in first.players if item.player_id == player.player_id)
        self.assertEqual(retired.roster_status, "retired")
        self.assertEqual(retired.expected_minutes, 0.0)
        decision = next(item for item in first.decisions if item.player_id == player.player_id)
        self.assertEqual(decision.outcome, "retired")
        self.assertEqual(decision.probability, 1.0)
        self.assertTrue(any(player.player_id in item.player_ids for item in first.transactions))
        self.assertTrue(all(
            item.status != "active"
            for item in first.contracts
            if item.player_id == player.player_id
        ))

        retired_state = replace(
            state,
            players=first.players,
            contracts=first.contracts,
            player_lifecycles=first.lifecycles,
            career_decisions=first.decisions,
            transactions=(*state.transactions, *first.transactions),
        )
        history = career_history_response(retired_state)
        record = next(item for item in history["records"] if item["player_id"] == player.player_id)
        self.assertEqual(record["status"], "retired")
        self.assertIsNotNone(record["retirement"])
        self.assertIn(player.player_id, {item.player_id for item in retired_state.players})

    def test_unknown_age_is_never_given_an_actual_retirement_decision(self) -> None:
        lifecycle = self.state.player_lifecycles[0]
        state = replace(
            self.state,
            player_lifecycles=tuple(
                replace(item, age=None, age_source="not_available", stage="unknown")
                if item.player_id == lifecycle.player_id else item
                for item in self.state.player_lifecycles
            ),
        )
        result = advance_career_state(
            state,
            season_minutes={},
            season_games={},
            games_missed={},
        )
        self.assertFalse(any(
            item.player_id == lifecycle.player_id for item in result.decisions
        ))

    def test_rare_comeback_returns_retiree_to_free_agency(self) -> None:
        lifecycle = replace(
            self.state.player_lifecycles[0],
            age=34.0,
            stage="veteran",
            overall=94.0,
        )
        player = next(item for item in self.state.players if item.player_id == lifecycle.player_id)
        retired_player = replace(player, roster_status="retired", expected_minutes=0.0)
        prior = CareerDecisionRecord(
            decision_id=f"career-2025-26-{player.player_id}",
            player_id=player.player_id,
            season="2025-26",
            decided_on=date(2026, 6, 30),
            outcome="retired",
            reason="personal_decision",
            last_team=player.team,
            age=34.0,
            overall=94.0,
            probability=0.1,
            random_draw=0.01,
            season_games=70,
            season_minutes=2_000,
            injury_burden=0.0,
            model_version=CAREER_MODEL_VERSION,
        )
        base = replace(
            self.state,
            season="2026-27",
            players=tuple(retired_player if item.player_id == player.player_id else item for item in self.state.players),
            player_lifecycles=tuple(lifecycle if item.player_id == player.player_id else item for item in self.state.player_lifecycles),
            career_decisions=(prior,),
        )
        self.assertGreater(comeback_probability(age=35, overall=94, seasons_retired=1), 0)
        returned = None
        for seed in range(2_000):
            candidate = advance_career_state(
                replace(base, seed=seed),
                season_minutes={},
                season_games={},
                games_missed={},
            )
            changed = next(item for item in candidate.players if item.player_id == player.player_id)
            if changed.roster_status == "free_agent":
                returned = candidate
                break
        self.assertIsNotNone(returned)
        decision = next(item for item in returned.decisions if item.player_id == player.player_id)
        self.assertEqual(decision.outcome, "returned")
        self.assertTrue(any(item.transaction_type == "comeback" for item in returned.transactions))


if __name__ == "__main__":
    unittest.main()
