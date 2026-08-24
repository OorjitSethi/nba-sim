from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from itertools import combinations, groupby
from typing import Callable, Mapping, Protocol

from nba_sim.domain.profiles import TeamProfile
from nba_sim.domain.events import EventType
from nba_sim.forecast.distributions import GameDistribution
from nba_sim.forecast.ratings import GameObservation
from nba_sim.randomness import RandomStreamFactory
from nba_sim.simulation.game import GameResult, GameSimulator
from nba_sim.simulation.statistics import PlayerBoxScore


DIVISIONS = {
    "Atlantic": ("BOS", "BKN", "NYK", "PHI", "TOR"),
    "Central": ("CHI", "CLE", "DET", "IND", "MIL"),
    "Southeast": ("ATL", "CHA", "MIA", "ORL", "WAS"),
    "Northwest": ("DEN", "MIN", "OKC", "POR", "UTA"),
    "Pacific": ("GSW", "LAC", "LAL", "PHX", "SAC"),
    "Southwest": ("DAL", "HOU", "MEM", "NOP", "SAS"),
}

CONFERENCES = {
    "East": ("Atlantic", "Central", "Southeast"),
    "West": ("Northwest", "Pacific", "Southwest"),
}

TEAM_TO_DIVISION = {
    team: division
    for division, teams in DIVISIONS.items()
    for team in teams
}
TEAM_TO_CONFERENCE = {
    team: conference
    for conference, divisions in CONFERENCES.items()
    for division in divisions
    for team in DIVISIONS[division]
}


class MutableForecastModel(Protocol):
    name: str
    version: str

    def predict(
        self,
        *,
        home_team: TeamProfile,
        away_team: TeamProfile,
    ) -> GameDistribution:
        ...

    def update(self, observation: GameObservation) -> None:
        ...


LeagueProgressCallback = Callable[
    [int, int, int, int, "LeagueScheduledGame"],
    None,
]


class LeagueSimulationCancelled(RuntimeError):
    """Raised between deterministic games when a league job is cancelled."""


@dataclass(frozen=True)
class LeagueScheduledGame:
    game_id: str
    game_date: date
    home_team: str
    away_team: str


@dataclass(frozen=True)
class LeagueGameResult:
    scheduled: LeagueScheduledGame
    home_score: int
    away_score: int
    possessions: float
    box_scores: tuple[PlayerBoxScore, ...]
    forecast: GameDistribution

    @property
    def winner(self) -> str:
        return (
            self.scheduled.home_team
            if self.home_score > self.away_score
            else self.scheduled.away_team
        )

    def summary_dict(self) -> dict[str, object]:
        return {
            "game_id": self.scheduled.game_id,
            "date": self.scheduled.game_date.isoformat(),
            "home_team": self.scheduled.home_team,
            "away_team": self.scheduled.away_team,
            "home_score": self.home_score,
            "away_score": self.away_score,
            "winner": self.winner,
        }

    def detail_dict(self) -> dict[str, object]:
        result = self.summary_dict()
        result.update(
            {
                "possessions": round(self.possessions, 2),
                "forecast": self.forecast.as_dict(),
                "box_scores": [
                    box.as_dict()
                    for box in sorted(
                        self.box_scores,
                        key=lambda row: (
                            row.team,
                            -row.minutes,
                            row.name,
                        ),
                    )
                ],
            }
        )
        return result


@dataclass
class LeagueStanding:
    team: str
    conference: str
    division: str
    wins: int = 0
    losses: int = 0
    points_for: int = 0
    points_against: int = 0
    home_wins: int = 0
    home_losses: int = 0
    away_wins: int = 0
    away_losses: int = 0

    @property
    def games(self) -> int:
        return self.wins + self.losses

    @property
    def win_percentage(self) -> float:
        return self.wins / self.games if self.games else 0.0

    @property
    def point_differential(self) -> int:
        return self.points_for - self.points_against

    def as_dict(self) -> dict[str, object]:
        return {
            "team": self.team,
            "conference": self.conference,
            "division": self.division,
            "wins": self.wins,
            "losses": self.losses,
            "games": self.games,
            "win_percentage": round(self.win_percentage, 6),
            "point_differential": self.point_differential,
            "points_for": self.points_for,
            "points_against": self.points_against,
            "home_record": f"{self.home_wins}-{self.home_losses}",
            "away_record": f"{self.away_wins}-{self.away_losses}",
        }


@dataclass(frozen=True)
class LeagueSeasonResult:
    seed: int
    schedule: tuple[LeagueScheduledGame, ...]
    games: tuple[LeagueGameResult, ...]
    standings: tuple[LeagueStanding, ...]
    model_name: str
    model_version: str

    def as_dict(self) -> dict[str, object]:
        conference_standings = {
            conference: [
                row.as_dict()
                for row in self.standings
                if row.conference == conference
            ]
            for conference in CONFERENCES
        }
        return {
            "seed": self.seed,
            "games_played": len(self.games),
            "teams": len(self.standings),
            "model_name": self.model_name,
            "model_version": self.model_version,
            "standings": [row.as_dict() for row in self.standings],
            "conference_standings": conference_standings,
            "games": [game.summary_dict() for game in self.games],
            "regular_season_leader": self.standings[0].team,
        }


def nba_regular_season_schedule(
    *,
    start_date: date,
    end_date: date,
    seed: int = 2026,
) -> tuple[LeagueScheduledGame, ...]:
    """Generate the NBA's 82-game opponent-frequency structure.

    Every team plays division opponents four times, six non-division conference
    opponents four times, the other four three times, and the opposite
    conference twice. Home/away is exactly 41/41 for every team.
    """

    if end_date <= start_date:
        raise ValueError("season end must follow season start")
    teams = tuple(sorted(TEAM_TO_DIVISION))
    three_game_edges = _three_game_conference_edges()
    occurrences: list[tuple[str, str]] = []
    for first, second in combinations(teams, 2):
        count = _matchup_count(first, second, three_game_edges)
        if count % 2 == 0:
            occurrences.extend((first, second) for _ in range(count // 2))
            occurrences.extend((second, first) for _ in range(count // 2))
        else:
            extra_home = _three_game_extra_home(first, second)
            other = second if extra_home == first else first
            occurrences.extend(
                (
                    (extra_home, other),
                    (extra_home, other),
                    (other, extra_home),
                )
            )

    rng = RandomStreamFactory(seed).generator("nba-schedule")
    order = rng.permutation(len(occurrences))
    rounds: list[list[tuple[str, str]]] = []
    round_teams: list[set[str]] = []
    for index in order:
        home, away = occurrences[int(index)]
        placed = False
        for round_index, used in enumerate(round_teams):
            if home not in used and away not in used:
                rounds[round_index].append((home, away))
                used.update((home, away))
                placed = True
                break
        if not placed:
            rounds.append([(home, away)])
            round_teams.append({home, away})

    span = (end_date - start_date).days
    schedule: list[LeagueScheduledGame] = []
    sequence = 1
    for round_index, games in enumerate(rounds):
        offset = (
            round(round_index * span / max(1, len(rounds) - 1))
            if len(rounds) > 1
            else 0
        )
        game_date = start_date + timedelta(days=offset)
        for home, away in sorted(games):
            schedule.append(
                LeagueScheduledGame(
                    game_id=f"SIM-{start_date.year}-{sequence:04d}",
                    game_date=game_date,
                    home_team=home,
                    away_team=away,
                )
            )
            sequence += 1
    result = tuple(
        sorted(schedule, key=lambda game: (game.game_date, game.game_id))
    )
    _validate_nba_schedule(result)
    return result


class DetailedLeagueSeasonSimulator:
    """Chronological NBA season built from one event-level game per matchup.

    The pregame forecast is retained as context and updated chronologically, but
    the actual result is one untouched possession simulation. This deliberately
    preserves the night-to-night variance of a real season instead of selecting
    from an ensemble to pull every result toward its expected distribution.
    """

    def __init__(
        self,
        *,
        teams: Mapping[str, TeamProfile],
        schedule: tuple[LeagueScheduledGame, ...],
        forecast_model: MutableForecastModel,
        allow_partial_schedule: bool = False,
    ) -> None:
        self.teams = dict(teams)
        self.schedule = tuple(
            sorted(schedule, key=lambda game: (game.game_date, game.game_id))
        )
        self.forecast_model = forecast_model
        if set(self.teams) != set(TEAM_TO_DIVISION):
            raise ValueError("league simulation requires all 30 NBA teams")
        if not self.schedule:
            raise ValueError("league simulation requires at least one game")
        if not allow_partial_schedule and len(self.schedule) != 1_230:
            raise ValueError("league simulation requires a 1,230-game schedule")

    def simulate(
        self,
        *,
        seed: int,
        progress: LeagueProgressCallback | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> LeagueSeasonResult:
        streams = RandomStreamFactory(seed)
        standings = {
            team: LeagueStanding(
                team=team,
                conference=TEAM_TO_CONFERENCE[team],
                division=TEAM_TO_DIVISION[team],
            )
            for team in self.teams
        }
        results: list[LeagueGameResult] = []
        total_games = len(self.schedule)
        for game_date, dated_games_iter in groupby(
            self.schedule,
            key=lambda game: game.game_date,
        ):
            dated_games = tuple(dated_games_iter)
            observations: list[GameObservation] = []
            for scheduled in dated_games:
                if cancelled is not None and cancelled():
                    raise LeagueSimulationCancelled("league simulation cancelled")
                home = self.teams[scheduled.home_team]
                away = self.teams[scheduled.away_team]
                forecast = self.forecast_model.predict(
                    home_team=home,
                    away_team=away,
                )
                simulator = GameSimulator(home_team=home, away_team=away)
                if progress is not None:
                    progress(len(results), total_games, 0, 1, scheduled)
                selected = simulator.simulate(
                    seed=streams.seed_for(
                        f"league-game:{scheduled.game_id}"
                    )
                )
                possessions = _event_possessions(selected)
                result = LeagueGameResult(
                    scheduled=scheduled,
                    home_score=selected.home_score,
                    away_score=selected.away_score,
                    possessions=possessions,
                    box_scores=tuple(
                        box
                        for box in selected.box_scores.values()
                        if box.minutes > 0
                    ),
                    forecast=forecast,
                )
                results.append(result)
                observations.append(
                    GameObservation(
                        game_date=game_date,
                        home_team=scheduled.home_team,
                        away_team=scheduled.away_team,
                        home_points=selected.home_score,
                        away_points=selected.away_score,
                        possessions=possessions,
                    )
                )
                _update_standings(standings, result)
                if progress is not None:
                    progress(len(results), total_games, 0, 1, scheduled)
            # Preserve the backtest-safe rule: no same-day result can leak into
            # another forecast made on the same date.
            for observation in observations:
                self.forecast_model.update(observation)

        ordered = tuple(
            sorted(
                standings.values(),
                key=lambda row: (
                    row.win_percentage,
                    row.point_differential,
                    row.points_for,
                    row.team,
                ),
                reverse=True,
            )
        )
        return LeagueSeasonResult(
            seed=seed,
            schedule=self.schedule,
            games=tuple(results),
            standings=ordered,
            model_name=f"detailed-event-single+{self.forecast_model.name}",
            model_version=f"2.0.0+{self.forecast_model.version}",
        )


def _event_possessions(result: GameResult) -> float:
    home = sum(
        event.event_type is EventType.POSSESSION_STARTED
        and event.team == result.home_team.abbreviation
        for event in result.events
    )
    away = sum(
        event.event_type is EventType.POSSESSION_STARTED
        and event.team == result.away_team.abbreviation
        for event in result.events
    )
    possessions = (home + away) / 2.0
    if possessions <= 0:
        raise RuntimeError("detailed simulation produced no possessions")
    return possessions


def _three_game_conference_edges() -> set[frozenset[str]]:
    edges: set[frozenset[str]] = set()
    for divisions in CONFERENCES.values():
        ordered = tuple(
            team
            for position in range(5)
            for division in divisions
            for team in (DIVISIONS[division][position],)
        )
        for index, team in enumerate(ordered):
            for offset in (1, 2):
                edges.add(
                    frozenset((team, ordered[(index + offset) % len(ordered)]))
                )
    return edges


def _matchup_count(
    first: str,
    second: str,
    three_game_edges: set[frozenset[str]],
) -> int:
    if TEAM_TO_CONFERENCE[first] != TEAM_TO_CONFERENCE[second]:
        return 2
    if TEAM_TO_DIVISION[first] == TEAM_TO_DIVISION[second]:
        return 4
    return 3 if frozenset((first, second)) in three_game_edges else 4


def _three_game_extra_home(first: str, second: str) -> str:
    conference = TEAM_TO_CONFERENCE[first]
    divisions = CONFERENCES[conference]
    ordered = tuple(
        team
        for position in range(5)
        for division in divisions
        for team in (DIVISIONS[division][position],)
    )
    first_index = ordered.index(first)
    second_index = ordered.index(second)
    return (
        first
        if (second_index - first_index) % len(ordered) in {1, 2}
        else second
    )


def _validate_nba_schedule(
    schedule: tuple[LeagueScheduledGame, ...],
) -> None:
    if len(schedule) != 1_230:
        raise RuntimeError(f"NBA schedule has {len(schedule)} games, expected 1230")
    counts = {
        team: {"games": 0, "home": 0, "away": 0}
        for team in TEAM_TO_DIVISION
    }
    team_dates: set[tuple[str, date]] = set()
    for game in schedule:
        for team, location in (
            (game.home_team, "home"),
            (game.away_team, "away"),
        ):
            if (team, game.game_date) in team_dates:
                raise RuntimeError(f"{team} plays twice on {game.game_date}")
            team_dates.add((team, game.game_date))
            counts[team]["games"] += 1
            counts[team][location] += 1
    invalid = {
        team: values
        for team, values in counts.items()
        if values != {"games": 82, "home": 41, "away": 41}
    }
    if invalid:
        raise RuntimeError(f"unbalanced NBA schedule: {invalid}")


def _update_standings(
    standings: dict[str, LeagueStanding],
    game: LeagueGameResult,
) -> None:
    home = standings[game.scheduled.home_team]
    away = standings[game.scheduled.away_team]
    home.points_for += game.home_score
    home.points_against += game.away_score
    away.points_for += game.away_score
    away.points_against += game.home_score
    if game.home_score > game.away_score:
        home.wins += 1
        home.home_wins += 1
        away.losses += 1
        away.away_losses += 1
    else:
        away.wins += 1
        away.away_wins += 1
        home.losses += 1
        home.home_losses += 1
