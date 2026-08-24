from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import IntEnum

import numpy as np


class TrackingEventClass(IntEnum):
    NO_ACTION = 0
    FREE_THROW = 1
    SHOT_ATTEMPT = 2
    PASS = 3
    DEFLECTION = 4
    BLOCK = 5
    REBOUND = 6
    STEAL = 7
    DRIBBLE = 8


def _readonly(
    value: np.ndarray,
    *,
    name: str,
    ndim: int | None = None,
) -> np.ndarray:
    result = np.asarray(value).copy()
    if ndim is not None and result.ndim != ndim:
        raise ValueError(f"{name} must have {ndim} dimensions, got {result.ndim}")
    if not np.isfinite(result).all():
        raise ValueError(f"{name} contains non-finite values")
    result.flags.writeable = False
    return result


@dataclass(frozen=True, eq=False)
class TrackingSequence:
    """Aligned CourtMotion/SportsNGEN training sequence.

    Player pose is sampled at 30 Hz; positions, ball, and event labels are sampled
    at 5 Hz. A sequence contains exactly ten players and one ball.
    """

    sequence_id: str
    player_ids: np.ndarray
    team_indices: np.ndarray
    possession_team_index: int
    positions_5hz: np.ndarray
    ball_positions_5hz: np.ndarray
    skeletons_30hz: np.ndarray
    shoulder_normals_5hz: np.ndarray
    event_labels_5hz: np.ndarray
    context_features: np.ndarray
    model_hz: int = 5
    skeleton_hz: int = 30
    game_date: date | None = None

    def __post_init__(self) -> None:
        if not self.sequence_id:
            raise ValueError("sequence_id cannot be empty")
        player_ids = _readonly(self.player_ids, name="player_ids", ndim=1)
        team_indices = _readonly(self.team_indices, name="team_indices", ndim=1)
        positions = _readonly(self.positions_5hz, name="positions_5hz", ndim=3)
        ball = _readonly(
            self.ball_positions_5hz,
            name="ball_positions_5hz",
            ndim=2,
        )
        skeletons = _readonly(
            self.skeletons_30hz,
            name="skeletons_30hz",
            ndim=4,
        )
        shoulder = _readonly(
            self.shoulder_normals_5hz,
            name="shoulder_normals_5hz",
            ndim=3,
        )
        events = _readonly(
            self.event_labels_5hz,
            name="event_labels_5hz",
            ndim=3,
        )
        context = _readonly(
            self.context_features,
            name="context_features",
            ndim=1,
        )
        players = player_ids.shape[0]
        timesteps = positions.shape[0]
        if players != 10:
            raise ValueError("NBA tracking sequences require exactly ten players")
        if len(set(int(value) for value in player_ids)) != players:
            raise ValueError("player IDs must be unique")
        if team_indices.shape != (players,):
            raise ValueError("team indices must align with players")
        if set(int(value) for value in team_indices) != {0, 1}:
            raise ValueError("team indices must contain both teams encoded as 0 and 1")
        if sum(team_indices == 0) != 5 or sum(team_indices == 1) != 5:
            raise ValueError("each tracking team must contain five players")
        if self.possession_team_index not in {0, 1}:
            raise ValueError("possession team index must be zero or one")
        if self.game_date is not None and not isinstance(self.game_date, date):
            raise ValueError("game_date must be a date")
        if positions.shape != (timesteps, players, 2):
            raise ValueError("positions must have shape [time, 10, 2]")
        if ball.shape != (timesteps, 3):
            raise ValueError("ball positions must have shape [time, 3]")
        if shoulder.shape != (timesteps, players, 2):
            raise ValueError("shoulder normals must align with player positions")
        if events.shape[:2] != (timesteps, players):
            raise ValueError("event labels must align with time and players")
        if self.skeleton_hz % self.model_hz:
            raise ValueError("skeleton_hz must be divisible by model_hz")
        expected_skeleton_steps = timesteps * (self.skeleton_hz // self.model_hz)
        if skeletons.shape[:2] != (expected_skeleton_steps, players):
            raise ValueError(
                "skeleton frames must align with the 30 Hz to 5 Hz sampling ratio"
            )
        norms = np.linalg.norm(shoulder, axis=-1)
        nonzero = norms > 1e-9
        if nonzero.any() and not np.allclose(norms[nonzero], 1.0, atol=1e-4):
            raise ValueError("nonzero shoulder-normal vectors must be unit length")

        object.__setattr__(self, "player_ids", player_ids)
        object.__setattr__(self, "team_indices", team_indices)
        object.__setattr__(self, "positions_5hz", positions)
        object.__setattr__(self, "ball_positions_5hz", ball)
        object.__setattr__(self, "skeletons_30hz", skeletons)
        object.__setattr__(self, "shoulder_normals_5hz", shoulder)
        object.__setattr__(self, "event_labels_5hz", events)
        object.__setattr__(self, "context_features", context)

    @property
    def timesteps(self) -> int:
        return self.positions_5hz.shape[0]

    @property
    def event_classes(self) -> int:
        return self.event_labels_5hz.shape[-1]

    def courtmotion_trajectory_targets(
        self,
        discretizer: "TrajectoryDiscretizer2D",
    ) -> np.ndarray:
        deltas = np.diff(self.positions_5hz, axis=0)
        return discretizer.encode(deltas)

    def event_window_targets(
        self,
        *,
        past_seconds: float = 2.0,
        future_seconds: float = 2.0,
    ) -> np.ndarray:
        past_steps = max(1, int(round(past_seconds * self.model_hz)))
        future_steps = max(1, int(round(future_seconds * self.model_hz)))
        labels = self.event_labels_5hz.astype(bool)
        output = np.zeros(
            (self.timesteps, 10, 3, self.event_classes),
            dtype=np.float32,
        )
        for timestep in range(self.timesteps):
            past_start = max(0, timestep - past_steps)
            future_stop = min(self.timesteps, timestep + future_steps + 1)
            if past_start < timestep:
                output[timestep, :, 0, :] = labels[past_start:timestep].max(axis=0)
            output[timestep, :, 1, :] = labels[timestep]
            if timestep + 1 < future_stop:
                output[timestep, :, 2, :] = labels[
                    timestep + 1 : future_stop
                ].max(axis=0)
        return output

    def sportsngen_object_features(
        self,
        *,
        inject_noise: bool = False,
        rng: np.random.Generator | None = None,
        position_noise_ft: float = 0.025,
        velocity_noise_ft_s: float = 0.025,
    ) -> np.ndarray:
        """Build [position, velocity, ball delta, time, team flags, ball flag]."""

        player_xyz = np.concatenate(
            [
                self.positions_5hz.astype(np.float64),
                np.zeros((self.timesteps, 10, 1), dtype=np.float64),
            ],
            axis=-1,
        )
        ball = self.ball_positions_5hz.astype(np.float64)[:, None, :]
        positions = np.concatenate([player_xyz, ball], axis=1)
        dt = 1.0 / self.model_hz
        velocities = np.zeros_like(positions)
        velocities[1:] = np.diff(positions, axis=0) / dt

        if inject_noise:
            if rng is None:
                raise ValueError("noise injection requires an explicit RNG")
            # SportsNGEN found input noise essential for recovery from rollout
            # errors. Apply it to the ball only, preserving observed player pose.
            positions[:, -1, :] += rng.uniform(
                -position_noise_ft,
                position_noise_ft,
                size=positions[:, -1, :].shape,
            )
            velocities[:, -1, :] += rng.uniform(
                -velocity_noise_ft_s,
                velocity_noise_ft_s,
                size=velocities[:, -1, :].shape,
            )

        delta_to_ball = positions[:, -1:, :] - positions
        elapsed = (
            np.arange(self.timesteps, dtype=np.float64)[:, None, None]
            * dt
        )
        elapsed = np.broadcast_to(elapsed, (self.timesteps, 11, 1))

        offense_flag = np.zeros((self.timesteps, 11, 1), dtype=np.float64)
        defense_flag = np.zeros_like(offense_flag)
        for player_index, team_index in enumerate(self.team_indices):
            if int(team_index) == self.possession_team_index:
                offense_flag[:, player_index, 0] = 1.0
            else:
                defense_flag[:, player_index, 0] = 1.0
        ball_flag = np.zeros_like(offense_flag)
        ball_flag[:, -1, 0] = 1.0

        return np.concatenate(
            [
                positions,
                velocities,
                delta_to_ball,
                elapsed,
                offense_flag,
                defense_flag,
                ball_flag,
            ],
            axis=-1,
        ).astype(np.float32)


@dataclass(frozen=True)
class TrajectoryDiscretizer2D:
    bins_per_axis: int = 11
    max_abs_offset_ft: float = 5.0

    def __post_init__(self) -> None:
        if self.bins_per_axis < 3 or self.bins_per_axis % 2 == 0:
            raise ValueError("bins_per_axis must be an odd integer >= 3")
        if self.max_abs_offset_ft <= 0:
            raise ValueError("max_abs_offset_ft must be positive")

    @property
    def centers(self) -> np.ndarray:
        return np.linspace(
            -self.max_abs_offset_ft,
            self.max_abs_offset_ft,
            self.bins_per_axis,
        )

    def encode(self, offsets: np.ndarray) -> np.ndarray:
        offsets = np.asarray(offsets, dtype=np.float64)
        if offsets.shape[-1] != 2:
            raise ValueError("2D trajectory offsets must end in dimension two")
        clipped = np.clip(
            offsets,
            -self.max_abs_offset_ft,
            self.max_abs_offset_ft,
        )
        width = 2.0 * self.max_abs_offset_ft / (self.bins_per_axis - 1)
        indices = np.rint(
            (clipped + self.max_abs_offset_ft) / width
        ).astype(np.int64)
        return indices[..., 0] * self.bins_per_axis + indices[..., 1]

    def decode_centers(self, classes: np.ndarray) -> np.ndarray:
        classes = np.asarray(classes, dtype=np.int64)
        if np.any(classes < 0) or np.any(classes >= self.bins_per_axis**2):
            raise ValueError("trajectory class is outside the grid")
        x_index = classes // self.bins_per_axis
        y_index = classes % self.bins_per_axis
        centers = self.centers
        return np.stack([centers[x_index], centers[y_index]], axis=-1)


@dataclass(frozen=True)
class AxisOffsetDiscretizer:
    bins_per_axis: int
    max_abs_offsets: tuple[float, float, float]

    def __post_init__(self) -> None:
        if self.bins_per_axis < 3 or self.bins_per_axis % 2 == 0:
            raise ValueError("bins_per_axis must be an odd integer >= 3")
        if any(value <= 0 for value in self.max_abs_offsets):
            raise ValueError("offset limits must be positive")

    def encode(self, offsets: np.ndarray) -> np.ndarray:
        offsets = np.asarray(offsets, dtype=np.float64)
        if offsets.shape[-1] != 3:
            raise ValueError("axis offsets must end in dimension three")
        limits = np.asarray(self.max_abs_offsets)
        clipped = np.clip(offsets, -limits, limits)
        widths = 2.0 * limits / (self.bins_per_axis - 1)
        return np.rint((clipped + limits) / widths).astype(np.int64)
