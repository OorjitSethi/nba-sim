from __future__ import annotations

import unittest
from datetime import date

from nba_sim.franchise.models import PlayerLifecycleRecord, PlayerRecord
from nba_sim.franchise.scouting import (
    MINIMUM_SCOUTING_SD,
    build_initial_scouting_report,
    default_scouting_department,
    run_automatic_scouting_cycle,
    scout_player,
)


def _player(
    player_id: int,
    team: str = "AAA",
    roster_status: str = "active",
) -> PlayerRecord:
    return PlayerRecord(
        player_id, f"Player {player_id}", team, "G", roster_status, 28, "prior"
    )


def _lifecycle(player_id: int, overall: float = 70) -> PlayerLifecycleRecord:
    return PlayerLifecycleRecord(
        player_id=player_id,
        as_of_season="2026-27",
        age=22,
        age_source="test",
        stage="developing",
        offense=overall + 2,
        playmaking=overall + 1,
        defense=overall - 2,
        athleticism=overall + 3,
        overall=overall,
        potential_mean=overall + 8,
        potential_sd=5,
        workload_minutes=1800,
        games_played=70,
        confidence="moderate",
        model_version="test",
    )


class ScoutingModelTests(unittest.TestCase):
    def test_more_evidence_narrows_belief_without_false_certainty(self) -> None:
        player = _player(1)
        lifecycle = _lifecycle(1)
        prior = build_initial_scouting_report(
            player, lifecycle, as_of=date(2026, 7, 28), seed=9
        )
        updated = scout_player(
            prior,
            lifecycle,
            hours=40,
            evaluation_quality=60,
            occurred_on=date(2026, 8, 4),
            seed=9,
            namespace="test-report",
        )
        self.assertLess(updated.overall_sd, prior.overall_sd)
        self.assertGreaterEqual(updated.overall_sd, MINIMUM_SCOUTING_SD)
        self.assertEqual(updated.evaluations, 1)
        self.assertEqual(updated.observation_hours, 40)

    def test_scouting_is_reproducible_and_archetypes_sum_to_one(self) -> None:
        player = _player(1)
        lifecycle = _lifecycle(1)
        first = build_initial_scouting_report(
            player, lifecycle, as_of=date(2026, 7, 28), seed=33
        )
        second = build_initial_scouting_report(
            player, lifecycle, as_of=date(2026, 7, 28), seed=33
        )
        self.assertEqual(first, second)
        total = sum(
            (
                first.creator_probability,
                first.shooter_probability,
                first.two_way_probability,
                first.rim_probability,
                first.connector_probability,
            )
        )
        self.assertAlmostEqual(total, 1.0)

    def test_automatic_cycle_allocates_hours_to_ten_targets(self) -> None:
        players = tuple(
            _player(
                index,
                "AAA" if index < 4 else "BBB",
                "prospect",
            )
            for index in range(1, 13)
        )
        lifecycles = tuple(
            _lifecycle(player.player_id, 60 + player.player_id)
            for player in players
        )
        reports = tuple(
            build_initial_scouting_report(
                player,
                lifecycles[player.player_id - 1],
                as_of=date(2026, 7, 28),
                seed=7,
            )
            for player in players
        )
        department = default_scouting_department(
            "AAA", as_of=date(2026, 7, 28)
        )
        updated_department, updated = run_automatic_scouting_cycle(
            department,
            reports,
            players,
            lifecycles,
            occurred_on=date(2026, 8, 4),
            seed=7,
        )
        self.assertEqual(len(updated), 10)
        self.assertEqual(updated_department.cycles_completed, 1)
        self.assertAlmostEqual(
            sum(item.observation_hours for item in updated),
            department.weekly_hours,
        )


if __name__ == "__main__":
    unittest.main()
