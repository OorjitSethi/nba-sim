"""Read-only statistical views of saved games; never rerun a simulation."""
from __future__ import annotations

from nba_sim.competition.league import TEAM_TO_CONFERENCE
from nba_sim.franchise.season_cycle import FranchiseSeasonRecord

COUNTING = (
    "points", "rebounds", "assists", "steals", "blocks", "turnovers",
    "offensive_rebounds", "defensive_rebounds", "personal_fouls",
    "field_goals_made", "field_goals_attempted", "threes_made",
    "threes_attempted", "free_throws_made", "free_throws_attempted",
)


def _empty(**identity: object) -> dict:
    return {**identity, "games": 0, "minutes": 0.0, **dict.fromkeys(COUNTING, 0)}


def _rates(row: dict) -> dict:
    result = dict(row)
    for key, made, attempted in (
        ("fg_pct", "field_goals_made", "field_goals_attempted"),
        ("three_pct", "threes_made", "threes_attempted"),
        ("ft_pct", "free_throws_made", "free_throws_attempted"),
    ):
        result[key] = row[made] / row[attempted] if row[attempted] else None
    return result


def season_statistics(cycle: FranchiseSeasonRecord | None, *, stage: str = "regular_season", player_id: int | None = None) -> dict:
    if stage not in {"regular_season", "playoffs", "play_in"}:
        raise ValueError("Unknown statistics stage")
    teams = {team: _empty(team=team, conference=conference, wins=0, losses=0,
                         points_against=0, box_score_games=0)
             for team, conference in TEAM_TO_CONFERENCE.items()}
    players: dict[int, dict] = {}
    stints: dict[tuple[int, str], dict] = {}
    logs = []
    games = [game for game in cycle.games if game.completed and game.stage == stage] if cycle else []
    for game in games:
        for team, points, opponent_points in (
            (game.home_team, game.home_score, game.away_score),
            (game.away_team, game.away_score, game.home_score),
        ):
            row = teams[team]
            row["games"] += 1
            row["wins"] += int(points > opponent_points)
            row["losses"] += int(points < opponent_points)
            row["points"] += points
            row["points_against"] += opponent_points
            row["box_score_games"] += int(any(box.team == team for box in game.box_scores))
        for box in game.box_scores:
            # A DNP is not an appearance and must not depress per-game averages.
            if box.minutes <= 0:
                continue
            player = players.setdefault(box.player_id, _empty(player_id=box.player_id, name=box.name, teams=[]))
            if box.team not in player["teams"]:
                player["teams"].append(box.team)
            stint = stints.setdefault((box.player_id, box.team), _empty(player_id=box.player_id, name=box.name, team=box.team))
            for row in (player, stint):
                row["games"] += 1
                row["minutes"] += box.minutes
                for key in COUNTING:
                    row[key] += getattr(box, key)
            team_row = teams[box.team]
            team_row["minutes"] += box.minutes
            for key in COUNTING:
                if key != "points":
                    team_row[key] += getattr(box, key)
            if box.player_id == player_id:
                home = box.team == game.home_team
                logs.append({"game_id": game.game_id, "date": game.game_date.isoformat(),
                             "team": box.team, "opponent": game.away_team if home else game.home_team,
                             "home": home, "result": "W" if (game.home_score > game.away_score) == home else "L",
                             "minutes": box.minutes, **{key: getattr(box, key) for key in COUNTING}})
    return {
        "season": cycle.season if cycle else None, "stage": stage,
        "completed_games": len(games),
        "players": [_rates({**row, "team": row["teams"][0] if len(row["teams"]) == 1 else "TOT"}) for row in players.values()],
        "player_stints": [_rates(row) for row in stints.values()],
        "teams": [_rates(row) for row in teams.values()],
        "game_log": sorted(logs, key=lambda row: row["date"], reverse=True),
    }
