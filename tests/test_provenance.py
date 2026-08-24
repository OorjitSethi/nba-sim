from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nba_sim.data.provenance import RawSnapshotStore


class SnapshotStoreTests(unittest.TestCase):
    def test_snapshot_is_atomic_verifiable_and_point_in_time_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RawSnapshotStore(directory)
            available = datetime(2026, 1, 2, 10, 0, tzinfo=timezone.utc)
            snapshot = store.write_json(
                "2025-26/injuries/10-00.json",
                [{"player": 1, "status": "questionable"}],
                source="nba-official",
                dataset="injuries",
                season="2025-26",
                retrieved_at=available + timedelta(minutes=1),
                available_at=available,
                schema_version="1",
            )
            loaded = store.load("2025-26/injuries/10-00.json")
            self.assertEqual(loaded.manifest.sha256, snapshot.manifest.sha256)
            self.assertEqual(loaded.manifest.record_count, 1)
            loaded.manifest.assert_available_as_of(available)
            with self.assertRaisesRegex(ValueError, "after forecast cutoff"):
                loaded.manifest.assert_available_as_of(
                    available - timedelta(seconds=1)
                )

    def test_checksum_tampering_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RawSnapshotStore(directory)
            now = datetime.now(timezone.utc)
            snapshot = store.write_bytes(
                "games.json",
                b"[]",
                source="test",
                dataset="games",
                season="2025-26",
                retrieved_at=now,
                available_at=now,
                schema_version="1",
            )
            snapshot.data_path.write_bytes(b"[1]")
            with self.assertRaisesRegex(ValueError, "checksum"):
                store.verify(snapshot)

    def test_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RawSnapshotStore(directory)
            now = datetime.now(timezone.utc)
            with self.assertRaisesRegex(ValueError, "escapes"):
                store.write_bytes(
                    Path("..") / "escape.json",
                    json.dumps([]).encode(),
                    source="test",
                    dataset="test",
                    season="test",
                    retrieved_at=now,
                    available_at=now,
                    schema_version="1",
                )


if __name__ == "__main__":
    unittest.main()
