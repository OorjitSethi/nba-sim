from __future__ import annotations

from dataclasses import dataclass, field

from nba_sim.domain.enums import GameStatus
from nba_sim.domain.events import Event, EventType
from nba_sim.domain.rules import Ruleset


@dataclass
class GameState:
    home_team: str
    away_team: str
    period: int
    period_clock_ms: int
    shot_clock_ms: int
    possession_team: str
    home_score: int = 0
    away_score: int = 0
    status: GameStatus = GameStatus.SCHEDULED
    possession_number: int = 0
    team_fouls: dict[str, int] = field(default_factory=dict)
    last_two_minute_fouls: dict[str, int] = field(default_factory=dict)
    player_fouls: dict[int, int] = field(default_factory=dict)
    transition_opportunity: bool = False

    @classmethod
    def initial(
        cls,
        *,
        home_team: str,
        away_team: str,
        opening_possession: str,
        rules: Ruleset,
    ) -> "GameState":
        if opening_possession not in {home_team, away_team}:
            raise ValueError("opening possession must belong to one of the teams")
        return cls(
            home_team=home_team,
            away_team=away_team,
            period=1,
            period_clock_ms=rules.period_length_ms(1),
            shot_clock_ms=rules.initial_shot_clock_ms,
            possession_team=opening_possession,
            team_fouls={home_team: 0, away_team: 0},
            last_two_minute_fouls={home_team: 0, away_team: 0},
        )

    @property
    def score(self) -> tuple[int, int]:
        return self.home_score, self.away_score

    def opponent(self, team: str) -> str:
        if team == self.home_team:
            return self.away_team
        if team == self.away_team:
            return self.home_team
        raise KeyError(team)

    def apply(self, event: Event, rules: Ruleset) -> None:
        if event.event_type is EventType.GAME_STARTED:
            self.status = GameStatus.LIVE
        elif event.event_type is EventType.PERIOD_STARTED:
            self.period = event.period
            self.period_clock_ms = rules.period_length_ms(event.period)
            self.shot_clock_ms = rules.shot_clock_for_new_possession(
                self.period_clock_ms
            )
            self.transition_opportunity = False
            self.team_fouls = {self.home_team: 0, self.away_team: 0}
            self.last_two_minute_fouls = {self.home_team: 0, self.away_team: 0}
        elif event.event_type is EventType.POSSESSION_STARTED:
            if event.team is None:
                raise ValueError("possession event requires a team")
            self.possession_team = event.team
            self.possession_number += 1
        elif event.event_type is EventType.CLOCK_ADVANCED:
            elapsed_ms = int(event.payload["elapsed_ms"])
            if elapsed_ms < 0:
                raise ValueError("clock advancement cannot be negative")
            self.period_clock_ms = max(0, self.period_clock_ms - elapsed_ms)
            self.shot_clock_ms = max(0, self.shot_clock_ms - elapsed_ms)
        elif event.event_type in {
            EventType.SHOT_MADE,
            EventType.FREE_THROW_MADE,
        }:
            if event.team == self.home_team:
                self.home_score += event.points
            elif event.team == self.away_team:
                self.away_score += event.points
            else:
                raise ValueError("scoring event requires a valid team")
        elif event.event_type is EventType.FOUL:
            if event.team is None or event.player_id is None:
                raise ValueError("foul requires team and player")
            self.team_fouls[event.team] = self.team_fouls.get(event.team, 0) + 1
            self.player_fouls[event.player_id] = (
                self.player_fouls.get(event.player_id, 0) + 1
            )
            if self.period_clock_ms <= rules.final_period_seconds * 1_000:
                self.last_two_minute_fouls[event.team] = (
                    self.last_two_minute_fouls.get(event.team, 0) + 1
                )
            reset_ms = event.payload.get("reset_shot_clock_ms")
            if reset_ms is not None:
                self.shot_clock_ms = min(
                    self.period_clock_ms,
                    max(self.shot_clock_ms, int(reset_ms)),
                )
        elif event.event_type is EventType.OFFENSIVE_REBOUND:
            self.shot_clock_ms = rules.shot_clock_after_offensive_rebound(
                self.period_clock_ms
            )
        elif event.event_type is EventType.POSSESSION_CHANGED:
            if event.team is None:
                raise ValueError("possession change requires the new team")
            self.possession_team = event.team
            self.transition_opportunity = bool(event.payload.get("transition", False))
            self.shot_clock_ms = rules.shot_clock_for_new_possession(
                self.period_clock_ms
            )
        elif event.event_type is EventType.GAME_ENDED:
            self.status = GameStatus.FINAL
