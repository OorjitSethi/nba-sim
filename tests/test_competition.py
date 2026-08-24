from __future__ import annotations

import unittest
from collections import Counter
from datetime import date

from nba_sim.competition.league import (
    DetailedLeagueSeasonSimulator,
    LeagueScheduledGame,
    LeagueSimulationCancelled,
    TEAM_TO_CONFERENCE,
    TEAM_TO_DIVISION,
    nba_regular_season_schedule,
)
from nba_sim.validation.backtest import CalibratedDynamicTeamModel
from nba_sim.competition.season import (
    PlayoffSeriesSimulator,
    SeasonSimulator,
    round_robin_schedule,
)
from tests.factories import make_team


class CompetitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.teams = {
            abbreviation: make_team(abbreviation, id_offset=index * 100 + 100)
            for index, abbreviation in enumerate(("AAA", "BBB", "CCC", "DDD"))
        }

    def test_round_robin_and_standings_reconcile(self) -> None:
        schedule = round_robin_schedule(
            self.teams,
            start_date=date(2026, 10, 20),
            repeats=2,
        )
        self.assertEqual(len(schedule), 12)
        result = SeasonSimulator(teams=self.teams, schedule=schedule).simulate(seed=5)
        self.assertEqual(len(result.games), 12)
        self.assertEqual(sum(row.wins for row in result.standings), 12)
        self.assertEqual(sum(row.losses for row in result.standings), 12)
        self.assertTrue(all(row.games == 6 for row in result.standings))
        replay = SeasonSimulator(teams=self.teams, schedule=schedule).simulate(seed=5)
        self.assertEqual(result.as_dict(), replay.as_dict())

    def test_best_of_seven_uses_valid_home_pattern_and_ends_at_four(self) -> None:
        series = PlayoffSeriesSimulator(
            higher_seed=self.teams["AAA"],
            lower_seed=self.teams["BBB"],
        ).simulate(seed=77)
        self.assertTrue(4 <= len(series.games) <= 7)
        self.assertEqual(max(series.higher_seed_wins, series.lower_seed_wins), 4)
        expected_home = ("AAA", "AAA", "BBB", "BBB", "AAA", "BBB", "AAA")
        actual_home = tuple(game.home_team.abbreviation for game in series.games)
        self.assertEqual(actual_home, expected_home[: len(actual_home)])

    def test_invalid_series_length_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "odd"):
            PlayoffSeriesSimulator(
                higher_seed=self.teams["AAA"],
                lower_seed=self.teams["BBB"],
                best_of=6,
            )

    def test_full_nba_schedule_is_1230_games_and_41_home_away(self) -> None:
        schedule = nba_regular_season_schedule(
            start_date=date(2026, 10, 20),
            end_date=date(2027, 4, 12),
            seed=9,
        )
        self.assertEqual(len(schedule), 1_230)
        games = Counter()
        home = Counter()
        away = Counter()
        dates = set()
        for game in schedule:
            games[game.home_team] += 1
            games[game.away_team] += 1
            home[game.home_team] += 1
            away[game.away_team] += 1
            self.assertNotIn((game.home_team, game.game_date), dates)
            self.assertNotIn((game.away_team, game.game_date), dates)
            dates.add((game.home_team, game.game_date))
            dates.add((game.away_team, game.game_date))
        self.assertEqual(set(games), set(TEAM_TO_DIVISION))
        self.assertTrue(all(value == 82 for value in games.values()))
        self.assertTrue(all(value == 41 for value in home.values()))
        self.assertTrue(all(value == 41 for value in away.values()))

    def test_nba_schedule_opponent_frequencies_match_league_structure(self) -> None:
        schedule = nba_regular_season_schedule(
            start_date=date(2026, 10, 20),
            end_date=date(2027, 4, 12),
        )
        opponents = Counter(
            tuple(sorted((game.home_team, game.away_team)))
            for game in schedule
        )
        for (first, second), games in opponents.items():
            if TEAM_TO_CONFERENCE[first] != TEAM_TO_CONFERENCE[second]:
                self.assertEqual(games, 2)
            elif TEAM_TO_DIVISION[first] == TEAM_TO_DIVISION[second]:
                self.assertEqual(games, 4)
            else:
                self.assertIn(games, {3, 4})

    def test_detailed_league_game_uses_native_event_box_score(self) -> None:
        teams = {
            abbreviation: make_team(
                abbreviation,
                id_offset=20_000 + index * 100,
            )
            for index, abbreviation in enumerate(sorted(TEAM_TO_DIVISION))
        }
        schedule = (
            LeagueScheduledGame(
                game_id="SIM-DETAIL-0001",
                game_date=date(2026, 10, 20),
                home_team="BOS",
                away_team="NYK",
            ),
        )
        progress = []
        result = DetailedLeagueSeasonSimulator(
            teams=teams,
            schedule=schedule,
            forecast_model=CalibratedDynamicTeamModel(tuple(teams)),
            allow_partial_schedule=True,
        ).simulate(seed=91, progress=lambda *values: progress.append(values))
        game = result.games[0]
        self.assertEqual(len(result.games), 1)
        self.assertEqual(sum(row.wins for row in result.standings), 1)
        self.assertGreater(game.possessions, 80)
        self.assertEqual(progress[-1][:4], (1, 1, 0, 1))
        self.assertEqual(
            sum(
                box.points
                for box in game.box_scores
                if box.team == game.scheduled.home_team
            ),
            game.home_score,
        )
        self.assertEqual(
            sum(
                box.points
                for box in game.box_scores
                if box.team == game.scheduled.away_team
            ),
            game.away_score,
        )

    def test_detailed_league_job_honors_cancellation_between_games(self) -> None:
        teams = {
            abbreviation: make_team(
                abbreviation,
                id_offset=30_000 + index * 100,
            )
            for index, abbreviation in enumerate(sorted(TEAM_TO_DIVISION))
        }
        simulator = DetailedLeagueSeasonSimulator(
            teams=teams,
            schedule=(
                LeagueScheduledGame(
                    game_id="SIM-CANCEL-0001",
                    game_date=date(2026, 10, 20),
                    home_team="BOS",
                    away_team="NYK",
                ),
            ),
            forecast_model=CalibratedDynamicTeamModel(tuple(teams)),
            allow_partial_schedule=True,
        )
        with self.assertRaises(LeagueSimulationCancelled):
            simulator.simulate(seed=4, cancelled=lambda: True)


if __name__ == "__main__":
    unittest.main()
