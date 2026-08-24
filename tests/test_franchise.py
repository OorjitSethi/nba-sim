from __future__ import annotations

import hashlib
import json
import sqlite3
import unittest
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from nba_sim.franchise.events import LeagueEventType
from nba_sim.franchise.models import (
    FranchiseRecord,
    LeagueCalendar,
    PlayerRecord,
    PlayerLifecycleRecord,
)
from nba_sim.franchise.repository import FranchiseSaveRepository
from nba_sim.franchise.state import LeagueState


def _state() -> LeagueState:
    return LeagueState(
        schema_version=1,
        league_id="league-test",
        league_name="Test League",
        season="2026-27",
        seed=77,
        user_team="AAA",
        calendar=LeagueCalendar(
            season="2026-27",
            cap_year_start=date(2026, 7, 1),
            cap_year_end=date(2027, 6, 30),
            regular_season_start=date(2026, 10, 20),
            regular_season_end=date(2027, 4, 12),
            current_date=date(2026, 7, 26),
        ),
        franchises=(
            FranchiseRecord("AAA", "Alpha", "East", "Atlantic"),
            FranchiseRecord("BBB", "Beta", "West", "Pacific"),
        ),
        players=(
            PlayerRecord(1, "One", "AAA", "G", "active", 32.0, "test"),
            PlayerRecord(2, "Two", "BBB", "F", "active", 31.0, "test"),
        ),
    )


class FranchiseKernelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "franchise.sqlite"
        self.repository = FranchiseSaveRepository(self.path)
        self.recorded_at = datetime(2026, 7, 26, 10, tzinfo=timezone.utc)

    def test_save_replays_event_ledger_and_advances_calendar(self) -> None:
        created = self.repository.create_save(
            _state(),
            name="My League",
            save_id="save-main",
            recorded_at=self.recorded_at,
        )
        self.assertEqual(created.state.revision, 1)
        self.assertEqual(
            created.events[0].event_type,
            LeagueEventType.LEAGUE_CREATED,
        )
        advanced = self.repository.append_event(
            "save-main",
            event_type=LeagueEventType.DATE_ADVANCED,
            payload={"to_date": "2026-08-02"},
            occurred_on=date(2026, 8, 2),
            recorded_at=datetime(2026, 7, 26, 11, tzinfo=timezone.utc),
        )
        replay = self.repository.load("save-main")
        self.assertEqual(advanced.state, replay.state)
        self.assertEqual(replay.state.calendar.current_date, date(2026, 8, 2))
        self.assertEqual(replay.state.revision, 2)
        self.assertEqual(replay.metadata.event_count, 2)

    def test_branch_is_independent_and_retains_parent_lineage(self) -> None:
        main = self.repository.create_save(
            _state(),
            name="My League",
            save_id="save-main",
            recorded_at=self.recorded_at,
        )
        branch = self.repository.branch(
            main.metadata.save_id,
            branch_name="Keep the core",
            recorded_at=datetime(2026, 7, 26, 11, tzinfo=timezone.utc),
        )
        self.repository.append_event(
            branch.metadata.save_id,
            event_type=LeagueEventType.DATE_ADVANCED,
            payload={"to_date": "2026-08-09"},
            occurred_on=date(2026, 8, 9),
            recorded_at=datetime(2026, 7, 26, 12, tzinfo=timezone.utc),
        )
        unchanged_main = self.repository.load(main.metadata.save_id)
        advanced_branch = self.repository.load(branch.metadata.save_id)
        self.assertEqual(
            unchanged_main.state.calendar.current_date,
            date(2026, 7, 26),
        )
        self.assertEqual(
            advanced_branch.state.calendar.current_date,
            date(2026, 8, 9),
        )
        self.assertEqual(
            advanced_branch.metadata.parent_save_id,
            main.metadata.save_id,
        )
        self.assertEqual(
            advanced_branch.metadata.parent_revision,
            main.state.revision,
        )

    def test_hash_chain_detects_tampering(self) -> None:
        self.repository.create_save(
            _state(),
            name="My League",
            save_id="save-main",
            recorded_at=self.recorded_at,
        )
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                UPDATE franchise_events
                SET payload_json = '{"tampered":true}'
                WHERE save_id = 'save-main' AND sequence = 1
                """
            )
        with self.assertRaisesRegex(ValueError, "hash"):
            self.repository.load("save-main")

    def test_genesis_checksum_detects_snapshot_tampering(self) -> None:
        self.repository.create_save(
            _state(),
            name="My League",
            save_id="save-main",
            recorded_at=self.recorded_at,
        )
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                """
                SELECT genesis_json FROM franchise_saves
                WHERE save_id = 'save-main'
                """
            ).fetchone()
            connection.execute(
                """
                UPDATE franchise_saves
                SET genesis_json = ?
                WHERE save_id = 'save-main'
                """,
                (str(row[0]).replace("Test League", "Tampered League"),),
            )
        with self.assertRaisesRegex(ValueError, "genesis"):
            self.repository.load("save-main")

    def test_contract_record_is_supported_by_the_reducer(self) -> None:
        self.repository.create_save(
            _state(),
            name="My League",
            save_id="save-main",
            recorded_at=self.recorded_at,
        )
        loaded = self.repository.append_event(
            "save-main",
            event_type=LeagueEventType.CONTRACT_REGISTERED,
            payload={
                "record": {
                    "contract_id": "contract-1",
                    "player_id": 1,
                    "team": "AAA",
                    "signed_on": "2026-07-26",
                    "years": [
                        {
                            "season": "2026-27",
                            "salary": 10_000_000,
                            "option": None,
                        }
                    ],
                    "status": "active",
                    "source": "test",
                }
            },
            recorded_at=datetime(2026, 7, 26, 11, tzinfo=timezone.utc),
        )
        self.assertEqual(len(loaded.state.contracts), 1)
        self.assertEqual(loaded.state.contracts[0].years[0].salary, 10_000_000)

    def test_player_lifecycle_initialization_is_durable(self) -> None:
        self.repository.create_save(
            _state(),
            name="My League",
            save_id="save-main",
            recorded_at=self.recorded_at,
        )
        record = PlayerLifecycleRecord(
            player_id=1,
            as_of_season="2026-27",
            age=24,
            age_source="test",
            stage="developing",
            offense=65,
            playmaking=64,
            defense=63,
            athleticism=70,
            overall=65,
            potential_mean=72,
            potential_sd=4,
            workload_minutes=1800,
            games_played=70,
            confidence="moderate",
            model_version="test",
        )
        loaded = self.repository.append_event(
            "save-main",
            event_type=LeagueEventType.PLAYER_LIFECYCLES_INITIALIZED,
            payload={
                "records": [
                    record.as_dict(),
                    replace(record, player_id=2).as_dict(),
                ]
            },
            recorded_at=datetime(2026, 7, 26, 11, tzinfo=timezone.utc),
        )
        self.assertEqual(
            loaded.state.player_lifecycles,
            (record, replace(record, player_id=2)),
        )
        self.assertEqual(
            self.repository.load("save-main").state.player_lifecycles,
            (record, replace(record, player_id=2)),
        )

    def test_pre_lifecycle_genesis_hash_remains_compatible(self) -> None:
        value = _state().as_dict()
        value.pop("player_lifecycles")
        value.pop("player_health")
        value.pop("team_chemistry")
        value.pop("coaching_profiles")
        value["revision"] = 0
        value["head_hash"] = ""
        legacy_hash = hashlib.sha256(
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        value["head_hash"] = legacy_hash
        loaded = LeagueState.from_dict(value)
        self.assertEqual(loaded.head_hash, legacy_hash)
        self.assertEqual(loaded.player_lifecycles, ())


if __name__ == "__main__":
    unittest.main()
