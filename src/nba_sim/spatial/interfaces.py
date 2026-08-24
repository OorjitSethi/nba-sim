from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from nba_sim.spatial.state import (
    COURT_LENGTH_FT,
    COURT_WIDTH_FT,
    AgentState,
    SpatialFrame,
)


@dataclass(frozen=True)
class TrajectoryRollout:
    frames: tuple[SpatialFrame, ...]
    model_name: str
    trained: bool

    def __post_init__(self) -> None:
        if not self.frames:
            raise ValueError("trajectory rollout cannot be empty")


class TrajectoryModel(Protocol):
    name: str
    trained: bool

    def rollout(
        self,
        initial_frame: SpatialFrame,
        *,
        steps: int,
        step_seconds: float,
        rng: np.random.Generator,
    ) -> TrajectoryRollout:
        ...


class KinematicTrajectoryModel:
    """Physics-constrained fallback, clearly separated from learned models."""

    name = "kinematic-spacing-fallback"
    trained = False

    def __init__(
        self,
        *,
        max_player_speed_ft_s: float = 28.0,
        player_noise_ft_s: float = 0.35,
    ) -> None:
        self.max_player_speed_ft_s = max_player_speed_ft_s
        self.player_noise_ft_s = player_noise_ft_s

    def rollout(
        self,
        initial_frame: SpatialFrame,
        *,
        steps: int,
        step_seconds: float,
        rng: np.random.Generator,
    ) -> TrajectoryRollout:
        if steps < 0:
            raise ValueError("steps cannot be negative")
        if step_seconds <= 0:
            raise ValueError("step_seconds must be positive")

        frames = [initial_frame]
        current = initial_frame
        for _ in range(steps):
            current = self._step(current, step_seconds, rng)
            frames.append(current)
        return TrajectoryRollout(tuple(frames), self.name, self.trained)

    def _step(
        self,
        frame: SpatialFrame,
        dt: float,
        rng: np.random.Generator,
    ) -> SpatialFrame:
        updated: list[AgentState] = []
        for agent in frame.agents:
            velocity = np.asarray(agent.velocity, dtype=np.float64).copy()
            if not agent.is_ball:
                velocity[:2] += rng.normal(0.0, self.player_noise_ft_s, size=2)
                speed = float(np.linalg.norm(velocity[:2]))
                if speed > self.max_player_speed_ft_s:
                    velocity[:2] *= self.max_player_speed_ft_s / speed
                velocity[2] = 0.0

            position = np.asarray(agent.position, dtype=np.float64) + velocity * dt
            position[0] = np.clip(position[0], 0.0, COURT_LENGTH_FT)
            position[1] = np.clip(position[1], 0.0, COURT_WIDTH_FT)
            if not agent.is_ball:
                position[2] = 0.0
            else:
                position[2] = max(0.0, position[2])

            updated.append(
                AgentState(
                    agent_id=agent.agent_id,
                    team=agent.team,
                    position=position,
                    velocity=velocity,
                    is_ball=agent.is_ball,
                    shoulder_normal=agent.shoulder_normal,
                    skeleton=agent.skeleton,
                )
            )

        return SpatialFrame(
            timestamp_seconds=frame.timestamp_seconds + dt,
            game_clock_seconds=max(0.0, frame.game_clock_seconds - dt),
            shot_clock_seconds=max(0.0, frame.shot_clock_seconds - dt),
            possession_team=frame.possession_team,
            agents=tuple(updated),
        )
