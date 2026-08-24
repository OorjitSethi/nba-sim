from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from nba_sim.data.point_in_time import (
    HistoricalGame,
    InjuryObservation,
    MarketQuote,
    PlayerSeasonStat,
    PointInTimeWarehouse,
    RosterObservation,
    ScheduledGame,
)
from nba_sim.data.provenance import RawSnapshotStore


class PointInTimeWarehouseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.snapshots = RawSnapshotStore(root / "raw")
        self.warehouse = PointInTimeWarehouse(root / "warehouse.sqlite")
        self.t1 = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
        self.t2 = self.t1 + timedelta(days=1)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def snapshot(self, name: str, available_at: datetime):
        return self.snapshots.write_json(
            f"test/{name}.json",
            [{"name": name}],
            source="test",
            dataset="rosters",
            season="2025-26",
            retrieved_at=available_at,
            available_at=available_at,
            schema_version="test-v1",
        )

    def test_roster_query_cannot_see_future_snapshot(self) -> None:
        first = self.snapshot("first", self.t1)
        second = self.snapshot("second", self.t2)
        self.warehouse.ingest_roster(
            first,
            (RosterObservation("2025-26", 1, "AAA", 10, "First Player"),),
        )
        self.warehouse.ingest_roster(
            second,
            (RosterObservation("2025-26", 1, "AAA", 20, "Future Player"),),
        )
        visible = self.warehouse.roster_as_of(
            team="AAA",
            cutoff=self.t1 + timedelta(hours=1),
        )
        self.assertEqual([row.player_id for row in visible], [10])
        latest = self.warehouse.roster_as_of(
            team="AAA",
            cutoff=self.t2 + timedelta(hours=1),
        )
        self.assertEqual([row.player_id for row in latest], [20])

    def test_games_injuries_and_market_quotes_respect_availability(self) -> None:
        game_snapshot = self.snapshot("games", self.t1)
        game = HistoricalGame(
            game_id="g1",
            season="2025-26",
            game_date=date(2026, 1, 1),
            home_team="AAA",
            away_team="BBB",
            home_points=110,
            away_points=104,
            possessions=98.5,
            result_available_at=self.t2,
        )
        self.warehouse.ingest_games(game_snapshot, (game,))
        self.assertEqual(
            self.warehouse.games(known_as_of=self.t1 + timedelta(hours=1)),
            (),
        )
        self.assertEqual(
            self.warehouse.games(known_as_of=self.t2 + timedelta(hours=1))[0],
            game,
        )

        injury_snapshot = self.snapshots.write_json(
            "test/injury.json",
            [{"player": "A"}],
            source="test",
            dataset="injuries",
            season="2025-26",
            retrieved_at=self.t1,
            available_at=self.t1,
            schema_version="test-v1",
        )
        self.warehouse.ingest_injuries(
            injury_snapshot,
            (
                InjuryObservation(
                    game_date=date(2026, 1, 1),
                    matchup="BBB@AAA",
                    team="AAA",
                    player_name="A Player",
                    status="Questionable",
                    reason="Ankle",
                    report_timestamp=self.t1,
                ),
            ),
        )
        self.assertEqual(
            len(
                self.warehouse.injuries_as_of(
                    game_date=date(2026, 1, 1),
                    cutoff=self.t1,
                )
            ),
            1,
        )

        quotes = (
            MarketQuote("g1", "vendor", self.t1, -2.5, 224.5),
            MarketQuote("g1", "vendor", self.t2, -4.0, 226.0),
        )
        self.warehouse.ingest_market_quotes(quotes)
        visible_quote = self.warehouse.market_quote_as_of(
            game_id="g1",
            cutoff=self.t1 + timedelta(hours=1),
        )
        self.assertEqual(visible_quote.home_spread, -2.5)

    def test_player_stats_respect_snapshot_cutoff(self) -> None:
        snapshot = self.snapshots.write_json(
            "test/player-stats.json",
            [{"player": 10}],
            source="test",
            dataset="player-stats",
            season="2025-26",
            retrieved_at=self.t2,
            available_at=self.t2,
            schema_version="test-v1",
        )
        stat = PlayerSeasonStat(
            season="2025-26",
            player_id=10,
            player_name="Test Player",
            team_abbreviation="AAA",
            games_played=60,
            minutes=32.0,
            field_goals_made=8.0,
            field_goals_attempted=17.0,
            threes_made=2.0,
            threes_attempted=6.0,
            free_throws_made=4.0,
            free_throws_attempted=5.0,
            offensive_rebounds=1.0,
            defensive_rebounds=5.0,
            assists=4.0,
            turnovers=2.0,
            steals=1.0,
            blocks=0.5,
            personal_fouls=2.0,
            fouls_drawn=4.0,
            usage_rate=0.25,
            assist_rate=0.22,
            offensive_rebound_rate=0.04,
            defensive_rebound_rate=0.16,
            defensive_rating=112.0,
            pace=101.0,
            player_impact_estimate=0.12,
            height_inches=80.0,
        )
        self.warehouse.ingest_player_stats(snapshot, (stat,))
        self.assertIsNone(
            self.warehouse.latest_player_stat_season(cutoff=self.t1)
        )
        self.assertEqual(
            self.warehouse.latest_player_stat_season(cutoff=self.t2),
            "2025-26",
        )
        self.assertEqual(
            self.warehouse.player_stats_as_of(
                season="2025-26",
                cutoff=self.t1,
            ),
            (),
        )
        self.assertEqual(
            self.warehouse.player_stats_as_of(
                season="2025-26",
                cutoff=self.t2,
            ),
            (stat,),
        )

    def test_schedule_uses_latest_complete_snapshot(self) -> None:
        first = self.snapshots.write_json(
            "test/schedule-first.json",
            [{"game": "g1"}],
            source="test",
            dataset="schedule",
            season="2026-27",
            retrieved_at=self.t1,
            available_at=self.t1,
            schema_version="test-v1",
        )
        second = self.snapshots.write_json(
            "test/schedule-second.json",
            [{"game": "g2"}],
            source="test",
            dataset="schedule",
            season="2026-27",
            retrieved_at=self.t2,
            available_at=self.t2,
            schema_version="test-v1",
        )
        g1 = ScheduledGame(
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
        g2 = ScheduledGame(
            game_id="g2",
            season="2026-27",
            game_date=date(2026, 10, 22),
            scheduled_at=datetime(2026, 10, 23, 0, tzinfo=timezone.utc),
            home_team="CCC",
            away_team="DDD",
            status=1,
            status_text="8:00 pm ET",
            game_label="Regular Season",
            game_sub_label="",
            arena_name="Other Arena",
            arena_city="Other City",
            arena_state="TS",
        )
        self.warehouse.ingest_schedule(first, (g1,))
        self.warehouse.ingest_schedule(second, (g2,))
        self.assertEqual(
            self.warehouse.schedule_as_of(
                season="2026-27",
                cutoff=self.t1,
            ),
            (g1,),
        )
        self.assertEqual(
            self.warehouse.schedule_as_of(
                season="2026-27",
                cutoff=self.t2,
            ),
            (g2,),
        )


if __name__ == "__main__":
    unittest.main()
