from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

from nba_sim.data.provenance import Snapshot


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class RosterObservation:
    season: str
    team_id: int
    team_abbreviation: str
    player_id: int
    player_name: str
    roster_status: str = "active"
    position: str | None = None


@dataclass(frozen=True)
class PlayerSeasonStat:
    season: str
    player_id: int
    player_name: str
    team_abbreviation: str
    games_played: int
    minutes: float
    field_goals_made: float
    field_goals_attempted: float
    threes_made: float
    threes_attempted: float
    free_throws_made: float
    free_throws_attempted: float
    offensive_rebounds: float
    defensive_rebounds: float
    assists: float
    turnovers: float
    steals: float
    blocks: float
    personal_fouls: float
    fouls_drawn: float
    usage_rate: float
    assist_rate: float
    offensive_rebound_rate: float
    defensive_rebound_rate: float
    defensive_rating: float
    pace: float
    player_impact_estimate: float
    height_inches: float
    age: float | None = None
    draft_year: int | None = None
    country: str | None = None

    def __post_init__(self) -> None:
        if self.player_id <= 0 or not self.player_name:
            raise ValueError("player stat requires a valid player")
        if self.games_played < 0 or self.minutes < 0:
            raise ValueError("games and minutes cannot be negative")
        for name in (
            "field_goals_made",
            "field_goals_attempted",
            "threes_made",
            "threes_attempted",
            "free_throws_made",
            "free_throws_attempted",
            "offensive_rebounds",
            "defensive_rebounds",
            "assists",
            "turnovers",
            "steals",
            "blocks",
            "personal_fouls",
            "fouls_drawn",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.height_inches <= 0:
            raise ValueError("height_inches must be positive")
        if self.age is not None and not 15 <= self.age <= 50:
            raise ValueError("player age must be between 15 and 50")
        if self.draft_year is not None and self.draft_year < 1947:
            raise ValueError("draft_year is invalid")


@dataclass(frozen=True)
class HistoricalGame:
    game_id: str
    season: str
    game_date: date
    home_team: str
    away_team: str
    home_points: int
    away_points: int
    possessions: float
    result_available_at: datetime
    neutral_site: bool = False

    def __post_init__(self) -> None:
        if not self.game_id:
            raise ValueError("game_id cannot be empty")
        if self.home_team == self.away_team:
            raise ValueError("a team cannot play itself")
        if self.home_points < 0 or self.away_points < 0:
            raise ValueError("points cannot be negative")
        if self.possessions <= 0:
            raise ValueError("possessions must be positive")
        object.__setattr__(
            self,
            "result_available_at",
            _utc(self.result_available_at, "result_available_at"),
        )

    @property
    def margin(self) -> int:
        return self.home_points - self.away_points

    @property
    def total(self) -> int:
        return self.home_points + self.away_points


@dataclass(frozen=True)
class ScheduledGame:
    game_id: str
    season: str
    game_date: date
    scheduled_at: datetime | None
    home_team: str | None
    away_team: str | None
    status: int
    status_text: str
    game_label: str
    game_sub_label: str
    arena_name: str
    arena_city: str
    arena_state: str
    neutral_site: bool = False
    if_necessary: bool = False

    def __post_init__(self) -> None:
        if not self.game_id:
            raise ValueError("game_id cannot be empty")
        if self.home_team and self.away_team and self.home_team == self.away_team:
            raise ValueError("a team cannot play itself")
        if (self.home_team is None) != (self.away_team is None):
            raise ValueError("scheduled game must identify both teams or neither")
        if self.scheduled_at is not None:
            object.__setattr__(
                self,
                "scheduled_at",
                _utc(self.scheduled_at, "scheduled_at"),
            )

    @property
    def teams_identified(self) -> bool:
        return self.home_team is not None and self.away_team is not None


@dataclass(frozen=True)
class InjuryObservation:
    game_date: date
    matchup: str
    team: str
    player_name: str
    status: str
    reason: str
    report_timestamp: datetime
    player_id: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "report_timestamp",
            _utc(self.report_timestamp, "report_timestamp"),
        )
        if not self.player_name or not self.team:
            raise ValueError("injury observation requires team and player")


@dataclass(frozen=True)
class MarketQuote:
    game_id: str
    source: str
    quote_timestamp: datetime
    home_spread: float
    total: float
    home_moneyline_probability: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "quote_timestamp",
            _utc(self.quote_timestamp, "quote_timestamp"),
        )
        if self.total <= 0:
            raise ValueError("market total must be positive")
        if (
            self.home_moneyline_probability is not None
            and not 0 < self.home_moneyline_probability < 1
        ):
            raise ValueError("moneyline probability must be strictly between 0 and 1")


class PointInTimeWarehouse:
    """Append-only bitemporal store for forecast-safe NBA inputs."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def register_snapshot(self, snapshot: Snapshot) -> str:
        manifest = snapshot.manifest
        identity = "|".join(
            (
                manifest.source,
                manifest.dataset,
                manifest.season,
                manifest.available_at.isoformat(),
                manifest.sha256,
            )
        )
        snapshot_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO source_snapshots (
                    snapshot_id, source, dataset, season, retrieved_at,
                    available_at, schema_version, sha256, byte_size,
                    record_count, rights_tier, data_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    manifest.source,
                    manifest.dataset,
                    manifest.season,
                    manifest.retrieved_at.isoformat(),
                    manifest.available_at.isoformat(),
                    manifest.schema_version,
                    manifest.sha256,
                    manifest.byte_size,
                    manifest.record_count,
                    manifest.rights_tier,
                    str(snapshot.data_path),
                ),
            )
        return snapshot_id

    def ingest_roster(
        self,
        snapshot: Snapshot,
        rows: Iterable[RosterObservation],
    ) -> int:
        snapshot_id = self.register_snapshot(snapshot)
        records = tuple(rows)
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO roster_observations (
                    snapshot_id, season, team_id, team_abbreviation,
                    player_id, player_name, roster_status, position
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        snapshot_id,
                        row.season,
                        row.team_id,
                        row.team_abbreviation,
                        row.player_id,
                        row.player_name,
                        row.roster_status,
                        row.position,
                    )
                    for row in records
                ),
            )
        return len(records)

    def ingest_games(
        self,
        snapshot: Snapshot,
        games: Iterable[HistoricalGame],
    ) -> int:
        snapshot_id = self.register_snapshot(snapshot)
        records = tuple(games)
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO game_observations (
                    snapshot_id, game_id, season, game_date, home_team,
                    away_team, home_points, away_points, possessions,
                    result_available_at, neutral_site
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        snapshot_id,
                        game.game_id,
                        game.season,
                        game.game_date.isoformat(),
                        game.home_team,
                        game.away_team,
                        game.home_points,
                        game.away_points,
                        game.possessions,
                        game.result_available_at.isoformat(),
                        int(game.neutral_site),
                    )
                    for game in records
                ),
            )
        return len(records)

    def ingest_schedule(
        self,
        snapshot: Snapshot,
        games: Iterable[ScheduledGame],
    ) -> int:
        snapshot_id = self.register_snapshot(snapshot)
        records = tuple(games)
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO schedule_observations (
                    snapshot_id, game_id, season, game_date, scheduled_at,
                    home_team, away_team, status, status_text, game_label,
                    game_sub_label, arena_name, arena_city, arena_state,
                    neutral_site, if_necessary
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        snapshot_id,
                        game.game_id,
                        game.season,
                        game.game_date.isoformat(),
                        (
                            game.scheduled_at.isoformat()
                            if game.scheduled_at is not None
                            else None
                        ),
                        game.home_team,
                        game.away_team,
                        game.status,
                        game.status_text,
                        game.game_label,
                        game.game_sub_label,
                        game.arena_name,
                        game.arena_city,
                        game.arena_state,
                        int(game.neutral_site),
                        int(game.if_necessary),
                    )
                    for game in records
                ),
            )
        return len(records)

    def ingest_player_stats(
        self,
        snapshot: Snapshot,
        rows: Iterable[PlayerSeasonStat],
    ) -> int:
        snapshot_id = self.register_snapshot(snapshot)
        records = tuple(rows)
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO player_stat_observations (
                    snapshot_id, season, player_id, player_name,
                    team_abbreviation, games_played, minutes,
                    field_goals_made, field_goals_attempted, threes_made,
                    threes_attempted, free_throws_made, free_throws_attempted,
                    offensive_rebounds, defensive_rebounds, assists, turnovers,
                    steals, blocks, personal_fouls, fouls_drawn, usage_rate,
                    assist_rate, offensive_rebound_rate, defensive_rebound_rate,
                    defensive_rating, pace, player_impact_estimate, height_inches
                    , age, draft_year, country
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    (
                        snapshot_id,
                        row.season,
                        row.player_id,
                        row.player_name,
                        row.team_abbreviation,
                        row.games_played,
                        row.minutes,
                        row.field_goals_made,
                        row.field_goals_attempted,
                        row.threes_made,
                        row.threes_attempted,
                        row.free_throws_made,
                        row.free_throws_attempted,
                        row.offensive_rebounds,
                        row.defensive_rebounds,
                        row.assists,
                        row.turnovers,
                        row.steals,
                        row.blocks,
                        row.personal_fouls,
                        row.fouls_drawn,
                        row.usage_rate,
                        row.assist_rate,
                        row.offensive_rebound_rate,
                        row.defensive_rebound_rate,
                        row.defensive_rating,
                        row.pace,
                        row.player_impact_estimate,
                        row.height_inches,
                        row.age,
                        row.draft_year,
                        row.country,
                    )
                    for row in records
                ),
            )
        return len(records)

    def ingest_injuries(
        self,
        snapshot: Snapshot,
        rows: Iterable[InjuryObservation],
    ) -> int:
        snapshot_id = self.register_snapshot(snapshot)
        records = tuple(rows)
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO injury_observations (
                    snapshot_id, game_date, matchup, team, player_id,
                    player_name, status, reason, report_timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        snapshot_id,
                        row.game_date.isoformat(),
                        row.matchup,
                        row.team,
                        row.player_id,
                        row.player_name,
                        row.status,
                        row.reason,
                        row.report_timestamp.isoformat(),
                    )
                    for row in records
                ),
            )
        return len(records)

    def ingest_market_quotes(self, quotes: Iterable[MarketQuote]) -> int:
        records = tuple(quotes)
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO market_quotes (
                    game_id, source, quote_timestamp, home_spread, total,
                    home_moneyline_probability
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        quote.game_id,
                        quote.source,
                        quote.quote_timestamp.isoformat(),
                        quote.home_spread,
                        quote.total,
                        quote.home_moneyline_probability,
                    )
                    for quote in records
                ),
            )
        return len(records)

    def roster_as_of(
        self,
        *,
        team: str,
        cutoff: datetime,
    ) -> tuple[RosterObservation, ...]:
        cutoff = _utc(cutoff, "cutoff")
        with self._connect() as connection:
            rows = connection.execute(
                """
                WITH latest AS (
                    SELECT r.*, s.available_at,
                           DENSE_RANK() OVER (
                               ORDER BY s.available_at DESC, s.snapshot_id DESC
                           ) AS snapshot_rank
                    FROM roster_observations r
                    JOIN source_snapshots s USING (snapshot_id)
                    WHERE r.team_abbreviation = ?
                      AND s.available_at <= ?
                )
                SELECT season, team_id, team_abbreviation, player_id,
                       player_name, roster_status, position
                FROM latest
                WHERE snapshot_rank = 1
                ORDER BY player_name
                """,
                (team.upper(), cutoff.isoformat()),
            ).fetchall()
        return tuple(RosterObservation(**dict(row)) for row in rows)

    def current_roster_season(self, *, cutoff: datetime) -> str | None:
        cutoff = _utc(cutoff, "cutoff")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT season
                FROM source_snapshots
                WHERE dataset = 'rosters'
                  AND available_at <= ?
                ORDER BY available_at DESC, snapshot_id DESC
                LIMIT 1
                """,
                (cutoff.isoformat(),),
            ).fetchone()
        return str(row["season"]) if row is not None else None

    def latest_player_stat_season(self, *, cutoff: datetime) -> str | None:
        cutoff = _utc(cutoff, "cutoff")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT season
                FROM source_snapshots
                WHERE dataset = 'player-stats'
                  AND available_at <= ?
                ORDER BY available_at DESC, snapshot_id DESC
                LIMIT 1
                """,
                (cutoff.isoformat(),),
            ).fetchone()
        return str(row["season"]) if row is not None else None

    def player_stats_as_of(
        self,
        *,
        season: str,
        cutoff: datetime,
    ) -> tuple[PlayerSeasonStat, ...]:
        cutoff = _utc(cutoff, "cutoff")
        with self._connect() as connection:
            rows = connection.execute(
                """
                WITH latest AS (
                    SELECT p.*, s.available_at,
                           DENSE_RANK() OVER (
                               ORDER BY s.available_at DESC, s.snapshot_id DESC
                           ) AS snapshot_rank
                    FROM player_stat_observations p
                    JOIN source_snapshots s USING (snapshot_id)
                    WHERE p.season = ?
                      AND s.available_at <= ?
                )
                SELECT season, player_id, player_name, team_abbreviation,
                       games_played, minutes, field_goals_made,
                       field_goals_attempted, threes_made, threes_attempted,
                       free_throws_made, free_throws_attempted,
                       offensive_rebounds, defensive_rebounds, assists,
                       turnovers, steals, blocks, personal_fouls, fouls_drawn,
                       usage_rate, assist_rate, offensive_rebound_rate,
                       defensive_rebound_rate, defensive_rating, pace,
                       player_impact_estimate, height_inches, age, draft_year,
                       country
                FROM latest
                WHERE snapshot_rank = 1
                ORDER BY player_id
                """,
                (season, cutoff.isoformat()),
            ).fetchall()
        return tuple(PlayerSeasonStat(**dict(row)) for row in rows)

    def games(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        known_as_of: datetime | None = None,
    ) -> tuple[HistoricalGame, ...]:
        clauses = []
        parameters: list[object] = []
        if start_date is not None:
            clauses.append("g.game_date >= ?")
            parameters.append(start_date.isoformat())
        if end_date is not None:
            clauses.append("g.game_date <= ?")
            parameters.append(end_date.isoformat())
        if known_as_of is not None:
            cutoff = _utc(known_as_of, "known_as_of")
            clauses.append("s.available_at <= ?")
            parameters.append(cutoff.isoformat())
            clauses.append("g.result_available_at <= ?")
            parameters.append(cutoff.isoformat())
        where = " AND ".join(clauses) if clauses else "1 = 1"
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                WITH ranked AS (
                    SELECT g.*, s.available_at,
                           ROW_NUMBER() OVER (
                               PARTITION BY g.game_id
                               ORDER BY s.available_at DESC, s.snapshot_id DESC
                           ) AS observation_rank
                    FROM game_observations g
                    JOIN source_snapshots s USING (snapshot_id)
                    WHERE {where}
                )
                SELECT game_id, season, game_date, home_team, away_team,
                       home_points, away_points, possessions,
                       result_available_at, neutral_site
                FROM ranked
                WHERE observation_rank = 1
                ORDER BY game_date, game_id
                """,
                parameters,
            ).fetchall()
        return tuple(
            HistoricalGame(
                game_id=row["game_id"],
                season=row["season"],
                game_date=date.fromisoformat(row["game_date"]),
                home_team=row["home_team"],
                away_team=row["away_team"],
                home_points=row["home_points"],
                away_points=row["away_points"],
                possessions=row["possessions"],
                result_available_at=datetime.fromisoformat(
                    row["result_available_at"]
                ),
                neutral_site=bool(row["neutral_site"]),
            )
            for row in rows
        )

    def schedule_as_of(
        self,
        *,
        season: str,
        cutoff: datetime,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> tuple[ScheduledGame, ...]:
        """Return the complete latest schedule snapshot known at ``cutoff``.

        Schedule snapshots are complete-state observations. Selecting one
        snapshot (instead of independently ranking each game) ensures removals
        and postponements in later official payloads are reflected correctly.
        """

        cutoff = _utc(cutoff, "cutoff")
        clauses = ["s.season = ?", "s.available_at <= ?"]
        parameters: list[object] = [season, cutoff.isoformat()]
        if start_date is not None:
            clauses.append("g.game_date >= ?")
            parameters.append(start_date.isoformat())
        if end_date is not None:
            clauses.append("g.game_date <= ?")
            parameters.append(end_date.isoformat())
        where = " AND ".join(clauses)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                WITH latest_snapshot AS (
                    SELECT snapshot_id
                    FROM source_snapshots
                    WHERE dataset = 'schedule'
                      AND season = ?
                      AND available_at <= ?
                    ORDER BY available_at DESC, snapshot_id DESC
                    LIMIT 1
                )
                SELECT g.game_id, g.season, g.game_date, g.scheduled_at,
                       g.home_team, g.away_team, g.status, g.status_text,
                       g.game_label, g.game_sub_label, g.arena_name,
                       g.arena_city, g.arena_state, g.neutral_site,
                       g.if_necessary
                FROM schedule_observations g
                JOIN source_snapshots s USING (snapshot_id)
                WHERE g.snapshot_id IN (SELECT snapshot_id FROM latest_snapshot)
                  AND {where}
                ORDER BY g.game_date, COALESCE(g.scheduled_at, ''), g.game_id
                """,
                [season, cutoff.isoformat(), *parameters],
            ).fetchall()
        return tuple(_scheduled_game_from_row(row) for row in rows)

    def scheduled_game_as_of(
        self,
        *,
        game_id: str,
        cutoff: datetime,
    ) -> ScheduledGame | None:
        cutoff = _utc(cutoff, "cutoff")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT g.game_id, g.season, g.game_date, g.scheduled_at,
                       g.home_team, g.away_team, g.status, g.status_text,
                       g.game_label, g.game_sub_label, g.arena_name,
                       g.arena_city, g.arena_state, g.neutral_site,
                       g.if_necessary
                FROM schedule_observations g
                JOIN source_snapshots s USING (snapshot_id)
                WHERE g.game_id = ?
                  AND s.available_at <= ?
                ORDER BY s.available_at DESC, s.snapshot_id DESC
                LIMIT 1
                """,
                (game_id, cutoff.isoformat()),
            ).fetchone()
        return _scheduled_game_from_row(row) if row is not None else None

    def latest_snapshot(
        self,
        *,
        dataset: str,
        season: str,
        cutoff: datetime,
    ) -> dict[str, object] | None:
        cutoff = _utc(cutoff, "cutoff")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT source, dataset, season, retrieved_at, available_at,
                       record_count, rights_tier
                FROM source_snapshots
                WHERE dataset = ?
                  AND season = ?
                  AND available_at <= ?
                ORDER BY available_at DESC, snapshot_id DESC
                LIMIT 1
                """,
                (dataset, season, cutoff.isoformat()),
            ).fetchone()
        return dict(row) if row is not None else None

    def injuries_as_of(
        self,
        *,
        game_date: date,
        cutoff: datetime,
    ) -> tuple[InjuryObservation, ...]:
        cutoff = _utc(cutoff, "cutoff")
        with self._connect() as connection:
            rows = connection.execute(
                """
                WITH ranked AS (
                    SELECT i.*, s.available_at,
                           DENSE_RANK() OVER (
                               ORDER BY s.available_at DESC, s.snapshot_id DESC
                           ) AS snapshot_rank
                    FROM injury_observations i
                    JOIN source_snapshots s USING (snapshot_id)
                    WHERE i.game_date = ?
                      AND i.report_timestamp <= ?
                      AND s.available_at <= ?
                )
                SELECT game_date, matchup, team, player_name, status, reason,
                       report_timestamp, player_id
                FROM ranked
                WHERE snapshot_rank = 1
                ORDER BY matchup, team, player_name
                """,
                (
                    game_date.isoformat(),
                    cutoff.isoformat(),
                    cutoff.isoformat(),
                ),
            ).fetchall()
        return tuple(
            InjuryObservation(
                game_date=date.fromisoformat(row["game_date"]),
                matchup=row["matchup"],
                team=row["team"],
                player_name=row["player_name"],
                status=row["status"],
                reason=row["reason"],
                report_timestamp=datetime.fromisoformat(row["report_timestamp"]),
                player_id=row["player_id"],
            )
            for row in rows
        )

    def market_quote_as_of(
        self,
        *,
        game_id: str,
        cutoff: datetime,
        source: str | None = None,
    ) -> MarketQuote | None:
        cutoff = _utc(cutoff, "cutoff")
        source_clause = "AND source = ?" if source is not None else ""
        parameters: list[object] = [game_id, cutoff.isoformat()]
        if source is not None:
            parameters.append(source)
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT game_id, source, quote_timestamp, home_spread, total,
                       home_moneyline_probability
                FROM market_quotes
                WHERE game_id = ?
                  AND quote_timestamp <= ?
                  {source_clause}
                ORDER BY quote_timestamp DESC
                LIMIT 1
                """,
                parameters,
            ).fetchone()
        if row is None:
            return None
        return MarketQuote(
            game_id=row["game_id"],
            source=row["source"],
            quote_timestamp=datetime.fromisoformat(row["quote_timestamp"]),
            home_spread=row["home_spread"],
            total=row["total"],
            home_moneyline_probability=row["home_moneyline_probability"],
        )

    def snapshot_inventory(self) -> tuple[dict[str, object], ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT dataset, season, COUNT(*) AS snapshots,
                       MAX(available_at) AS latest_available_at,
                       SUM(COALESCE(record_count, 0)) AS recorded_rows
                FROM source_snapshots
                GROUP BY dataset, season
                ORDER BY dataset, season
                """
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS source_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    dataset TEXT NOT NULL,
                    season TEXT NOT NULL,
                    retrieved_at TEXT NOT NULL,
                    available_at TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    byte_size INTEGER NOT NULL,
                    record_count INTEGER,
                    rights_tier TEXT NOT NULL,
                    data_path TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_snapshots_dataset_available
                ON source_snapshots(dataset, available_at);

                CREATE TABLE IF NOT EXISTS roster_observations (
                    snapshot_id TEXT NOT NULL REFERENCES source_snapshots(snapshot_id),
                    season TEXT NOT NULL,
                    team_id INTEGER NOT NULL,
                    team_abbreviation TEXT NOT NULL,
                    player_id INTEGER NOT NULL,
                    player_name TEXT NOT NULL,
                    roster_status TEXT NOT NULL,
                    position TEXT,
                    PRIMARY KEY (snapshot_id, team_id, player_id)
                );

                CREATE INDEX IF NOT EXISTS idx_roster_team
                ON roster_observations(team_abbreviation, player_id);

                CREATE TABLE IF NOT EXISTS player_stat_observations (
                    snapshot_id TEXT NOT NULL REFERENCES source_snapshots(snapshot_id),
                    season TEXT NOT NULL,
                    player_id INTEGER NOT NULL,
                    player_name TEXT NOT NULL,
                    team_abbreviation TEXT NOT NULL,
                    games_played INTEGER NOT NULL,
                    minutes REAL NOT NULL,
                    field_goals_made REAL NOT NULL,
                    field_goals_attempted REAL NOT NULL,
                    threes_made REAL NOT NULL,
                    threes_attempted REAL NOT NULL,
                    free_throws_made REAL NOT NULL,
                    free_throws_attempted REAL NOT NULL,
                    offensive_rebounds REAL NOT NULL,
                    defensive_rebounds REAL NOT NULL,
                    assists REAL NOT NULL,
                    turnovers REAL NOT NULL,
                    steals REAL NOT NULL,
                    blocks REAL NOT NULL,
                    personal_fouls REAL NOT NULL,
                    fouls_drawn REAL NOT NULL,
                    usage_rate REAL NOT NULL,
                    assist_rate REAL NOT NULL,
                    offensive_rebound_rate REAL NOT NULL,
                    defensive_rebound_rate REAL NOT NULL,
                    defensive_rating REAL NOT NULL,
                    pace REAL NOT NULL,
                    player_impact_estimate REAL NOT NULL,
                    height_inches REAL NOT NULL,
                    age REAL,
                    draft_year INTEGER,
                    country TEXT,
                    PRIMARY KEY (snapshot_id, player_id)
                );

                CREATE INDEX IF NOT EXISTS idx_player_stats_season
                ON player_stat_observations(season, player_id);

                CREATE TABLE IF NOT EXISTS game_observations (
                    snapshot_id TEXT NOT NULL REFERENCES source_snapshots(snapshot_id),
                    game_id TEXT NOT NULL,
                    season TEXT NOT NULL,
                    game_date TEXT NOT NULL,
                    home_team TEXT NOT NULL,
                    away_team TEXT NOT NULL,
                    home_points INTEGER NOT NULL,
                    away_points INTEGER NOT NULL,
                    possessions REAL NOT NULL,
                    result_available_at TEXT NOT NULL,
                    neutral_site INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (snapshot_id, game_id)
                );

                CREATE INDEX IF NOT EXISTS idx_games_date
                ON game_observations(game_date, game_id);

                CREATE TABLE IF NOT EXISTS schedule_observations (
                    snapshot_id TEXT NOT NULL REFERENCES source_snapshots(snapshot_id),
                    game_id TEXT NOT NULL,
                    season TEXT NOT NULL,
                    game_date TEXT NOT NULL,
                    scheduled_at TEXT,
                    home_team TEXT,
                    away_team TEXT,
                    status INTEGER NOT NULL,
                    status_text TEXT NOT NULL,
                    game_label TEXT NOT NULL,
                    game_sub_label TEXT NOT NULL,
                    arena_name TEXT NOT NULL,
                    arena_city TEXT NOT NULL,
                    arena_state TEXT NOT NULL,
                    neutral_site INTEGER NOT NULL DEFAULT 0,
                    if_necessary INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (snapshot_id, game_id)
                );

                CREATE INDEX IF NOT EXISTS idx_schedule_season_date
                ON schedule_observations(season, game_date, game_id);

                CREATE TABLE IF NOT EXISTS injury_observations (
                    snapshot_id TEXT NOT NULL REFERENCES source_snapshots(snapshot_id),
                    game_date TEXT NOT NULL,
                    matchup TEXT NOT NULL,
                    team TEXT NOT NULL,
                    player_id INTEGER,
                    player_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    report_timestamp TEXT NOT NULL,
                    PRIMARY KEY (
                        snapshot_id, game_date, matchup, team, player_name
                    )
                );

                CREATE INDEX IF NOT EXISTS idx_injuries_game_report
                ON injury_observations(game_date, report_timestamp);

                CREATE TABLE IF NOT EXISTS market_quotes (
                    game_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    quote_timestamp TEXT NOT NULL,
                    home_spread REAL NOT NULL,
                    total REAL NOT NULL,
                    home_moneyline_probability REAL,
                    PRIMARY KEY (game_id, source, quote_timestamp)
                );

                CREATE INDEX IF NOT EXISTS idx_market_game_time
                ON market_quotes(game_id, quote_timestamp);
                """
            )
            _ensure_column(connection, "player_stat_observations", "age", "REAL")
            _ensure_column(
                connection,
                "player_stat_observations",
                "draft_year",
                "INTEGER",
            )
            _ensure_column(
                connection,
                "player_stat_observations",
                "country",
                "TEXT",
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection


def _scheduled_game_from_row(row: sqlite3.Row) -> ScheduledGame:
    return ScheduledGame(
        game_id=row["game_id"],
        season=row["season"],
        game_date=date.fromisoformat(row["game_date"]),
        scheduled_at=(
            datetime.fromisoformat(row["scheduled_at"])
            if row["scheduled_at"] is not None
            else None
        ),
        home_team=row["home_team"],
        away_team=row["away_team"],
        status=row["status"],
        status_text=row["status_text"],
        game_label=row["game_label"],
        game_sub_label=row["game_sub_label"],
        arena_name=row["arena_name"],
        arena_city=row["arena_city"],
        arena_state=row["arena_state"],
        neutral_site=bool(row["neutral_site"]),
        if_necessary=bool(row["if_necessary"]),
    )


def _ensure_column(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    columns = {
        str(row["name"])
        for row in connection.execute(f"PRAGMA table_info({table})")
    }
    if column not in columns:
        connection.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )
