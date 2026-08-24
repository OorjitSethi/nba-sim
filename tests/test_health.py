from __future__ import annotations

import unittest
from datetime import date, timedelta

from nba_sim.franchise.health import (
    advance_health_record,
    apply_workload,
    availability_policy,
    build_health_record,
    update_health_status,
)
from nba_sim.franchise.models import PlayerRecord


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


if __name__ == "__main__":
    unittest.main()
