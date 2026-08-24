from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from nba_sim.data.point_in_time import InjuryObservation, ScheduledGame
from nba_sim.forecast.game_day import (
    resolve_game_availability,
    simulate_calibrated_availability,
    simulate_with_availability,
)
from nba_sim.forecast.distributions import GameDistribution
from tests.factories import make_team


class GameDayForecastTests(unittest.TestCase):
    def setUp(self) -> None:
        self.home = make_team("AAA", id_offset=100)
        self.away = make_team("BBB", id_offset=200)
        self.game = ScheduledGame(
            game_id="g1",
            season="2026-27",
            game_date=date(2026, 10, 20),
            scheduled_at=datetime(2026, 10, 21, 0, tzinfo=timezone.utc),
            home_team="AAA",
            away_team="BBB",
            status=1,
            status_text="8:00 pm ET",
            game_label="Regular Season",
            game_sub_label="",
            arena_name="Test Arena",
            arena_city="Test City",
            arena_state="TS",
        )

    def test_official_name_and_team_are_resolved_to_roster_id(self) -> None:
        availability = resolve_game_availability(
            game=self.game,
            home_team=self.home,
            away_team=self.away,
            observations=(
                InjuryObservation(
                    game_date=self.game.game_date,
                    matchup="BBB@AAA",
                    team="AAA Test Team",
                    player_name="AAA Player 100",
                    status="Out",
                    reason="Left ankle",
                    report_timestamp=datetime(
                        2026,
                        10,
                        20,
                        18,
                        tzinfo=timezone.utc,
                    ),
                ),
            ),
        )
        self.assertEqual(len(availability), 1)
        self.assertEqual(availability[0].player_id, 100)
        self.assertTrue(availability[0].automatically_inactive)

    def test_availability_ensemble_is_reproducible(self) -> None:
        availability = resolve_game_availability(
            game=self.game,
            home_team=self.home,
            away_team=self.away,
            observations=(
                InjuryObservation(
                    game_date=self.game.game_date,
                    matchup="BBB@AAA",
                    team="AAA",
                    player_name="AAA Player 100",
                    status="Out",
                    reason="Left ankle",
                    report_timestamp=datetime(
                        2026,
                        10,
                        20,
                        18,
                        tzinfo=timezone.utc,
                    ),
                ),
            ),
        )
        first = simulate_with_availability(
            home_team=self.home,
            away_team=self.away,
            availability=availability,
            trials=5,
            seed=19,
        ).as_dict()
        second = simulate_with_availability(
            home_team=self.home,
            away_team=self.away,
            availability=availability,
            trials=5,
            seed=19,
        ).as_dict()
        self.assertEqual(first, second)
        self.assertEqual(first["distinct_availability_scenarios"], 1)
        self.assertEqual(first["availability"][0]["player_id"], 100)

    def test_calibrated_availability_preserves_macro_provenance(self) -> None:
        base = GameDistribution(
            home_team="AAA",
            away_team="BBB",
            mean_margin=3.0,
            margin_standard_deviation=13.0,
            mean_total=224.0,
            total_standard_deviation=18.0,
            model_name="chronological-test",
            model_version="1",
        )
        result = simulate_calibrated_availability(
            home_team=self.home,
            away_team=self.away,
            availability=(),
            base_distribution=base,
            trials=100,
            seed=44,
        ).as_dict()
        self.assertEqual(result["trials"], 100)
        self.assertEqual(
            result["base_distribution"]["model_name"],
            "chronological-test",
        )
        self.assertEqual(result["distinct_availability_scenarios"], 1)
        self.assertAlmostEqual(result["mean_roster_margin_delta"], 0.0)


if __name__ == "__main__":
    unittest.main()
