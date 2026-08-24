"""Vercel entry point for the bounded public Matchup Lab demo."""

from __future__ import annotations

import sys
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs, urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from nba_sim.demo import build_demo_database  # noqa: E402
from nba_sim.web import DashboardService, _handler  # noqa: E402


RUNTIME_DIRECTORY = Path("/tmp/nba-sim-vercel")
RUNTIME_DIRECTORY.mkdir(parents=True, exist_ok=True)
DEMO_DATABASE = RUNTIME_DIRECTORY / "fictional-demo.sqlite"
if not DEMO_DATABASE.exists():
    build_demo_database(DEMO_DATABASE)

SERVICE = DashboardService(
    DEMO_DATABASE,
    warehouse_path=RUNTIME_DIRECTORY / "warehouse.sqlite",
    deployment_mode="vercel-demo",
    matchup_trial_limit=25,
)
BaseDashboardHandler = _handler(SERVICE)


def _request_path(raw_path: str) -> str:
    """Recover the public API path after Vercel's catch-all rewrite."""

    parsed = urlparse(raw_path)
    rewritten = parse_qs(parsed.query).get("route")
    if rewritten:
        return f"/api/{rewritten[0].lstrip('/')}"
    if parsed.path in {"/api", "/api/", "/api/index", "/api/index.py"}:
        return "/api/metadata"
    return parsed.path


class handler(BaseDashboardHandler):
    """Expose only stateless, bounded operations in the public deployment."""

    def do_GET(self) -> None:
        public_path = _request_path(self.path)
        if public_path != "/api/metadata":
            self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return
        self.path = public_path
        super().do_GET()

    def do_POST(self) -> None:
        public_path = _request_path(self.path)
        if public_path != "/api/matchup":
            self._json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {
                    "error": (
                        "The hosted demo supports Matchup Lab only. "
                        "Run the repository locally for persistent league, "
                        "franchise, competition, and validation workspaces."
                    )
                },
            )
            return
        self.path = public_path
        super().do_POST()
