from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date, timedelta
from types import SimpleNamespace

from nba_sim.franchise.health import (
    advance_health_record,
    apply_workload,
    availability_policy,
    build_health_record,
    reconcile_injury_history,
    sample_game_injuries,
    update_health_status,
)
from nba_sim.franchise.models import PlayerLifecycleRecord, PlayerRecord


class PlayerHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.today = date(2026, 10, 20)
        self.record = build_health_record(
            PlayerRecord(1, "Player", "AAA", "G", "active", 32, "test"),
            lifecycle=None,
            as_of=self.today,
        )

    def test_workload_accumulates_then_recovers_with_time(self) -> None:
        loaded = apply_workload(
            self.record,
            occurred_on=self.today,
            minutes=36,
            intensity=1.25,
        )
        self.assertGreater(loaded.fatigue, self.record.fatigue)
        self.assertGreater(loaded.acute_load, self.record.acute_load)
        recovered = advance_health_record(
            loaded,
            target=self.today + timedelta(days=3),
        )
        self.assertLess(recovered.fatigue, loaded.fatigue)
        self.assertLess(recovered.acute_load, loaded.acute_load)

    def test_medical_status_does_not_auto_clear(self) -> None:
        out = update_health_status(
            self.record,
            occurred_on=self.today,
            availability="out",
            body_area="ankle",
            expected_return=self.today + timedelta(days=7),
        )
        advanced = advance_health_record(
            out,
            target=self.today + timedelta(days=10),
        )
        self.assertEqual(advanced.availability, "out")
        self.assertEqual(availability_policy((advanced,))[0], (1,))

    def test_managed_status_creates_default_minute_limit(self) -> None:
        managed = update_health_status(
            self.record,
            occurred_on=self.today,
            availability="managed",
        )
        self.assertEqual(managed.minute_limit, 28)
        inactive, limits = availability_policy((managed,))
        self.assertEqual(inactive, ())
        self.assertEqual(limits, {1: 28})

    def test_seeded_game_injury_is_reproducible_and_recovers_automatically(self) -> None:
        player = PlayerRecord(1, "Player", "AAA", "G", "active", 36, "test")
        lifecycle = PlayerLifecycleRecord(
            player_id=1,
            as_of_season="2026-27",
            age=36,
            age_source="test",
            stage="decline",
            offense=80,
            playmaking=75,
            defense=70,
            athleticism=68,
            overall=78,
            potential_mean=78,
            potential_sd=2,
            workload_minutes=2200,
            games_played=70,
            confidence="high",
            model_version="test",
        )
        exposed = replace(
            self.record,
            availability="managed",
            minute_limit=38,
            fatigue=90,
            load_concern=1.0,
        )
        outcome = None
        game_id = ""
        for index in range(1_000):
            game_id = f"TEST-{index}"
            health, injuries = sample_game_injuries(
                game_id=game_id,
                occurred_on=self.today,
                player_minutes={1: 42},
                players={1: player},
                lifecycles={1: lifecycle},
                health={1: exposed},
                injury_history=(),
                seed=77,
            )
            if injuries:
                outcome = (health, injuries)
                break
        self.assertIsNotNone(outcome)
        health, injuries = outcome
        repeated = sample_game_injuries(
            game_id=game_id,
            occurred_on=self.today,
            player_minutes={1: 42},
            players={1: player},
            lifecycles={1: lifecycle},
            health={1: exposed},
            injury_history=(),
            seed=77,
        )
        self.assertEqual(
            ([item.as_dict() for item in health], [item.as_dict() for item in injuries]),
            ([item.as_dict() for item in repeated[0]], [item.as_dict() for item in repeated[1]]),
        )
        injured = health[0]
        self.assertEqual(injured.availability, "out")
        managed = advance_health_record(injured, target=injured.expected_return)
        self.assertEqual(managed.availability, "managed")
        recovered = advance_health_record(managed, target=managed.expected_return)
        self.assertEqual(recovered.availability, "available")

    def test_injury_history_counts_missed_games_and_clears(self) -> None:
        # A concrete record keeps this test focused on reconciliation, not occurrence.
        from nba_sim.franchise.models import InjuryRecord
        injury = InjuryRecord(
            "inj-1", 1, "AAA", "active", "ankle sprain", self.today,
            self.today + timedelta(days=7), "simulation", severity="minor",
            body_area="ankle", model_version="test",
        )
        game = SimpleNamespace(
            home_team="AAA",
            away_team="BBB",
            game_date=self.today + timedelta(days=2),
            box_scores=(),
        )
        cleared_health = replace(
            self.record,
            as_of_date=self.today + timedelta(days=10),
            source="simulated-recovery",
        )
        result = reconcile_injury_history(
            (injury,), health={1: cleared_health}, games=(game,)
        )[0]
        self.assertEqual(result.status, "cleared")
        self.assertEqual(result.games_missed, 1)


if __name__ == "__main__":
    unittest.main()
