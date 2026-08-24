from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import date

from nba_sim.competition.league import (
    TEAM_TO_CONFERENCE,
    TEAM_TO_DIVISION,
)
from nba_sim.data.current_profiles import CurrentRosterProfileRepository
from nba_sim.franchise.models import (
    FranchiseRecord,
    CoachingProfileRecord,
    LeagueCalendar,
    PlayerLifecycleRecord,
    PlayerHealthRecord,
    PlayerRecord,
    ScoutingDepartmentRecord,
    ScoutingReportRecord,
    TeamChemistryRecord,
)
from nba_sim.franchise.lifecycle import build_lifecycle_record
from nba_sim.franchise.health import build_health_record
from nba_sim.franchise.chemistry import (
    default_coaching_profile,
    default_team_chemistry,
)
from nba_sim.franchise.scouting import (
    build_initial_scouting_report,
    default_scouting_department,
)
from nba_sim.franchise.ratings import (
    RatingInput,
    build_league_ratings,
    lifecycle_composites,
)
from nba_sim.franchise.state import LeagueState


def build_current_league_state(
    profiles: CurrentRosterProfileRepository,
    *,
    league_name: str,
    user_team: str,
    seed: int,
    as_of: date | None = None,
) -> LeagueState:
    normalized_team = user_team.upper()
    teams = tuple(sorted(profiles.available_teams()))
    if set(teams) != set(TEAM_TO_DIVISION):
        raise ValueError("franchise mode requires all 30 NBA teams")
    if normalized_team not in teams:
        raise ValueError(f"unknown user team: {normalized_team}")
    if seed < 0:
        raise ValueError("franchise seed must be non-negative")
    normalized_name = league_name.strip()
    if not normalized_name:
        raise ValueError("league name cannot be empty")

    franchises: list[FranchiseRecord] = []
    players: list[PlayerRecord] = []
    player_lifecycles: list[PlayerLifecycleRecord] = []
    profiles_by_id = {}
    for abbreviation in teams:
        team = profiles.load_team(abbreviation)
        franchises.append(
            FranchiseRecord(
                team=abbreviation,
                name=team.name,
                conference=TEAM_TO_CONFERENCE[abbreviation],
                division=TEAM_TO_DIVISION[abbreviation],
            )
        )
        for player in team.roster:
            profiles_by_id[player.player_id] = player
            player_record = PlayerRecord(
                player_id=player.player_id,
                name=player.name,
                team=abbreviation,
                position=player.position,
                roster_status="active",
                expected_minutes=player.expected_minutes,
                profile_source=profiles.profile_source(player.player_id),
            )
            players.append(player_record)
            player_lifecycles.append(
                build_lifecycle_record(
                    player_record,
                    profile=player,
                    statistics=profiles.player_statistics(player.player_id),
                    season="2026-27",
                )
            )

    lifecycle_by_id = {
        record.player_id: record for record in player_lifecycles
    }
    ratings = build_league_ratings(
        RatingInput(
            player=player,
            profile=profiles_by_id[player.player_id],
            statistics=profiles.player_statistics(player.player_id),
            lifecycle=lifecycle_by_id[player.player_id],
            historical_profile=profiles.legacy.load_player(
                player.player_id
            ),
        )
        for player in players
    )
    player_lifecycles = [
        replace(
            lifecycle_by_id[player.player_id],
            **lifecycle_composites(ratings[player.player_id]),
            potential_mean=max(
                float(ratings[player.player_id]["overall"]),
                float(ratings[player.player_id]["attributes"]["potential"]),
            ),
        )
        for player in players
    ]

    current = as_of or date.today()
    cap_start = date(2026, 7, 1)
    cap_end = date(2027, 6, 30)
    current = max(cap_start, min(current, cap_end))
    calendar = LeagueCalendar(
        season="2026-27",
        cap_year_start=cap_start,
        cap_year_end=cap_end,
        regular_season_start=date(2026, 10, 20),
        regular_season_end=date(2027, 4, 12),
        current_date=current,
    )
    lifecycle_by_id = {
        record.player_id: record for record in player_lifecycles
    }
    player_health: list[PlayerHealthRecord] = [
        build_health_record(
            player,
            lifecycle=lifecycle_by_id.get(player.player_id),
            as_of=current,
        )
        for player in players
    ]
    team_chemistry: list[TeamChemistryRecord] = [
        default_team_chemistry(team, as_of=current) for team in teams
    ]
    coaching_profiles: list[CoachingProfileRecord] = [
        default_coaching_profile(team, as_of=current) for team in teams
    ]
    scouting_reports: list[ScoutingReportRecord] = [
        build_initial_scouting_report(
            player,
            lifecycle_by_id[player.player_id],
            as_of=current,
            seed=seed,
        )
        for player in players
    ]
    scouting_departments: list[ScoutingDepartmentRecord] = [
        default_scouting_department(team, as_of=current) for team in teams
    ]
    identity = "|".join(
        (
            "2026-27",
            normalized_name,
            normalized_team,
            str(seed),
            current.isoformat(),
        )
    )
    return LeagueState(
        schema_version=1,
        league_id=f"league-{hashlib.sha256(identity.encode()).hexdigest()[:16]}",
        league_name=normalized_name,
        season="2026-27",
        seed=seed,
        user_team=normalized_team,
        calendar=calendar,
        franchises=tuple(franchises),
        players=tuple(
            sorted(players, key=lambda player: (player.team, player.player_id))
        ),
        player_lifecycles=tuple(
            sorted(
                player_lifecycles,
                key=lambda record: record.player_id,
            )
        ),
        player_health=tuple(
            sorted(player_health, key=lambda record: record.player_id)
        ),
        team_chemistry=tuple(team_chemistry),
        coaching_profiles=tuple(coaching_profiles),
        scouting_reports=tuple(
            sorted(scouting_reports, key=lambda record: record.player_id)
        ),
        scouting_departments=tuple(scouting_departments),
    )
