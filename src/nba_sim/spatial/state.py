from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from nba_sim.domain.profiles import PlayerProfile


COURT_LENGTH_FT = 94.0
COURT_WIDTH_FT = 50.0
HOOP_X_FT = 89.75
HOOP_Y_FT = 25.0
BALL_AGENT_ID = -1


def _immutable_vector(
    value: np.ndarray | tuple[float, ...] | list[float],
    *,
    dimensions: int,
    name: str,
) -> np.ndarray:
    result = np.asarray(value, dtype=np.float64).copy()
    if result.shape != (dimensions,):
        raise ValueError(f"{name} must have shape ({dimensions},), got {result.shape}")
    if not np.isfinite(result).all():
        raise ValueError(f"{name} contains non-finite values")
    result.flags.writeable = False
    return result


def _immutable_skeleton(value: np.ndarray | None) -> np.ndarray | None:
    if value is None:
        return None
    result = np.asarray(value, dtype=np.float64).copy()
    if result.ndim != 2 or result.shape[1] != 3:
        raise ValueError("skeleton must have shape (joints, 3)")
    if not np.isfinite(result).all():
        raise ValueError("skeleton contains non-finite values")
    result.flags.writeable = False
    return result


@dataclass(frozen=True, eq=False)
class AgentState:
    agent_id: int
    team: str | None
    position: np.ndarray
    velocity: np.ndarray
    is_ball: bool = False
    shoulder_normal: np.ndarray | None = None
    skeleton: np.ndarray | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "position",
            _immutable_vector(self.position, dimensions=3, name="position"),
        )
        object.__setattr__(
            self,
            "velocity",
            _immutable_vector(self.velocity, dimensions=3, name="velocity"),
        )
        if self.shoulder_normal is not None:
            normal = _immutable_vector(
                self.shoulder_normal,
                dimensions=2,
                name="shoulder_normal",
            )
            magnitude = float(np.linalg.norm(normal))
            if magnitude < 1e-9:
                raise ValueError("shoulder normal cannot be zero")
            normalized = np.asarray(normal / magnitude)
            normalized.flags.writeable = False
            object.__setattr__(self, "shoulder_normal", normalized)
        object.__setattr__(self, "skeleton", _immutable_skeleton(self.skeleton))
        if self.is_ball and self.team is not None:
            raise ValueError("the ball cannot belong to a team")
        if not self.is_ball and self.team is None:
            raise ValueError("a player agent requires a team")


@dataclass(frozen=True)
class SpatialFrame:
    timestamp_seconds: float
    game_clock_seconds: float
    shot_clock_seconds: float
    possession_team: str
    agents: tuple[AgentState, ...]

    def __post_init__(self) -> None:
        if self.timestamp_seconds < 0:
            raise ValueError("timestamp cannot be negative")
        if self.game_clock_seconds < 0 or self.shot_clock_seconds < 0:
            raise ValueError("clocks cannot be negative")
        ids = [agent.agent_id for agent in self.agents]
        if len(ids) != len(set(ids)):
            raise ValueError("agent IDs must be unique within a frame")
        balls = [agent for agent in self.agents if agent.is_ball]
        if len(balls) != 1:
            raise ValueError("a spatial frame requires exactly one ball")
        if not any(
            agent.team == self.possession_team
            for agent in self.agents
            if not agent.is_ball
        ):
            raise ValueError("possession team has no player in the frame")

    @property
    def ball(self) -> AgentState:
        return next(agent for agent in self.agents if agent.is_ball)

    @property
    def players(self) -> tuple[AgentState, ...]:
        return tuple(agent for agent in self.agents if not agent.is_ball)

    def team_players(self, team: str) -> tuple[AgentState, ...]:
        return tuple(agent for agent in self.players if agent.team == team)

    def player(self, player_id: int) -> AgentState:
        for agent in self.players:
            if agent.agent_id == player_id:
                return agent
        raise KeyError(player_id)


@dataclass(frozen=True)
class SpatialSummary:
    offensive_spacing_ft: float
    closest_defender_ft: float
    ball_to_rim_ft: float
    rim_defenders_within_six_ft: int
    mean_offensive_speed_ft_s: float
    orientation_to_rim: float

    @classmethod
    def from_frame(cls, frame: SpatialFrame) -> "SpatialSummary":
        offense = frame.team_players(frame.possession_team)
        defense = tuple(
            player for player in frame.players if player.team != frame.possession_team
        )
        if not offense or not defense:
            raise ValueError("spatial summary requires both teams")

        ball_xy = frame.ball.position[:2]
        handler = min(
            offense,
            key=lambda player: float(np.linalg.norm(player.position[:2] - ball_xy)),
        )
        pair_distances = [
            float(np.linalg.norm(first.position[:2] - second.position[:2]))
            for i, first in enumerate(offense)
            for second in offense[i + 1 :]
        ]
        closest_defender = min(
            float(np.linalg.norm(player.position[:2] - handler.position[:2]))
            for player in defense
        )
        hoop = np.asarray((HOOP_X_FT, HOOP_Y_FT))
        ball_to_rim = float(np.linalg.norm(ball_xy - hoop))
        rim_defenders = sum(
            float(np.linalg.norm(player.position[:2] - hoop)) <= 6.0
            for player in defense
        )
        speed = float(
            np.mean([np.linalg.norm(player.velocity[:2]) for player in offense])
        )

        orientation_scores: list[float] = []
        for player in offense:
            if player.shoulder_normal is None:
                continue
            rim_vector = hoop - player.position[:2]
            magnitude = float(np.linalg.norm(rim_vector))
            if magnitude > 1e-9:
                orientation_scores.append(
                    float(np.dot(player.shoulder_normal, rim_vector / magnitude))
                )

        return cls(
            offensive_spacing_ft=float(np.mean(pair_distances)),
            closest_defender_ft=closest_defender,
            ball_to_rim_ft=ball_to_rim,
            rim_defenders_within_six_ft=rim_defenders,
            mean_offensive_speed_ft_s=speed,
            orientation_to_rim=(
                float(np.mean(orientation_scores)) if orientation_scores else 0.0
            ),
        )


def initial_half_court_frame(
    *,
    offense: tuple[PlayerProfile, ...],
    defense: tuple[PlayerProfile, ...],
    possession_team: str,
    game_clock_seconds: float,
    shot_clock_seconds: float,
    ball_handler_id: int,
) -> SpatialFrame:
    if len(offense) != 5 or len(defense) != 5:
        raise ValueError("initial spatial frame requires two five-player lineups")

    offensive_spots = (
        (70.0, 25.0),
        (72.0, 5.0),
        (72.0, 45.0),
        (80.0, 16.0),
        (84.0, 34.0),
    )
    agents: list[AgentState] = []
    for player, (x, y) in zip(offense, offensive_spots):
        direction = np.asarray((HOOP_X_FT - x, HOOP_Y_FT - y))
        direction /= max(float(np.linalg.norm(direction)), 1e-9)
        agents.append(
            AgentState(
                agent_id=player.player_id,
                team=player.team_abbreviation,
                position=np.asarray((x, y, 0.0)),
                velocity=np.zeros(3),
                shoulder_normal=direction,
            )
        )

    for player, (x, y) in zip(defense, offensive_spots):
        defensive_x = min(HOOP_X_FT - 2.0, x + 3.5)
        agents.append(
            AgentState(
                agent_id=player.player_id,
                team=player.team_abbreviation,
                position=np.asarray((defensive_x, y, 0.0)),
                velocity=np.zeros(3),
                shoulder_normal=np.asarray((-1.0, 0.0)),
            )
        )

    handler = next(player for player in agents if player.agent_id == ball_handler_id)
    agents.append(
        AgentState(
            agent_id=BALL_AGENT_ID,
            team=None,
            position=handler.position + np.asarray((0.0, 0.0, 3.5)),
            velocity=np.zeros(3),
            is_ball=True,
        )
    )
    return SpatialFrame(
        timestamp_seconds=0.0,
        game_clock_seconds=game_clock_seconds,
        shot_clock_seconds=shot_clock_seconds,
        possession_team=possession_team,
        agents=tuple(agents),
    )
