from __future__ import annotations

import unittest
from datetime import date

from nba_sim.franchise.chemistry import (
    apply_team_environment,
    default_coaching_profile,
    default_team_chemistry,
    record_shared_session,
)
from tests.factories import make_team


class ChemistryCoachingTests(unittest.TestCase):
    def test_shared_session_improves_target_with_diminishing_bounds(self) -> None:
        baseline = default_team_chemistry("AAA", as_of=date(2026, 7, 27))
        updated = record_shared_session(
            baseline,
            occurred_on=date(2026, 7, 27),
            emphasis="system",
            intensity=1.5,
        )
        self.assertGreater(
            updated.system_familiarity,
            baseline.system_familiarity,
        )
        self.assertEqual(updated.shared_sessions, 1)
        self.assertLessEqual(updated.system_familiarity, 100)

    def test_environment_effects_are_bounded_and_deterministic(self) -> None:
        team = make_team("AAA", id_offset=1)
        chemistry = default_team_chemistry("AAA", as_of=date(2026, 7, 27))
        coaching = default_coaching_profile("AAA", as_of=date(2026, 7, 27))
        first = apply_team_environment(
            team,
            chemistry=chemistry,
            coaching=coaching,
        )
        second = apply_team_environment(
            team,
            chemistry=chemistry,
            coaching=coaching,
        )
        self.assertEqual(first, second)
        self.assertAlmostEqual(first.pace, team.pace)


if __name__ == "__main__":
    unittest.main()
