"""Vercel entry point for the complete NBA Sim web application."""

from __future__ import annotations

import re
import secrets
import shutil
import sys
import threading
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from nba_sim.franchise.cloud_repository import (  # noqa: E402
    BlobBackedFranchiseSaveRepository,
)
from nba_sim.web import DashboardService, _handler  # noqa: E402


RUNTIME_DIRECTORY = Path("/tmp/nba-sim-vercel")
SEED_DIRECTORY = PROJECT_ROOT / "deploy_data"
BASE_DATABASE = SEED_DIRECTORY / "nba_universe.db"
BASE_WAREHOUSE = SEED_DIRECTORY / "nba_sim.sqlite"
RUNTIME_DIRECTORY.mkdir(parents=True, exist_ok=True)

_SESSION_PATTERN = re.compile(r"^[a-f0-9]{32}$")
_SERVICES: dict[str, DashboardService] = {}
_SERVICES_LOCK = threading.RLock()


def _request_path(raw_path: str) -> str:
    parsed = urlparse(raw_path)
    rewritten = parse_qs(parsed.query).get("route")
    if rewritten:
        return f"/api/{rewritten[0].lstrip('/')}"
    if parsed.path in {"/api", "/api/", "/api/index", "/api/index.py"}:
        return "/api/metadata"
    return parsed.path


def _session_id(request) -> str:  # type: ignore[no-untyped-def]
    cookies = SimpleCookie()
    cookies.load(request.headers.get("Cookie", ""))
    morsel = cookies.get("nba_sim_session")
    value = morsel.value if morsel is not None else ""
    if not _SESSION_PATTERN.fullmatch(value):
        value = secrets.token_hex(16)
        request.new_session_cookie = True
    request.nba_sim_session = value
    return value


def _service_for_request(request) -> DashboardService:  # type: ignore[no-untyped-def]
    session_id = _session_id(request)
    with _SERVICES_LOCK:
        cached = _SERVICES.get(session_id)
        if cached is not None:
            return cached
        session_directory = RUNTIME_DIRECTORY / session_id
        session_directory.mkdir(parents=True, exist_ok=True)
        warehouse = session_directory / "warehouse.sqlite"
        if not warehouse.exists():
            shutil.copy2(BASE_WAREHOUSE, warehouse)
        franchise_repository = BlobBackedFranchiseSaveRepository(
            session_directory / "franchise_saves.sqlite",
            blob_pathname=f"franchise-sessions/{session_id}.sqlite",
        )
        service = DashboardService(
            BASE_DATABASE,
            warehouse_path=warehouse,
            deployment_mode="vercel-full",
            matchup_trial_limit=1_000,
            franchise_repository=franchise_repository,
        )
        _SERVICES[session_id] = service
        while len(_SERVICES) > 64:
            _SERVICES.pop(next(iter(_SERVICES)))
        return service


BaseDashboardHandler = _handler(_service_for_request)


class handler(BaseDashboardHandler):
    """Serve every dashboard API with an anonymous private save namespace."""

    new_session_cookie = False
    nba_sim_session = ""

    def send_response(self, code: int, message: str | None = None) -> None:
        super().send_response(code, message)
        if self.new_session_cookie and self.nba_sim_session:
            self.send_header(
                "Set-Cookie",
                (
                    f"nba_sim_session={self.nba_sim_session}; Path=/; "
                    "Max-Age=31536000; Secure; HttpOnly; SameSite=Lax"
                ),
            )

    def do_GET(self) -> None:
        self.path = _request_path(self.path)
        super().do_GET()

    def do_POST(self) -> None:
        self.path = _request_path(self.path)
        super().do_POST()
