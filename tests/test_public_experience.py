from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nba_sim.franchise.public_experience import recovery_guidance
from nba_sim.web import DashboardService


class PublicExperienceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.service = DashboardService(
            Path(__file__).parents[1] / "ETL" / "nba_universe.db",
            warehouse_path=Path(self.temporary.name) / "warehouse.sqlite",
        )
        self.created = self.service.create_franchise(
            {"name": "Public Test League", "user_team": "LAL", "seed": 2031}
        )
        self.save_id = self.created["save"]["save_id"]

    def test_new_league_has_accuracy_neutral_guided_defaults(self) -> None:
        experience = self.created["experience"]
        self.assertEqual(experience["preset"], "guided")
        self.assertEqual(experience["difficulty"], "pro")
        self.assertEqual(experience["ratings_modifier"], 0)
        self.assertIn("never modifies player ratings", experience["accuracy_contract"])

    def test_presets_persist_and_map_staff_delegation(self) -> None:
        result = self.service.configure_franchise_experience(
            {
                "save_id": self.save_id,
                "preset": "full_control",
                "difficulty": "expert",
                "contextual_help": False,
                "confirm_consequential_moves": True,
                "show_advanced_by_default": True,
            }
        )
        self.assertEqual(result["experience"]["information_level"], "front_office_fog")
        self.assertEqual(result["experience"]["ratings_modifier"], 0)
        self.assertFalse(result["general_manager"]["user_plan"]["automation_enabled"])
        self.assertEqual(result["roster_operations"]["delegation"], "manual")
        self.assertFalse(result["scouting"]["department"]["automation_enabled"])

        guided = self.service.configure_franchise_experience(
            {
                "save_id": self.save_id,
                "preset": "guided",
                "difficulty": "rookie",
                "contextual_help": True,
                "confirm_consequential_moves": True,
                "show_advanced_by_default": False,
            }
        )
        self.assertTrue(guided["general_manager"]["user_plan"]["automation_enabled"])
        self.assertEqual(guided["roster_operations"]["delegation"], "automatic")
        self.assertTrue(guided["scouting"]["department"]["automation_enabled"])

    def test_difficulty_never_changes_established_player_ratings(self) -> None:
        loaded = self.service.franchise_repository.load(self.save_id)
        before = self.service._league_rating_profiles(loaded.state)
        result = self.service.configure_franchise_experience(
            {
                "save_id": self.save_id,
                "preset": "guided",
                "difficulty": "expert",
                "contextual_help": True,
                "confirm_consequential_moves": True,
                "show_advanced_by_default": False,
            }
        )
        after_loaded = self.service.franchise_repository.load(self.save_id)
        after = self.service._league_rating_profiles(after_loaded.state)
        self.assertEqual(before, after)
        self.assertEqual(result["experience_configuration"]["ratings_modified"], False)

    def test_release_audit_and_report_are_reproducible(self) -> None:
        audit = self.service.franchise_playtest_audit({"save_id": self.save_id})
        self.assertTrue(audit["ready_for_playtest"])
        self.assertEqual(audit["passed"], audit["required"])
        self.assertIn("Revision:", audit["tester_report"])
        self.assertIn("Seed: 2031", audit["tester_report"])
        self.assertIn("Reproduction:", audit["tester_report"])

    def test_legacy_save_can_add_experience_without_roster_drift(self) -> None:
        loaded = self.service.franchise_repository.load(self.save_id)
        legacy_state = replace(loaded.state, experience=None, head_hash="")
        legacy = self.service.franchise_repository.create_save(
            legacy_state,
            name="Legacy public branch",
        )
        before = [item.as_dict() for item in legacy.state.players]
        configured = self.service.configure_franchise_experience(
            {
                "save_id": legacy.metadata.save_id,
                "preset": "balanced",
                "difficulty": "pro",
                "contextual_help": True,
                "confirm_consequential_moves": True,
                "show_advanced_by_default": False,
            }
        )
        replay = self.service.franchise_repository.load(legacy.metadata.save_id)
        self.assertEqual(before, [item.as_dict() for item in replay.state.players])
        self.assertEqual(configured["experience"]["preset"], "balanced")
        self.assertTrue(configured["integrity"]["verified"])

    def test_ui_and_recovery_copy_expose_public_playtest_tools(self) -> None:
        assets = Path(__file__).parents[1] / "src" / "nba_sim" / "web_assets"
        html = (assets / "index.html").read_text(encoding="utf-8")
        javascript = (assets / "app.js").read_text(encoding="utf-8")
        self.assertIn('data-franchise-tab="playtest"', html)
        self.assertIn('id="experience-form"', html)
        self.assertIn('id="playtest-audit-run"', html)
        self.assertIn('/api/franchise/configure-experience', javascript)
        self.assertIn('/api/franchise/playtest-audit', javascript)
        self.assertIn("ratings, injuries, game probabilities, or seeds", javascript)
        self.assertIn("Reload the active save", recovery_guidance("unknown player ids"))

    def test_first_run_tutorial_is_remembered_and_replayable(self) -> None:
        assets = Path(__file__).parents[1] / "src" / "nba_sim" / "web_assets"
        html = (assets / "index.html").read_text(encoding="utf-8")
        javascript = (assets / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="tutorial-overlay"', html)
        self.assertIn('id="tutorial-replay"', html)
        self.assertIn("const TUTORIAL_STEPS = [", javascript)
        self.assertIn('localStorage.setItem(TUTORIAL_STORAGE_KEY, "seen")', javascript)
        self.assertIn("Max-Age=31536000", javascript)
        self.assertIn("if (!force && tutorialHasBeenSeen()) return", javascript)
        self.assertIn("openTutorial();", javascript)
        self.assertIn('$("#franchise-team").value = "PHX"', javascript)
        self.assertIn("Phoenix Suns Dynasty", javascript)
        self.assertIn("Difficulty never cheats", javascript)


if __name__ == "__main__":
    unittest.main()
