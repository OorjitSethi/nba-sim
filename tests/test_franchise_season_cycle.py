from __future__ import annotations

import unittest
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from nba_sim.franchise.season_cycle import games_to_simulate
from nba_sim.franchise.draft import (
    generate_draft_ecosystem,
    make_next_pick,
    run_321_lottery,
)
from nba_sim.franchise.events import LeagueEventType
from nba_sim.franchise.season_cycle import (
    SeasonHonorRecipientRecord,
    SeasonHonorRecord,
)
from nba_sim.web import DashboardService


class FranchiseSeasonCycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.service = DashboardService(
            Path(__file__).parents[1] / "ETL" / "nba_universe.db",
            warehouse_path=Path(self.temporary.name) / "warehouse.sqlite",
        )
        self.created = self.service.create_franchise(
            {"name": "Season Loop", "user_team": "LAL", "seed": 2027}
        )
        self.save_id = self.created["save"]["save_id"]

    def test_new_franchise_has_balanced_persistent_schedule(self) -> None:
        hub = self.created["season_hub"]
        self.assertTrue(hub["ready"])
        self.assertEqual(hub["total_games"], 1230)
        loaded = self.service.franchise_repository.load(self.save_id)
        assert loaded.state.season_cycle is not None
        counts = Counter()
        home = Counter()
        for game in loaded.state.season_cycle.games:
            counts[game.home_team] += 1
            counts[game.away_team] += 1
            home[game.home_team] += 1
        self.assertEqual(set(counts.values()), {82})
        self.assertEqual(set(home.values()), {41})
        remaining = games_to_simulate(
            loaded.state.season_cycle,
            user_team=loaded.state.user_team,
            scope="full_season",
        )
        self.assertEqual(len(remaining), 1_230)

    def test_simulated_day_persists_results_box_scores_and_standings(self) -> None:
        result = self.service.simulate_franchise_games(
            {"save_id": self.save_id, "scope": "next_day"}
        )
        count = result["season_simulation"]["games_completed"]
        self.assertGreater(count, 0)
        self.assertEqual(result["season_hub"]["games_played"], count)
        self.assertTrue(result["season_hub"]["league_leaders"])
        replay = self.service.load_franchise({"save_id": self.save_id})
        self.assertTrue(replay["integrity"]["verified"])
        self.assertEqual(replay["season_hub"]["games_played"], count)

        user_game = result["season_simulation"]["user_games"][0]
        detail = self.service.franchise_season_game(
            {"save_id": self.save_id, "game_id": user_game["game_id"]}
        )
        self.assertTrue(detail["completed"])
        self.assertGreaterEqual(len(detail["box_scores"]), 10)
        self.assertEqual(
            sum(item["points"] for item in detail["box_scores"] if item["team"] == detail["home_team"]),
            detail["home_score"],
        )

    def test_season_hub_ui_exposes_guided_and_detailed_controls(self) -> None:
        assets = Path(__file__).parents[1] / "src" / "nba_sim" / "web_assets"
        html = (assets / "index.html").read_text(encoding="utf-8")
        javascript = (assets / "app.js").read_text(encoding="utf-8")
        self.assertIn('data-franchise-tab="season"', html)
        self.assertIn('id="season-progress-fill"', html)
        self.assertIn('id="season-job-detail"', html)
        self.assertIn('id="season-game-detail"', html)
        self.assertIn('/api/franchise/simulate-games/start', javascript)
        self.assertIn('/api/franchise/simulate-games/progress', javascript)
        self.assertIn('/api/franchise/simulate-games/cancel', javascript)
        self.assertIn('/api/franchise/simulate-postseason', javascript)
        self.assertIn('id="season-simulate-all"', html)
        self.assertIn('full_season', javascript)
        self.assertIn('/api/franchise/season-game', javascript)
        self.assertIn('id="offseason-progress-fill"', html)
        self.assertIn('id="offseason-continue"', html)
        self.assertIn('/api/franchise/advance-offseason', javascript)
        self.assertIn('id="career-ledger-list"', html)
        self.assertIn("renderCareerLedger", javascript)

    def _enter_offseason(self, *, stage: str = "awards_and_lottery"):
        loaded = self.service.franchise_repository.load(self.save_id)
        assert loaded.state.season_cycle is not None
        honor = SeasonHonorRecord(
            key="mvp",
            label="Most Valuable Player",
            kind="award",
            recipients=(
                SeasonHonorRecipientRecord(
                    player_id=loaded.state.players[0].player_id,
                    name=loaded.state.players[0].name,
                    team=loaded.state.players[0].team,
                    rank=1,
                    score=1.0,
                ),
            ),
            rationale="Test ballot",
        )
        cycle = replace(
            loaded.state.season_cycle,
            status="offseason",
            champion="LAL",
            offseason_stage=stage,
            honors=(honor,),
            awards=(("champion", "LAL"),),
        )
        return self.service.franchise_repository.append_event(
            self.save_id,
            event_type=LeagueEventType.SEASON_STAGE_ADVANCED,
            payload={"season_cycle": cycle.as_dict()},
            actor="test-league-office",
        )

    def test_offseason_automatic_stages_are_replayable_and_idempotent(self) -> None:
        self._enter_offseason()
        first = self.service.advance_franchise_offseason({
            "save_id": self.save_id,
            "expected_stage": "awards_and_lottery",
        })
        self.assertEqual(
            first["offseason_hub"]["current_stage"],
            "combine_and_scouting",
        )
        self.assertEqual(len(first["draft"]["order"]), 60)
        revision = first["summary"]["revision"]

        retry = self.service.advance_franchise_offseason({
            "save_id": self.save_id,
            "expected_stage": "awards_and_lottery",
        })
        self.assertTrue(retry["offseason_transition"]["idempotent"])
        self.assertEqual(retry["summary"]["revision"], revision)

        combined = self.service.advance_franchise_offseason({
            "save_id": self.save_id,
            "expected_stage": "combine_and_scouting",
        })
        self.assertTrue(combined["draft"]["combine_complete"])
        self.assertEqual(combined["offseason_hub"]["current_stage"], "nba_draft")
        replay = self.service.load_franchise({"save_id": self.save_id})
        self.assertTrue(replay["integrity"]["verified"])

    def test_progression_commits_once_and_rollover_archives_old_season(self) -> None:
        loaded = self._enter_offseason(stage="player_progression")
        before = {
            item.player_id: item.as_dict()
            for item in loaded.state.player_lifecycles
        }
        progressed = self.service.advance_franchise_offseason({
            "save_id": self.save_id,
            "expected_stage": "player_progression",
        })
        self.assertEqual(progressed["offseason_hub"]["current_stage"], "training_camp")
        after_loaded = self.service.franchise_repository.load(self.save_id)
        self.assertTrue(any(
            item.as_dict() != before[item.player_id]
            for item in after_loaded.state.player_lifecycles
        ))
        progression_revision = after_loaded.state.revision
        self.service.advance_franchise_offseason({
            "save_id": self.save_id,
            "expected_stage": "player_progression",
        })
        self.assertEqual(
            self.service.franchise_repository.load(self.save_id).state.revision,
            progression_revision,
        )

        training = self.service.advance_franchise_offseason({
            "save_id": self.save_id,
            "expected_stage": "training_camp",
        })
        self.assertEqual(training["offseason_hub"]["current_stage"], "ready_for_next_season")
        camp = self.service.franchise_repository.load(self.save_id)
        self.assertTrue(all(
            5 <= len(camp.state.roster(item.team)) <= 15
            for item in camp.state.franchises
        ))
        self.assertIn("training_camp_cuts", camp.events[-1].payload)
        opened = self.service.advance_franchise_offseason({
            "save_id": self.save_id,
            "expected_stage": "ready_for_next_season",
        })
        self.assertEqual(opened["summary"]["season"], "2027-28")
        self.assertEqual(opened["save"]["season"], "2027-28")
        self.assertEqual(opened["season_hub"]["total_games"], 1230)
        self.assertEqual(opened["summary"]["counts"]["season_history"], 1)
        self.assertEqual(opened["season_history"][0]["season"], "2026-27")
        replay = self.service.load_franchise({"save_id": self.save_id})
        self.assertTrue(replay["integrity"]["verified"])
        self.assertEqual(replay["season_hub"]["season"], "2027-28")
        self.assertEqual(replay["cba"]["season"], "2027-28")
        self.assertGreater(replay["cba"]["salary_cap"], 164_961_000)

    def test_rollover_archives_draft_and_next_offseason_generates_next_year(self) -> None:
        loaded = self.service.franchise_repository.load(self.save_id)
        teams = tuple(item.team for item in loaded.state.franchises)
        draft, assets = generate_draft_ecosystem(
            teams=teams,
            draft_year=2027,
            season="2026-27",
            seed=611,
            as_of=loaded.state.calendar.current_date,
        )
        draft = run_321_lottery(
            draft,
            team_strengths={team: float(index) for index, team in enumerate(teams)},
            assets=assets,
            seed=612,
        )
        while draft.status != "complete":
            slot = draft.order[len(draft.selections)]
            selected = next(
                item.player_id for item in draft.prospects
                if item.player_id not in {value.player_id for value in draft.selections}
            )
            draft = make_next_pick(
                draft,
                user_team=slot.current_team,
                player_id=selected,
                seed=draft.class_seed,
            )
        self.service.franchise_repository.append_event(
            self.save_id,
            event_type=LeagueEventType.DRAFT_ECOSYSTEM_INITIALIZED,
            payload={
                "draft": draft.as_dict(),
                "assets": [item.as_dict() for item in assets],
            },
            actor="test-league-office",
        )
        self._enter_offseason(stage="ready_for_next_season")
        opened = self.service.advance_franchise_offseason({
            "save_id": self.save_id,
            "expected_stage": "ready_for_next_season",
        })
        self.assertEqual(opened["summary"]["counts"]["draft_history"], 1)
        self.assertEqual(opened["draft_history"][0]["draft_year"], 2027)
        self.assertFalse(opened["draft"]["ready"])
        self.assertEqual(opened["draft"]["draft_year"], 2028)

        self._enter_offseason(stage="awards_and_lottery")
        next_draft = self.service.advance_franchise_offseason({
            "save_id": self.save_id,
            "expected_stage": "awards_and_lottery",
        })
        self.assertTrue(next_draft["draft"]["ready"])
        self.assertEqual(next_draft["draft"]["draft_year"], 2028)
        self.assertEqual(len(next_draft["draft"]["order"]), 60)
        self.assertTrue(self.service.load_franchise({"save_id": self.save_id})["integrity"]["verified"])

    def test_parallel_batch_matches_serial_and_reports_every_game(self) -> None:
        loaded = self.service.franchise_repository.load(self.save_id)
        assert loaded.state.season_cycle is not None
        scheduled = games_to_simulate(
            loaded.state.season_cycle,
            user_team=loaded.state.user_team,
            scope="next_day",
        )
        serial, serial_health, serial_injuries = self.service._execute_franchise_game_batch(
            loaded,
            scheduled,
            workers=1,
        )
        progress = []
        parallel, parallel_health, parallel_injuries = self.service._execute_franchise_game_batch(
            loaded,
            scheduled,
            workers=4,
            progress=lambda count, game: progress.append((count, game.game_id)),
        )

        self.assertEqual(
            [item.as_dict() for item in parallel],
            [item.as_dict() for item in serial],
        )
        self.assertEqual(
            {key: value.as_dict() for key, value in parallel_health.items()},
            {key: value.as_dict() for key, value in serial_health.items()},
        )
        self.assertEqual(
            [item.as_dict() for item in parallel_injuries],
            [item.as_dict() for item in serial_injuries],
        )
        self.assertEqual(
            [item[0] for item in progress],
            list(range(1, len(scheduled) + 1)),
        )

    def test_background_job_finishes_and_returns_persisted_result(self) -> None:
        started = self.service.start_franchise_season_simulation(
            {"save_id": self.save_id, "scope": "next_day"}
        )
        deadline = time.monotonic() + 15.0
        while True:
            job = self.service.franchise_season_simulation_progress(
                {"job_id": started["job_id"]}
            )
            if job["status"] in {"completed", "cancelled", "failed"}:
                break
            if time.monotonic() >= deadline:
                self.fail("franchise season background job did not finish")
            time.sleep(0.02)

        self.assertEqual(job["status"], "completed", job.get("error"))
        self.assertEqual(job["completed_games"], job["total_games"])
        self.assertEqual(
            job["result"]["season_hub"]["games_played"],
            job["total_games"],
        )


if __name__ == "__main__":
    unittest.main()
