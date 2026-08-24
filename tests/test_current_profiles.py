from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from nba_sim.data.current_profiles import CurrentRosterProfileRepository
from nba_sim.data.legacy import LegacySQLiteRepository
from nba_sim.data.point_in_time import (
    PlayerSeasonStat,
    PointInTimeWarehouse,
    RosterObservation,
)
from nba_sim.data.provenance import RawSnapshotStore
from nba_sim.web import DashboardService


class CurrentRosterProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.database = Path(__file__).parents[1] / "ETL" / "nba_universe.db"
        self.warehouse = PointInTimeWarehouse(self.root / "warehouse.sqlite")
        available = datetime(2026, 7, 25, 0, tzinfo=timezone.utc)
        snapshot = RawSnapshotStore(self.root / "raw").write_json(
            Path("2026-27") / "rosters" / "current.json",
            {"test": True},
            source="test",
            dataset="rosters",
            season="2026-27",
            retrieved_at=available,
            available_at=available,
            schema_version="test-v1",
            rights_tier="test",
        )
        players = (
            (1628374, "Lauri Markkanen"),
            (1641718, "Keyonte George"),
            (1641729, "Brice Sensabaugh"),
            (1628991, "Jaren Jackson Jr."),
            (1642846, "Ace Bailey"),
            (9_999_999, "New Prospect"),
        )
        self.warehouse.ingest_roster(
            snapshot,
            (
                RosterObservation(
                    season="2026-27",
                    team_id=1,
                    team_abbreviation="UTA",
                    player_id=player_id,
                    player_name=name,
                )
                for player_id, name in players
            ),
        )
        stat_snapshot = RawSnapshotStore(self.root / "raw").write_json(
            Path("2025-26") / "player-stats" / "complete.json",
            {"test": True},
            source="test",
            dataset="player-stats",
            season="2025-26",
            retrieved_at=available,
            available_at=available,
            schema_version="test-v1",
            rights_tier="test",
        )
        self.warehouse.ingest_player_stats(
            stat_snapshot,
            (
                PlayerSeasonStat(
                    season="2025-26",
                    player_id=1628374,
                    player_name="Lauri Markkanen",
                    team_abbreviation="UTA",
                    games_played=60,
                    minutes=34.0,
                    field_goals_made=9.0,
                    field_goals_attempted=19.0,
                    threes_made=3.0,
                    threes_attempted=8.0,
                    free_throws_made=5.0,
                    free_throws_attempted=6.0,
                    offensive_rebounds=2.0,
                    defensive_rebounds=5.0,
                    assists=2.0,
                    turnovers=1.5,
                    steals=1.0,
                    blocks=0.5,
                    personal_fouls=2.0,
                    fouls_drawn=5.0,
                    usage_rate=0.28,
                    assist_rate=0.11,
                    offensive_rebound_rate=0.05,
                    defensive_rebound_rate=0.14,
                    defensive_rating=112.0,
                    pace=102.0,
                    player_impact_estimate=0.14,
                    height_inches=85.0,
                ),
            ),
        )
        self.cutoff = datetime(2026, 7, 26, tzinfo=timezone.utc)

    def test_current_membership_overlays_historical_and_explicit_priors(self) -> None:
        repository = CurrentRosterProfileRepository(
            legacy=LegacySQLiteRepository(self.database),
            warehouse=self.warehouse,
            cutoff=self.cutoff,
        )
        team = repository.load_team("UTA")
        self.assertEqual(repository.season, "2026-27")
        self.assertEqual(len(team.roster), 6)
        self.assertAlmostEqual(
            sum(player.expected_minutes for player in team.roster),
            240.0,
        )
        self.assertEqual(
            repository.profile_source(1628374),
            "official-2025-26",
        )
        lauri = team.player(1628374)
        self.assertAlmostEqual(lauri.usage_rate, 0.28)
        self.assertEqual(lauri.height_inches, 85.0)
        self.assertEqual(
            repository.profile_source(9_999_999),
            "replacement-prior",
        )

    def test_dashboard_metadata_exposes_current_roster_and_sources(self) -> None:
        service = DashboardService(
            self.database,
            warehouse_path=self.warehouse.path,
        )
        # The service cutoff is the actual current time, later than the test
        # snapshot timestamp in this environment.
        metadata = service.metadata()
        utah = next(
            team for team in metadata["teams"] if team["abbreviation"] == "UTA"
        )
        self.assertEqual(metadata["roster_season"], "2026-27")
        self.assertEqual(len(utah["roster"]), 6)
        prospect = next(
            player for player in utah["roster"] if player["player_id"] == 9_999_999
        )
        self.assertEqual(prospect["profile_source"], "replacement-prior")


if __name__ == "__main__":
    unittest.main()
