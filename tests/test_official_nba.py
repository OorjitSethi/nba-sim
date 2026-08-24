from __future__ import annotations

import unittest
from datetime import datetime, timezone

from nba_sim.data.official_nba import (
    OfficialInjuryPdfParser,
    _TextFragment,
    _normalize_game_log,
    _normalize_player_stats,
    _normalize_roster_rows,
    _normalize_schedule,
    injury_report_timestamp_from_url,
)


class OfficialNBAIngestionTests(unittest.TestCase):
    def test_roster_and_game_log_normalization(self) -> None:
        roster = tuple(
            _normalize_roster_rows(
                (
                    {
                        "TEAM_ID": 1,
                        "TEAM_ABBREVIATION": "AAA",
                        "PERSON_ID": 10,
                        "DISPLAY_FIRST_LAST": "Test Player",
                        "ROSTERSTATUS": 1,
                    },
                    {
                        "TEAM_ID": 0,
                        "TEAM_ABBREVIATION": "",
                        "PERSON_ID": 20,
                        "DISPLAY_FIRST_LAST": "Free Agent",
                        "ROSTERSTATUS": 0,
                    },
                ),
                season="2025-26",
            )
        )
        self.assertEqual(len(roster), 1)
        self.assertEqual(roster[0].player_name, "Test Player")

        base = {
            "GAME_ID": "g1",
            "GAME_DATE": "2026-01-02",
            "FGA": 88,
            "FTA": 20,
            "OREB": 10,
            "TOV": 12,
        }
        games = tuple(
            _normalize_game_log(
                (
                    {
                        **base,
                        "TEAM_ABBREVIATION": "AAA",
                        "MATCHUP": "AAA vs. BBB",
                        "PTS": 112,
                    },
                    {
                        **base,
                        "TEAM_ABBREVIATION": "BBB",
                        "MATCHUP": "BBB @ AAA",
                        "PTS": 108,
                    },
                ),
                season="2025-26",
            )
        )
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0].home_team, "AAA")
        self.assertEqual(games[0].margin, 4)

    def test_injury_parser_preserves_report_context(self) -> None:
        report_time = datetime(2026, 4, 23, 20, 30, tzinfo=timezone.utc)
        fragments = (
            _TextFragment(0, 143.0, 24.0, "04/24/2026"),
            _TextFragment(0, 143.0, 201.0, "AAA@BBB"),
            _TextFragment(0, 143.0, 265.0, "Boston"),
            _TextFragment(0, 143.0, 300.0, "Celtics"),
            _TextFragment(0, 143.0, 426.0, "Doe,"),
            _TextFragment(0, 143.0, 460.0, "John"),
            _TextFragment(0, 143.0, 586.0, "Out"),
            _TextFragment(0, 150.0, 667.0, "Left Ankle; Sprain"),
            _TextFragment(0, 173.0, 426.0, "Roe,"),
            _TextFragment(0, 173.0, 460.0, "Richard"),
            _TextFragment(0, 173.0, 586.0, "Available"),
            _TextFragment(0, 180.0, 667.0, "Illness"),
        )
        rows = OfficialInjuryPdfParser().parse_fragments(
            fragments,
            report_timestamp=report_time,
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].team, "Boston Celtics")
        self.assertEqual(rows[0].player_name, "John Doe")
        self.assertEqual(rows[1].matchup, "AAA@BBB")
        self.assertEqual(rows[1].status, "Available")

    def test_player_stat_sources_are_joined_by_player_id(self) -> None:
        rows = tuple(
            _normalize_player_stats(
                (
                    {
                        "PLAYER_ID": 10,
                        "PLAYER_NAME": "Test Player",
                        "TEAM_ABBREVIATION": "AAA",
                        "GP": 50,
                        "MIN": 30,
                        "FGM": 7,
                        "FGA": 15,
                        "FG3M": 2,
                        "FG3A": 6,
                        "FTM": 3,
                        "FTA": 4,
                        "OREB": 1,
                        "DREB": 4,
                        "AST": 5,
                        "TOV": 2,
                        "STL": 1,
                        "BLK": 0.5,
                        "PF": 2,
                        "PFD": 3,
                    },
                ),
                (
                    {
                        "PLAYER_ID": 10,
                        "USG_PCT": 0.24,
                        "AST_PCT": 0.27,
                        "OREB_PCT": 0.04,
                        "DREB_PCT": 0.15,
                        "DEF_RATING": 111.5,
                        "PACE": 101.2,
                        "PIE": 0.13,
                    },
                ),
                (
                    {
                        "PLAYER_ID": 10,
                        "PLAYER_HEIGHT_INCHES": 79,
                        "AGE": 25,
                        "DRAFT_YEAR": "2021",
                        "COUNTRY": "USA",
                    },
                ),
                season="2025-26",
            )
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].player_id, 10)
        self.assertEqual(rows[0].usage_rate, 0.24)
        self.assertEqual(rows[0].height_inches, 79)
        self.assertEqual(rows[0].age, 25)
        self.assertEqual(rows[0].draft_year, 2021)
        self.assertEqual(rows[0].country, "USA")

    def test_injury_url_timestamp_is_eastern_then_utc(self) -> None:
        timestamp = injury_report_timestamp_from_url(
            "https://example.test/Injury-Report_2026-04-23_08_30PM.pdf"
        )
        self.assertEqual(timestamp.tzinfo, timezone.utc)
        self.assertEqual(timestamp.hour, 0)
        self.assertEqual(timestamp.day, 24)

    def test_schedule_normalization_preserves_local_game_date(self) -> None:
        games = tuple(
            _normalize_schedule(
                (
                    {
                        "gameId": "0012600010",
                        "gameDate": "10/06/2026 00:00:00",
                        "gameDateTimeUTC": "2026-10-07T02:00:00Z",
                        "homeTeam_teamTricode": "GSW",
                        "awayTeam_teamTricode": "LAL",
                        "gameStatus": 1,
                        "gameStatusText": "10:00 pm ET",
                        "gameLabel": "Preseason",
                        "gameSubLabel": "",
                        "arenaName": "Chase Center",
                        "arenaCity": "San Francisco",
                        "arenaState": "CA",
                        "isNeutral": False,
                        "ifNecessary": False,
                    },
                ),
                season="2026-27",
            )
        )
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0].game_date.isoformat(), "2026-10-06")
        self.assertEqual(
            games[0].scheduled_at.isoformat(),
            "2026-10-07T02:00:00+00:00",
        )
        self.assertEqual(games[0].away_team, "LAL")


if __name__ == "__main__":
    unittest.main()
