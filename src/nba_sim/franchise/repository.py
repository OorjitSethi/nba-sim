from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Mapping

from nba_sim.franchise.events import LeagueEvent, LeagueEventType
from nba_sim.franchise.state import LeagueState, apply_league_event


@dataclass(frozen=True)
class FranchiseSaveMetadata:
    save_id: str
    name: str
    branch_name: str
    league_id: str
    season: str
    user_team: str
    parent_save_id: str | None
    parent_revision: int | None
    created_at: datetime
    updated_at: datetime
    revision: int
    head_hash: str
    event_count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "save_id": self.save_id,
            "name": self.name,
            "branch_name": self.branch_name,
            "league_id": self.league_id,
            "season": self.season,
            "user_team": self.user_team,
            "parent_save_id": self.parent_save_id,
            "parent_revision": self.parent_revision,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "revision": self.revision,
            "head_hash": self.head_hash,
            "event_count": self.event_count,
        }


@dataclass(frozen=True)
class LoadedFranchise:
    metadata: FranchiseSaveMetadata
    state: LeagueState
    events: tuple[LeagueEvent, ...]


class FranchiseSaveRepository:
    """Durable event store with deterministic replay and hash-chain checks."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def create_save(
        self,
        state: LeagueState,
        *,
        name: str,
        branch_name: str = "Main",
        parent_save_id: str | None = None,
        parent_revision: int | None = None,
        actor: str = "user",
        event_type: LeagueEventType = LeagueEventType.LEAGUE_CREATED,
        event_payload: Mapping[str, object] | None = None,
        save_id: str | None = None,
        recorded_at: datetime | None = None,
    ) -> LoadedFranchise:
        normalized_name = name.strip()
        normalized_branch = branch_name.strip()
        if not normalized_name:
            raise ValueError("save name cannot be empty")
        if not normalized_branch:
            raise ValueError("branch name cannot be empty")
        identity = save_id or f"save-{secrets.token_hex(8)}"
        timestamp = (recorded_at or datetime.now(timezone.utc)).astimezone(
            timezone.utc
        )
        with self._lock, self._connect() as connection:
            genesis_json = self._json(state.as_dict())
            connection.execute(
                """
                INSERT INTO franchise_saves (
                    save_id, name, branch_name, league_id, season, user_team,
                    parent_save_id, parent_revision, created_at, updated_at,
                    genesis_json, genesis_checksum, head_revision, head_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identity,
                    normalized_name,
                    normalized_branch,
                    state.league_id,
                    state.season,
                    state.user_team,
                    parent_save_id,
                    parent_revision,
                    timestamp.isoformat(),
                    timestamp.isoformat(),
                    genesis_json,
                    hashlib.sha256(genesis_json.encode("utf-8")).hexdigest(),
                    state.revision,
                    state.head_hash,
                ),
            )
            self._append_with_connection(
                connection,
                save_id=identity,
                state=state,
                event_type=event_type,
                payload=dict(event_payload or {}),
                actor=actor,
                occurred_on=state.calendar.current_date,
                recorded_at=timestamp,
            )
        return self.load(identity)

    def append_event(
        self,
        save_id: str,
        *,
        event_type: LeagueEventType,
        payload: Mapping[str, object],
        actor: str = "user",
        occurred_on: date | None = None,
        recorded_at: datetime | None = None,
    ) -> LoadedFranchise:
        with self._lock, self._connect() as connection:
            loaded = self._load_with_connection(connection, save_id)
            self._append_with_connection(
                connection,
                save_id=save_id,
                state=loaded.state,
                event_type=event_type,
                payload=payload,
                actor=actor,
                occurred_on=occurred_on or loaded.state.calendar.current_date,
                recorded_at=recorded_at,
            )
        return self.load(save_id)

    def branch(
        self,
        source_save_id: str,
        *,
        branch_name: str,
        name: str | None = None,
        actor: str = "user",
        recorded_at: datetime | None = None,
    ) -> LoadedFranchise:
        source = self.load(source_save_id)
        return self.create_save(
            source.state,
            name=name or source.metadata.name,
            branch_name=branch_name,
            parent_save_id=source.metadata.save_id,
            parent_revision=source.state.revision,
            actor=actor,
            event_type=LeagueEventType.BRANCH_CREATED,
            event_payload={
                "parent_save_id": source.metadata.save_id,
                "parent_revision": source.state.revision,
                "parent_head_hash": source.state.head_hash,
            },
            recorded_at=recorded_at,
        )

    def load(self, save_id: str) -> LoadedFranchise:
        with self._lock, self._connect() as connection:
            return self._load_with_connection(connection, save_id)

    def list_saves(self) -> tuple[FranchiseSaveMetadata, ...]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT saves.*, COUNT(events.event_id) AS event_count
                FROM franchise_saves AS saves
                LEFT JOIN franchise_events AS events
                    ON events.save_id = saves.save_id
                GROUP BY saves.save_id
                ORDER BY saves.updated_at DESC, saves.save_id
                """
            ).fetchall()
        return tuple(self._metadata(row) for row in rows)

    def _append_with_connection(
        self,
        connection: sqlite3.Connection,
        *,
        save_id: str,
        state: LeagueState,
        event_type: LeagueEventType,
        payload: Mapping[str, object],
        actor: str,
        occurred_on: date,
        recorded_at: datetime | None,
    ) -> LeagueState:
        event = LeagueEvent.create(
            namespace=save_id,
            sequence=state.revision + 1,
            event_type=event_type,
            occurred_on=occurred_on,
            actor=actor,
            payload=payload,
            previous_hash=state.head_hash,
            recorded_at=recorded_at,
        )
        updated = apply_league_event(state, event)
        connection.execute(
            """
            INSERT INTO franchise_events (
                save_id, sequence, event_id, event_type, occurred_on,
                recorded_at, actor, payload_json, previous_hash, event_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                save_id,
                event.sequence,
                event.event_id,
                event.event_type.value,
                event.occurred_on.isoformat(),
                event.recorded_at.isoformat(),
                event.actor,
                self._json(dict(event.payload)),
                event.previous_hash,
                event.event_hash,
            ),
        )
        connection.execute(
            """
            UPDATE franchise_saves
            SET updated_at = ?, head_revision = ?, head_hash = ?
            WHERE save_id = ?
            """,
            (
                event.recorded_at.isoformat(),
                updated.revision,
                updated.head_hash,
                save_id,
            ),
        )
        return updated

    def _load_with_connection(
        self,
        connection: sqlite3.Connection,
        save_id: str,
    ) -> LoadedFranchise:
        row = connection.execute(
            """
            SELECT saves.*, COUNT(events.event_id) AS event_count
            FROM franchise_saves AS saves
            LEFT JOIN franchise_events AS events
                ON events.save_id = saves.save_id
            WHERE saves.save_id = ?
            GROUP BY saves.save_id
            """,
            (save_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown franchise save: {save_id}")
        genesis_json = str(row["genesis_json"])
        expected_checksum = hashlib.sha256(
            genesis_json.encode("utf-8")
        ).hexdigest()
        if expected_checksum != str(row["genesis_checksum"]):
            raise ValueError("franchise genesis snapshot hash is invalid")
        state = LeagueState.from_dict(json.loads(genesis_json))
        event_rows = connection.execute(
            """
            SELECT * FROM franchise_events
            WHERE save_id = ?
            ORDER BY sequence
            """,
            (save_id,),
        ).fetchall()
        events = tuple(self._event(event_row) for event_row in event_rows)
        for event in events:
            state = apply_league_event(state, event)
        if (
            state.revision != int(row["head_revision"])
            or state.head_hash != str(row["head_hash"])
        ):
            raise ValueError("franchise save head does not match replayed ledger")
        return LoadedFranchise(
            metadata=self._metadata(row),
            state=state,
            events=events,
        )

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS franchise_saves (
                    save_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    branch_name TEXT NOT NULL,
                    league_id TEXT NOT NULL,
                    season TEXT NOT NULL,
                    user_team TEXT NOT NULL,
                    parent_save_id TEXT,
                    parent_revision INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    genesis_json TEXT NOT NULL,
                    genesis_checksum TEXT NOT NULL,
                    head_revision INTEGER NOT NULL,
                    head_hash TEXT NOT NULL
                )
                """
            )
            columns = {
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(franchise_saves)"
                ).fetchall()
            }
            if "genesis_checksum" not in columns:
                connection.execute(
                    "ALTER TABLE franchise_saves ADD COLUMN genesis_checksum TEXT"
                )
                rows = connection.execute(
                    "SELECT save_id, genesis_json FROM franchise_saves"
                ).fetchall()
                for row in rows:
                    genesis_json = str(row["genesis_json"])
                    connection.execute(
                        """
                        UPDATE franchise_saves
                        SET genesis_checksum = ?
                        WHERE save_id = ?
                        """,
                        (
                            hashlib.sha256(
                                genesis_json.encode("utf-8")
                            ).hexdigest(),
                            row["save_id"],
                        ),
                    )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS franchise_events (
                    save_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_id TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    occurred_on TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL,
                    PRIMARY KEY (save_id, sequence),
                    FOREIGN KEY (save_id) REFERENCES franchise_saves(save_id)
                        ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS franchise_events_save_date_idx
                ON franchise_events (save_id, occurred_on, sequence)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS franchise_saves_updated_idx
                ON franchise_saves (updated_at DESC)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

    @staticmethod
    def _metadata(row: sqlite3.Row) -> FranchiseSaveMetadata:
        return FranchiseSaveMetadata(
            save_id=str(row["save_id"]),
            name=str(row["name"]),
            branch_name=str(row["branch_name"]),
            league_id=str(row["league_id"]),
            season=str(row["season"]),
            user_team=str(row["user_team"]),
            parent_save_id=(
                str(row["parent_save_id"])
                if row["parent_save_id"] is not None
                else None
            ),
            parent_revision=(
                int(row["parent_revision"])
                if row["parent_revision"] is not None
                else None
            ),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
            revision=int(row["head_revision"]),
            head_hash=str(row["head_hash"]),
            event_count=int(row["event_count"]),
        )

    @staticmethod
    def _event(row: sqlite3.Row) -> LeagueEvent:
        return LeagueEvent.from_dict(
            {
                "event_id": row["event_id"],
                "sequence": row["sequence"],
                "event_type": row["event_type"],
                "occurred_on": row["occurred_on"],
                "recorded_at": row["recorded_at"],
                "actor": row["actor"],
                "payload": json.loads(row["payload_json"]),
                "previous_hash": row["previous_hash"],
                "event_hash": row["event_hash"],
            }
        )
