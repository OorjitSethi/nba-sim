from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from nba_sim.web import DashboardService


class DashboardServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        database = Path(__file__).parents[1] / "ETL" / "nba_universe.db"
        cls.temporary = TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.service = DashboardService(
            database,
            warehouse_path=Path(cls.temporary.name) / "warehouse.sqlite",
        )

    def test_metadata_contains_teams_and_rotation_players(self) -> None:
        metadata = self.service.metadata()
        self.assertEqual(len(metadata["teams"]), 30)
        utah = next(
            team for team in metadata["teams"] if team["abbreviation"] == "UTA"
        )
        self.assertEqual(len(utah["roster"]), 10)

    def test_hosted_demo_reports_and_enforces_its_trial_cap(self) -> None:
        hosted = DashboardService(
            self.service.database_path,
            warehouse_path=Path(self.temporary.name) / "hosted.sqlite",
            deployment_mode="vercel-demo",
            matchup_trial_limit=25,
        )
        metadata = hosted.metadata()
        self.assertEqual(metadata["deployment"]["mode"], "vercel-demo")
        self.assertFalse(metadata["deployment"]["persistent_storage"])
        self.assertEqual(metadata["deployment"]["matchup_trial_limit"], 25)
        with self.assertRaisesRegex(ValueError, r"trials must be 25\.\.25"):
            hosted.run_matchup(
                {
                    "mode": "hybrid",
                    "home": "UTA",
                    "away": "MEM",
                    "trials": 26,
                }
            )

    def test_vercel_public_assets_match_the_local_dashboard(self) -> None:
        root = Path(__file__).parents[1]
        source = root / "src" / "nba_sim" / "web_assets"
        public = root / "public"
        for filename in ("index.html", "app.js", "styles.css"):
            self.assertEqual(
                (public / filename).read_bytes(),
                (source / filename).read_bytes(),
            )

    def test_dashboard_uses_automatic_seed_controls(self) -> None:
        assets = Path(__file__).parents[1] / "src" / "nba_sim" / "web_assets"
        html = (assets / "index.html").read_text(encoding="utf-8")
        javascript = (assets / "app.js").read_text(encoding="utf-8")
        self.assertNotIn('id="matchup-seed"', html)
        self.assertNotIn('id="season-seed"', html)
        self.assertNotIn('id="series-seed"', html)
        self.assertNotIn("randomSeed()", javascript)
        self.assertIn("Fresh seed", html)

    def test_league_sim_uses_resumable_detailed_progress_ui(self) -> None:
        assets = Path(__file__).parents[1] / "src" / "nba_sim" / "web_assets"
        html = (assets / "index.html").read_text(encoding="utf-8")
        javascript = (assets / "app.js").read_text(encoding="utf-8")
        self.assertIn('role="progressbar"', html)
        self.assertIn("one complete possession-level", html)
        self.assertIn('api("/api/league-season/start"', javascript)
        self.assertIn('api("/api/league-season/progress"', javascript)
        self.assertIn('api("/api/league-season/cancel"', javascript)
        self.assertIn("LEAGUE_JOB_STORAGE_KEY", javascript)

    def test_franchise_workspace_exposes_durable_kernel_controls(self) -> None:
        assets = Path(__file__).parents[1] / "src" / "nba_sim" / "web_assets"
        html = (assets / "index.html").read_text(encoding="utf-8")
        javascript = (assets / "app.js").read_text(encoding="utf-8")
        self.assertIn('data-view="franchise"', html)
        self.assertIn('id="franchise-create-form"', html)
        self.assertIn('id="franchise-branch-form"', html)
        self.assertIn('api("/api/franchise/create"', javascript)
        self.assertIn('api("/api/franchise/advance-date"', javascript)
        self.assertIn('api("/api/franchise/branch"', javascript)
        self.assertIn('api("/api/franchise/cap-scenario"', javascript)
        self.assertIn('data-franchise-tab="development"', html)
        self.assertIn('id="lifecycle-projection-form"', html)
        self.assertIn("/api/franchise/project-lifecycle", javascript)
        self.assertIn('data-franchise-tab="health"', html)
        self.assertIn('id="health-workload-form"', html)
        self.assertIn("/api/franchise/record-workload", javascript)
        self.assertIn('data-franchise-tab="chemistry"', html)
        self.assertIn("/api/franchise/update-coaching", javascript)
        self.assertIn('data-franchise-tab="scouting"', html)
        self.assertIn('id="scouting-board"', html)
        self.assertIn("/api/franchise/run-scouting-cycle", javascript)
        self.assertIn('data-franchise-tab="draft"', html)
        self.assertIn('id="draft-board"', html)
        self.assertIn("/api/franchise/initialize-draft", javascript)
        self.assertIn("/api/franchise/run-draft-lottery", javascript)
        self.assertIn("/api/franchise/make-draft-pick", javascript)
        self.assertNotIn("button.textContent = loadingLabel", javascript)
        self.assertIn('button.querySelector("span") || button', javascript)
        self.assertIn('data-franchise-tab="trades"', html)
        self.assertIn('id="trade-rules-form"', html)
        self.assertIn("/api/franchise/evaluate-trade", javascript)
        self.assertIn("/api/franchise/run-ai-trade-market", javascript)

    def test_draft_ecosystem_is_event_sourced_and_hides_true_talent(self) -> None:
        created = self.service.create_franchise(
            {
                "name": "Draft Test League",
                "user_team": "UTA",
                "seed": 2027,
            }
        )
        save_id = created["save"]["save_id"]
        initialized = self.service.initialize_draft_ecosystem(
            {"save_id": save_id, "seed": 991}
        )
        self.assertTrue(initialized["draft"]["ready"])
        self.assertEqual(initialized["draft"]["class_size"], 75)
        self.assertEqual(initialized["coverage"]["draft_assets"]["records"], 60)
        visible = initialized["draft"]["prospects"][0]
        self.assertNotIn("overall", visible)
        self.assertNotIn("public_score", visible)
        cycle = self.service.run_franchise_scouting_cycle(
            {"save_id": save_id}
        )
        self.assertEqual(cycle["scouting_cycle_targets"], 10)
        self.assertEqual(cycle["scouting"]["department"]["cycles_completed"], 1)
        advanced = self.service.advance_franchise_date(
            {"save_id": save_id, "days": 7}
        )
        self.assertEqual(
            advanced["scouting"]["department"]["cycles_completed"],
            2,
        )

        lottery = self.service.run_draft_lottery(
            {"save_id": save_id, "seed": 992}
        )
        self.assertEqual(len(lottery["draft"]["order"]), 60)
        self.assertEqual(len(lottery["draft"]["lottery"]), 16)
        replay = self.service.load_franchise({"save_id": save_id})
        self.assertEqual(replay["draft"]["order"], lottery["draft"]["order"])
        self.assertTrue(replay["integrity"]["verified"])

    def test_scouting_board_and_manual_observation_are_persistent(self) -> None:
        created = self.service.create_franchise(
            {
                "name": "Scouting Test League",
                "user_team": "UTA",
                "seed": 515,
            }
        )
        self.assertTrue(created["scouting"]["ready"])
        save_id = created["save"]["save_id"]
        board = self.service.franchise_scouting_board({"save_id": save_id})
        self.assertEqual(len(board["records"]), created["summary"]["counts"]["players"])
        target = board["records"][0]
        self.assertTrue(target["exact"])
        self.assertTrue(target["established_player"])
        self.assertEqual(target["overall_low"], target["overall_high"])
        with self.assertRaisesRegex(ValueError, "do not require scouting"):
            self.service.scout_franchise_player(
                {
                    "save_id": save_id,
                    "player_id": target["player_id"],
                    "hours": 32,
                }
            )
        cycle = self.service.run_franchise_scouting_cycle({"save_id": save_id})
        self.assertEqual(cycle["scouting_cycle_targets"], 0)
        self.assertEqual(cycle["scouting"]["department"]["cycles_completed"], 0)

    def test_established_ratings_are_normalized_detailed_and_role_specific(self) -> None:
        created = self.service.create_franchise(
            {
                "name": "Ratings Test League",
                "user_team": "OKC",
                "seed": 717,
            }
        )
        board = self.service.franchise_scouting_board(
            {"save_id": created["save"]["save_id"]}
        )["records"]
        shai = next(
            row for row in board
            if row["name"] == "Shai Gilgeous-Alexander"
        )
        embiid = next(row for row in board if row["name"] == "Joel Embiid")
        cam = next(row for row in board if row["name"] == "Cam Thomas")
        giannis = next(
            row for row in board
            if row["name"] == "Giannis Antetokounmpo"
        )
        duren = next(row for row in board if row["name"] == "Jalen Duren")
        booker = next(row for row in board if row["name"] == "Devin Booker")
        durant = next(row for row in board if row["name"] == "Kevin Durant")
        butler = next(
            row for row in board if row["name"] == "Jimmy Butler III"
        )
        edwards = next(
            row for row in board if row["name"] == "Anthony Edwards"
        )
        curry = next(row for row in board if row["name"] == "Stephen Curry")
        chet = next(row for row in board if row["name"] == "Chet Holmgren")
        jalen_johnson = next(
            row for row in board if row["name"] == "Jalen Johnson"
        )
        self.assertEqual(max(row["overall"] for row in board), 99)
        self.assertGreater(shai["overall"], cam["overall"])
        self.assertGreater(giannis["overall"], duren["overall"])
        self.assertGreater(booker["overall"], butler["overall"])
        self.assertGreater(durant["overall"], butler["overall"])
        self.assertGreater(edwards["overall"], jalen_johnson["overall"])
        self.assertGreater(curry["overall"], jalen_johnson["overall"])
        self.assertGreater(chet["overall"], jalen_johnson["overall"])
        self.assertIn("established_prior", shai["overall_components"])
        self.assertIn("current_performance", shai["overall_components"])
        self.assertIn("age_adjustment", shai["overall_components"])
        self.assertGreaterEqual(len(shai["attributes"]), 35)
        self.assertEqual(len(shai["zones"]), 6)
        self.assertLess(embiid["role_probabilities"]["Creator"], 0.05)
        for record in created["player_lifecycle"]["records"][:10]:
            recomputed = (
                0.38 * record["offense"]
                + 0.22 * record["playmaking"]
                + 0.28 * record["defense"]
                + 0.12 * record["athleticism"]
            )
            self.assertAlmostEqual(recomputed, record["overall"], places=5)

    def test_single_game_api_returns_events_and_box_scores(self) -> None:
        result = self.service.run_matchup(
            {
                "mode": "single",
                "home": "UTA",
                "away": "MEM",
                "seed": 7,
            }
        )
        self.assertEqual(result["kind"], "single")
        self.assertEqual(result["home_team"], "UTA")
        self.assertGreater(len(result["events"]), 100)
        self.assertEqual(len(result["box_scores"]), 20)

    def test_invalid_mode_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "mode"):
            self.service.run_matchup(
                {
                    "mode": "oracle",
                    "home": "UTA",
                    "away": "MEM",
                }
            )

    def test_omitted_seed_generates_a_fresh_reproducible_seed(self) -> None:
        with patch(
            "nba_sim.web.secrets.randbelow",
            side_effect=(101, 202),
        ):
            first = self.service.run_matchup(
                {
                    "mode": "single",
                    "home": "UTA",
                    "away": "MEM",
                    "include_events": False,
                }
            )
            second = self.service.run_matchup(
                {
                    "mode": "single",
                    "home": "UTA",
                    "away": "MEM",
                    "include_events": False,
                }
            )
        self.assertIsInstance(first["seed"], int)
        self.assertGreaterEqual(first["seed"], 0)
        self.assertNotEqual(first["seed"], second["seed"])
        replay = self.service.run_matchup(
            {
                "mode": "single",
                "home": "UTA",
                "away": "MEM",
                "seed": first["seed"],
                "include_events": False,
            }
        )
        self.assertEqual(first, replay)

    def test_competition_endpoints_return_complete_results(self) -> None:
        season = self.service.run_season(
            {
                "teams": ["UTA", "MEM"],
                "repeats": 1,
                "start_date": "2026-10-20",
                "seed": 7,
            }
        )
        self.assertEqual(season["kind"], "season")
        self.assertEqual(season["games_played"], 1)
        self.assertEqual(len(season["standings"]), 2)

        series = self.service.run_series(
            {
                "higher_seed": "DEN",
                "lower_seed": "MIN",
                "best_of": 3,
                "seed": 7,
            }
        )
        self.assertEqual(series["kind"], "series")
        self.assertEqual(
            max(series["higher_seed_wins"], series["lower_seed_wins"]),
            2,
        )

    def test_franchise_endpoints_create_advance_and_branch_state(self) -> None:
        created = self.service.create_franchise(
            {
                "name": "Web Test League",
                "user_team": "UTA",
                "seed": 404,
            }
        )
        self.assertEqual(created["kind"], "franchise")
        self.assertEqual(created["summary"]["counts"]["franchises"], 30)
        self.assertEqual(created["summary"]["user_team"], "UTA")
        self.assertTrue(created["integrity"]["verified"])
        original_date = created["summary"]["current_date"]

        advanced = self.service.advance_franchise_date(
            {
                "save_id": created["save"]["save_id"],
                "days": 7,
            }
        )
        self.assertNotEqual(advanced["summary"]["current_date"], original_date)
        self.assertEqual(
            advanced["summary"]["revision"],
            created["summary"]["revision"] + 1,
        )
        self.assertEqual(
            advanced["scouting"]["department"]["cycles_completed"],
            0,
        )

        branch = self.service.branch_franchise(
            {
                "save_id": advanced["save"]["save_id"],
                "branch_name": "Alternate timeline",
            }
        )
        self.assertEqual(branch["save"]["branch_name"], "Alternate timeline")
        self.assertEqual(
            branch["save"]["parent_save_id"],
            advanced["save"]["save_id"],
        )
        self.assertEqual(
            branch["summary"]["current_date"],
            advanced["summary"]["current_date"],
        )

    def test_cap_scenario_endpoint_exposes_official_2026_27_rules(self) -> None:
        result = self.service.franchise_cap_scenario(
            {
                "team_salary": 205_000_000,
                "incoming_salary": 6_000_000,
                "outgoing_salary": 0,
                "action": "taxpayer_mle",
            }
        )
        self.assertEqual(result["kind"], "franchise_cap_scenario")
        self.assertEqual(result["rules"]["salary_cap"], 164_961_000)
        self.assertTrue(result["evaluation"]["legal"])

    def test_franchise_player_lifecycle_projects_saved_roster(self) -> None:
        created = self.service.create_franchise(
            {
                "name": "Lifecycle Test",
                "user_team": "UTA",
                "seed": 505,
            }
        )
        self.assertTrue(created["player_lifecycle"]["ready"])
        self.assertEqual(
            created["summary"]["counts"]["players"],
            created["summary"]["counts"]["player_lifecycles"],
        )
        player = created["player_lifecycle"]["records"][0]
        result = self.service.project_player_lifecycle(
            {
                "save_id": created["save"]["save_id"],
                "player_id": player["player_id"],
                "seasons": 3,
                "paths": 50,
                "seed": 101,
            }
        )
        self.assertEqual(result["kind"], "player_lifecycle_projection")
        self.assertEqual(result["seed"], 101)
        self.assertEqual(len(result["trajectory"]), 4)

    def test_franchise_health_updates_workload_and_conditions_matchup(self) -> None:
        created = self.service.create_franchise(
            {
                "name": "Health Test",
                "user_team": "UTA",
                "seed": 606,
            }
        )
        self.assertTrue(created["player_health"]["ready"])
        player = created["roster"][0]
        loaded = self.service.record_franchise_workload(
            {
                "save_id": created["save"]["save_id"],
                "player_id": player["player_id"],
                "minutes": 38,
                "intensity": 1.25,
                "kind": "game",
            }
        )
        health = next(
            row
            for row in loaded["player_health"]["records"]
            if row["player_id"] == player["player_id"]
        )
        self.assertGreater(health["fatigue"], 0)
        restricted = self.service.update_franchise_health(
            {
                "save_id": created["save"]["save_id"],
                "player_id": player["player_id"],
                "availability": "out",
                "body_area": "ankle",
            }
        )
        game = self.service.run_matchup(
            {
                "mode": "single",
                "home": "UTA",
                "away": "MEM",
                "seed": 9,
                "include_events": False,
                "franchise_save_id": restricted["save"]["save_id"],
            }
        )
        self.assertNotIn(
            player["player_id"],
            {row["player_id"] for row in game["box_scores"]},
        )
        without_health = self.service.run_matchup(
            {
                "mode": "single",
                "home": "UTA",
                "away": "MEM",
                "seed": 9,
                "include_events": False,
                "franchise_save_id": None,
            }
        )
        self.assertEqual(without_health["kind"], "single")

    def test_team_environment_is_saved_and_can_condition_matchup(self) -> None:
        created = self.service.create_franchise(
            {
                "name": "Chemistry Test",
                "user_team": "UTA",
                "seed": 707,
            }
        )
        self.assertTrue(created["team_environment"]["ready"])
        coached = self.service.update_coaching_profile(
            {
                "save_id": created["save"]["save_id"],
                "offensive_system": "motion",
                "defensive_system": "switch",
                "pace_emphasis": 1,
                "rotation_depth": 9,
                "development_priority": "prospects",
                "adaptability": 75,
                "coach_name": "Test staff",
            }
        )
        self.assertEqual(
            coached["team_environment"]["coaching"]["offensive_system"],
            "motion",
        )
        result = self.service.run_matchup(
            {
                "mode": "single",
                "home": "UTA",
                "away": "MEM",
                "seed": 3,
                "include_events": False,
                "franchise_environment_save_id": coached["save"]["save_id"],
            }
        )
        self.assertEqual(result["kind"], "single")


if __name__ == "__main__":
    unittest.main()
