from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np

from nba_sim.domain.enums import GameStatus
from nba_sim.domain.events import EventLog, EventType
from nba_sim.domain.profiles import TeamProfile
from nba_sim.domain.rules import NBA_2025_26, Ruleset
from nba_sim.domain.state import GameState
from nba_sim.epv.model import CompetingRiskEPVModel
from nba_sim.randomness import RandomStreamFactory
from nba_sim.simulation.emitter import EventEmitter
from nba_sim.simulation.possession import PossessionSimulator
from nba_sim.simulation.rotation import RotationManager
from nba_sim.simulation.statistics import PlayerBoxScore, build_box_scores
from nba_sim.spatial.interfaces import TrajectoryModel


@dataclass(frozen=True)
class GameResult:
    home_team: TeamProfile
    away_team: TeamProfile
    home_score: int
    away_score: int
    periods: int
    seed: int
    events: EventLog
    box_scores: Mapping[int, PlayerBoxScore]

    @property
    def winner(self) -> str:
        if self.home_score > self.away_score:
            return self.home_team.abbreviation
        return self.away_team.abbreviation

    @property
    def margin(self) -> int:
        return self.home_score - self.away_score

    @property
    def total(self) -> int:
        return self.home_score + self.away_score

    def team_box_scores(self, abbreviation: str) -> tuple[PlayerBoxScore, ...]:
        return tuple(
            box
            for box in self.box_scores.values()
            if box.team == abbreviation and box.minutes > 0
        )

    def as_dict(self, *, include_events: bool = False) -> dict[str, object]:
        result: dict[str, object] = {
            "home_team": self.home_team.abbreviation,
            "away_team": self.away_team.abbreviation,
            "home_score": self.home_score,
            "away_score": self.away_score,
            "winner": self.winner,
            "margin": self.margin,
            "total": self.total,
            "periods": self.periods,
            "seed": self.seed,
            "box_scores": [
                box.as_dict()
                for box in sorted(
                    self.box_scores.values(),
                    key=lambda row: (row.team, -row.minutes, row.name),
                )
                if box.minutes > 0
            ],
        }
        if include_events:
            result["events"] = self.events.as_records()
        return result


class GameSimulator:
    def __init__(
        self,
        *,
        home_team: TeamProfile,
        away_team: TeamProfile,
        rules: Ruleset = NBA_2025_26,
        epv_model: CompetingRiskEPVModel | None = None,
        trajectory_model: TrajectoryModel | None = None,
    ) -> None:
        if home_team.abbreviation == away_team.abbreviation:
            raise ValueError("a team cannot play itself")
        self.home_team = home_team
        self.away_team = away_team
        self.rules = rules
        self.possession_simulator = PossessionSimulator(
            epv_model=epv_model,
            trajectory_model=trajectory_model,
        )

    def simulate(self, *, seed: int = 0) -> GameResult:
        streams = RandomStreamFactory(seed)
        rng = streams.generator("game")
        opening_team = (
            self.home_team.abbreviation
            if rng.random() < 0.5
            else self.away_team.abbreviation
        )
        state = GameState.initial(
            home_team=self.home_team.abbreviation,
            away_team=self.away_team.abbreviation,
            opening_possession=opening_team,
            rules=self.rules,
        )
        emitter = EventEmitter(state, self.rules)
        home_rotation = RotationManager(self.home_team)
        away_rotation = RotationManager(self.away_team)
        rotations = {
            self.home_team.abbreviation: home_rotation,
            self.away_team.abbreviation: away_rotation,
        }
        teams = {
            self.home_team.abbreviation: self.home_team,
            self.away_team.abbreviation: self.away_team,
        }

        emitter.emit(EventType.GAME_STARTED)
        period = 1
        maximum_periods = self.rules.regulation_periods + 12
        while period <= maximum_periods:
            emitter.emit(EventType.PERIOD_STARTED, period=period)
            period_starter = self._period_starter(
                period=period,
                opening_team=opening_team,
                rng=rng,
            )
            if state.possession_team != period_starter:
                emitter.emit(
                    EventType.POSSESSION_CHANGED,
                    team=period_starter,
                )

            while state.period_clock_ms > 0:
                offense_abbreviation = state.possession_team
                defense_abbreviation = state.opponent(offense_abbreviation)
                offense = teams[offense_abbreviation]
                defense = teams[defense_abbreviation]
                emitter.emit(
                    EventType.POSSESSION_STARTED,
                    team=offense_abbreviation,
                )
                result = self.possession_simulator.simulate(
                    emitter=emitter,
                    offense=offense,
                    defense=defense,
                    offense_lineup=rotations[offense_abbreviation].lineup,
                    defense_lineup=rotations[defense_abbreviation].lineup,
                    rng=rng,
                )
                elapsed_seconds = result.elapsed_ms / 1_000.0
                home_rotation.advance(elapsed_seconds)
                away_rotation.advance(elapsed_seconds)

                if state.period_clock_ms <= 0:
                    break
                self._update_rotations(
                    emitter=emitter,
                    rotations=rotations,
                    period=period,
                )

            emitter.emit(EventType.PERIOD_ENDED, period=period)
            regulation_complete = period >= self.rules.regulation_periods
            if regulation_complete and state.home_score != state.away_score:
                break
            period += 1

        if state.home_score == state.away_score:
            raise RuntimeError("game remained tied after the overtime safety limit")
        emitter.emit(EventType.GAME_ENDED)
        if state.status is not GameStatus.FINAL:
            raise AssertionError("game reducer did not reach final state")

        player_seconds = dict(home_rotation.seconds_played)
        player_seconds.update(away_rotation.seconds_played)
        box_scores = build_box_scores(
            emitter.log,
            (self.home_team, self.away_team),
            player_seconds,
        )
        return GameResult(
            home_team=self.home_team,
            away_team=self.away_team,
            home_score=state.home_score,
            away_score=state.away_score,
            periods=period,
            seed=seed,
            events=emitter.log,
            box_scores=box_scores,
        )

    def _period_starter(
        self,
        *,
        period: int,
        opening_team: str,
        rng: np.random.Generator,
    ) -> str:
        other = (
            self.away_team.abbreviation
            if opening_team == self.home_team.abbreviation
            else self.home_team.abbreviation
        )
        if period <= self.rules.regulation_periods:
            return opening_team if period in {1, 4} else other
        return (
            self.home_team.abbreviation
            if rng.random() < 0.5
            else self.away_team.abbreviation
        )

    def _update_rotations(
        self,
        *,
        emitter: EventEmitter,
        rotations: Mapping[str, RotationManager],
        period: int,
    ) -> None:
        if period <= self.rules.regulation_periods:
            completed_periods = period - 1
            period_elapsed = (
                self.rules.regulation_period_ms - emitter.state.period_clock_ms
            ) / 1_000.0
            regulation_elapsed = (
                completed_periods * self.rules.regulation_period_ms / 1_000.0
                + period_elapsed
            )
        else:
            regulation_elapsed = 48.0 * 60.0

        for abbreviation, rotation in rotations.items():
            fouled_out = {
                player_id
                for player_id, fouls in emitter.state.player_fouls.items()
                if fouls >= self.rules.personal_foul_limit
            }
            substitutions = rotation.update(
                regulation_elapsed_seconds=regulation_elapsed,
                fouled_out=fouled_out,
                overtime=period > self.rules.regulation_periods,
            )
            for substitution in substitutions:
                emitter.emit(
                    EventType.SUBSTITUTION,
                    team=abbreviation,
                    player_id=substitution.outgoing,
                    related_player_id=substitution.incoming,
                    payload={
                        "outgoing_player_id": substitution.outgoing,
                        "incoming_player_id": substitution.incoming,
                    },
                )
