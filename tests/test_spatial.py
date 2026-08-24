from __future__ import annotations

import unittest

import numpy as np

from nba_sim.spatial.interfaces import KinematicTrajectoryModel
from nba_sim.spatial.sampling import OffsetGrid, nucleus_sample_index
from nba_sim.spatial.state import (
    COURT_LENGTH_FT,
    COURT_WIDTH_FT,
    SpatialSummary,
    initial_half_court_frame,
)
from nba_sim.spatial.torch_models import (
    CourtMotionConfig,
    CourtMotionModel,
    SportsNGENConfig,
    torch_available,
)
from tests.factories import make_team


class SpatialStateTests(unittest.TestCase):
    def setUp(self) -> None:
        home = make_team("HOM", id_offset=100)
        away = make_team("AWY", id_offset=200)
        self.frame = initial_half_court_frame(
            offense=home.starting_lineup,
            defense=away.starting_lineup,
            possession_team="HOM",
            game_clock_seconds=720.0,
            shot_clock_seconds=24.0,
            ball_handler_id=home.starting_lineup[0].player_id,
        )

    def test_frame_contains_joint_multi_agent_state(self) -> None:
        self.assertEqual(len(self.frame.players), 10)
        self.assertTrue(self.frame.ball.is_ball)
        self.assertEqual(len(self.frame.team_players("HOM")), 5)
        summary = SpatialSummary.from_frame(self.frame)
        self.assertGreater(summary.offensive_spacing_ft, 0)
        self.assertGreater(summary.closest_defender_ft, 0)
        with self.assertRaises(ValueError):
            self.frame.ball.position[0] = 0.0

    def test_kinematic_rollout_stays_in_bounds(self) -> None:
        model = KinematicTrajectoryModel(player_noise_ft_s=2.0)
        rollout = model.rollout(
            self.frame,
            steps=100,
            step_seconds=0.2,
            rng=np.random.default_rng(4),
        )
        self.assertEqual(len(rollout.frames), 101)
        for frame in rollout.frames:
            for player in frame.players:
                self.assertGreaterEqual(player.position[0], 0.0)
                self.assertLessEqual(player.position[0], COURT_LENGTH_FT)
                self.assertGreaterEqual(player.position[1], 0.0)
                self.assertLessEqual(player.position[1], COURT_WIDTH_FT)


class SamplingTests(unittest.TestCase):
    def test_nucleus_sampling_respects_dominant_mass(self) -> None:
        logits = np.asarray((10.0, 0.0, -5.0))
        rng = np.random.default_rng(9)
        samples = {
            nucleus_sample_index(logits, rng, top_p=0.8)
            for _ in range(50)
        }
        self.assertEqual(samples, {0})

    def test_offset_grid_is_bounded_and_reproducible(self) -> None:
        grid = OffsetGrid(2, 11, (3.0, 2.0))
        logits = np.linspace(-1.0, 1.0, grid.size)
        first = grid.sample(logits, np.random.default_rng(12))
        second = grid.sample(logits, np.random.default_rng(12))
        np.testing.assert_array_equal(first, second)
        self.assertTrue(np.all(np.abs(first) <= np.asarray((3.0, 2.0))))


class NeuralArchitectureTests(unittest.TestCase):
    def test_paper_scale_configuration_is_validated(self) -> None:
        court = CourtMotionConfig()
        sports = SportsNGENConfig()
        self.assertEqual(court.temporal_stride, 6)
        self.assertEqual(court.trajectory_classes, 121)
        self.assertEqual(sports.offset_bins_per_axis, 31)

    def test_missing_tracking_dependency_fails_clearly(self) -> None:
        if torch_available():
            self.skipTest("PyTorch is installed")
        with self.assertRaisesRegex(ImportError, "tracking"):
            CourtMotionModel(CourtMotionConfig(), [(0, 1)])


if __name__ == "__main__":
    unittest.main()
