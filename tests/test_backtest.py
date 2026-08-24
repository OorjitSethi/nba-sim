from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone

from nba_sim.data.point_in_time import HistoricalGame, MarketQuote
from nba_sim.validation.backtest import (
    CalibratedDynamicTeamModel,
    default_backtester,
    market_distribution,
)
from nba_sim.forecast.ratings import GameObservation
from tests.factories import make_team


class ChronologicalBacktestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profiles = {
            abbreviation: make_team(
                abbreviation,
                id_offset=index * 100 + 100,
            )
            for index, abbreviation in enumerate(("AAA", "BBB", "CCC", "DDD"))
        }
        start = date(2025, 10, 1)
        self.games = tuple(
            HistoricalGame(
                game_id=f"g{index:03d}",
                season="2025-26",
                game_date=start + timedelta(days=index),
                home_team=("AAA", "BBB", "CCC", "DDD")[index % 4],
                away_team=("BBB", "CCC", "DDD", "AAA")[index % 4],
                home_points=108 + (index % 9),
                away_points=103 + ((index * 3) % 11),
                possessions=97.0 + index % 5,
                result_available_at=datetime.combine(
                    start + timedelta(days=index + 1),
                    datetime.min.time(),
                    tzinfo=timezone.utc,
                )
                + timedelta(hours=12),
            )
            for index in range(30)
        )

    def test_rolling_origin_backtest_produces_aligned_baselines(self) -> None:
        report = default_backtester(
            self.profiles,
            bootstrap_samples=200,
            bootstrap_seed=9,
        ).run(
            self.games,
            evaluation_start=date(2025, 10, 16),
        )
        self.assertEqual(report.games, 15)
        self.assertEqual(len(report.metrics), 3)
        self.assertEqual(len(report.records), 45)
        self.assertEqual(len(report.comparisons), 2)
        self.assertIsInstance(report.promotion_passed, bool)
        for record in report.records:
            game = next(
                game for game in self.games if game.game_id == record.game_id
            )
            self.assertLess(record.forecast_cutoff, game.result_available_at)

    def test_market_spread_sign_is_converted_to_home_margin(self) -> None:
        game = self.games[0]
        quote = MarketQuote(
            game_id=game.game_id,
            source="test",
            quote_timestamp=game.result_available_at - timedelta(hours=8),
            home_spread=-3.5,
            total=226.5,
        )
        distribution = market_distribution(game=game, quote=quote)
        self.assertEqual(distribution.mean_margin, 3.5)
        self.assertEqual(distribution.mean_total, 226.5)

    def test_calibrated_dynamic_total_updates_without_changing_margin_model(self) -> None:
        model = CalibratedDynamicTeamModel(
            tuple(self.profiles),
            prior_total=220.0,
            prior_total_weight=2,
        )
        before = model.predict(
            home_team=self.profiles["AAA"],
            away_team=self.profiles["BBB"],
        )
        model.update(
            GameObservation(
                game_date=date(2025, 10, 1),
                home_team="AAA",
                away_team="BBB",
                home_points=130,
                away_points=120,
                possessions=100.0,
            )
        )
        after = model.predict(
            home_team=self.profiles["AAA"],
            away_team=self.profiles["BBB"],
        )
        self.assertEqual(before.mean_total, 220.0)
        self.assertGreater(after.mean_total, before.mean_total)
        self.assertEqual(after.model_name, model.name)
        self.assertGreater(after.margin_standard_deviation, 0.0)


if __name__ == "__main__":
    unittest.main()
