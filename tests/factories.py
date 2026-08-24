from __future__ import annotations

from nba_sim.domain.enums import ShotZone
from nba_sim.domain.profiles import PlayerProfile, TeamProfile, ZoneProfile


def make_player(
    player_id: int,
    team: str,
    *,
    position: str,
    minutes: float,
    usage: float,
    defense: float = 0.0,
) -> PlayerProfile:
    return PlayerProfile(
        player_id=player_id,
        name=f"{team} Player {player_id}",
        team_abbreviation=team,
        position=position,
        expected_minutes=minutes,
        usage_rate=usage,
        free_throw_probability=0.78,
        turnover_probability=0.13,
        assist_probability=0.55,
        shooting_foul_probability=0.105,
        steal_share=0.8,
        block_probability=0.025,
        offensive_rebound_weight=55.0,
        defensive_rebound_weight=70.0,
        defensive_impact=defense,
        speed=0.65,
        height_inches=78.0,
        shot_zones={
            ShotZone.RESTRICTED_AREA: ZoneProfile(0.34, 0.64),
            ShotZone.PAINT_NON_RA: ZoneProfile(0.15, 0.44),
            ShotZone.MID_RANGE: ZoneProfile(0.10, 0.42),
            ShotZone.LEFT_CORNER_THREE: ZoneProfile(0.08, 0.38),
            ShotZone.RIGHT_CORNER_THREE: ZoneProfile(0.08, 0.38),
            ShotZone.ABOVE_BREAK_THREE: ZoneProfile(0.25, 0.36),
        },
    )


def make_team(team: str, *, id_offset: int, defense: float = 0.0) -> TeamProfile:
    positions = ("G", "G", "F", "F-C", "C", "G", "F", "F-C", "G", "C")
    minutes = (36.0, 34.0, 32.0, 30.0, 28.0, 22.0, 20.0, 16.0, 12.0, 10.0)
    usages = (0.29, 0.25, 0.22, 0.20, 0.18, 0.17, 0.15, 0.14, 0.12, 0.10)
    roster = tuple(
        make_player(
            id_offset + index,
            team,
            position=position,
            minutes=player_minutes,
            usage=usage,
            defense=defense,
        )
        for index, (position, player_minutes, usage) in enumerate(
            zip(positions, minutes, usages)
        )
    )
    return TeamProfile(
        abbreviation=team,
        name=f"{team} Test Team",
        roster=roster,
    )
