from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Sequence


TEAM_ABBREVIATIONS = (
    "ATL",
    "BOS",
    "BKN",
    "CHA",
    "CHI",
    "CLE",
    "DAL",
    "DEN",
    "DET",
    "GSW",
    "HOU",
    "IND",
    "LAC",
    "LAL",
    "MEM",
    "MIA",
    "MIL",
    "MIN",
    "NOP",
    "NYK",
    "OKC",
    "ORL",
    "PHI",
    "PHX",
    "POR",
    "SAC",
    "SAS",
    "TOR",
    "UTA",
    "WAS",
)

POSITIONS = ("G", "G", "F", "F-C", "C", "G", "F", "F-C", "G", "C")
HEIGHTS = (75, 76, 79, 81, 83, 74, 78, 80, 77, 82)

KNOWN_PLAYERS = {
    ("ATL", 0): (1_630_552, "Jalen Johnson"),
    ("BOS", 0): (1_628_369, "Jayson Tatum"),
    ("BOS", 1): (1_627_759, "Jaylen Brown"),
    ("BOS", 2): (1_628_401, "Derrick White"),
    ("BOS", 3): (201_950, "Jrue Holiday"),
    ("BOS", 4): (204_001, "Kristaps Porzingis"),
    ("BKN", 0): (1_630_560, "Cam Thomas"),
    ("DET", 0): (1_631_105, "Jalen Duren"),
    ("GSW", 0): (201_939, "Stephen Curry"),
    ("LAL", 0): (2_544, "LeBron James"),
    ("MIA", 0): (202_710, "Jimmy Butler III"),
    ("MIL", 0): (203_507, "Giannis Antetokounmpo"),
    ("MIN", 0): (1_630_162, "Anthony Edwards"),
    ("OKC", 0): (1_628_983, "Shai Gilgeous-Alexander"),
    ("OKC", 1): (1_631_096, "Chet Holmgren"),
    ("PHI", 0): (203_954, "Joel Embiid"),
    ("PHX", 0): (1_626_164, "Devin Booker"),
    ("PHX", 1): (201_142, "Kevin Durant"),
    ("UTA", 0): (1_628_374, "Lauri Markkanen"),
    ("UTA", 1): (1_641_718, "Keyonte George"),
    ("UTA", 2): (1_641_729, "Brice Sensabaugh"),
    ("MEM", 0): (1_628_991, "Jaren Jackson Jr."),
}


def build_demo_database(path: str | Path, *, overwrite: bool = False) -> Path:
    """Create a deterministic demonstration database with no downloaded data."""

    destination = Path(path)
    if destination.exists() and not overwrite:
        raise FileExistsError(
            f"{destination} already exists; pass --force to replace it"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.unlink(missing_ok=True)

    try:
        with sqlite3.connect(temporary) as connection:
            _create_schema(connection)
            _insert_demo_rows(connection)
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE Players (
            PLAYER_ID INTEGER PRIMARY KEY,
            PLAYER_NAME TEXT NOT NULL,
            TEAM_ABBREVIATION TEXT NOT NULL,
            POSITION TEXT NOT NULL,
            AGE INTEGER NOT NULL,
            PLAYER_HEIGHT_INCHES INTEGER NOT NULL,
            PLAYER_WEIGHT INTEGER NOT NULL,
            MIN REAL NOT NULL
        );
        CREATE TABLE Attributes (
            PLAYER_ID INTEGER PRIMARY KEY,
            DrawFoul INTEGER NOT NULL,
            PassIQ INTEGER NOT NULL,
            Usage REAL NOT NULL,
            PassPerception INTEGER NOT NULL,
            Steal INTEGER NOT NULL,
            Block INTEGER NOT NULL,
            OffRebound INTEGER NOT NULL,
            DefRebound INTEGER NOT NULL,
            Speed INTEGER NOT NULL,
            DefIQ INTEGER NOT NULL,
            FreeThrow INTEGER NOT NULL
        );
        CREATE TABLE SpatialTendencies (
            PLAYER_ID INTEGER NOT NULL,
            ZoneName TEXT NOT NULL,
            Frequency REAL NOT NULL,
            Efficiency REAL NOT NULL
        );
        CREATE INDEX idx_player_id ON Players(PLAYER_ID);
        CREATE INDEX idx_attr_id ON Attributes(PLAYER_ID);
        CREATE INDEX idx_spatial_id ON SpatialTendencies(PLAYER_ID);
        """
    )


def _insert_demo_rows(connection: sqlite3.Connection) -> None:
    zones = (
        ("Restricted Area", 0.34, 0.64),
        ("In The Paint (Non-RA)", 0.16, 0.43),
        ("Mid-Range", 0.12, 0.41),
        ("Left Corner 3", 0.08, 0.37),
        ("Right Corner 3", 0.08, 0.37),
        ("Above the Break 3", 0.22, 0.35),
    )
    for team_index, team in enumerate(TEAM_ABBREVIATIONS):
        for rotation_index, position in enumerate(POSITIONS):
            known = KNOWN_PLAYERS.get((team, rotation_index))
            player_id = (
                known[0]
                if known
                else 9_000_000 + team_index * 100 + rotation_index
            )
            name = known[1] if known else f"{team} Demo Player {rotation_index + 1}"
            height = HEIGHTS[rotation_index]
            connection.execute(
                """
                INSERT INTO Players VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    player_id,
                    name,
                    team,
                    position,
                    20 + (team_index + rotation_index) % 15,
                    height,
                    175 + (height - 72) * 7,
                    2_500.0 - rotation_index * 180.0,
                ),
            )
            connection.execute(
                """
                INSERT INTO Attributes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    player_id,
                    48 + (rotation_index * 3) % 35,
                    68 - rotation_index * 3,
                    29.0 - rotation_index * 1.8,
                    52 + rotation_index,
                    50 + (team_index + rotation_index) % 30,
                    42 + (height - 74) * 4,
                    38 + (height - 74) * 4,
                    44 + (height - 74) * 4,
                    76 - rotation_index * 2,
                    50 + (team_index * 3 + rotation_index) % 30,
                    72 + (team_index + rotation_index) % 17,
                ),
            )
            for zone_name, frequency, efficiency in zones:
                adjustment = ((team_index + rotation_index) % 5 - 2) * 0.004
                connection.execute(
                    "INSERT INTO SpatialTendencies VALUES (?, ?, ?, ?)",
                    (player_id, zone_name, frequency, efficiency + adjustment),
                )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nba-sim-demo",
        description="Generate a deterministic, non-authoritative demo database.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("ETL") / "nba_universe.db",
    )
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    destination = build_demo_database(args.output, overwrite=args.force)
    print(f"Created demonstration database at {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
