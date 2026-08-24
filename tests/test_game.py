from __future__ import annotations

import unittest

from nba_sim.domain.events import EventType
from nba_sim.simulation.game import GameSimulator
from nba_sim.simulation.monte_carlo import run_monte_carlo
from tests.factories import make_team


class FullGameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.home = make_team("HOM", id_offset=100)
        cls.away = make_team("AWY", id_offset=200, defense=0.01)
        cls.simulator = GameSimulator(home_team=cls.home, away_team=cls.away)

    def test_seeded_game_is_exactly_reproducible(self) -> None:
        first = self.simulator.simulate(seed=2026)
        second = self.simulator.simulate(seed=2026)
        self.assertEqual(first.as_dict(include_events=True), second.as_dict(include_events=True))

    def test_game_and_box_score_invariants(self) -> None:
        result = self.simulator.simulate(seed=41)
        self.assertNotEqual(result.home_score, result.away_score)
        self.assertGreaterEqual(result.periods, 4)
        sequences = [event.sequence for event in result.events]
        self.assertEqual(sequences, list(range(len(sequences))))
        self.assertEqual(result.events.types()[-1], EventType.GAME_ENDED)

        for abbreviation, score in (
            ("HOM", result.home_score),
            ("AWY", result.away_score),
        ):
            team_boxes = result.team_box_scores(abbreviation)
            self.assertEqual(sum(box.points for box in team_boxes), score)
            expected_minutes = 240.0 + max(0, result.periods - 4) * 25.0
            self.assertAlmostEqual(
                sum(box.minutes for box in team_boxes),
                expected_minutes,
                delta=0.15,
            )
            for box in team_boxes:
                self.assertLessEqual(
                    box.field_goals_made,
                    box.field_goals_attempted,
                )
                self.assertLessEqual(box.threes_made, box.threes_attempted)
                self.assertLessEqual(
                    box.free_throws_made,
                    box.free_throws_attempted,
                )

    def test_game_generates_full_event_vocabulary(self) -> None:
        seen: set[EventType] = set()
        for seed in range(8):
            seen.update(self.simulator.simulate(seed=seed).events.types())
        required = {
            EventType.SHOT_ATTEMPT,
            EventType.SHOT_MADE,
            EventType.SHOT_MISSED,
            EventType.FOUL,
            EventType.FREE_THROW_MADE,
            EventType.OFFENSIVE_REBOUND,
            EventType.DEFENSIVE_REBOUND,
            EventType.TURNOVER,
            EventType.SUBSTITUTION,
        }
        self.assertTrue(required.issubset(seen), required - seen)

    def test_monte_carlo_summary_is_reproducible(self) -> None:
        first = run_monte_carlo(self.simulator, trials=20, seed=8)
        second = run_monte_carlo(self.simulator, trials=20, seed=8)
        self.assertEqual(first.as_dict(), second.as_dict())
        self.assertAlmostEqual(
            first.home_win_probability + first.away_win_probability,
            1.0,
        )
        self.assertGreater(first.mean_total, 150)
        self.assertLess(first.mean_total, 300)

    def test_worker_validation_rejects_negative_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "workers"):
            run_monte_carlo(self.simulator, trials=2, seed=8, workers=-1)


if __name__ == "__main__":
    unittest.main()
