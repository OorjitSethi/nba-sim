from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
import numpy as np

from nba_sim.data.point_in_time import MarketQuote, PointInTimeWarehouse
from nba_sim.data.provenance import RawSnapshotStore, Snapshot
from nba_sim.spatial.corpus import TrackingCorpus
from nba_sim.spatial.training_data import TrackingSequence


class MarketCsvIngestor:
    """Provider-neutral point-in-time market quote importer.

    Vendors differ substantially in naming and licensing. This adapter accepts a
    small normalized export and never attempts to scrape a sportsbook.
    """

    required_columns = {
        "game_id",
        "source",
        "quote_timestamp",
        "home_spread",
        "total",
    }

    def ingest(
        self,
        path: str | Path,
        *,
        warehouse: PointInTimeWarehouse,
    ) -> int:
        with Path(path).open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            missing = self.required_columns - set(reader.fieldnames or ())
            if missing:
                raise ValueError(
                    f"market CSV is missing columns: {sorted(missing)}"
                )
            quotes = tuple(self._quote(row) for row in reader)
        return warehouse.ingest_market_quotes(quotes)

    @staticmethod
    def _quote(row: dict[str, str]) -> MarketQuote:
        probability = row.get("home_moneyline_probability", "").strip()
        timestamp = datetime.fromisoformat(row["quote_timestamp"])
        if timestamp.tzinfo is None:
            raise ValueError("market quote timestamps must include a timezone")
        return MarketQuote(
            game_id=row["game_id"].strip(),
            source=row["source"].strip(),
            quote_timestamp=timestamp,
            home_spread=float(row["home_spread"]),
            total=float(row["total"]),
            home_moneyline_probability=(
                float(probability) if probability else None
            ),
        )


@dataclass(frozen=True)
class TrackingIngestResult:
    vendor: str
    season: str
    sequences: int
    snapshots: tuple[Snapshot, ...]
    corpus: TrackingCorpus


class LicensedTrackingArchiveIngestor:
    """Reads a safe, vendor-neutral NPZ export into the tracking corpus.

    Each archive contains one possession and must use the exact array names
    required by ``TrackingSequence``. ``allow_pickle=False`` is mandatory so a
    licensed delivery cannot execute embedded Python objects.
    """

    required_arrays = {
        "player_ids",
        "team_indices",
        "possession_team_index",
        "positions_5hz",
        "ball_positions_5hz",
        "skeletons_30hz",
        "shoulder_normals_5hz",
        "event_labels_5hz",
        "context_features",
    }

    def ingest_directory(
        self,
        directory: str | Path,
        *,
        vendor: str,
        season: str,
        available_at: datetime,
        snapshots: RawSnapshotStore,
    ) -> TrackingIngestResult:
        if not vendor.strip():
            raise ValueError("tracking vendor cannot be empty")
        if available_at.tzinfo is None:
            raise ValueError("available_at must be timezone-aware")
        root = Path(directory)
        files = tuple(sorted(root.glob("*.npz")))
        if not files:
            raise ValueError("tracking directory contains no NPZ archives")

        sequences = []
        stored = []
        retrieved = datetime.now(timezone.utc)
        for path in files:
            sequence = self.load_sequence(path)
            raw = path.read_bytes()
            snapshot = snapshots.write_bytes(
                Path(season) / "tracking" / vendor / path.name,
                raw,
                source=vendor,
                dataset="tracking",
                season=season,
                retrieved_at=retrieved,
                available_at=available_at,
                schema_version="tracking-npz-v1",
                record_count=sequence.timesteps,
                rights_tier="licensed",
            )
            sequences.append(sequence)
            stored.append(snapshot)
        corpus = TrackingCorpus(sequences)
        return TrackingIngestResult(
            vendor=vendor,
            season=season,
            sequences=len(sequences),
            snapshots=tuple(stored),
            corpus=corpus,
        )

    def load_directory(self, directory: str | Path) -> TrackingCorpus:
        files = tuple(sorted(Path(directory).glob("*.npz")))
        if not files:
            raise ValueError("tracking directory contains no NPZ archives")
        return TrackingCorpus(self.load_sequence(path) for path in files)

    def load_sequence(self, path: str | Path) -> TrackingSequence:
        path = Path(path)
        with np.load(path, allow_pickle=False) as archive:
            missing = self.required_arrays - set(archive.files)
            if missing:
                raise ValueError(
                    f"{path.name} is missing tracking arrays: {sorted(missing)}"
                )
            sequence_id = (
                str(archive["sequence_id"].item())
                if "sequence_id" in archive.files
                else path.stem
            )
            model_hz = (
                int(archive["model_hz"].item())
                if "model_hz" in archive.files
                else 5
            )
            skeleton_hz = (
                int(archive["skeleton_hz"].item())
                if "skeleton_hz" in archive.files
                else 30
            )
            game_date = (
                date.fromisoformat(str(archive["game_date"].item()))
                if "game_date" in archive.files
                else None
            )
            return TrackingSequence(
                sequence_id=sequence_id,
                player_ids=archive["player_ids"],
                team_indices=archive["team_indices"],
                possession_team_index=int(
                    archive["possession_team_index"].item()
                ),
                positions_5hz=archive["positions_5hz"],
                ball_positions_5hz=archive["ball_positions_5hz"],
                skeletons_30hz=archive["skeletons_30hz"],
                shoulder_normals_5hz=archive["shoulder_normals_5hz"],
                event_labels_5hz=archive["event_labels_5hz"],
                context_features=archive["context_features"],
                model_hz=model_hz,
                skeleton_hz=skeleton_hz,
                game_date=game_date,
            )
