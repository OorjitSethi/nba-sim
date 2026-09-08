from __future__ import annotations

import unittest

import numpy as np

from nba_sim.epv.model import CompetingRiskEPVModel, PossessionContext
from nba_sim.simulation.game import GameSimulator
from tests.factories import make_team


class _UncachedEPVModel(CompetingRiskEPVModel):
    """The pre-optimization formulas, retained as an exact parity oracle."""

    def _lineup_three_share(self, lineup):
        attempts = 0.0
        threes = 0.0
        for player in lineup:
            weight = max(0.01, player.usage_rate)
            attempts += weight
            threes += weight * sum(
                profile.frequency
                for zone, profile in player.shot_zones.items()
                if zone.point_value == 3
            )
        return threes / max(attempts, 1e-9)

    def _lineup_defensive_pressure(self, lineup):
        return float(np.mean([
            max(0.0, defender.defensive_impact)
            for defender in lineup
        ]))


class EPVTests(unittest.TestCase):
    def setUp(self) -> None:
        self.home = make_team("HOM", id_offset=100)
        self.away = make_team("AWY", id_offset=200)
        self.model = CompetingRiskEPVModel(integration_step_seconds=0.1)

    def context(self, shot_clock: float) -> PossessionContext:
        return PossessionContext(
            offense=self.home.starting_lineup,
            defense=self.away.starting_lineup,
            ball_handler=self.home.starting_lineup[0],
            period=1,
            period_clock_seconds=300.0,
            shot_clock_seconds=shot_clock,
            score_margin=0,
            offense_is_home=True,
        )

    def test_terminal_hazard_rises_near_shot_clock_expiry(self) -> None:
        early = self.model.hazards(self.context(24.0), elapsed_seconds=0.0)
        late = self.model.hazards(self.context(3.0), elapsed_seconds=0.0)
        self.assertGreater(late.total, early.total)
        self.assertAlmostEqual(
            early.probabilities_given_event().sum(),
            1.0,
        )

    def test_sampled_holding_time_is_clock_bounded(self) -> None:
        rng = np.random.default_rng(17)
        for _ in range(200):
            sample = self.model.sample_terminal_action(self.context(7.0), rng)
            self.assertGreater(sample.elapsed_seconds, 0)
            self.assertLessEqual(sample.elapsed_seconds, 7.0 + 1e-9)

    def test_expected_value_is_finite_and_basketball_scaled(self) -> None:
        value = self.model.expected_possession_value(self.context(24.0))
        self.assertGreater(value, 0.5)
        self.assertLess(value, 2.0)

    def test_cached_lineup_math_preserves_seeded_game_exactly(self) -> None:
        reference = GameSimulator(
            home_team=self.home,
            away_team=self.away,
            epv_model=_UncachedEPVModel(),
        ).simulate(seed=894_211)
        optimized = GameSimulator(
            home_team=self.home,
            away_team=self.away,
            epv_model=CompetingRiskEPVModel(),
        ).simulate(seed=894_211)

        self.assertEqual(optimized.home_score, reference.home_score)
        self.assertEqual(optimized.away_score, reference.away_score)
        self.assertEqual(
            [event.as_dict() for event in optimized.events],
            [event.as_dict() for event in reference.events],
        )
        self.assertEqual(
            {key: value.as_dict() for key, value in optimized.box_scores.items()},
            {key: value.as_dict() for key, value in reference.box_scores.items()},
        )


if __name__ == "__main__":
    unittest.main()
