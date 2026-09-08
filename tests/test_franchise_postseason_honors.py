from __future__ import annotations

import unittest
import time
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from nba_sim.franchise.honors import build_regular_season_honors, postseason_performance
from nba_sim.franchise.season_cycle import SeasonBoxScoreRecord, SeasonGameRecord, postseason_bracket
from nba_sim.web import DashboardService


class FranchisePostseasonHonorsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.service = DashboardService(
            Path(__file__).parents[1] / "ETL" / "nba_universe.db",
            warehouse_path=Path(self.temporary.name) / "warehouse.sqlite",
        )
        self.created = self.service.create_franchise(
            {"name": "Postseason Lab", "user_team": "LAL", "seed": 731}
        )
        self.save_id = self.created["save"]["save_id"]

    def _completed_regular_season(self):
        loaded = self.service.franchise_repository.load(self.save_id)
        assert loaded.state.season_cycle is not None
        completed = tuple(
            replace(
                game,
                completed=True,
                home_score=112 + index % 5,
                away_score=104 + index % 4,
                possessions=99.0,
                seed=index + 1,
            )
            for index, game in enumerate(loaded.state.season_cycle.games)
        )
        cycle = replace(loaded.state.season_cycle, games=completed, status="postseason")
        state = replace(loaded.state, season_cycle=cycle, revision=0, head_hash="")
        return self.service.franchise_repository.create_save(
            state,
            name="Postseason Ready",
            save_id="postseason-ready",
        )

    def test_play_in_is_a_durable_independent_round(self) -> None:
        loaded = self._completed_regular_season()
        result = self.service.simulate_franchise_postseason(
            {"save_id": loaded.metadata.save_id, "scope": "next_round"}
        )
        bracket = result["season_hub"]["postseason"]
        self.assertEqual(bracket["completed_round"], "play_in")
        self.assertEqual(bracket["next_round"], "first_round")
        self.assertEqual(bracket["games_completed"], 6)
        self.assertEqual(len(bracket["series"]), 6)
        self.assertTrue(all(item["winner"] for item in bracket["series"]))
        self.assertTrue(result["integrity"]["verified"])

        replay = self.service.load_franchise({"save_id": loaded.metadata.save_id})
        self.assertEqual(replay["season_hub"]["postseason"], bracket)

    def test_background_postseason_reports_individual_game_progress(self) -> None:
        loaded = self._completed_regular_season()
        job = self.service.start_franchise_postseason_simulation({
            "save_id": loaded.metadata.save_id,
            "scope": "next_round",
        })
        observations = []
        deadline = time.monotonic() + 15
        while True:
            job = self.service.franchise_season_simulation_progress({"job_id": job["job_id"]})
            observations.append(job["completed_games"])
            if job["status"] in {"completed", "failed", "cancelled"}:
                break
            if time.monotonic() > deadline:
                self.fail("postseason background simulation did not finish")
            time.sleep(0.01)
        self.assertEqual(job["status"], "completed", job.get("error"))
        self.assertEqual(job["completed_games"], 6)
        self.assertEqual(job["progress"], 1.0)
        self.assertTrue(any(0 < value < 6 for value in observations))
        self.assertEqual(job["result"]["season_hub"]["postseason"]["completed_round"], "play_in")

    def test_honors_are_regular_season_only_and_playoff_deltas_are_shrunk(self) -> None:
        loaded = self.service.franchise_repository.load(self.save_id)
        assert loaded.state.season_cycle is not None
        first = loaded.state.players[0]
        second = next(item for item in loaded.state.players if item.team != first.team)
        start = loaded.state.calendar.regular_season_start

        def box(player, points, assists, blocks):
            return SeasonBoxScoreRecord(
                player_id=player.player_id,
                name=player.name,
                team=player.team,
                minutes=36.0,
                points=points,
                field_goals_made=points // 2,
                field_goals_attempted=max(points // 2 + 7, 10),
                threes_made=2,
                threes_attempted=5,
                free_throws_made=4,
                free_throws_attempted=5,
                offensive_rebounds=1,
                defensive_rebounds=7,
                assists=assists,
                steals=2,
                blocks=blocks,
                turnovers=2,
                personal_fouls=2,
            )

        regular = tuple(
            SeasonGameRecord(
                game_id=f"REG-{index}",
                game_date=start + timedelta(days=index),
                home_team=first.team,
                away_team=second.team,
                completed=True,
                home_score=120,
                away_score=100,
                possessions=100,
                seed=index,
                box_scores=(box(first, 34, 9, 2), box(second, 18, 3, 0)),
            )
            for index in range(65)
        )
        playoff = SeasonGameRecord(
            game_id="POST-1",
            game_date=start + timedelta(days=100),
            home_team=first.team,
            away_team=second.team,
            stage="playoffs",
            completed=True,
            home_score=90,
            away_score=130,
            possessions=96,
            seed=999,
            round_name="first_round",
            series_id="T-R1",
            series_game_number=1,
            box_scores=(box(first, 5, 1, 0), box(second, 55, 12, 4)),
        )
        cycle = replace(loaded.state.season_cycle, games=(*regular, playoff), status="postseason")
        honors = build_regular_season_honors(loaded.state, cycle)
        mvp = next(item for item in honors if item.key == "mvp")
        self.assertEqual(mvp.recipients[0].player_id, first.player_id)
        self.assertTrue(any(item.key == "all_nba_1" for item in honors))

        performance = postseason_performance(cycle)
        first_delta = next(item for item in performance["all"] if item["player_id"] == first.player_id)
        self.assertLess(first_delta["adjusted_delta"], 0)
        self.assertGreater(abs(first_delta["playoff_game_score"] - first_delta["regular_game_score"]), abs(first_delta["adjusted_delta"]))

    def test_bracket_payload_exposes_series_games_for_box_score_navigation(self) -> None:
        loaded = self._completed_regular_season()
        self.service.simulate_franchise_postseason(
            {"save_id": loaded.metadata.save_id, "scope": "next_round"}
        )
        replay = self.service.franchise_repository.load(loaded.metadata.save_id)
        assert replay.state.season_cycle is not None
        bracket = postseason_bracket(replay.state.season_cycle)
        sample = bracket["series"][0]
        self.assertIn("series_game_number", sample["games"][0])
        detail = self.service.franchise_season_game({
            "save_id": loaded.metadata.save_id,
            "game_id": sample["games"][0]["game_id"],
        })
        self.assertTrue(detail["box_scores"])


if __name__ == "__main__":
    unittest.main()
