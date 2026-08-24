from __future__ import annotations

import unittest
from dataclasses import replace

from nba_sim.domain.scenarios import condition_team_profile
from nba_sim.simulation.game import GameSimulator
from tests.factories import make_team


class LineupScenarioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.team = make_team("AAA", id_offset=100)

    def test_inactive_player_and_minute_limit_are_redistributed(self) -> None:
        inactive = self.team.roster[0].player_id
        limited = self.team.roster[1].player_id
        conditioned = condition_team_profile(
            self.team,
            inactive_player_ids=(inactive,),
            minute_limits={limited: 30.0},
        )
        self.assertNotIn(inactive, {player.player_id for player in conditioned.roster})
        self.assertAlmostEqual(
            sum(player.expected_minutes for player in conditioned.roster),
            240.0,
            places=8,
        )
        self.assertLessEqual(conditioned.player(limited).expected_minutes, 30.0)
        self.assertEqual(conditioned.minute_limits[limited], 30.0)
        self.assertIn(inactive, {player.player_id for player in self.team.roster})

        opponent = make_team("BBB", id_offset=200)
        result = GameSimulator(
            home_team=conditioned,
            away_team=opponent,
        ).simulate(seed=11)
        # Enforcement occurs at the next dead ball; one possession of overshoot is
        # allowed, but a capped player can never re-enter.
        self.assertLessEqual(result.box_scores[limited].minutes, 30.75)

    def test_illegal_availability_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "fewer than five"):
            condition_team_profile(
                self.team,
                inactive_player_ids=tuple(
                    player.player_id for player in self.team.roster[:-4]
                ),
            )

    def test_insufficient_minute_capacity_is_rejected(self) -> None:
        limits = {player.player_id: 20.0 for player in self.team.roster}
        with self.assertRaisesRegex(ValueError, "240"):
            condition_team_profile(self.team, minute_limits=limits)

    def test_large_offseason_roster_allocates_only_primary_rotation(self) -> None:
        extras = tuple(
            replace(
                self.team.roster[index],
                player_id=9_000 + index,
                name=f"Reserve {index}",
                expected_minutes=5.0,
            )
            for index in range(2)
        )
        expanded = replace(
            self.team,
            roster=self.team.roster + extras,
        )
        conditioned = condition_team_profile(expanded)
        self.assertAlmostEqual(
            sum(player.expected_minutes for player in conditioned.rotation),
            240.0,
        )
        self.assertEqual(
            sum(
                player.expected_minutes
                for player in conditioned.roster
                if player.player_id in {extra.player_id for extra in extras}
            ),
            0.0,
        )


if __name__ == "__main__":
    unittest.main()
