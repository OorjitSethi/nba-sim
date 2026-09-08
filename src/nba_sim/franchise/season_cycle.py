from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Iterable, Mapping

from nba_sim.competition.league import (
    TEAM_TO_CONFERENCE,
    TEAM_TO_DIVISION,
    LeagueScheduledGame,
    nba_regular_season_schedule,
)


SEASON_CYCLE_MODEL_VERSION = "franchise-season-cycle.v2"
POSTSEASON_ROUNDS = (
    "play_in",
    "first_round",
    "conference_semifinals",
    "conference_finals",
    "nba_finals",
)


@dataclass(frozen=True)
class SeasonHonorRecipientRecord:
    name: str
    team: str
    rank: int
    score: float
    player_id: int | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "player_id": self.player_id,
            "name": self.name,
            "team": self.team,
            "rank": self.rank,
            "score": round(self.score, 4),
        }

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, object],
    ) -> "SeasonHonorRecipientRecord":
        return cls(
            player_id=(
                int(value["player_id"])
                if value.get("player_id") is not None
                else None
            ),
            name=str(value["name"]),
            team=str(value["team"]).upper(),
            rank=int(value.get("rank", 1)),
            score=float(value.get("score", 0.0)),
        )


@dataclass(frozen=True)
class SeasonHonorRecord:
    key: str
    label: str
    kind: str
    recipients: tuple[SeasonHonorRecipientRecord, ...]
    rationale: str
    model_version: str = "season-honors.v1"

    def __post_init__(self) -> None:
        if self.kind not in {"award", "honors_team", "statistical_title"}:
            raise ValueError("unknown season honor kind")
        if not self.key or not self.label or not self.recipients:
            raise ValueError("season honor requires identity and recipients")

    def as_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "kind": self.kind,
            "recipients": [item.as_dict() for item in self.recipients],
            "rationale": self.rationale,
            "model_version": self.model_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "SeasonHonorRecord":
        return cls(
            key=str(value["key"]),
            label=str(value["label"]),
            kind=str(value["kind"]),
            recipients=tuple(
                SeasonHonorRecipientRecord.from_dict(item)
                for item in value.get("recipients", [])  # type: ignore[arg-type]
                if isinstance(item, Mapping)
            ),
            rationale=str(value.get("rationale", "")),
            model_version=str(value.get("model_version", "season-honors.v1")),
        )


@dataclass(frozen=True)
class SeasonBoxScoreRecord:
    player_id: int
    name: str
    team: str
    minutes: float
    points: int
    field_goals_made: int
    field_goals_attempted: int
    threes_made: int
    threes_attempted: int
    free_throws_made: int
    free_throws_attempted: int
    offensive_rebounds: int
    defensive_rebounds: int
    assists: int
    steals: int
    blocks: int
    turnovers: int
    personal_fouls: int

    @property
    def rebounds(self) -> int:
        return self.offensive_rebounds + self.defensive_rebounds

    def as_dict(self) -> dict[str, object]:
        return {
            "player_id": self.player_id,
            "name": self.name,
            "team": self.team,
            "minutes": self.minutes,
            "points": self.points,
            "field_goals_made": self.field_goals_made,
            "field_goals_attempted": self.field_goals_attempted,
            "threes_made": self.threes_made,
            "threes_attempted": self.threes_attempted,
            "free_throws_made": self.free_throws_made,
            "free_throws_attempted": self.free_throws_attempted,
            "offensive_rebounds": self.offensive_rebounds,
            "defensive_rebounds": self.defensive_rebounds,
            "rebounds": self.rebounds,
            "assists": self.assists,
            "steals": self.steals,
            "blocks": self.blocks,
            "turnovers": self.turnovers,
            "personal_fouls": self.personal_fouls,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "SeasonBoxScoreRecord":
        return cls(
            player_id=int(value["player_id"]),
            name=str(value["name"]),
            team=str(value["team"]).upper(),
            minutes=float(value.get("minutes", 0)),
            points=int(value.get("points", 0)),
            field_goals_made=int(value.get("field_goals_made", 0)),
            field_goals_attempted=int(value.get("field_goals_attempted", 0)),
            threes_made=int(value.get("threes_made", 0)),
            threes_attempted=int(value.get("threes_attempted", 0)),
            free_throws_made=int(value.get("free_throws_made", 0)),
            free_throws_attempted=int(value.get("free_throws_attempted", 0)),
            offensive_rebounds=int(value.get("offensive_rebounds", 0)),
            defensive_rebounds=int(value.get("defensive_rebounds", 0)),
            assists=int(value.get("assists", 0)),
            steals=int(value.get("steals", 0)),
            blocks=int(value.get("blocks", 0)),
            turnovers=int(value.get("turnovers", 0)),
            personal_fouls=int(value.get("personal_fouls", 0)),
        )


@dataclass(frozen=True)
class SeasonGameRecord:
    game_id: str
    game_date: date
    home_team: str
    away_team: str
    stage: str = "regular_season"
    completed: bool = False
    home_score: int | None = None
    away_score: int | None = None
    possessions: float | None = None
    seed: int | None = None
    box_scores: tuple[SeasonBoxScoreRecord, ...] = ()
    round_name: str | None = None
    series_id: str | None = None
    series_game_number: int | None = None

    def __post_init__(self) -> None:
        if not self.game_id or self.home_team == self.away_team:
            raise ValueError("season game identity is invalid")
        if self.stage not in {"regular_season", "play_in", "playoffs"}:
            raise ValueError("unknown season game stage")
        if self.round_name is not None and self.round_name not in POSTSEASON_ROUNDS:
            raise ValueError("unknown postseason round")
        if self.series_game_number is not None and self.series_game_number < 1:
            raise ValueError("series game number must be positive")
        if self.completed and (self.home_score is None or self.away_score is None):
            raise ValueError("completed season game requires a score")
        if not self.completed and (self.home_score is not None or self.box_scores):
            raise ValueError("unplayed season game cannot contain results")

    @property
    def winner(self) -> str | None:
        if not self.completed:
            return None
        return self.home_team if int(self.home_score) > int(self.away_score) else self.away_team

    def as_dict(self, *, include_box_score: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "game_id": self.game_id,
            "date": self.game_date.isoformat(),
            "home_team": self.home_team,
            "away_team": self.away_team,
            "stage": self.stage,
            "completed": self.completed,
            "home_score": self.home_score,
            "away_score": self.away_score,
            "winner": self.winner,
            "possessions": self.possessions,
            "seed": self.seed,
            "round_name": self.round_name,
            "series_id": self.series_id,
            "series_game_number": self.series_game_number,
        }
        if include_box_score:
            value["box_scores"] = [item.as_dict() for item in self.box_scores]
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "SeasonGameRecord":
        return cls(
            game_id=str(value["game_id"]),
            game_date=date.fromisoformat(str(value.get("date", value.get("game_date")))),
            home_team=str(value["home_team"]).upper(),
            away_team=str(value["away_team"]).upper(),
            stage=str(value.get("stage", "regular_season")),
            completed=bool(value.get("completed", False)),
            home_score=int(value["home_score"]) if value.get("home_score") is not None else None,
            away_score=int(value["away_score"]) if value.get("away_score") is not None else None,
            possessions=float(value["possessions"]) if value.get("possessions") is not None else None,
            seed=int(value["seed"]) if value.get("seed") is not None else None,
            round_name=(
                str(value["round_name"])
                if value.get("round_name")
                else None
            ),
            series_id=(
                str(value["series_id"])
                if value.get("series_id")
                else None
            ),
            series_game_number=(
                int(value["series_game_number"])
                if value.get("series_game_number") is not None
                else None
            ),
            box_scores=tuple(
                SeasonBoxScoreRecord.from_dict(item)
                for item in value.get("box_scores", [])  # type: ignore[arg-type]
            ),
        )


@dataclass(frozen=True)
class FranchiseSeasonRecord:
    season: str
    status: str
    games: tuple[SeasonGameRecord, ...]
    champion: str | None = None
    offseason_stage: str | None = None
    awards: tuple[tuple[str, str], ...] = ()
    honors: tuple[SeasonHonorRecord, ...] = ()
    postseason_round: str | None = None
    model_version: str = SEASON_CYCLE_MODEL_VERSION

    def __post_init__(self) -> None:
        if self.status not in {"preseason", "regular_season", "postseason", "offseason", "complete"}:
            raise ValueError("unknown franchise season status")
        if self.postseason_round is not None and self.postseason_round not in POSTSEASON_ROUNDS:
            raise ValueError("unknown completed postseason round")
        ids = [item.game_id for item in self.games]
        if len(ids) != len(set(ids)):
            raise ValueError("franchise season contains duplicate games")

    def as_dict(self) -> dict[str, object]:
        return {
            "season": self.season,
            "status": self.status,
            "games": [item.as_dict() for item in self.games],
            "champion": self.champion,
            "offseason_stage": self.offseason_stage,
            "awards": dict(self.awards),
            "honors": [item.as_dict() for item in self.honors],
            "postseason_round": self.postseason_round,
            "model_version": self.model_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "FranchiseSeasonRecord":
        awards = value.get("awards", {})
        return cls(
            season=str(value["season"]),
            status=str(value["status"]),
            games=tuple(
                SeasonGameRecord.from_dict(item)
                for item in value.get("games", [])  # type: ignore[arg-type]
            ),
            champion=str(value["champion"]) if value.get("champion") else None,
            offseason_stage=str(value["offseason_stage"]) if value.get("offseason_stage") else None,
            awards=tuple(
                (str(key), str(item))
                for key, item in (awards.items() if isinstance(awards, Mapping) else ())
            ),
            honors=tuple(
                SeasonHonorRecord.from_dict(item)
                for item in value.get("honors", [])  # type: ignore[arg-type]
                if isinstance(item, Mapping)
            ),
            postseason_round=(
                str(value["postseason_round"])
                if value.get("postseason_round")
                else None
            ),
            model_version=str(value.get("model_version", SEASON_CYCLE_MODEL_VERSION)),
        )


def initialize_season_cycle(*, season: str, start: date, end: date, seed: int, current: date) -> FranchiseSeasonRecord:
    schedule = nba_regular_season_schedule(start_date=start, end_date=end, seed=seed)
    return FranchiseSeasonRecord(
        season=season,
        status="preseason" if current < start else "regular_season",
        games=tuple(
            SeasonGameRecord(
                game_id=item.game_id,
                game_date=item.game_date,
                home_team=item.home_team,
                away_team=item.away_team,
            )
            for item in schedule
        ),
    )


def games_to_simulate(cycle: FranchiseSeasonRecord, *, user_team: str, scope: str) -> tuple[SeasonGameRecord, ...]:
    remaining = tuple(item for item in cycle.games if not item.completed)
    if not remaining:
        return ()
    if scope == "next_day":
        cutoff = remaining[0].game_date
    elif scope == "next_user_game":
        user_game = next((item for item in remaining if user_team in {item.home_team, item.away_team}), None)
        if user_game is None:
            return ()
        cutoff = user_game.game_date
    elif scope == "seven_days":
        cutoff = remaining[0].game_date + timedelta(days=6)
    elif scope == "thirty_days":
        cutoff = remaining[0].game_date + timedelta(days=29)
    elif scope == "full_season":
        cutoff = remaining[-1].game_date
    else:
        raise ValueError(
            "scope must be next_day, next_user_game, seven_days, thirty_days, or full_season"
        )
    return tuple(item for item in remaining if item.game_date <= cutoff)


def replace_games(cycle: FranchiseSeasonRecord, completed: Iterable[SeasonGameRecord]) -> FranchiseSeasonRecord:
    updates = {item.game_id: item for item in completed}
    games = tuple(updates.get(item.game_id, item) for item in cycle.games)
    regular_done = all(item.completed for item in games if item.stage == "regular_season")
    return replace(cycle, games=games, status="postseason" if regular_done else "regular_season")


def standings(cycle: FranchiseSeasonRecord) -> tuple[dict[str, object], ...]:
    rows = {
        team: {
            "team": team,
            "conference": TEAM_TO_CONFERENCE[team],
            "division": TEAM_TO_DIVISION[team],
            "wins": 0,
            "losses": 0,
            "points_for": 0,
            "points_against": 0,
            "home_wins": 0,
            "home_losses": 0,
            "away_wins": 0,
            "away_losses": 0,
        }
        for team in TEAM_TO_CONFERENCE
    }
    for game in cycle.games:
        if not game.completed or game.stage != "regular_season":
            continue
        home, away = rows[game.home_team], rows[game.away_team]
        home["points_for"] += int(game.home_score)
        home["points_against"] += int(game.away_score)
        away["points_for"] += int(game.away_score)
        away["points_against"] += int(game.home_score)
        if game.winner == game.home_team:
            home["wins"] += 1; home["home_wins"] += 1
            away["losses"] += 1; away["away_losses"] += 1
        else:
            away["wins"] += 1; away["away_wins"] += 1
            home["losses"] += 1; home["home_losses"] += 1
    result = []
    for row in rows.values():
        games = int(row["wins"]) + int(row["losses"])
        result.append({
            **row,
            "games": games,
            "win_percentage": round(int(row["wins"]) / games, 6) if games else 0.0,
            "point_differential": int(row["points_for"]) - int(row["points_against"]),
            "home_record": f"{row['home_wins']}-{row['home_losses']}",
            "away_record": f"{row['away_wins']}-{row['away_losses']}",
        })
    return tuple(sorted(result, key=lambda row: (str(row["conference"]), -float(row["win_percentage"]), -int(row["point_differential"]), str(row["team"]))))


def season_cycle_response(cycle: FranchiseSeasonRecord | None, *, user_team: str) -> dict[str, object]:
    if cycle is None:
        return {"ready": False, "model_version": SEASON_CYCLE_MODEL_VERSION}
    table = standings(cycle)
    played = sum(item.completed for item in cycle.games if item.stage == "regular_season")
    total = sum(item.stage == "regular_season" for item in cycle.games)
    upcoming = [item for item in cycle.games if not item.completed and user_team in {item.home_team, item.away_team}][:8]
    recent = [item for item in cycle.games if item.completed and user_team in {item.home_team, item.away_team}][-8:]
    leaders = aggregate_player_stats(cycle, stages={"regular_season"})
    return {
        "ready": True,
        "season": cycle.season,
        "status": cycle.status,
        "champion": cycle.champion,
        "offseason_stage": cycle.offseason_stage,
        "awards": dict(cycle.awards),
        "honors": [item.as_dict() for item in cycle.honors],
        "postseason": postseason_bracket(cycle),
        "games_played": played,
        "total_games": total,
        "progress": round(played / total, 6) if total else 0.0,
        "standings": list(table),
        "conference_standings": {
            conference: [item for item in table if item["conference"] == conference]
            for conference in ("East", "West")
        },
        "upcoming_user_games": [item.as_dict(include_box_score=False) for item in upcoming],
        "recent_user_games": [item.as_dict(include_box_score=False) for item in reversed(recent)],
        "league_leaders": leaders[:10],
        "model_version": cycle.model_version,
        "simulation": "one complete possession-level game per scheduled matchup",
    }


def aggregate_player_stats(
    cycle: FranchiseSeasonRecord,
    *,
    stages: set[str] | None = None,
    round_name: str | None = None,
) -> list[dict[str, object]]:
    totals: dict[int, dict[str, object]] = {}
    for game in cycle.games:
        if stages is not None and game.stage not in stages:
            continue
        if round_name is not None and game.round_name != round_name:
            continue
        for box in game.box_scores:
            row = totals.setdefault(box.player_id, {
                "player_id": box.player_id, "name": box.name, "team": box.team,
                "games": 0, "points": 0, "rebounds": 0, "assists": 0,
                "steals": 0, "blocks": 0, "minutes": 0.0,
                "field_goals_made": 0, "field_goals_attempted": 0,
                "threes_made": 0, "threes_attempted": 0,
                "free_throws_made": 0, "free_throws_attempted": 0,
                "offensive_rebounds": 0, "defensive_rebounds": 0,
                "turnovers": 0, "personal_fouls": 0,
            })
            row["games"] = int(row["games"]) + 1
            for key, value in (
                ("points", box.points),
                ("rebounds", box.rebounds),
                ("assists", box.assists),
                ("steals", box.steals),
                ("blocks", box.blocks),
                ("field_goals_made", box.field_goals_made),
                ("field_goals_attempted", box.field_goals_attempted),
                ("threes_made", box.threes_made),
                ("threes_attempted", box.threes_attempted),
                ("free_throws_made", box.free_throws_made),
                ("free_throws_attempted", box.free_throws_attempted),
                ("offensive_rebounds", box.offensive_rebounds),
                ("defensive_rebounds", box.defensive_rebounds),
                ("turnovers", box.turnovers),
                ("personal_fouls", box.personal_fouls),
            ):
                row[key] = int(row[key]) + value
            row["minutes"] = float(row["minutes"]) + box.minutes
    result = []
    for row in totals.values():
        games = int(row["games"])
        result.append({
            **row,
            "ppg": round(int(row["points"]) / games, 1),
            "rpg": round(int(row["rebounds"]) / games, 1),
            "apg": round(int(row["assists"]) / games, 1),
            "spg": round(int(row["steals"]) / games, 1),
            "bpg": round(int(row["blocks"]) / games, 1),
            "mpg": round(float(row["minutes"]) / games, 1),
            "fg_pct": round(
                int(row["field_goals_made"]) / int(row["field_goals_attempted"]),
                4,
            ) if int(row["field_goals_attempted"]) else 0.0,
            "three_pct": round(
                int(row["threes_made"]) / int(row["threes_attempted"]),
                4,
            ) if int(row["threes_attempted"]) else 0.0,
            "ft_pct": round(
                int(row["free_throws_made"]) / int(row["free_throws_attempted"]),
                4,
            ) if int(row["free_throws_attempted"]) else 0.0,
        })
    return sorted(result, key=lambda row: (float(row["ppg"]), float(row["apg"]), float(row["rpg"])), reverse=True)


def postseason_bracket(cycle: FranchiseSeasonRecord) -> dict[str, object]:
    postseason_games = [
        item for item in cycle.games
        if item.stage in {"play_in", "playoffs"}
    ]
    table = standings(cycle)
    seeds = {
        str(row["team"]): index + 1
        for conference in ("East", "West")
        for index, row in enumerate(
            item for item in table if item["conference"] == conference
        )
    }
    grouped: dict[str, list[SeasonGameRecord]] = {}
    for game in postseason_games:
        grouped.setdefault(game.series_id or game.game_id, []).append(game)
    order = {name: index for index, name in enumerate(POSTSEASON_ROUNDS)}
    series = []
    for series_id, games in grouped.items():
        games.sort(key=lambda item: (item.series_game_number or 1, item.game_date))
        teams = sorted({team for game in games for team in (game.home_team, game.away_team)})
        wins = {
            team: sum(game.winner == team for game in games)
            for team in teams
        }
        required = 1 if games[0].stage == "play_in" else 4
        winner = next((team for team, value in wins.items() if value >= required), None)
        conference = (
            "East" if series_id.startswith("E-")
            else "West" if series_id.startswith("W-")
            else "NBA"
        )
        series.append({
            "series_id": series_id,
            "round": games[0].round_name or games[0].stage,
            "conference": conference,
            "teams": [
                {
                    "team": team,
                    "seed": seeds.get(team),
                    "wins": wins[team],
                }
                for team in sorted(teams, key=lambda team: (seeds.get(team, 99), team))
            ],
            "winner": winner,
            "status": "complete" if winner else "in_progress",
            "games": [item.as_dict(include_box_score=False) for item in games],
        })
    series.sort(key=lambda item: (
        order.get(str(item["round"]), 99),
        str(item["conference"]),
        str(item["series_id"]),
    ))
    completed_index = (
        order.get(cycle.postseason_round, -1)
        if cycle.postseason_round is not None
        else -1
    )
    next_round = (
        POSTSEASON_ROUNDS[completed_index + 1]
        if completed_index + 1 < len(POSTSEASON_ROUNDS)
        and cycle.status == "postseason"
        else None
    )
    conference_champions = {}
    for item in series:
        if item["round"] == "conference_finals" and item["winner"]:
            conference_champions[str(item["conference"])] = item["winner"]
    return {
        "started": bool(postseason_games),
        "completed_round": cycle.postseason_round,
        "next_round": next_round,
        "series": series,
        "conference_champions": conference_champions,
        "champion": cycle.champion,
        "games_completed": len(postseason_games),
    }


def scheduled_game(game: SeasonGameRecord) -> LeagueScheduledGame:
    return LeagueScheduledGame(game.game_id, game.game_date, game.home_team, game.away_team)
