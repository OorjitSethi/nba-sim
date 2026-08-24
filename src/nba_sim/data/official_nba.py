from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from nba_sim.data.point_in_time import (
    HistoricalGame,
    InjuryObservation,
    PointInTimeWarehouse,
    PlayerSeasonStat,
    RosterObservation,
    ScheduledGame,
)
from nba_sim.data.provenance import RawSnapshotStore, Snapshot


_EASTERN = ZoneInfo("America/New_York")
_INJURY_STATUSES = {
    "available",
    "doubtful",
    "out",
    "probable",
    "questionable",
}


def _require_nba_api() -> tuple[type[Any], type[Any]]:
    try:
        from nba_api.stats.endpoints.commonallplayers import CommonAllPlayers
        from nba_api.stats.endpoints.leaguegamelog import LeagueGameLog
    except ImportError as error:
        raise ImportError(
            "Official NBA ingestion requires the 'data' extra: "
            "pip install -e '.[data]'"
        ) from error
    return CommonAllPlayers, LeagueGameLog


def _require_player_stat_endpoints() -> tuple[type[Any], type[Any]]:
    try:
        from nba_api.stats.endpoints.leaguedashplayerbiostats import (
            LeagueDashPlayerBioStats,
        )
        from nba_api.stats.endpoints.leaguedashplayerstats import (
            LeagueDashPlayerStats,
        )
    except ImportError as error:
        raise ImportError(
            "Official NBA ingestion requires the 'data' extra: "
            "pip install -e '.[data]'"
        ) from error
    return LeagueDashPlayerStats, LeagueDashPlayerBioStats


def _require_schedule_endpoint() -> type[Any]:
    try:
        from nba_api.stats.endpoints.scheduleleaguev2 import ScheduleLeagueV2
    except ImportError as error:
        raise ImportError(
            "Official NBA ingestion requires the 'data' extra: "
            "pip install -e '.[data]'"
        ) from error
    return ScheduleLeagueV2


def _require_requests() -> Any:
    try:
        import requests
    except ImportError as error:
        raise ImportError(
            "Official NBA ingestion requires the 'data' extra: "
            "pip install -e '.[data]'"
        ) from error
    return requests


@dataclass(frozen=True)
class SyncResult:
    dataset: str
    season: str
    records: int
    snapshot_path: str
    available_at: str


class OfficialNBAStatsIngestor:
    """Snapshots official NBA Stats responses before normalization."""

    source_name = "stats.nba.com"

    def __init__(
        self,
        *,
        snapshots: RawSnapshotStore,
        warehouse: PointInTimeWarehouse,
    ) -> None:
        self.snapshots = snapshots
        self.warehouse = warehouse

    def sync_current_rosters(
        self,
        *,
        season: str,
        retrieved_at: datetime | None = None,
        timeout: int = 30,
    ) -> SyncResult:
        CommonAllPlayers, _ = _require_nba_api()
        retrieved = (retrieved_at or datetime.now(timezone.utc)).astimezone(
            timezone.utc
        )
        endpoint = CommonAllPlayers(
            season=season,
            is_only_current_season=1,
            timeout=timeout,
        )
        raw = endpoint.get_normalized_dict()["CommonAllPlayers"]
        rows = tuple(_normalize_roster_rows(raw, season=season))
        snapshot = self._write_json_snapshot(
            dataset="rosters",
            season=season,
            records=raw,
            retrieved_at=retrieved,
        )
        count = self.warehouse.ingest_roster(snapshot, rows)
        return SyncResult(
            dataset="rosters",
            season=season,
            records=count,
            snapshot_path=str(snapshot.data_path),
            available_at=snapshot.manifest.available_at.isoformat(),
        )

    def sync_game_log(
        self,
        *,
        season: str,
        retrieved_at: datetime | None = None,
        timeout: int = 30,
    ) -> SyncResult:
        _, LeagueGameLog = _require_nba_api()
        retrieved = (retrieved_at or datetime.now(timezone.utc)).astimezone(
            timezone.utc
        )
        endpoint = LeagueGameLog(
            season=season,
            season_type_all_star="Regular Season",
            player_or_team_abbreviation="T",
            timeout=timeout,
        )
        raw = endpoint.get_normalized_dict()["LeagueGameLog"]
        games = tuple(_normalize_game_log(raw, season=season))
        snapshot = self._write_json_snapshot(
            dataset="game-logs",
            season=season,
            records=raw,
            retrieved_at=retrieved,
        )
        count = self.warehouse.ingest_games(snapshot, games)
        return SyncResult(
            dataset="game-logs",
            season=season,
            records=count,
            snapshot_path=str(snapshot.data_path),
            available_at=snapshot.manifest.available_at.isoformat(),
        )

    def sync_schedule(
        self,
        *,
        season: str,
        retrieved_at: datetime | None = None,
        timeout: int = 30,
    ) -> SyncResult:
        ScheduleLeagueV2 = _require_schedule_endpoint()
        retrieved = (retrieved_at or datetime.now(timezone.utc)).astimezone(
            timezone.utc
        )
        endpoint = ScheduleLeagueV2(season=season, timeout=timeout)
        schedule_table = endpoint.season_games.data
        headers = schedule_table["headers"]
        raw = [
            dict(zip(headers, values))
            for values in schedule_table["data"]
        ]
        games = tuple(_normalize_schedule(raw, season=season))
        snapshot = self._write_json_snapshot(
            dataset="schedule",
            season=season,
            records=raw,
            retrieved_at=retrieved,
        )
        count = self.warehouse.ingest_schedule(snapshot, games)
        return SyncResult(
            dataset="schedule",
            season=season,
            records=count,
            snapshot_path=str(snapshot.data_path),
            available_at=snapshot.manifest.available_at.isoformat(),
        )

    def sync_player_stats(
        self,
        *,
        season: str,
        retrieved_at: datetime | None = None,
        timeout: int = 30,
    ) -> SyncResult:
        LeagueDashPlayerStats, LeagueDashPlayerBioStats = (
            _require_player_stat_endpoints()
        )
        retrieved = (retrieved_at or datetime.now(timezone.utc)).astimezone(
            timezone.utc
        )
        common = {
            "season": season,
            "season_type_all_star": "Regular Season",
            "timeout": timeout,
        }
        base = LeagueDashPlayerStats(
            **common,
            measure_type_detailed_defense="Base",
            per_mode_detailed="PerGame",
        ).get_normalized_dict()["LeagueDashPlayerStats"]
        advanced = LeagueDashPlayerStats(
            **common,
            measure_type_detailed_defense="Advanced",
            per_mode_detailed="PerGame",
        ).get_normalized_dict()["LeagueDashPlayerStats"]
        bio = LeagueDashPlayerBioStats(
            **common,
            per_mode_simple="PerGame",
        ).get_normalized_dict()["LeagueDashPlayerBioStats"]
        rows = tuple(
            _normalize_player_stats(
                base,
                advanced,
                bio,
                season=season,
            )
        )
        timestamp = retrieved.strftime("%Y%m%dT%H%M%SZ")
        snapshot = self.snapshots.write_json(
            Path(season) / "player-stats" / f"{timestamp}.json",
            {
                "base_per_game": base,
                "advanced_per_game": advanced,
                "bio_per_game": bio,
            },
            source=self.source_name,
            dataset="player-stats",
            season=season,
            retrieved_at=retrieved,
            available_at=retrieved,
            schema_version="official-nba-player-stats-v1",
            record_count=len(rows),
            rights_tier="public-official",
        )
        count = self.warehouse.ingest_player_stats(snapshot, rows)
        return SyncResult(
            dataset="player-stats",
            season=season,
            records=count,
            snapshot_path=str(snapshot.data_path),
            available_at=snapshot.manifest.available_at.isoformat(),
        )

    def _write_json_snapshot(
        self,
        *,
        dataset: str,
        season: str,
        records: list[dict[str, Any]],
        retrieved_at: datetime,
    ) -> Snapshot:
        timestamp = retrieved_at.strftime("%Y%m%dT%H%M%SZ")
        return self.snapshots.write_json(
            Path(season) / dataset / f"{timestamp}.json",
            records,
            source=self.source_name,
            dataset=dataset,
            season=season,
            retrieved_at=retrieved_at,
            available_at=retrieved_at,
            schema_version="official-nba-v1",
            rights_tier="public-official",
        )


class OfficialNBAInjuryIngestor:
    source_name = "official.nba.com"

    def __init__(
        self,
        *,
        snapshots: RawSnapshotStore,
        warehouse: PointInTimeWarehouse,
    ) -> None:
        self.snapshots = snapshots
        self.warehouse = warehouse

    def sync_pdf_url(
        self,
        url: str,
        *,
        season: str,
        retrieved_at: datetime | None = None,
        timeout: int = 30,
    ) -> SyncResult:
        report_timestamp = injury_report_timestamp_from_url(url)
        retrieved = (retrieved_at or datetime.now(timezone.utc)).astimezone(
            timezone.utc
        )
        requests = _require_requests()
        response = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "nba-sim-research/0.1"},
        )
        response.raise_for_status()
        rows = OfficialInjuryPdfParser().parse(
            response.content,
            report_timestamp=report_timestamp,
        )
        filename = Path(urlparse(url).path).name
        snapshot = self.snapshots.write_bytes(
            Path(season) / "injuries" / filename,
            response.content,
            source=self.source_name,
            dataset="injuries",
            season=season,
            retrieved_at=retrieved,
            available_at=report_timestamp,
            schema_version="official-injury-pdf-v1",
            record_count=len(rows),
            rights_tier="public-official",
        )
        count = self.warehouse.ingest_injuries(snapshot, rows)
        return SyncResult(
            dataset="injuries",
            season=season,
            records=count,
            snapshot_path=str(snapshot.data_path),
            available_at=report_timestamp.isoformat(),
        )


@dataclass(frozen=True)
class _TextFragment:
    page: int
    y: float
    x: float
    text: str


class OfficialInjuryPdfParser:
    """Column-aware parser for the NBA's official injury-report PDF."""

    def parse(
        self,
        payload: bytes,
        *,
        report_timestamp: datetime,
    ) -> tuple[InjuryObservation, ...]:
        try:
            from pypdf import PdfReader
        except ImportError as error:
            raise ImportError(
                "Injury PDF parsing requires the 'data' extra: "
                "pip install -e '.[data]'"
            ) from error

        fragments: list[_TextFragment] = []
        reader = PdfReader(BytesIO(payload))
        for page_number, page in enumerate(reader.pages):
            page_fragments: list[_TextFragment] = []

            def visitor(
                text: str,
                _cm: list[float],
                tm: list[float],
                _font: dict[str, Any] | None,
                _size: float,
            ) -> None:
                normalized = " ".join(text.split())
                if normalized:
                    page_fragments.append(
                        _TextFragment(
                            page=page_number,
                            y=round(float(tm[5]), 1),
                            x=round(float(tm[4]), 1),
                            text=normalized,
                        )
                    )

            page.extract_text(visitor_text=visitor)
            fragments.extend(page_fragments)
        return self.parse_fragments(
            fragments,
            report_timestamp=report_timestamp,
        )

    def parse_fragments(
        self,
        fragments: Iterable[_TextFragment],
        *,
        report_timestamp: datetime,
    ) -> tuple[InjuryObservation, ...]:
        timestamp = report_timestamp.astimezone(timezone.utc)
        current_date: date | None = None
        current_matchup = ""
        current_team = ""
        result: list[InjuryObservation] = []

        by_page: dict[int, list[_TextFragment]] = {}
        for fragment in fragments:
            by_page.setdefault(fragment.page, []).append(fragment)

        for page_number in sorted(by_page):
            page = by_page[page_number]
            status_rows = sorted(
                (
                    fragment
                    for fragment in page
                    if 565.0 <= fragment.x < 665.0
                    and fragment.text.lower() in _INJURY_STATUSES
                ),
                key=lambda fragment: fragment.y,
            )
            for status_index, status_fragment in enumerate(status_rows):
                y = status_fragment.y
                same_line = [
                    fragment
                    for fragment in page
                    if abs(fragment.y - y) <= 1.1
                ]
                date_tokens = [
                    fragment.text for fragment in same_line if fragment.x < 110.0
                ]
                if date_tokens:
                    parsed_date = _parse_game_date(" ".join(date_tokens))
                    if parsed_date is not None:
                        current_date = parsed_date
                matchup_tokens = [
                    fragment.text
                    for fragment in same_line
                    if 190.0 <= fragment.x < 260.0
                ]
                if matchup_tokens:
                    current_matchup = " ".join(matchup_tokens)
                team_tokens = [
                    fragment.text
                    for fragment in same_line
                    if 255.0 <= fragment.x < 420.0
                ]
                if team_tokens:
                    current_team = " ".join(team_tokens)
                player_tokens = [
                    fragment.text
                    for fragment in same_line
                    if 420.0 <= fragment.x < 565.0
                ]
                player_name = _display_player_name(" ".join(player_tokens))
                if current_date is None or not current_matchup or not current_team:
                    raise ValueError(
                        "injury report row is missing game or team context"
                    )
                if not player_name:
                    raise ValueError("injury report row is missing a player")

                lower = (
                    (status_rows[status_index - 1].y + y) / 2.0
                    if status_index > 0
                    else y - 22.0
                )
                upper = (
                    (y + status_rows[status_index + 1].y) / 2.0
                    if status_index + 1 < len(status_rows)
                    else y + 24.0
                )
                reason_tokens = [
                    fragment.text
                    for fragment in sorted(
                        page,
                        key=lambda fragment: (fragment.y, fragment.x),
                    )
                    if 660.0 <= fragment.x
                    and lower <= fragment.y < upper
                    and fragment.text.lower() != "reason"
                ]
                result.append(
                    InjuryObservation(
                        game_date=current_date,
                        matchup=current_matchup,
                        team=current_team,
                        player_name=player_name,
                        status=status_fragment.text.title(),
                        reason=_clean_reason(" ".join(reason_tokens)),
                        report_timestamp=timestamp,
                    )
                )
        if not result:
            raise ValueError("official injury report contained no player rows")
        return tuple(result)


def injury_report_timestamp_from_url(url: str) -> datetime:
    match = re.search(
        r"Injury-Report_(\d{4}-\d{2}-\d{2})_(\d{1,2})_(\d{2})(AM|PM)\.pdf",
        url,
        flags=re.IGNORECASE,
    )
    if match is None:
        raise ValueError("injury report URL does not contain an official timestamp")
    local = datetime.strptime(
        "_".join(match.groups()),
        "%Y-%m-%d_%I_%M_%p",
    ).replace(tzinfo=_EASTERN)
    return local.astimezone(timezone.utc)


def _normalize_roster_rows(
    rows: Iterable[dict[str, Any]],
    *,
    season: str,
) -> Iterable[RosterObservation]:
    for row in rows:
        team_id = int(row.get("TEAM_ID") or 0)
        abbreviation = str(row.get("TEAM_ABBREVIATION") or "").strip()
        if team_id <= 0 or not abbreviation:
            continue
        yield RosterObservation(
            season=season,
            team_id=team_id,
            team_abbreviation=abbreviation,
            player_id=int(row["PERSON_ID"]),
            player_name=str(row["DISPLAY_FIRST_LAST"]),
            roster_status=(
                "active" if int(row.get("ROSTERSTATUS") or 0) == 1 else "inactive"
            ),
        )


def _normalize_player_stats(
    base_rows: Iterable[dict[str, Any]],
    advanced_rows: Iterable[dict[str, Any]],
    bio_rows: Iterable[dict[str, Any]],
    *,
    season: str,
) -> Iterable[PlayerSeasonStat]:
    advanced = {int(row["PLAYER_ID"]): row for row in advanced_rows}
    bios = {int(row["PLAYER_ID"]): row for row in bio_rows}
    for base in base_rows:
        player_id = int(base["PLAYER_ID"])
        advanced_row = advanced.get(player_id)
        bio = bios.get(player_id)
        if advanced_row is None or bio is None:
            continue
        yield PlayerSeasonStat(
            season=season,
            player_id=player_id,
            player_name=str(base["PLAYER_NAME"]),
            team_abbreviation=str(base.get("TEAM_ABBREVIATION") or ""),
            games_played=int(base.get("GP") or 0),
            minutes=float(base.get("MIN") or 0.0),
            field_goals_made=float(base.get("FGM") or 0.0),
            field_goals_attempted=float(base.get("FGA") or 0.0),
            threes_made=float(base.get("FG3M") or 0.0),
            threes_attempted=float(base.get("FG3A") or 0.0),
            free_throws_made=float(base.get("FTM") or 0.0),
            free_throws_attempted=float(base.get("FTA") or 0.0),
            offensive_rebounds=float(base.get("OREB") or 0.0),
            defensive_rebounds=float(base.get("DREB") or 0.0),
            assists=float(base.get("AST") or 0.0),
            turnovers=float(base.get("TOV") or 0.0),
            steals=float(base.get("STL") or 0.0),
            blocks=float(base.get("BLK") or 0.0),
            personal_fouls=float(base.get("PF") or 0.0),
            fouls_drawn=float(base.get("PFD") or 0.0),
            usage_rate=float(advanced_row.get("USG_PCT") or 0.0),
            assist_rate=float(advanced_row.get("AST_PCT") or 0.0),
            offensive_rebound_rate=float(
                advanced_row.get("OREB_PCT") or 0.0
            ),
            defensive_rebound_rate=float(
                advanced_row.get("DREB_PCT") or 0.0
            ),
            defensive_rating=float(
                advanced_row.get("DEF_RATING") or 114.0
            ),
            pace=float(advanced_row.get("PACE") or 99.0),
            player_impact_estimate=float(advanced_row.get("PIE") or 0.0),
            height_inches=float(bio.get("PLAYER_HEIGHT_INCHES") or 78.0),
            age=(
                float(bio["AGE"])
                if bio.get("AGE") not in {None, ""}
                else None
            ),
            draft_year=_optional_draft_year(bio.get("DRAFT_YEAR")),
            country=str(bio.get("COUNTRY") or "").strip() or None,
        )


def _optional_draft_year(value: object) -> int | None:
    normalized = str(value or "").strip()
    if not normalized or not normalized.isdigit():
        return None
    year = int(normalized)
    return year if year >= 1947 else None


def _normalize_game_log(
    rows: Iterable[dict[str, Any]],
    *,
    season: str,
) -> Iterable[HistoricalGame]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["GAME_ID"]), []).append(row)

    for game_id, game_rows in sorted(grouped.items()):
        if len(game_rows) != 2:
            raise ValueError(f"game {game_id} does not have exactly two team rows")
        home_rows = [row for row in game_rows if " vs. " in str(row["MATCHUP"])]
        away_rows = [row for row in game_rows if " @ " in str(row["MATCHUP"])]
        neutral_site = False
        if len(home_rows) == 1 and len(away_rows) == 1:
            home = home_rows[0]
            away = away_rows[0]
        elif len(home_rows) in {0, 2} and len(away_rows) in {0, 2}:
            # Some international neutral-site games label both team rows with
            # the same location marker. NBA LeagueGameLog places the designated
            # home row first; preserve that designation but remove home advantage.
            home, away = game_rows
            neutral_site = True
        else:
            raise ValueError(f"game {game_id} has ambiguous home/away rows")
        game_date = date.fromisoformat(str(home["GAME_DATE"])[:10])
        home_possessions = _estimate_possessions(home)
        away_possessions = _estimate_possessions(away)
        yield HistoricalGame(
            game_id=game_id,
            season=season,
            game_date=game_date,
            home_team=str(home["TEAM_ABBREVIATION"]),
            away_team=str(away["TEAM_ABBREVIATION"]),
            home_points=int(home["PTS"]),
            away_points=int(away["PTS"]),
            possessions=(home_possessions + away_possessions) / 2.0,
            result_available_at=datetime.combine(
                game_date + timedelta(days=1),
                time(hour=12),
                tzinfo=timezone.utc,
            ),
            neutral_site=neutral_site,
        )


def _normalize_schedule(
    rows: Iterable[dict[str, Any]],
    *,
    season: str,
) -> Iterable[ScheduledGame]:
    for row in rows:
        game_id = str(row.get("gameId") or "").strip()
        if not game_id:
            continue
        scheduled_at = _schedule_datetime(row)
        raw_date = str(row.get("gameDate") or "").strip()
        game_date = _schedule_date(raw_date)
        if game_date is None and scheduled_at is not None:
            game_date = scheduled_at.astimezone(_EASTERN).date()
        if game_date is None:
            raise ValueError(f"scheduled game {game_id} has no date")
        home = _optional_text(row.get("homeTeam_teamTricode"))
        away = _optional_text(row.get("awayTeam_teamTricode"))
        if (home is None) != (away is None):
            raise ValueError(
                f"scheduled game {game_id} identifies only one team"
            )
        yield ScheduledGame(
            game_id=game_id,
            season=season,
            game_date=game_date,
            scheduled_at=scheduled_at,
            home_team=home,
            away_team=away,
            status=int(row.get("gameStatus") or 0),
            status_text=str(row.get("gameStatusText") or "").strip(),
            game_label=str(row.get("gameLabel") or "").strip(),
            game_sub_label=str(row.get("gameSubLabel") or "").strip(),
            arena_name=str(row.get("arenaName") or "").strip(),
            arena_city=str(row.get("arenaCity") or "").strip(),
            arena_state=str(row.get("arenaState") or "").strip(),
            neutral_site=_boolish(row.get("isNeutral")),
            if_necessary=_boolish(row.get("ifNecessary")),
        )


def _schedule_datetime(row: dict[str, Any]) -> datetime | None:
    value = str(row.get("gameDateTimeUTC") or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
            timezone.utc
        )
    except ValueError as error:
        raise ValueError(f"invalid official schedule timestamp: {value}") from error


def _schedule_date(value: str) -> date | None:
    if not value:
        return None
    candidates = (
        (value[:10], "%Y-%m-%d"),
        (value[:10], "%m/%d/%Y"),
        (value[:19], "%m/%d/%Y %H:%M:%S"),
    )
    for candidate, pattern in candidates:
        try:
            return datetime.strptime(candidate, pattern).date()
        except ValueError:
            continue
    match = re.search(r"\d{1,2}/\d{1,2}/\d{4}", value)
    if match is not None:
        return datetime.strptime(match.group(0), "%m/%d/%Y").date()
    raise ValueError(f"invalid official schedule date: {value}")


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _boolish(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _estimate_possessions(row: dict[str, Any]) -> float:
    return max(
        1.0,
        float(row["FGA"])
        + 0.44 * float(row["FTA"])
        - float(row["OREB"])
        + float(row["TOV"]),
    )


def _parse_game_date(value: str) -> date | None:
    match = re.search(r"\d{2}/\d{2}/\d{4}", value)
    if match is None:
        return None
    return datetime.strptime(match.group(0), "%m/%d/%Y").date()


def _display_player_name(value: str) -> str:
    value = " ".join(value.split())
    if "," not in value:
        return value
    family, given = value.split(",", maxsplit=1)
    return f"{given.strip()} {family.strip()}".strip()


def _clean_reason(value: str) -> str:
    result = " ".join(value.split())
    result = re.sub(r"\s+([;,])", r"\1", result)
    result = result.replace(" - ", " — ")
    return result
