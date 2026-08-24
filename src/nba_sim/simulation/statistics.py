from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable, Mapping

from nba_sim.domain.events import Event, EventType
from nba_sim.domain.profiles import TeamProfile


@dataclass
class PlayerBoxScore:
    player_id: int
    name: str
    team: str
    minutes: float = 0.0
    points: int = 0
    field_goals_made: int = 0
    field_goals_attempted: int = 0
    threes_made: int = 0
    threes_attempted: int = 0
    free_throws_made: int = 0
    free_throws_attempted: int = 0
    offensive_rebounds: int = 0
    defensive_rebounds: int = 0
    assists: int = 0
    steals: int = 0
    blocks: int = 0
    turnovers: int = 0
    personal_fouls: int = 0

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def build_box_scores(
    events: Iterable[Event],
    teams: tuple[TeamProfile, TeamProfile],
    player_seconds: Mapping[int, float],
) -> dict[int, PlayerBoxScore]:
    players = {
        player.player_id: player
        for team in teams
        for player in team.roster
    }
    result = {
        player_id: PlayerBoxScore(
            player_id=player_id,
            name=player.name,
            team=player.team_abbreviation,
            minutes=round(player_seconds.get(player_id, 0.0) / 60.0, 2),
        )
        for player_id, player in players.items()
    }

    for event in events:
        if event.player_id is None or event.player_id not in result:
            continue
        box = result[event.player_id]
        if event.event_type is EventType.SHOT_ATTEMPT:
            if bool(event.payload.get("counts_as_fga", True)):
                box.field_goals_attempted += 1
                if int(event.payload["point_value"]) == 3:
                    box.threes_attempted += 1
        elif event.event_type is EventType.SHOT_MADE:
            box.field_goals_made += 1
            box.points += event.points
            if event.points == 3:
                box.threes_made += 1
        elif event.event_type in {
            EventType.FREE_THROW_MADE,
            EventType.FREE_THROW_MISSED,
        }:
            box.free_throws_attempted += 1
            if event.event_type is EventType.FREE_THROW_MADE:
                box.free_throws_made += 1
                box.points += 1
        elif event.event_type is EventType.OFFENSIVE_REBOUND:
            box.offensive_rebounds += 1
        elif event.event_type is EventType.DEFENSIVE_REBOUND:
            box.defensive_rebounds += 1
        elif event.event_type is EventType.ASSIST:
            box.assists += 1
        elif event.event_type is EventType.STEAL:
            box.steals += 1
        elif event.event_type is EventType.BLOCK:
            box.blocks += 1
        elif event.event_type is EventType.TURNOVER:
            box.turnovers += 1
        elif event.event_type is EventType.FOUL:
            box.personal_fouls += 1
    return result
