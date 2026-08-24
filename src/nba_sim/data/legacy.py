from __future__ import annotations

from dataclasses import replace
import sqlite3
from pathlib import Path
from typing import Iterable

from nba_sim.domain.enums import ShotZone
from nba_sim.domain.profiles import PlayerProfile, TeamProfile, ZoneProfile


_ZONE_MAP = {
    "Restricted Area": ShotZone.RESTRICTED_AREA,
    "In The Paint (Non-RA)": ShotZone.PAINT_NON_RA,
    "Mid-Range": ShotZone.MID_RANGE,
    "Left Corner 3": ShotZone.LEFT_CORNER_THREE,
    "Right Corner 3": ShotZone.RIGHT_CORNER_THREE,
    "Above the Break 3": ShotZone.ABOVE_BREAK_THREE,
    "Backcourt": ShotZone.BACKCOURT,
}

_ZONE_PRIORS = {
    ShotZone.RESTRICTED_AREA: 0.64,
    ShotZone.PAINT_NON_RA: 0.42,
    ShotZone.MID_RANGE: 0.40,
    ShotZone.LEFT_CORNER_THREE: 0.37,
    ShotZone.RIGHT_CORNER_THREE: 0.37,
    ShotZone.ABOVE_BREAK_THREE: 0.35,
    ShotZone.BACKCOURT: 0.02,
}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(float(value), high))


def _normalize_minutes(raw_minutes: list[float]) -> list[float]:
    """Convert season-minute weights to a coherent 240-minute rotation."""

    if not raw_minutes or sum(raw_minutes) <= 0:
        return [48.0 / len(raw_minutes)] * len(raw_minutes)
    weights = [max(0.0, value) for value in raw_minutes]
    allocations = [240.0 * value / sum(weights) for value in weights]

    # Redistribute any amount above a realistic 40-minute expectation.
    for _ in range(8):
        excess = sum(max(0.0, value - 40.0) for value in allocations)
        allocations = [min(40.0, value) for value in allocations]
        if excess < 1e-9:
            break
        eligible = [i for i, value in enumerate(allocations) if value < 40.0]
        denominator = sum(weights[i] for i in eligible)
        if not eligible or denominator <= 0:
            break
        for i in eligible:
            allocations[i] += excess * weights[i] / denominator
    return allocations


class LegacySQLiteRepository:
    """Read-only adapter for the prototype's 2023-24 SQLite artifact."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        if not self.database_path.is_file():
            raise FileNotFoundError(self.database_path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            f"file:{self.database_path.resolve()}?mode=ro",
            uri=True,
        )
        connection.row_factory = sqlite3.Row
        return connection

    def available_teams(self) -> tuple[str, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT TEAM_ABBREVIATION
                FROM Players
                WHERE TEAM_ABBREVIATION IS NOT NULL
                ORDER BY TEAM_ABBREVIATION
                """
            ).fetchall()
        return tuple(str(row[0]) for row in rows)

    def load_team(self, abbreviation: str) -> TeamProfile:
        abbreviation = abbreviation.upper()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    p.PLAYER_ID,
                    p.PLAYER_NAME,
                    p.TEAM_ABBREVIATION,
                    p.POSITION,
                    p.PLAYER_HEIGHT_INCHES,
                    p.MIN,
                    a.DrawFoul,
                    a.PassIQ,
                    a.Usage,
                    a.PassPerception,
                    a.Steal,
                    a.Block,
                    a.OffRebound,
                    a.DefRebound,
                    a.Speed,
                    a.DefIQ,
                    a.FreeThrow
                FROM Players p
                JOIN Attributes a ON a.PLAYER_ID = p.PLAYER_ID
                WHERE p.TEAM_ABBREVIATION = ?
                ORDER BY p.MIN DESC
                """,
                (abbreviation,),
            ).fetchall()
            if len(rows) < 5:
                raise KeyError(f"team {abbreviation!r} is missing or unavailable")

            # The source contains all players who appeared for a team. Restrict the
            # fallback engine to a plausible ten-player rotation.
            rotation_rows = rows[: min(10, len(rows))]
            expected_minutes = _normalize_minutes(
                [float(row["MIN"] or 0.0) for row in rotation_rows]
            )
            player_ids = [int(row["PLAYER_ID"]) for row in rotation_rows]
            zones = self._load_zones(connection, player_ids)

        players = tuple(
            self._to_player(row, minutes, zones.get(int(row["PLAYER_ID"]), {}))
            for row, minutes in zip(rotation_rows, expected_minutes)
        )
        return TeamProfile(
            abbreviation=abbreviation,
            name=abbreviation,
            roster=players,
        )

    def load_player(
        self,
        player_id: int,
        *,
        team_abbreviation: str | None = None,
    ) -> PlayerProfile | None:
        """Load the best historical profile for a player, independent of team."""

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    p.PLAYER_ID,
                    p.PLAYER_NAME,
                    p.TEAM_ABBREVIATION,
                    p.POSITION,
                    p.PLAYER_HEIGHT_INCHES,
                    p.MIN,
                    a.DrawFoul,
                    a.PassIQ,
                    a.Usage,
                    a.PassPerception,
                    a.Steal,
                    a.Block,
                    a.OffRebound,
                    a.DefRebound,
                    a.Speed,
                    a.DefIQ,
                    a.FreeThrow
                FROM Players p
                JOIN Attributes a ON a.PLAYER_ID = p.PLAYER_ID
                WHERE p.PLAYER_ID = ?
                ORDER BY p.MIN DESC
                LIMIT 1
                """,
                (int(player_id),),
            ).fetchone()
            if row is None:
                return None
            zones = self._load_zones(connection, (int(player_id),)).get(
                int(player_id),
                {},
            )
        # The legacy MIN field is season minutes. Convert it to a conservative
        # per-game role weight before the current roster is normalized to 240.
        expected_minutes = _clamp(float(row["MIN"] or 0.0) / 82.0, 2.0, 36.0)
        profile = self._to_player(row, expected_minutes, zones)
        if team_abbreviation is not None:
            profile = replace(
                profile,
                team_abbreviation=team_abbreviation.upper(),
            )
        return profile

    def _load_zones(
        self,
        connection: sqlite3.Connection,
        player_ids: Iterable[int],
    ) -> dict[int, dict[ShotZone, ZoneProfile]]:
        ids = tuple(player_ids)
        placeholders = ",".join("?" for _ in ids)
        rows = connection.execute(
            f"""
            SELECT PLAYER_ID, ZoneName, Frequency, Efficiency
            FROM SpatialTendencies
            WHERE PLAYER_ID IN ({placeholders})
            """,
            ids,
        ).fetchall()
        result: dict[int, dict[ShotZone, ZoneProfile]] = {}
        for row in rows:
            zone = _ZONE_MAP.get(str(row["ZoneName"]))
            if zone is None:
                continue
            player_id = int(row["PLAYER_ID"])
            # The legacy table discarded attempt counts. Apply conservative
            # shrinkage rather than treating every observed percentage as exact.
            observed = _clamp(float(row["Efficiency"]), 0.0, 1.0)
            shrunk = 0.72 * observed + 0.28 * _ZONE_PRIORS[zone]
            result.setdefault(player_id, {})[zone] = ZoneProfile(
                frequency=_clamp(float(row["Frequency"]), 0.0, 1.0),
                make_probability=_clamp(shrunk, 0.01, 0.90),
            )
        return result

    def _to_player(
        self,
        row: sqlite3.Row,
        expected_minutes: float,
        zones: dict[ShotZone, ZoneProfile],
    ) -> PlayerProfile:
        if not zones:
            zones = {
                ShotZone.RESTRICTED_AREA: ZoneProfile(0.45, 0.58),
                ShotZone.MID_RANGE: ZoneProfile(0.20, 0.40),
                ShotZone.ABOVE_BREAK_THREE: ZoneProfile(0.35, 0.34),
            }

        pass_iq = float(row["PassIQ"] or 50.0)
        def_iq = float(row["DefIQ"] or 50.0)
        steal = float(row["Steal"] or 50.0)
        block = float(row["Block"] or 50.0)
        draw_foul = float(row["DrawFoul"] or 50.0)

        return PlayerProfile(
            player_id=int(row["PLAYER_ID"]),
            name=str(row["PLAYER_NAME"]),
            team_abbreviation=str(row["TEAM_ABBREVIATION"]),
            position=str(row["POSITION"] or "G"),
            expected_minutes=expected_minutes,
            usage_rate=_clamp(float(row["Usage"] or 20.0) / 100.0, 0.05, 0.45),
            free_throw_probability=_clamp(
                float(row["FreeThrow"] or 75.0) / 100.0,
                0.35,
                0.96,
            ),
            turnover_probability=_clamp(
                0.125 - (pass_iq - 50.0) * 0.00055,
                0.07,
                0.165,
            ),
            assist_probability=_clamp(0.28 + pass_iq * 0.0052, 0.28, 0.82),
            shooting_foul_probability=_clamp(
                0.065 + draw_foul * 0.00085,
                0.065,
                0.16,
            ),
            steal_share=max(0.05, 0.25 + steal / 100.0),
            block_probability=_clamp(0.003 + block * 0.00045, 0.003, 0.06),
            offensive_rebound_weight=max(
                0.1,
                float(row["OffRebound"] or 20.0) + float(row["PLAYER_HEIGHT_INCHES"]) * 0.35,
            ),
            defensive_rebound_weight=max(
                0.1,
                float(row["DefRebound"] or 30.0) + float(row["PLAYER_HEIGHT_INCHES"]) * 0.45,
            ),
            defensive_impact=_clamp((def_iq - 50.0) / 500.0, -0.10, 0.10),
            speed=_clamp(float(row["Speed"] or 50.0) / 100.0, 0.1, 1.0),
            height_inches=float(row["PLAYER_HEIGHT_INCHES"] or 78.0),
            shot_zones=zones,
        )
