from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class SnapshotManifest:
    source: str
    dataset: str
    season: str
    retrieved_at: datetime
    available_at: datetime
    schema_version: str
    sha256: str
    byte_size: int
    record_count: int | None = None
    rights_tier: str = "public"

    def __post_init__(self) -> None:
        if not self.source or not self.dataset or not self.schema_version:
            raise ValueError("source, dataset, and schema_version are required")
        object.__setattr__(
            self,
            "retrieved_at",
            _utc(self.retrieved_at, "retrieved_at"),
        )
        object.__setattr__(
            self,
            "available_at",
            _utc(self.available_at, "available_at"),
        )
        if len(self.sha256) != 64:
            raise ValueError("sha256 must be a 64-character digest")
        if self.byte_size < 0:
            raise ValueError("byte_size cannot be negative")
        if self.record_count is not None and self.record_count < 0:
            raise ValueError("record_count cannot be negative")

    def assert_available_as_of(self, cutoff: datetime) -> None:
        cutoff = _utc(cutoff, "cutoff")
        if self.available_at > cutoff:
            raise ValueError(
                f"{self.dataset} was available at {self.available_at.isoformat()}, "
                f"after forecast cutoff {cutoff.isoformat()}"
            )

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["retrieved_at"] = self.retrieved_at.isoformat()
        result["available_at"] = self.available_at.isoformat()
        return result

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SnapshotManifest":
        payload = dict(value)
        payload["retrieved_at"] = datetime.fromisoformat(payload["retrieved_at"])
        payload["available_at"] = datetime.fromisoformat(payload["available_at"])
        return cls(**payload)


@dataclass(frozen=True)
class Snapshot:
    data_path: Path
    manifest_path: Path
    manifest: SnapshotManifest


class SnapshotSource(Protocol):
    name: str

    def fetch(self, *, as_of: datetime) -> tuple[bytes, dict[str, Any]]:
        ...


class RawSnapshotStore:
    """Content-verified, atomic raw snapshot storage."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def write_bytes(
        self,
        relative_path: str | Path,
        payload: bytes,
        *,
        source: str,
        dataset: str,
        season: str,
        retrieved_at: datetime,
        available_at: datetime,
        schema_version: str,
        record_count: int | None = None,
        rights_tier: str = "public",
    ) -> Snapshot:
        target = self._safe_path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        checksum = hashlib.sha256(payload).hexdigest()
        manifest = SnapshotManifest(
            source=source,
            dataset=dataset,
            season=season,
            retrieved_at=retrieved_at,
            available_at=available_at,
            schema_version=schema_version,
            sha256=checksum,
            byte_size=len(payload),
            record_count=record_count,
            rights_tier=rights_tier,
        )
        manifest_path = target.with_suffix(target.suffix + ".manifest.json")
        self._atomic_write(target, payload)
        manifest_payload = json.dumps(
            manifest.as_dict(),
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        self._atomic_write(manifest_path, manifest_payload)
        return Snapshot(target, manifest_path, manifest)

    def write_json(
        self,
        relative_path: str | Path,
        records: Any,
        **metadata: Any,
    ) -> Snapshot:
        payload = json.dumps(
            records,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if "record_count" not in metadata and isinstance(records, list):
            metadata["record_count"] = len(records)
        return self.write_bytes(relative_path, payload, **metadata)

    def load(self, relative_path: str | Path) -> Snapshot:
        target = self._safe_path(relative_path)
        manifest_path = target.with_suffix(target.suffix + ".manifest.json")
        with manifest_path.open(encoding="utf-8") as handle:
            manifest = SnapshotManifest.from_dict(json.load(handle))
        snapshot = Snapshot(target, manifest_path, manifest)
        self.verify(snapshot)
        return snapshot

    @staticmethod
    def verify(snapshot: Snapshot) -> None:
        payload = snapshot.data_path.read_bytes()
        checksum = hashlib.sha256(payload).hexdigest()
        if checksum != snapshot.manifest.sha256:
            raise ValueError(f"checksum mismatch for {snapshot.data_path}")
        if len(payload) != snapshot.manifest.byte_size:
            raise ValueError(f"byte-size mismatch for {snapshot.data_path}")

    def _safe_path(self, relative_path: str | Path) -> Path:
        relative = Path(relative_path)
        if relative.is_absolute():
            raise ValueError("snapshot path must be relative")
        target = (self.root / relative).resolve()
        if self.root != target and self.root not in target.parents:
            raise ValueError("snapshot path escapes the configured root")
        return target

    @staticmethod
    def _atomic_write(target: Path, payload: bytes) -> None:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            dir=target.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()
