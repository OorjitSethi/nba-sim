from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import exp

import numpy as np

from nba_sim.domain.enums import ShotZone
from nba_sim.domain.profiles import PlayerProfile
from nba_sim.spatial.state import SpatialSummary


class TerminalAction(str, Enum):
    TURNOVER = "turnover"
    DEFENSIVE_FOUL = "defensive_foul"
    TWO_POINT_ATTEMPT = "two_point_attempt"
    THREE_POINT_ATTEMPT = "three_point_attempt"
    PERIOD_END = "period_end"


@dataclass(frozen=True)
class PossessionContext:
    offense: tuple[PlayerProfile, ...]
    defense: tuple[PlayerProfile, ...]
    ball_handler: PlayerProfile
    period: int
    period_clock_seconds: float
    shot_clock_seconds: float
    score_margin: int
    offense_is_home: bool
    spatial: SpatialSummary | None = None
    target_pace: float = 99.0
    transition: bool = False

    def __post_init__(self) -> None:
        if len(self.offense) != 5 or len(self.defense) != 5:
            raise ValueError("EPV context requires two five-player lineups")
        if self.ball_handler not in self.offense:
            raise ValueError("ball handler must be in the offensive lineup")
        if self.period <= 0:
            raise ValueError("period must be positive")
        if self.period_clock_seconds < 0 or self.shot_clock_seconds < 0:
            raise ValueError("clocks cannot be negative")
        if self.target_pace <= 0:
            raise ValueError("target pace must be positive")


@dataclass(frozen=True)
class HazardSnapshot:
    turnover: float
    defensive_foul: float
    two_point_attempt: float
    three_point_attempt: float

    def __post_init__(self) -> None:
        values = (
            self.turnover,
            self.defensive_foul,
            self.two_point_attempt,
            self.three_point_attempt,
        )
        if any(not np.isfinite(value) or value < 0 for value in values):
            raise ValueError("hazards must be finite and non-negative")
        if self.total <= 0:
            raise ValueError("at least one hazard must be positive")

    @property
    def total(self) -> float:
        return (
            self.turnover
            + self.defensive_foul
            + self.two_point_attempt
            + self.three_point_attempt
        )

    def probabilities_given_event(self) -> np.ndarray:
        return np.asarray(
            [
                self.turnover,
                self.defensive_foul,
                self.two_point_attempt,
                self.three_point_attempt,
            ],
            dtype=float,
        ) / self.total


@dataclass(frozen=True)
class ActionSample:
    action: TerminalAction
    elapsed_seconds: float
    hazards: HazardSnapshot | None


class CompetingRiskEPVModel:
    """Non-homogeneous semi-Markov terminal-action model.

    The fallback coefficients are league-shaped priors, not fitted weights. The API
    is deliberately identical to the future trained hazard model.
    """

    def __init__(self, *, integration_step_seconds: float = 0.25) -> None:
        if integration_step_seconds <= 0:
            raise ValueError("integration step must be positive")
        self.integration_step_seconds = integration_step_seconds

    def hazards(
        self,
        context: PossessionContext,
        *,
        elapsed_seconds: float,
    ) -> HazardSnapshot:
        shot_clock = max(0.0, context.shot_clock_seconds - elapsed_seconds)
        elapsed_seconds = max(0.0, elapsed_seconds)

        # Terminal pressure rises throughout a possession and sharply near expiry.
        urgency = 1.0 / (1.0 + exp((shot_clock - 4.0) / 1.15))
        terminal_rate = 0.985 * (
            0.027 + 0.0032 * elapsed_seconds + 0.55 * urgency
        )
        terminal_rate *= context.target_pace / 99.0
        if context.transition:
            terminal_rate *= 1.75

        late_game = context.period >= 4 and context.period_clock_seconds <= 120.0
        if late_game and context.score_margin > 0:
            # Leading offenses use the clock; the effect strengthens near zero.
            clock_fraction = context.period_clock_seconds / 120.0
            terminal_rate *= 0.74 + 0.18 * clock_fraction
        elif late_game and context.score_margin < 0:
            urgency_from_margin = min(0.55, -context.score_margin * 0.035)
            urgency_from_clock = 1.0 - context.period_clock_seconds / 120.0
            terminal_rate *= 1.0 + urgency_from_margin * urgency_from_clock

        turnover_share = context.ball_handler.turnover_probability
        turnover_share += 0.012 * np.mean(
            [max(0.0, defender.defensive_impact) for defender in context.defense]
        )
        if context.spatial is not None:
            if context.spatial.closest_defender_ft < 2.5:
                turnover_share += 0.018
            turnover_share -= min(
                0.012,
                context.spatial.offensive_spacing_ft * 0.0005,
            )
        turnover_share = float(np.clip(turnover_share, 0.075, 0.22))

        three_share = self._lineup_three_share(context.offense)
        if context.spatial is not None:
            # Rim pressure and compressed spacing push attempts outward.
            three_share += 0.018 * context.spatial.rim_defenders_within_six_ft
            three_share += max(
                0.0,
                (12.0 - context.spatial.offensive_spacing_ft) * 0.004,
            )
        if shot_clock <= 3.0:
            three_share += 0.035
        if late_game and context.score_margin < 0:
            three_share += min(0.30, -context.score_margin * 0.025)
        three_share = float(np.clip(three_share, 0.24, 0.58))

        live_ball_share = 1.0 - turnover_share
        defensive_foul_hazard = 0.0062 + 0.0015 * urgency
        if (
            late_game
            and 0 < context.score_margin <= 8
            and context.period_clock_seconds <= 45.0
        ):
            # The defense is trailing and intentionally extends the game.
            defensive_foul_hazard += 0.22
        return HazardSnapshot(
            turnover=terminal_rate * turnover_share,
            defensive_foul=defensive_foul_hazard,
            two_point_attempt=terminal_rate * live_ball_share * (1.0 - three_share),
            three_point_attempt=terminal_rate * live_ball_share * three_share,
        )

    def sample_terminal_action(
        self,
        context: PossessionContext,
        rng: np.random.Generator,
    ) -> ActionSample:
        available = min(
            context.shot_clock_seconds,
            context.period_clock_seconds,
        )
        elapsed = 0.0
        latest: HazardSnapshot | None = None
        actions = (
            TerminalAction.TURNOVER,
            TerminalAction.DEFENSIVE_FOUL,
            TerminalAction.TWO_POINT_ATTEMPT,
            TerminalAction.THREE_POINT_ATTEMPT,
        )

        while elapsed < available - 1e-9:
            dt = min(self.integration_step_seconds, available - elapsed)
            latest = self.hazards(context, elapsed_seconds=elapsed)
            terminal_probability = 1.0 - exp(-latest.total * dt)
            elapsed += dt
            if rng.random() < terminal_probability:
                action = actions[
                    int(rng.choice(4, p=latest.probabilities_given_event()))
                ]
                return ActionSample(action, elapsed, latest)

        if context.period_clock_seconds <= context.shot_clock_seconds:
            return ActionSample(TerminalAction.PERIOD_END, available, latest)
        # At expiry, most NBA possessions still produce a rushed attempt rather
        # than an official shot-clock violation. Preserve a smaller violation tail.
        if rng.random() < 0.15:
            return ActionSample(TerminalAction.TURNOVER, available, latest)
        late_three_probability = min(
            0.72,
            self._lineup_three_share(context.offense) + 0.20,
        )
        forced_action = (
            TerminalAction.THREE_POINT_ATTEMPT
            if rng.random() < late_three_probability
            else TerminalAction.TWO_POINT_ATTEMPT
        )
        return ActionSample(forced_action, available, latest)

    def expected_possession_value(self, context: PossessionContext) -> float:
        snapshot = self.hazards(context, elapsed_seconds=0.0)
        probabilities = snapshot.probabilities_given_event()
        two_probability = self._lineup_make_probability(
            context.offense,
            point_value=2,
        )
        three_probability = self._lineup_make_probability(
            context.offense,
            point_value=3,
        )
        defense_adjustment = np.mean(
            [defender.defensive_impact for defender in context.defense]
        )
        two_probability = float(np.clip(two_probability - defense_adjustment, 0.2, 0.8))
        three_probability = float(
            np.clip(three_probability - 0.65 * defense_adjustment, 0.15, 0.65)
        )
        # Add a conservative free-throw expectation to shot branches.
        foul_value = np.mean(
            [
                player.shooting_foul_probability * player.free_throw_probability
                for player in context.offense
            ]
        )
        return float(
            probabilities[2] * (2.0 * two_probability + 2.0 * foul_value)
            + probabilities[3] * (3.0 * three_probability + 2.2 * foul_value)
            + probabilities[1] * 0.10
        )

    @staticmethod
    def _lineup_three_share(lineup: tuple[PlayerProfile, ...]) -> float:
        attempts = 0.0
        threes = 0.0
        for player in lineup:
            weight = max(0.01, player.usage_rate)
            attempts += weight
            threes += weight * sum(
                profile.frequency
                for zone, profile in player.shot_zones.items()
                if zone.point_value == 3
            )
        return threes / max(attempts, 1e-9)

    @staticmethod
    def _lineup_make_probability(
        lineup: tuple[PlayerProfile, ...],
        *,
        point_value: int,
    ) -> float:
        numerator = 0.0
        denominator = 0.0
        for player in lineup:
            usage = max(0.01, player.usage_rate)
            for zone, profile in player.shot_zones.items():
                if zone.point_value != point_value:
                    continue
                weight = usage * profile.frequency
                numerator += weight * profile.make_probability
                denominator += weight
        if denominator <= 0:
            return 0.35 if point_value == 3 else 0.50
        return numerator / denominator
