from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone

from nba_sim.data.point_in_time import HistoricalGame, ScheduledGame
from nba_sim.forecast.game_context import (
    ScheduleContextModel,
    context_for_scheduled_game,
)


class ScheduleContextTests(unittest.TestCase):
    def test_scheduled_context_tracks_rest_travel_and_neutral_site(self) -> None:
        history = (
            HistoricalGame(
                game_id="old",
                season="2025-26",
                game_date=date(2026, 4, 12),
                home_team="ATL",
                away_team="MEM",
                home_points=110,
                away_points=105,
                possessions=99.0,
                result_available_at=datetime(
                    2026,
                    4,
                    13,
                    12,
                    tzinfo=timezone.utc,
                ),
            ),
        )
        prior = ScheduledGame(
            game_id="pre1",
            season="2026-27",
            game_date=date(2026, 10, 5),
            scheduled_at=datetime(2026, 10, 5, 23, tzinfo=timezone.utc),
            home_team="ATL",
            away_team="MEM",
            status=1,
            status_text="7:00 pm ET",
            game_label="Preseason",
            game_sub_label="",
            arena_name="State Farm Arena",
            arena_city="Atlanta",
            arena_state="GA",
        )
        game = ScheduledGame(
            game_id="pre2",
            season="2026-27",
            game_date=date(2026, 10, 6),
            scheduled_at=datetime(2026, 10, 7, 1, tzinfo=timezone.utc),
            home_team="DEN",
            away_team="MEM",
            status=1,
            status_text="9:00 pm ET",
            game_label="Preseason",
            game_sub_label="",
            arena_name="Ball Arena",
            arena_city="Denver",
            arena_state="CO",
        )
        context = context_for_scheduled_game(
            game,
            historical_games=history,
            season_schedule=(prior, game),
        )
        self.assertTrue(context.away.back_to_back)
        self.assertEqual(context.away.rest_days, 0)
        self.assertGreater(context.away.travel_miles, 1_000)
        self.assertEqual(context.home.rest_days, 7)

    def test_context_model_keeps_learned_effects_behind_holdout_gate(self) -> None:
        start = date(2024, 10, 1)
        teams = ("ATL", "BOS", "DEN", "MEM")
        games = []
        for index in range(240):
            home = teams[index % len(teams)]
            away = teams[(index + 1) % len(teams)]
            game_date = start + timedelta(days=index)
            games.append(
                HistoricalGame(
                    game_id=f"g{index}",
                    season="2024-25" if index < 120 else "2025-26",
                    game_date=game_date,
                    home_team=home,
                    away_team=away,
                    home_points=111 + (index % 5),
                    away_points=108 + (index % 3),
                    possessions=99.0,
                    result_available_at=datetime.combine(
                        game_date + timedelta(days=1),
                        datetime.min.time(),
                        tzinfo=timezone.utc,
                    ),
                )
            )
        model = ScheduleContextModel().fit(
            games,
            evaluation_start=start + timedelta(days=120),
            bootstrap_samples=100,
            seed=8,
        )
        self.assertEqual(model.validation.training_games, 120)
        self.assertEqual(model.validation.holdout_games, 120)
        self.assertIn("home_court", model.validation.coefficients)


if __name__ == "__main__":
    unittest.main()
