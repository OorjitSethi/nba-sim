from __future__ import annotations

import unittest
from datetime import date, timedelta

import numpy as np

from nba_sim.forecast.ratings import (
    BayesianRAPM,
    DynamicTeamStrengthModel,
    GameObservation,
    StintObservation,
)
from tests.factories import make_team


class DynamicTeamStrengthTests(unittest.TestCase):
    def test_chronological_updates_learn_team_direction_and_uncertainty(self) -> None:
        model = DynamicTeamStrengthModel(("AAA", "BBB", "CCC", "DDD"))
        observations = []
        start = date(2025, 10, 20)
        for index in range(40):
            opponent = ("BBB", "CCC", "DDD")[index % 3]
            observations.append(
                GameObservation(
                    game_date=start + timedelta(days=index),
                    home_team="AAA",
                    away_team=opponent,
                    home_points=120,
                    away_points=106,
                    possessions=100,
                )
            )
        prior_uncertainty = model.estimates()[0].offense_standard_error
        model.fit(observations)
        estimates = {estimate.team: estimate for estimate in model.estimates()}
        self.assertGreater(estimates["AAA"].offense_per_100, 0)
        self.assertGreater(estimates["AAA"].defense_per_100, 0)
        self.assertLess(estimates["AAA"].offense_standard_error, prior_uncertainty)

        distribution = model.predict(
            home_team=make_team("AAA", id_offset=100),
            away_team=make_team("BBB", id_offset=200),
        )
        self.assertGreater(distribution.mean_margin, 0)
        self.assertGreater(distribution.home_win_probability, 0.5)
        self.assertEqual(model.snapshot()["observations_seen"], 40)

    def test_out_of_order_update_is_rejected(self) -> None:
        model = DynamicTeamStrengthModel(("AAA", "BBB"))
        model.update(
            GameObservation(date(2026, 1, 2), "AAA", "BBB", 110, 100, 98)
        )
        with self.assertRaisesRegex(ValueError, "chronological"):
            model.update(
                GameObservation(date(2026, 1, 1), "AAA", "BBB", 110, 100, 98)
            )


class RAPMTests(unittest.TestCase):
    def test_synthetic_impacts_are_recovered_with_shrinkage(self) -> None:
        rng = np.random.default_rng(14)
        player_ids = np.arange(20) + 1
        true_offense = rng.normal(0.0, 1.5, size=20)
        true_defense = rng.normal(0.0, 1.2, size=20)
        stints = []
        for _ in range(800):
            offense = tuple(
                int(value) for value in rng.choice(player_ids, 5, replace=False)
            )
            remaining = np.asarray(
                [value for value in player_ids if value not in offense]
            )
            defense = tuple(
                int(value) for value in rng.choice(remaining, 5, replace=False)
            )
            possessions = float(rng.integers(5, 20))
            expected_rating = (
                114.0
                + sum(true_offense[player_id - 1] for player_id in offense)
                - sum(true_defense[player_id - 1] for player_id in defense)
            )
            points = max(
                0,
                int(round(expected_rating * possessions / 100.0 + rng.normal(0, 0.4))),
            )
            stints.append(StintObservation(offense, defense, points, possessions))

        model = BayesianRAPM(ridge_strength=50.0).fit(stints)
        estimates = model.estimates
        estimated_offense = np.asarray(
            [estimate.offense_per_100 for estimate in estimates]
        )
        estimated_defense = np.asarray(
            [estimate.defense_per_100 for estimate in estimates]
        )
        self.assertGreater(np.corrcoef(true_offense, estimated_offense)[0, 1], 0.75)
        self.assertGreater(np.corrcoef(true_defense, estimated_defense)[0, 1], 0.70)
        self.assertTrue(all(estimate.offense_standard_error > 0 for estimate in estimates))

    def test_lineup_shape_is_enforced(self) -> None:
        with self.assertRaisesRegex(ValueError, "five-player"):
            StintObservation((1, 2), (3, 4, 5, 6, 7), 2, 1)


if __name__ == "__main__":
    unittest.main()
