from datetime import date
from dataclasses import replace
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from nba_sim.franchise.season_cycle import FranchiseSeasonRecord, SeasonGameRecord, SeasonBoxScoreRecord
from nba_sim.franchise.statistics import season_statistics
from nba_sim.web import DashboardService, FranchiseSeasonSimulationJob, _ASSETS, _ASSET_DIRECTORY
from tests.factories import make_team


def box(player_id=1, team="LAL", **kwargs):
    values = dict(player_id=player_id, name=f"Player {player_id}", team=team,
                  minutes=30, points=20, field_goals_made=8, field_goals_attempted=15,
                  threes_made=2, threes_attempted=5, free_throws_made=2,
                  free_throws_attempted=2, offensive_rebounds=2, defensive_rebounds=5,
                  assists=4, steals=1, blocks=1, turnovers=2, personal_fouls=3)
    return SeasonBoxScoreRecord(**{**values, **kwargs})


def cycle():
    return FranchiseSeasonRecord(season="2026-27", status="regular_season", games=(
        SeasonGameRecord("one", date(2026, 10, 20), "LAL", "PHX", completed=True,
                         home_score=100, away_score=90, box_scores=(box(), box(2, "PHX"))),
        SeasonGameRecord("two", date(2026, 10, 22), "PHX", "LAL", completed=True,
                         home_score=105, away_score=98, box_scores=(box(1, "PHX", points=30, field_goals_made=10, field_goals_attempted=25), box(3, "LAL", minutes=0, points=0))),
        SeasonGameRecord("playoffs", date(2027, 4, 20), "LAL", "PHX", stage="playoffs", completed=True,
                         home_score=110, away_score=100, box_scores=(box(points=50),)),
        SeasonGameRecord("future", date(2027, 4, 22), "LAL", "PHX"),
    ))


class FranchiseStatisticsTests(TestCase):
    def test_totals_stints_and_weighted_shooting(self):
        result = season_statistics(cycle())
        player = next(row for row in result["players"] if row["player_id"] == 1)
        self.assertEqual((player["games"], player["points"], player["team"]), (2, 50, "TOT"))
        self.assertAlmostEqual(player["fg_pct"], 18 / 40)
        stints = [row for row in result["player_stints"] if row["player_id"] == 1]
        self.assertEqual({row["team"]: row["points"] for row in stints}, {"LAL": 20, "PHX": 30})
        self.assertNotIn(3, [row["player_id"] for row in result["players"]])

    def test_team_totals_use_score_not_incomplete_boxes(self):
        result = season_statistics(cycle())
        row = next(row for row in result["teams"] if row["team"] == "LAL")
        self.assertEqual((row["games"],row["wins"],row["losses"]), (2,1,1))
        self.assertEqual((row["points"],row["points_against"]), (198,195))
        self.assertEqual(len(result["teams"]),30)

    def test_stage_and_log_filters(self):
        result = season_statistics(cycle(), stage="playoffs", player_id=1)
        self.assertEqual(result["completed_games"],1)
        self.assertEqual(result["players"][0]["points"],50)
        log = result["game_log"][0]
        self.assertEqual((log["game_id"],log["opponent"],log["result"]), ("playoffs","PHX","W"))
        regular = season_statistics(cycle(), player_id=1)
        self.assertEqual([row["game_id"] for row in regular["game_log"]], ["two","one"])

    def test_empty_and_invalid_stage(self):
        result = season_statistics(None)
        self.assertEqual(result["players"],[])
        self.assertIsNone(result["teams"][0]["fg_pct"])
        with self.assertRaises(ValueError):
            season_statistics(cycle(),stage="made_up")

    def test_archived_season_endpoint_is_read_only(self):
        service = DashboardService.__new__(DashboardService)
        service.franchise_repository = Mock()
        service.franchise_repository.load.return_value = SimpleNamespace(state=SimpleNamespace(
            season_cycle=cycle(), season_history=(replace(cycle(),season="2025-26"),), user_team="LAL"))
        result = service.franchise_statistics({"save_id":"test","season":"2025-26"})
        self.assertEqual(result["season"],"2025-26")
        self.assertEqual(result["seasons"],["2026-27","2025-26"])
        service.franchise_repository.append_event.assert_not_called()
        with self.assertRaises(ValueError):
            service.franchise_statistics({"save_id":"test","season":"2040-41"})

    def test_inactive_rotation_player_cannot_keep_health_cap(self):
        service = DashboardService.__new__(DashboardService)
        profiles = {"LAL":make_team("LAL",id_offset=100), "PHX":make_team("PHX",id_offset=200)}
        service._franchise_team_profile = lambda loaded, team: profiles[team]
        loaded = SimpleNamespace(state=SimpleNamespace(roster=lambda team:profiles[team].roster,
                                                       roster_plans=(),team_chemistry=(),coaching_profiles=()))
        inactive = profiles["LAL"].roster[0].player_id
        limited = profiles["LAL"].roster[1].player_id
        with patch("nba_sim.web.availability_policy",side_effect=[((),{inactive:20,limited:28}),((),{})]), patch("nba_sim.web.roster_inactive_player_ids",side_effect=[(inactive,),()]):
            simulator = service._franchise_season_simulator(loaded,home_team="LAL",away_team="PHX",health=())
        self.assertNotIn(inactive,[player.player_id for player in simulator.home_team.roster])
        self.assertEqual(simulator.home_team.minute_limits[limited],28)

    def test_worker_reports_value_error_instead_of_staying_running(self):
        service = DashboardService.__new__(DashboardService)
        service._franchise_season_job_lock = Lock()
        job = FranchiseSeasonSimulationJob("job","save","next_day",1)
        service._franchise_season_jobs = {"job":job}
        service._execute_franchise_game_batch = Mock(side_effect=ValueError("invalid lineup"))
        service._run_franchise_season_job("job",None,())
        self.assertEqual((job.status,job.error),("failed","invalid lineup"))

    def test_icon_and_stats_assets_exist(self):
        self.assertTrue((_ASSET_DIRECTORY / _ASSETS["/favicon.ico"]).is_file())
        html = (_ASSET_DIRECTORY / "index.html").read_text()
        self.assertIn('href="/favicon.svg"',html)
        self.assertIn('data-franchise-tab="stats"',html)
        self.assertIn('id="stats-player-detail"',html)

    def test_mode_handlers_do_not_bind_to_document_body(self):
        javascript = (_ASSET_DIRECTORY / "app.js").read_text()
        self.assertIn("$$('button[data-interface]')", javascript)
        self.assertNotIn("$$('[data-interface]')", javascript)
