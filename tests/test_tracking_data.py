from __future__ import annotations

import unittest

import numpy as np

from nba_sim.spatial.training_data import (
    AxisOffsetDiscretizer,
    TrackingSequence,
    TrajectoryDiscretizer2D,
)


def make_sequence() -> TrackingSequence:
    timesteps = 6
    positions = np.zeros((timesteps, 10, 2), dtype=float)
    for timestep in range(timesteps):
        positions[timestep, :, 0] = np.arange(10) + timestep * 0.2
        positions[timestep, :, 1] = np.arange(10) * 0.5
    ball = np.zeros((timesteps, 3), dtype=float)
    ball[:, 0] = np.arange(timesteps) * 0.3
    ball[:, 2] = 3.5
    skeletons = np.zeros((timesteps * 6, 10, 29, 3), dtype=float)
    shoulder = np.zeros((timesteps, 10, 2), dtype=float)
    shoulder[..., 0] = 1.0
    events = np.zeros((timesteps, 10, 9), dtype=np.float32)
    events[3, 2, 1] = 1.0
    return TrackingSequence(
        sequence_id="test-possession",
        player_ids=np.arange(10) + 100,
        team_indices=np.asarray((0, 0, 0, 0, 0, 1, 1, 1, 1, 1)),
        possession_team_index=0,
        positions_5hz=positions,
        ball_positions_5hz=ball,
        skeletons_30hz=skeletons,
        shoulder_normals_5hz=shoulder,
        event_labels_5hz=events,
        context_features=np.zeros(16),
    )


class TrackingSequenceTests(unittest.TestCase):
    def test_object_tokens_match_sportsngen_contract(self) -> None:
        sequence = make_sequence()
        features = sequence.sportsngen_object_features()
        self.assertEqual(features.shape, (6, 11, 13))
        np.testing.assert_array_equal(features[:, -1, -1], np.ones(6))
        np.testing.assert_array_equal(features[:, :5, 10], np.ones((6, 5)))
        np.testing.assert_array_equal(features[:, 5:10, 11], np.ones((6, 5)))

    def test_noise_is_seeded_and_ball_only(self) -> None:
        sequence = make_sequence()
        clean = sequence.sportsngen_object_features()
        noisy_a = sequence.sportsngen_object_features(
            inject_noise=True,
            rng=np.random.default_rng(9),
        )
        noisy_b = sequence.sportsngen_object_features(
            inject_noise=True,
            rng=np.random.default_rng(9),
        )
        np.testing.assert_array_equal(noisy_a, noisy_b)
        np.testing.assert_array_equal(clean[:, :10, :6], noisy_a[:, :10, :6])
        self.assertFalse(np.array_equal(clean[:, -1, :6], noisy_a[:, -1, :6]))

    def test_event_projection_has_past_current_future_windows(self) -> None:
        targets = make_sequence().event_window_targets(
            past_seconds=0.4,
            future_seconds=0.4,
        )
        self.assertEqual(targets.shape, (6, 10, 3, 9))
        self.assertEqual(targets[3, 2, 1, 1], 1)
        self.assertEqual(targets[2, 2, 2, 1], 1)
        self.assertEqual(targets[4, 2, 0, 1], 1)

    def test_courtmotion_trajectory_classes_round_trip(self) -> None:
        sequence = make_sequence()
        discretizer = TrajectoryDiscretizer2D()
        targets = sequence.courtmotion_trajectory_targets(discretizer)
        decoded = discretizer.decode_centers(targets)
        self.assertEqual(targets.shape, (5, 10))
        np.testing.assert_allclose(decoded[..., 0], 0.0, atol=0.51)
        np.testing.assert_allclose(decoded[..., 1], 0.0, atol=0.51)

    def test_axis_discretizer_bounds_large_ball_offsets(self) -> None:
        discretizer = AxisOffsetDiscretizer(31, (4.0, 4.0, 8.0))
        encoded = discretizer.encode(np.asarray((99.0, -99.0, 2.0)))
        self.assertEqual(encoded[0], 30)
        self.assertEqual(encoded[1], 0)
        self.assertTrue(0 <= encoded[2] <= 30)


if __name__ == "__main__":
    unittest.main()
