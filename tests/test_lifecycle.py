from __future__ import annotations

import unittest

from nba_sim.franchise.lifecycle import (
    LifecycleProjectionConfig,
    lifecycle_stage,
    project_lifecycle,
)
from nba_sim.franchise.models import PlayerLifecycleRecord


def _record(*, age: float | None, overall: float = 66.0) -> PlayerLifecycleRecord:
    return PlayerLifecycleRecord(
        player_id=1,
        as_of_season="2026-27",
        age=age,
        age_source="test" if age is not None else "not_available",
        stage=lifecycle_stage(age),
        offense=overall,
        playmaking=overall,
        defense=overall,
        athleticism=overall,
        overall=overall,
        potential_mean=min(99.0, overall + 8.0),
        potential_sd=4.0,
        workload_minutes=1_800.0,
        games_played=68,
        confidence="moderate",
        model_version="test",
    )


class PlayerLifecycleTests(unittest.TestCase):
    def test_projection_is_seed_reproducible_and_bounded(self) -> None:
        config = LifecycleProjectionConfig(seasons=4, paths=100)
        first = project_lifecycle(_record(age=22), seed=88, config=config)
        second = project_lifecycle(_record(age=22), seed=88, config=config)
        self.assertEqual(first, second)
        self.assertEqual(len(first["trajectory"]), 5)
        for year in first["trajectory"]:
            overall = year["overall"]
            if overall is not None:
                self.assertLessEqual(overall["p10"], overall["p50"])
                self.assertLessEqual(overall["p50"], overall["p90"])

    def test_nonlinear_age_curve_grows_youth_and_declines_veterans(self) -> None:
        config = LifecycleProjectionConfig(seasons=3, paths=300)
        young = project_lifecycle(_record(age=21), seed=11, config=config)
        veteran = project_lifecycle(_record(age=35), seed=11, config=config)
        self.assertGreater(
            young["trajectory"][3]["overall"]["p50"],
            young["trajectory"][0]["overall"]["p50"],
        )
        self.assertLess(
            veteran["trajectory"][3]["overall"]["p50"],
            veteran["trajectory"][0]["overall"]["p50"],
        )

    def test_injury_burden_hurts_athletic_outlook(self) -> None:
        healthy = project_lifecycle(
            _record(age=25),
            seed=19,
            config=LifecycleProjectionConfig(
                injury_burden=0.0,
                seasons=3,
                paths=200,
            ),
        )
        burdened = project_lifecycle(
            _record(age=25),
            seed=19,
            config=LifecycleProjectionConfig(
                injury_burden=0.8,
                seasons=3,
                paths=200,
            ),
        )
        self.assertGreater(
            healthy["trajectory"][3]["attributes"]["athleticism"]["p50"],
            burdened["trajectory"][3]["attributes"]["athleticism"]["p50"],
        )

    def test_unknown_age_withholds_age_and_retirement_effects(self) -> None:
        result = project_lifecycle(
            _record(age=None),
            seed=2,
            config=LifecycleProjectionConfig(seasons=5, paths=100),
        )
        self.assertFalse(result["age_known"])
        self.assertEqual(result["retirement_probability_by_horizon"], 0)
        self.assertIsNone(result["trajectory"][5]["age"])


if __name__ == "__main__":
    unittest.main()
