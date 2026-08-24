from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

from nba_sim.data.licensed import (
    LicensedTrackingArchiveIngestor,
    MarketCsvIngestor,
)
from nba_sim.data.point_in_time import PointInTimeWarehouse
from nba_sim.data.provenance import RawSnapshotStore
from tests.test_tracking_data import make_sequence


class LicensedDataIngestionTests(unittest.TestCase):
    def test_market_csv_is_point_in_time_queryable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "market.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=(
                        "game_id",
                        "source",
                        "quote_timestamp",
                        "home_spread",
                        "total",
                        "home_moneyline_probability",
                    ),
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "game_id": "g1",
                        "source": "licensed-test",
                        "quote_timestamp": "2026-01-01T12:00:00+00:00",
                        "home_spread": "-2.5",
                        "total": "224.5",
                        "home_moneyline_probability": "0.58",
                    }
                )
            warehouse = PointInTimeWarehouse(root / "warehouse.sqlite")
            self.assertEqual(
                MarketCsvIngestor().ingest(path, warehouse=warehouse),
                1,
            )
            quote = warehouse.market_quote_as_of(
                game_id="g1",
                cutoff=datetime(2026, 1, 1, 13, tzinfo=timezone.utc),
            )
            self.assertEqual(quote.source, "licensed-test")

    def test_tracking_npz_is_safe_and_contract_validated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sequence = make_sequence()
            np.savez(
                root / "possession.npz",
                sequence_id=np.asarray(sequence.sequence_id),
                player_ids=sequence.player_ids,
                team_indices=sequence.team_indices,
                possession_team_index=np.asarray(
                    sequence.possession_team_index
                ),
                positions_5hz=sequence.positions_5hz,
                ball_positions_5hz=sequence.ball_positions_5hz,
                skeletons_30hz=sequence.skeletons_30hz,
                shoulder_normals_5hz=sequence.shoulder_normals_5hz,
                event_labels_5hz=sequence.event_labels_5hz,
                context_features=sequence.context_features,
                game_date=np.asarray("2025-12-01"),
            )
            result = LicensedTrackingArchiveIngestor().ingest_directory(
                root,
                vendor="licensed-test",
                season="2025-26",
                available_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                snapshots=RawSnapshotStore(root / "snapshots"),
            )
            self.assertEqual(result.sequences, 1)
            self.assertEqual(
                result.corpus.sequences[0].sequence_id,
                sequence.sequence_id,
            )
            self.assertEqual(
                result.snapshots[0].manifest.rights_tier,
                "licensed",
            )
            self.assertEqual(
                result.corpus.sequences[0].game_date,
                date(2025, 12, 1),
            )


if __name__ == "__main__":
    unittest.main()
