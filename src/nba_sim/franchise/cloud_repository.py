from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from nba_sim.franchise.repository import FranchiseSaveRepository


_BLOB_API = "https://blob.vercel-storage.com"


class BlobBackedFranchiseSaveRepository(FranchiseSaveRepository):
    """SQLite event store mirrored to a private Vercel Blob object.

    SQLite remains the canonical transactional implementation. The private blob
    is a durable checkpoint used to restore an anonymous browser's database when
    a serverless instance starts cold.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        blob_pathname: str,
        token: str | None = None,
    ) -> None:
        self.blob_pathname = blob_pathname
        self.token = token or os.environ.get("BLOB_READ_WRITE_TOKEN", "")
        destination = Path(path)
        if self.token and not destination.exists():
            self._restore(destination)
        super().__init__(destination)

    @property
    def cloud_enabled(self) -> bool:
        return bool(self.token)

    def create_save(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        loaded = super().create_save(*args, **kwargs)
        self._checkpoint()
        return loaded

    def append_event(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        loaded = super().append_event(*args, **kwargs)
        self._checkpoint()
        return loaded

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "x-api-version": "12",
        }

    def _restore(self, destination: Path) -> None:
        query = urlencode({"prefix": self.blob_pathname, "limit": "1"})
        request = Request(f"{_BLOB_API}?{query}", headers=self._headers())
        try:
            with urlopen(request, timeout=15) as response:
                listing = json.load(response)
        except HTTPError as error:
            if error.code == 404:
                return
            raise RuntimeError("could not read the private franchise store") from error
        blobs = listing.get("blobs", [])
        exact = next(
            (item for item in blobs if item.get("pathname") == self.blob_pathname),
            None,
        )
        if exact is None:
            return
        download_url = exact.get("downloadUrl") or exact.get("url")
        if not download_url:
            return
        download = Request(str(download_url), headers=self._headers())
        destination.parent.mkdir(parents=True, exist_ok=True)
        with urlopen(download, timeout=30) as response:
            destination.write_bytes(response.read())

    def _checkpoint(self) -> None:
        if not self.token:
            return
        with sqlite3.connect(self.path) as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        content = self.path.read_bytes()
        query = urlencode({"pathname": self.blob_pathname})
        headers = {
            **self._headers(),
            "x-vercel-blob-access": "private",
            "x-content-type": "application/vnd.sqlite3",
            "x-cache-control-max-age": "0",
            "x-allow-overwrite": "1",
            "Content-Type": "application/octet-stream",
        }
        request = Request(
            f"{_BLOB_API}/?{query}",
            data=content,
            headers=headers,
            method="PUT",
        )
        try:
            with urlopen(request, timeout=30) as response:
                response.read()
        except HTTPError as error:
            raise RuntimeError("could not persist the private franchise store") from error
