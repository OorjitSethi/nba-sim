from __future__ import annotations

import unittest
from datetime import date

from nba_sim.franchise.draft import (
    DRAFT_CLASS_SIZE,
    draft_response,
    generate_draft_ecosystem,
    make_next_pick,
    run_321_lottery,
    run_draft_combine,
    scout_prospect,
    set_user_board,
)


TEAMS = tuple(f"T{index:02}" for index in range(30))


class DraftEcosystemTests(unittest.TestCase):
    def ecosystem(self, seed: int = 27):
        return generate_draft_ecosystem(
            teams=TEAMS,
            draft_year=2027,
            season="2026-27",
            seed=seed,
            as_of=date(2027, 5, 18),
        )

    def test_class_generation_is_reproducible_and_complete(self) -> None:
        first, first_assets = self.ecosystem()
        second, second_assets = self.ecosystem()
        self.assertEqual(first, second)
        self.assertEqual(first_assets, second_assets)
        self.assertEqual(len(first.prospects), DRAFT_CLASS_SIZE)
        self.assertEqual(len({item.player_id for item in first.prospects}), 75)
        self.assertEqual(len(first_assets), 60)
        self.assertEqual(len(first.user_board), 75)

    def test_browser_response_never_exposes_hidden_truth(self) -> None:
        ecosystem, _ = self.ecosystem()
        response = draft_response(ecosystem, user_team="T00")
        prospect = response["prospects"][0]
        self.assertNotIn("overall", prospect)
        self.assertNotIn("offense", prospect)
        self.assertNotIn("potential", prospect)
        self.assertNotIn("public_score", prospect)
        self.assertIn("overall_mean", prospect)
        self.assertIsNone(prospect["height_inches"])

    def test_scouting_and_combine_narrow_beliefs(self) -> None:
        ecosystem, _ = self.ecosystem()
        target = ecosystem.prospects[0]
        scouted = scout_prospect(
            ecosystem,
            player_id=target.player_id,
            hours=48,
            evaluation_quality=70,
            occurred_on=date(2027, 5, 20),
            seed=ecosystem.class_seed,
            namespace="unit-workout",
        )
        updated = next(
            item for item in scouted.prospects
            if item.player_id == target.player_id
        )
        self.assertLess(updated.report.overall_sd, target.report.overall_sd)
        combined = run_draft_combine(
            scouted,
            occurred_on=date(2027, 5, 22),
            seed=ecosystem.class_seed,
        )
        self.assertTrue(combined.combine_complete)
        response = draft_response(combined, user_team="T00")
        self.assertIsNotNone(response["prospects"][0]["height_inches"])

    def test_321_lottery_draws_sixteen_and_enforces_relegation_floor(self) -> None:
        ecosystem, assets = self.ecosystem()
        strengths = {team: float(index) for index, team in enumerate(TEAMS)}
        lottery = run_321_lottery(
            ecosystem,
            team_strengths=strengths,
            assets=assets,
            seed=4,
        )
        self.assertEqual(len(lottery.order), 60)
        self.assertEqual(len({item.original_team for item in lottery.order[:16]}), 16)
        self.assertEqual(
            sorted(item.lottery_balls for item in lottery.order[:16]),
            sorted([2] * 3 + [3] * 7 + [2] * 4 + [1] * 2),
        )
        positions = {
            item.original_team: item.overall_pick for item in lottery.order[:16]
        }
        self.assertTrue(all(positions[team] <= 12 for team in TEAMS[:3]))

    def test_private_board_and_selections_are_persistent_values(self) -> None:
        ecosystem, assets = self.ecosystem()
        reversed_board = tuple(reversed(ecosystem.user_board))
        ecosystem = set_user_board(ecosystem, reversed_board)
        self.assertEqual(ecosystem.user_board, reversed_board)
        ecosystem = run_321_lottery(
            ecosystem,
            team_strengths={team: float(index) for index, team in enumerate(TEAMS)},
            assets=assets,
            seed=15,
        )
        on_clock = ecosystem.order[0].current_team
        selected_id = ecosystem.user_board[0]
        ecosystem = make_next_pick(
            ecosystem,
            user_team=on_clock,
            player_id=selected_id,
            seed=ecosystem.class_seed,
        )
        self.assertEqual(ecosystem.selections[0].player_id, selected_id)
        self.assertEqual(ecosystem.status, "in_progress")


if __name__ == "__main__":
    unittest.main()
