from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Iterable, Mapping

from nba_sim.domain.profiles import TeamProfile
from nba_sim.randomness import RandomStreamFactory
from nba_sim.simulation.game import GameResult, GameSimulator


@dataclass(frozen=True)
class ScheduledGame:
    game_id: str
    game_date: date
    home_team: str
    away_team: str

    def __post_init__(self) -> None:
        if not self.game_id:
            raise ValueError("game_id cannot be empty")
        if self.home_team == self.away_team:
            raise ValueError("a team cannot play itself")


@dataclass
class StandingsRow:
    team: str
    wins: int = 0
    losses: int = 0
    points_for: int = 0
    points_against: int = 0

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
        result = asdict(self)
        result["games"] = self.games
        result["win_percentage"] = round(self.win_percentage, 6)
        result["point_differential"] = self.point_differential
        return result


@dataclass(frozen=True)
class SeasonResult:
    games: tuple[tuple[ScheduledGame, GameResult], ...]
    standings: tuple[StandingsRow, ...]
    seed: int

    def as_dict(self, *, include_games: bool = True) -> dict[str, object]:
        result: dict[str, object] = {
            "seed": self.seed,
            "games_played": len(self.games),
            "standings": [row.as_dict() for row in self.standings],
        }
        if include_games:
            result["games"] = [
                {
                    "game_id": scheduled.game_id,
                    "date": scheduled.game_date.isoformat(),
                    "home_team": scheduled.home_team,
                    "away_team": scheduled.away_team,
                    "home_score": game.home_score,
                    "away_score": game.away_score,
                    "periods": game.periods,
                }
                for scheduled, game in self.games
            ]
        return result


class SeasonSimulator:
    def __init__(
        self,
        *,
        teams: Mapping[str, TeamProfile],
        schedule: Iterable[ScheduledGame],
    ) -> None:
        self.teams = dict(teams)
        self.schedule = tuple(
            sorted(schedule, key=lambda game: (game.game_date, game.game_id))
        )
        if not self.schedule:
            raise ValueError("season schedule cannot be empty")
        game_ids = [game.game_id for game in self.schedule]
        if len(game_ids) != len(set(game_ids)):
            raise ValueError("schedule contains duplicate game IDs")
        for game in self.schedule:
            if game.home_team not in self.teams:
                raise KeyError(game.home_team)
            if game.away_team not in self.teams:
                raise KeyError(game.away_team)

    def simulate(self, *, seed: int = 0) -> SeasonResult:
        streams = RandomStreamFactory(seed)
        standings = {
            abbreviation: StandingsRow(abbreviation)
            for abbreviation in self.teams
        }
        results: list[tuple[ScheduledGame, GameResult]] = []
        for scheduled in self.schedule:
            simulator = GameSimulator(
                home_team=self.teams[scheduled.home_team],
                away_team=self.teams[scheduled.away_team],
            )
            result = simulator.simulate(
                seed=streams.seed_for(f"game:{scheduled.game_id}")
            )
            results.append((scheduled, result))
            home = standings[scheduled.home_team]
            away = standings[scheduled.away_team]
            home.points_for += result.home_score
            home.points_against += result.away_score
            away.points_for += result.away_score
            away.points_against += result.home_score
            if result.home_score > result.away_score:
                home.wins += 1
                away.losses += 1
            else:
                away.wins += 1
                home.losses += 1

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
        return SeasonResult(tuple(results), ordered, seed)


@dataclass(frozen=True)
class PlayoffSeriesResult:
    higher_seed: str
    lower_seed: str
    higher_seed_wins: int
    lower_seed_wins: int
    games: tuple[GameResult, ...]
    seed: int

    @property
    def winner(self) -> str:
        if self.higher_seed_wins > self.lower_seed_wins:
            return self.higher_seed
        return self.lower_seed

    @property
    def loser(self) -> str:
        return self.lower_seed if self.winner == self.higher_seed else self.higher_seed

    def as_dict(self) -> dict[str, object]:
        return {
            "higher_seed": self.higher_seed,
            "lower_seed": self.lower_seed,
            "higher_seed_wins": self.higher_seed_wins,
            "lower_seed_wins": self.lower_seed_wins,
            "winner": self.winner,
            "games": [
                {
                    "home_team": game.home_team.abbreviation,
                    "away_team": game.away_team.abbreviation,
                    "home_score": game.home_score,
                    "away_score": game.away_score,
                    "periods": game.periods,
                }
                for game in self.games
            ],
            "seed": self.seed,
        }


class PlayoffSeriesSimulator:
    def __init__(
        self,
        *,
        higher_seed: TeamProfile,
        lower_seed: TeamProfile,
        best_of: int = 7,
    ) -> None:
        if higher_seed.abbreviation == lower_seed.abbreviation:
            raise ValueError("a team cannot play itself")
        if best_of < 1 or best_of % 2 == 0:
            raise ValueError("best_of must be a positive odd number")
        self.higher_seed = higher_seed
        self.lower_seed = lower_seed
        self.best_of = best_of

    def simulate(self, *, seed: int = 0) -> PlayoffSeriesResult:
        required_wins = self.best_of // 2 + 1
        streams = RandomStreamFactory(seed)
        higher_wins = 0
        lower_wins = 0
        games: list[GameResult] = []
        while higher_wins < required_wins and lower_wins < required_wins:
            game_number = len(games) + 1
            higher_is_home = self._higher_seed_is_home(game_number)
            home = self.higher_seed if higher_is_home else self.lower_seed
            away = self.lower_seed if higher_is_home else self.higher_seed
            result = GameSimulator(home_team=home, away_team=away).simulate(
                seed=streams.seed_for(f"game:{game_number}")
            )
            games.append(result)
            if result.winner == self.higher_seed.abbreviation:
                higher_wins += 1
            else:
                lower_wins += 1
        return PlayoffSeriesResult(
            higher_seed=self.higher_seed.abbreviation,
            lower_seed=self.lower_seed.abbreviation,
            higher_seed_wins=higher_wins,
            lower_seed_wins=lower_wins,
            games=tuple(games),
            seed=seed,
        )

    def _higher_seed_is_home(self, game_number: int) -> bool:
        if self.best_of == 7:
            return game_number in {1, 2, 5, 7}
        # General odd-length fallback: alternate with the deciding game at the
        # higher seed.
        return game_number % 2 == 1


def round_robin_schedule(
    teams: Iterable[str],
    *,
    start_date: date,
    repeats: int = 1,
) -> tuple[ScheduledGame, ...]:
    abbreviations = list(dict.fromkeys(teams))
    if len(abbreviations) < 2:
        raise ValueError("round robin requires at least two teams")
    if repeats <= 0:
        raise ValueError("repeats must be positive")
    bye = "__BYE__"
    if len(abbreviations) % 2:
        abbreviations.append(bye)

    fixed = abbreviations[0]
    rotating = abbreviations[1:]
    rounds: list[list[tuple[str, str]]] = []
    for round_index in range(len(abbreviations) - 1):
        arrangement = [fixed] + rotating
        pairings = []
        for index in range(len(arrangement) // 2):
            first = arrangement[index]
            second = arrangement[-1 - index]
            if bye in {first, second}:
                continue
            if (round_index + index) % 2:
                first, second = second, first
            pairings.append((first, second))
        rounds.append(pairings)
        rotating = [rotating[-1]] + rotating[:-1]

    schedule = []
    day = 0
    for repeat in range(repeats):
        for round_index, pairings in enumerate(rounds):
            for pairing_index, (home, away) in enumerate(pairings):
                if repeat % 2:
                    home, away = away, home
                schedule.append(
                    ScheduledGame(
                        game_id=(
                            f"rr-{repeat + 1}-{round_index + 1}-"
                            f"{pairing_index + 1}-{home}-{away}"
                        ),
                        game_date=start_date + timedelta(days=day),
                        home_team=home,
                        away_team=away,
                    )
                )
            day += 1
    return tuple(schedule)
