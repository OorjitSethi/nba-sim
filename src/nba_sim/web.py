from __future__ import annotations

import argparse
import copy
import json
import mimetypes
import re
import secrets
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

from nba_sim.competition.season import (
    PlayoffSeriesSimulator,
    SeasonSimulator,
    round_robin_schedule,
)
from nba_sim.competition.league import (
    DetailedLeagueSeasonSimulator,
    LeagueScheduledGame,
    LeagueSimulationCancelled,
    LeagueSeasonResult,
    nba_regular_season_schedule,
)
from nba_sim.data.legacy import LegacySQLiteRepository
from nba_sim.data.current_profiles import CurrentRosterProfileRepository
from nba_sim.data.official_nba import OfficialNBAStatsIngestor
from nba_sim.data.point_in_time import (
    HistoricalGame,
    PointInTimeWarehouse,
    ScheduledGame,
)
from nba_sim.data.provenance import RawSnapshotStore
from nba_sim.domain.profiles import TeamProfile
from nba_sim.domain.scenarios import condition_team_profile
from nba_sim.forecast.game_day import (
    resolve_game_availability,
    simulate_calibrated_availability,
)
from nba_sim.forecast.game_context import (
    ScheduleContextModel,
    context_for_scheduled_game,
)
from nba_sim.forecast.distributions import GameDistribution
from nba_sim.forecast.macro import HeuristicMacroModel
from nba_sim.forecast.reconcile import MomentReconciler
from nba_sim.simulation.game import GameSimulator
from nba_sim.simulation.monte_carlo import run_monte_carlo, simulate_ensemble
from nba_sim.validation.fidelity import (
    FidelityGate,
    evaluate_legacy_league_fidelity,
)
from nba_sim.validation.backtest import (
    CalibratedDynamicTeamModel,
    default_backtester,
)
from nba_sim.forecast.ratings import GameObservation
from nba_sim.franchise.bootstrap import build_current_league_state
from nba_sim.franchise.cba import (
    CBA_2026_27,
    TransactionAction,
    evaluate_transaction,
    team_cap_sheet,
)
from nba_sim.franchise.events import LeagueEventType
from nba_sim.franchise.lifecycle import (
    LIFECYCLE_MODEL_VERSION,
    LifecycleProjectionConfig,
    build_lifecycle_record,
    project_lifecycle,
)
from nba_sim.franchise.health import (
    HEALTH_MODEL_VERSION,
    apply_workload,
    availability_policy,
    build_health_record,
    update_health_status,
)
from nba_sim.franchise.chemistry import (
    CHEMISTRY_MODEL_VERSION,
    apply_team_environment,
    default_coaching_profile,
    default_team_chemistry,
    record_shared_session,
)
from nba_sim.franchise.models import (
    CoachingProfileRecord,
    PlayerRecord,
    TeamChemistryRecord,
    TransactionRecord,
)
from nba_sim.franchise.models import ScoutingDepartmentRecord
from nba_sim.franchise.scouting import (
    SCOUTING_MODEL_VERSION,
    build_initial_scouting_report,
    default_scouting_department,
    report_summary,
    run_automatic_scouting_cycle,
    scout_player,
)
from nba_sim.franchise.ratings import (
    RatingInput,
    build_league_ratings,
    lifecycle_composites,
)
from nba_sim.franchise.draft import (
    DRAFT_MODEL_VERSION,
    draft_response,
    generate_draft_ecosystem,
    make_next_pick,
    run_321_lottery,
    run_draft_combine,
    scout_prospect,
    set_user_board,
)
from nba_sim.franchise.trading import (
    TRADE_MODEL_VERSION,
    TradeRulePolicy,
    TradeTeamPackage,
    deterministic_trade_id,
    ensure_future_draft_assets,
    evaluate_trade,
    propose_ai_trades,
    rule_coverage,
    trade_board_response,
)
from nba_sim.franchise.repository import (
    FranchiseSaveRepository,
    LoadedFranchise,
)


_ASSET_DIRECTORY = Path(__file__).with_name("web_assets")
_ASSETS = {
    "/": "index.html",
    "/index.html": "index.html",
    "/app.js": "app.js",
    "/styles.css": "styles.css",
}


@dataclass
class LeagueSimulationJob:
    job_id: str
    seed: int
    start_date: date
    end_date: date
    trials_per_game: int
    total_games: int = 1_230
    status: str = "preparing"
    completed_games: int = 0
    current_trial: int = 0
    current_game_id: str | None = None
    current_game_date: date | None = None
    current_home_team: str | None = None
    current_away_team: str | None = None
    cancel_requested: bool = False
    error: str | None = None
    result: dict[str, object] | None = None
    started_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    started_monotonic: float = field(default_factory=time.monotonic)
    finished_monotonic: float | None = None


class DashboardService:
    """Small application layer shared by the local HTTP API and tests."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        warehouse_path: str | Path | None = None,
        deployment_mode: str = "local",
        matchup_trial_limit: int = 10_000,
    ) -> None:
        if matchup_trial_limit < 25:
            raise ValueError("matchup_trial_limit must be at least 25")
        self.database_path = Path(database_path)
        self.deployment_mode = deployment_mode
        self.matchup_trial_limit = matchup_trial_limit
        self.repository = LegacySQLiteRepository(self.database_path)
        self.warehouse = PointInTimeWarehouse(
            warehouse_path or Path.cwd() / "data" / "nba_sim.sqlite"
        )
        self.profile_repository = CurrentRosterProfileRepository(
            legacy=self.repository,
            warehouse=self.warehouse,
        )
        self._team_cache: dict[str, TeamProfile] = {}
        self._historical_games: tuple[HistoricalGame, ...] | None = None
        self._team_strength_model: CalibratedDynamicTeamModel | None = None
        self._context_model: ScheduleContextModel | None = None
        self._league_seasons: dict[str, LeagueSeasonResult] = {}
        self._league_jobs: dict[str, LeagueSimulationJob] = {}
        self._league_job_lock = threading.RLock()
        self.franchise_repository = FranchiseSaveRepository(
            self.warehouse.path.parent / "franchise_saves.sqlite"
        )

    def metadata(self) -> dict[str, object]:
        teams = []
        for abbreviation in self.profile_repository.available_teams():
            team = self._team(abbreviation)
            rotation_ids = {player.player_id for player in team.rotation}
            teams.append(
                {
                    "abbreviation": team.abbreviation,
                    "name": team.name,
                    "pace": team.pace,
                    "roster": [
                        {
                            "player_id": player.player_id,
                            "name": player.name,
                            "position": player.position,
                            "expected_minutes": round(
                                player.expected_minutes,
                                2,
                            ),
                            "profile_source": (
                                self.profile_repository.profile_source(
                                    player.player_id
                                )
                            ),
                            "modeled_rotation": player.player_id in rotation_ids,
                        }
                        for player in sorted(
                            team.roster,
                            key=lambda item: item.expected_minutes,
                            reverse=True,
                        )
                    ],
                }
            )
        return {
            "teams": teams,
            "defaults": {
                "home": "UTA" if "UTA" in self._team_cache else teams[0]["abbreviation"],
                "away": "MEM" if "MEM" in self._team_cache else teams[1]["abbreviation"],
                "seed": 7,
                "trials": min(100, self.matchup_trial_limit),
            },
            "deployment": {
                "mode": self.deployment_mode,
                "matchup_trial_limit": self.matchup_trial_limit,
                "persistent_storage": self.deployment_mode == "local",
            },
            "data_season": (
                f"{self.profile_repository.season} roster"
                if self.profile_repository.season
                else "2023-24 legacy"
            ),
            "attribute_season": (
                f"{self.profile_repository.stat_season} official stats"
                if self.profile_repository.stat_season
                else "2023-24 priors"
            ),
            "roster_season": self.profile_repository.season,
            "profile_coverage": {
                "official": sum(
                    player["profile_source"].startswith("official-")
                    for team in teams
                    for player in team["roster"]
                ),
                "historical": sum(
                    player["profile_source"].startswith("historical-")
                    for team in teams
                    for player in team["roster"]
                ),
                "replacement_prior": sum(
                    player["profile_source"] == "replacement-prior"
                    for team in teams
                    for player in team["roster"]
                ),
                "total": sum(len(team["roster"]) for team in teams),
            },
            "snapshot_inventory": self.warehouse.snapshot_inventory(),
            "game_day": self.game_day(),
        }

    def game_day(
        self,
        *,
        season: str = "2026-27",
        cutoff: datetime | None = None,
    ) -> dict[str, object]:
        known_at = (cutoff or datetime.now(timezone.utc)).astimezone(
            timezone.utc
        )
        games = self.warehouse.schedule_as_of(
            season=season,
            cutoff=known_at,
            start_date=known_at.date(),
        )
        latest = self.warehouse.latest_snapshot(
            dataset="schedule",
            season=season,
            cutoff=known_at,
        )
        historical = self._history()
        self._ensure_game_day_models()
        context_validation = (
            self._context_model.validation.as_dict()
            if self._context_model is not None
            and self._context_model.validation is not None
            else None
        )
        injury_cache: dict[date, tuple[object, ...]] = {}
        serialized_games: list[dict[str, object]] = []
        matched_reports = 0
        for game in games:
            availability = ()
            if game.teams_identified:
                observations = injury_cache.setdefault(
                    game.game_date,
                    self.warehouse.injuries_as_of(
                        game_date=game.game_date,
                        cutoff=known_at,
                    ),
                )
                availability = resolve_game_availability(
                    game=game,
                    home_team=self._team(str(game.home_team)),
                    away_team=self._team(str(game.away_team)),
                    observations=observations,
                )
                matched_reports += len(availability)
            game_payload = _scheduled_game_dict(game)
            game_payload["availability"] = [
                row.as_dict() for row in availability
            ]
            if game.teams_identified:
                schedule_context = context_for_scheduled_game(
                    game,
                    historical_games=historical,
                    season_schedule=games,
                )
                game_payload["schedule_context"] = schedule_context.as_dict()
                game_payload["context_adjustment"] = (
                    self._context_model.adjustment(
                        schedule_context,
                        deployed_home_court_points=1.5,
                    )
                    if self._context_model is not None
                    else None
                )
            serialized_games.append(game_payload)

        preseason = sum(
            "preseason" in game.game_label.lower() for game in games
        )
        regular_season = sum(
            "regular season" in game.game_label.lower() for game in games
        )
        identified = sum(game.teams_identified for game in games)
        if regular_season >= 1_200:
            release_state = "complete"
        elif regular_season:
            release_state = "partial"
        elif preseason:
            release_state = "preseason_only"
        elif games:
            release_state = "announced_events_only"
        else:
            release_state = "not_available"
        return {
            "season": season,
            "known_at": known_at.isoformat(),
            "release_state": release_state,
            "full_regular_season_available": release_state == "complete",
            "counts": {
                "published": len(games),
                "identified": identified,
                "preseason": preseason,
                "regular_season": regular_season,
                "placeholders": len(games) - identified,
                "injury_rows": matched_reports,
            },
            "latest_snapshot": latest,
            "context_validation": context_validation,
            "games": serialized_games,
        }

    def sync_schedule(self, payload: Mapping[str, Any]) -> dict[str, object]:
        season = str(payload.get("season", "2026-27")).strip()
        if not re_full_season(season):
            raise ValueError("season must use YYYY-YY")
        result = OfficialNBAStatsIngestor(
            snapshots=RawSnapshotStore(self.warehouse.path.parent / "raw"),
            warehouse=self.warehouse,
        ).sync_schedule(season=season, timeout=45)
        return {
            "sync": result.__dict__,
            "game_day": self.game_day(season=season),
        }

    def run_game_day(self, payload: Mapping[str, Any]) -> dict[str, object]:
        game_id = str(payload.get("game_id", "")).strip()
        if not game_id:
            raise ValueError("game_id is required")
        cutoff = datetime.now(timezone.utc)
        game = self.warehouse.scheduled_game_as_of(
            game_id=game_id,
            cutoff=cutoff,
        )
        if game is None:
            raise KeyError(f"unknown scheduled game: {game_id}")
        if not game.teams_identified:
            raise ValueError("this schedule entry does not have teams yet")
        home = self._team(str(game.home_team))
        away = self._team(str(game.away_team))
        self._ensure_game_day_models()
        if self._team_strength_model is None:
            raise ValueError("historical team-strength model is unavailable")
        schedule = self.warehouse.schedule_as_of(
            season=game.season,
            cutoff=cutoff,
        )
        schedule_context = context_for_scheduled_game(
            game,
            historical_games=self._history(),
            season_schedule=schedule,
        )
        context_adjustment = (
            self._context_model.adjustment(
                schedule_context,
                deployed_home_court_points=1.5,
            )
            if self._context_model is not None
            else {
                "margin_points": -1.5 if game.neutral_site else 0.0,
                "structural_neutral_correction": (
                    -1.5 if game.neutral_site else 0.0
                ),
                "learned_increment": 0.0,
                "learned_increment_applied": False,
                "promotion_passed": False,
            }
        )
        dynamic = self._team_strength_model.predict(
            home_team=home,
            away_team=away,
        )
        base_distribution = GameDistribution(
            home_team=dynamic.home_team,
            away_team=dynamic.away_team,
            mean_margin=(
                dynamic.mean_margin
                + float(context_adjustment["margin_points"])
            ),
            margin_standard_deviation=dynamic.margin_standard_deviation,
            mean_total=dynamic.mean_total,
            total_standard_deviation=dynamic.total_standard_deviation,
            margin_total_correlation=dynamic.margin_total_correlation,
            model_name=f"{dynamic.model_name}+schedule-context-gate",
            model_version=f"{dynamic.model_version}+1.0.0",
        )
        availability = resolve_game_availability(
            game=game,
            home_team=home,
            away_team=away,
            observations=self.warehouse.injuries_as_of(
                game_date=game.game_date,
                cutoff=cutoff,
            ),
        )
        forecast = simulate_calibrated_availability(
            home_team=home,
            away_team=away,
            availability=availability,
            base_distribution=base_distribution,
            trials=_integer(
                payload,
                "trials",
                default=1_000,
                minimum=100,
                maximum=20_000,
            ),
            seed=_seed(payload),
        ).as_dict()
        forecast["scheduled_game"] = _scheduled_game_dict(game)
        forecast["schedule_context"] = schedule_context.as_dict()
        forecast["context_adjustment"] = context_adjustment
        forecast["context_validation"] = (
            self._context_model.validation.as_dict()
            if self._context_model is not None
            and self._context_model.validation is not None
            else None
        )
        return forecast

    def run_matchup(self, payload: Mapping[str, Any]) -> dict[str, object]:
        mode = str(payload.get("mode", "single"))
        simulator = self._simulator(payload)
        seed = _seed(payload)

        if mode == "single":
            result = simulator.simulate(seed=seed)
            response = result.as_dict(
                include_events=bool(payload.get("include_events", True))
            )
            response["kind"] = "single"
            return response

        trials = _integer(
            payload,
            "trials",
            default=100,
            minimum=25 if mode == "hybrid" else 1,
            maximum=self.matchup_trial_limit,
        )
        workers = _integer(payload, "workers", default=1, minimum=0, maximum=16)
        if mode == "monte_carlo":
            response = run_monte_carlo(
                simulator,
                trials=trials,
                seed=seed,
                workers=workers,
            ).as_dict()
            response["kind"] = "monte_carlo"
            return response
        if mode == "hybrid":
            target = HeuristicMacroModel().predict(
                home_team=simulator.home_team,
                away_team=simulator.away_team,
            )
            results = simulate_ensemble(
                simulator,
                trials=trials,
                seed=seed,
                workers=workers,
            )
            response = MomentReconciler().reconcile(results, target).as_dict()
            response.update(
                {
                    "kind": "hybrid",
                    "home_team": simulator.home_team.abbreviation,
                    "away_team": simulator.away_team.abbreviation,
                    "seed": seed,
                }
            )
            return response
        raise ValueError("mode must be single, monte_carlo, or hybrid")

    def run_season(self, payload: Mapping[str, Any]) -> dict[str, object]:
        abbreviations = _team_list(payload.get("teams"))
        if not 2 <= len(abbreviations) <= 30:
            raise ValueError("season requires between 2 and 30 unique teams")
        teams = {abbreviation: self._team(abbreviation) for abbreviation in abbreviations}
        repeats = _integer(payload, "repeats", default=2, minimum=1, maximum=4)
        seed = _seed(payload)
        try:
            start = date.fromisoformat(str(payload.get("start_date", "2026-10-20")))
        except ValueError as error:
            raise ValueError("start_date must use YYYY-MM-DD") from error
        schedule = round_robin_schedule(
            abbreviations,
            start_date=start,
            repeats=repeats,
        )
        result = SeasonSimulator(teams=teams, schedule=schedule).simulate(seed=seed)
        response = result.as_dict(include_games=bool(payload.get("include_games", True)))
        response["kind"] = "season"
        return response

    def run_series(self, payload: Mapping[str, Any]) -> dict[str, object]:
        higher = str(payload.get("higher_seed", "")).upper()
        lower = str(payload.get("lower_seed", "")).upper()
        best_of = _integer(payload, "best_of", default=7, minimum=1, maximum=9)
        seed = _seed(payload)
        result = PlayoffSeriesSimulator(
            higher_seed=self._team(higher),
            lower_seed=self._team(lower),
            best_of=best_of,
        ).simulate(seed=seed)
        response = result.as_dict()
        response["kind"] = "series"
        return response

    def run_league_season(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        """Backward-compatible alias for the asynchronous detailed job."""
        return self.start_league_season(payload)

    def start_league_season(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        seed = _seed(payload)
        try:
            start = date.fromisoformat(
                str(payload.get("start_date", "2026-10-20"))
            )
            end = date.fromisoformat(
                str(payload.get("end_date", "2027-04-12"))
            )
        except ValueError as error:
            raise ValueError("league season dates must use YYYY-MM-DD") from error
        if end <= start:
            raise ValueError("league season end must follow its start")
        with self._league_job_lock:
            active = next(
                (
                    job
                    for job in self._league_jobs.values()
                    if job.status in {"preparing", "running", "cancelling"}
                ),
                None,
            )
            if active is not None:
                response = self._league_job_snapshot(active)
                response["reused"] = True
                return response
            job = LeagueSimulationJob(
                job_id=f"league-{secrets.token_hex(8)}",
                seed=seed,
                start_date=start,
                end_date=end,
                trials_per_game=1,
            )
            self._league_jobs[job.job_id] = job
            completed_jobs = [
                candidate
                for candidate in self._league_jobs.values()
                if candidate.status in {"completed", "cancelled", "failed"}
            ]
            for stale in completed_jobs[:-4]:
                self._league_jobs.pop(stale.job_id, None)

        thread = threading.Thread(
            target=self._run_league_job,
            args=(job.job_id,),
            name=f"nba-sim-{job.job_id}",
            daemon=True,
        )
        thread.start()
        return self._league_job_snapshot(job)

    def league_season_progress(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        job = self._league_job(payload)
        return self._league_job_snapshot(job, include_result=True)

    def cancel_league_season(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        job = self._league_job(payload)
        with self._league_job_lock:
            if job.status in {"preparing", "running"}:
                job.cancel_requested = True
                job.status = "cancelling"
        return self._league_job_snapshot(job)

    def _league_job(
        self,
        payload: Mapping[str, Any],
    ) -> LeagueSimulationJob:
        job_id = str(payload.get("job_id", "")).strip()
        if not job_id:
            raise ValueError("job_id is required")
        with self._league_job_lock:
            job = self._league_jobs.get(job_id)
        if job is None:
            raise KeyError("league simulation job is no longer loaded")
        return job

    def _run_league_job(self, job_id: str) -> None:
        with self._league_job_lock:
            job = self._league_jobs[job_id]
        try:
            self._ensure_game_day_models()
            if self._team_strength_model is None:
                raise ValueError("historical team-strength model is unavailable")
            if job.cancel_requested:
                raise LeagueSimulationCancelled("league simulation cancelled")
            teams = {
                abbreviation: self._team(abbreviation)
                for abbreviation in self.profile_repository.available_teams()
            }
            schedule = nba_regular_season_schedule(
                start_date=job.start_date,
                end_date=job.end_date,
                seed=2026,
            )
            with self._league_job_lock:
                job.status = "running"
                job.total_games = len(schedule)

            def update_progress(
                completed_games: int,
                total_games: int,
                current_trial: int,
                trials_per_game: int,
                scheduled: LeagueScheduledGame,
            ) -> None:
                with self._league_job_lock:
                    job.completed_games = completed_games
                    job.total_games = total_games
                    job.current_trial = current_trial
                    job.trials_per_game = trials_per_game
                    job.current_game_id = scheduled.game_id
                    job.current_game_date = scheduled.game_date
                    job.current_home_team = scheduled.home_team
                    job.current_away_team = scheduled.away_team

            result = DetailedLeagueSeasonSimulator(
                teams=teams,
                schedule=schedule,
                forecast_model=copy.deepcopy(self._team_strength_model),
            ).simulate(
                seed=job.seed,
                progress=update_progress,
                cancelled=lambda: job.cancel_requested,
            )
            season_id = f"league-2026-27-{job.seed}"
            response = result.as_dict()
            response.update(
                {
                    "kind": "league_season",
                    "season_id": season_id,
                    "season": "2026-27",
                    "box_scores_available": len(result.games),
                    "trials_per_game": job.trials_per_game,
                    "simulation_method": (
                        "one untouched event-level possession simulation per "
                        "matchup with chronological forecast context"
                    ),
                }
            )
            with self._league_job_lock:
                self._league_seasons[season_id] = result
                while len(self._league_seasons) > 3:
                    oldest = next(iter(self._league_seasons))
                    del self._league_seasons[oldest]
                job.completed_games = len(result.games)
                job.current_trial = 0
                job.status = "completed"
                job.result = response
                job.finished_monotonic = time.monotonic()
        except LeagueSimulationCancelled:
            with self._league_job_lock:
                job.status = "cancelled"
                job.finished_monotonic = time.monotonic()
        except Exception as error:
            with self._league_job_lock:
                job.status = "failed"
                job.error = f"{type(error).__name__}: {error}"
                job.finished_monotonic = time.monotonic()

    def _league_job_snapshot(
        self,
        job: LeagueSimulationJob,
        *,
        include_result: bool = False,
    ) -> dict[str, object]:
        with self._league_job_lock:
            ended = job.finished_monotonic or time.monotonic()
            elapsed = max(0.0, ended - job.started_monotonic)
            completed_work = (
                job.completed_games * job.trials_per_game
                + (
                    job.current_trial
                    if job.completed_games < job.total_games
                    else 0
                )
            )
            total_work = job.total_games * job.trials_per_game
            progress = (
                min(1.0, completed_work / total_work)
                if total_work
                else 0.0
            )
            eta = (
                elapsed * (total_work - completed_work) / completed_work
                if completed_work >= 5 and job.status in {"running", "cancelling"}
                else None
            )
            response: dict[str, object] = {
                "kind": "league_simulation_job",
                "job_id": job.job_id,
                "status": job.status,
                "seed": job.seed,
                "started_at": job.started_at.isoformat(),
                "completed_games": job.completed_games,
                "total_games": job.total_games,
                "current_trial": job.current_trial,
                "trials_per_game": job.trials_per_game,
                "progress": round(progress, 6),
                "percent": round(progress * 100.0, 2),
                "elapsed_seconds": round(elapsed, 1),
                "eta_seconds": round(eta, 1) if eta is not None else None,
                "current_game": (
                    {
                        "game_id": job.current_game_id,
                        "date": (
                            job.current_game_date.isoformat()
                            if job.current_game_date is not None
                            else None
                        ),
                        "home_team": job.current_home_team,
                        "away_team": job.current_away_team,
                    }
                    if job.current_game_id is not None
                    else None
                ),
                "error": job.error,
            }
            if include_result and job.result is not None:
                response["result"] = job.result
            return response

    def league_game(self, payload: Mapping[str, Any]) -> dict[str, object]:
        season_id = str(payload.get("season_id", "")).strip()
        game_id = str(payload.get("game_id", "")).strip()
        if season_id not in self._league_seasons:
            raise KeyError("league season is no longer loaded; simulate it again")
        if not game_id:
            raise ValueError("game_id is required")
        for game in self._league_seasons[season_id].games:
            if game.scheduled.game_id == game_id:
                response = game.detail_dict()
                response["season_id"] = season_id
                response["kind"] = "league_game"
                return response
        raise KeyError(f"unknown league game: {game_id}")

    def franchise_saves(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        del payload
        saves = self.franchise_repository.list_saves()
        return {
            "kind": "franchise_saves",
            "saves": [save.as_dict() for save in saves],
            "count": len(saves),
        }

    def create_franchise(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        name = str(payload.get("name", "My Franchise")).strip()
        if not name or len(name) > 80:
            raise ValueError("franchise name must be between 1 and 80 characters")
        user_team = str(payload.get("user_team", "")).upper()
        state = build_current_league_state(
            self.profile_repository,
            league_name=name,
            user_team=user_team,
            seed=_seed(payload),
            as_of=date.today(),
        )
        loaded = self.franchise_repository.create_save(
            state,
            name=name,
            actor="user",
            event_payload={
                "season": state.season,
                "user_team": state.user_team,
                "roster_source": self.profile_repository.season
                or "legacy-2023-24",
            },
        )
        return self._franchise_response(loaded)

    def load_franchise(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        save_id = str(payload.get("save_id", "")).strip()
        if not save_id:
            raise ValueError("save_id is required")
        return self._franchise_response(
            self.franchise_repository.load(save_id)
        )

    def advance_franchise_date(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        save_id = str(payload.get("save_id", "")).strip()
        if not save_id:
            raise ValueError("save_id is required")
        days = _integer(payload, "days", default=1, minimum=1, maximum=30)
        loaded = self.franchise_repository.load(save_id)
        target = loaded.state.calendar.current_date + timedelta(days=days)
        if target > loaded.state.calendar.cap_year_end:
            target = loaded.state.calendar.cap_year_end
        if target == loaded.state.calendar.current_date:
            raise ValueError("this save is already at the end of the cap year")
        advanced = self.franchise_repository.append_event(
            save_id,
            event_type=LeagueEventType.DATE_ADVANCED,
            payload={
                "from_date": loaded.state.calendar.current_date.isoformat(),
                "to_date": target.isoformat(),
                "days": (target - loaded.state.calendar.current_date).days,
            },
            occurred_on=target,
            actor="user",
        )
        department = next(
            (
                item for item in advanced.state.scouting_departments
                if item.team == advanced.state.user_team
            ),
            None,
        )
        if department is not None and department.automation_enabled:
            cycle_origin = department.last_cycle_date or department.as_of_date
            if (target - cycle_origin).days >= 7:
                draft = advanced.state.draft_ecosystem
                if draft is not None and draft.status != "complete":
                    selected_ids = {item.player_id for item in draft.selections}
                    prospects = tuple(
                        item for item in draft.prospects
                        if item.player_id not in selected_ids
                    )
                    updated_department, reports = run_automatic_scouting_cycle(
                        department,
                        tuple(item.report for item in prospects),
                        tuple(
                            PlayerRecord(
                                player_id=item.player_id,
                                name=item.name,
                                team="DRAFT",
                                position=item.position,
                                roster_status="prospect",
                                expected_minutes=0.0,
                                profile_source="draft-class",
                            )
                            for item in prospects
                        ),
                        tuple(
                            item.lifecycle(advanced.state.season)
                            for item in prospects
                        ),
                        occurred_on=target,
                        seed=advanced.state.seed,
                    )
                    if reports:
                        report_by_id = {
                            item.player_id: item for item in reports
                        }
                        updated_draft = replace(
                            draft,
                            scouting_cycles=draft.scouting_cycles + 1,
                            prospects=tuple(
                                replace(
                                    item,
                                    report=report_by_id.get(
                                        item.player_id,
                                        item.report,
                                    ),
                                )
                                for item in draft.prospects
                            ),
                        )
                        advanced = self.franchise_repository.append_event(
                            save_id,
                            event_type=LeagueEventType.DRAFT_PROSPECT_SCOUTED,
                            payload={
                                "draft": updated_draft.as_dict(),
                                "department": updated_department.as_dict(),
                                "player_ids": sorted(report_by_id),
                                "automatic": True,
                            },
                            occurred_on=target,
                            actor="scouting-department",
                        )
                else:
                    updated_department, reports = run_automatic_scouting_cycle(
                        department,
                        advanced.state.scouting_reports,
                        advanced.state.players,
                        advanced.state.player_lifecycles,
                        occurred_on=target,
                        seed=advanced.state.seed,
                    )
                    if reports:
                        advanced = self.franchise_repository.append_event(
                            save_id,
                            event_type=LeagueEventType.SCOUTING_CYCLE_COMPLETED,
                            payload={
                                "department": updated_department.as_dict(),
                                "reports": [item.as_dict() for item in reports],
                                "targets": len(reports),
                                "automatic": True,
                            },
                            occurred_on=target,
                            actor="scouting-department",
                        )
        policy = advanced.state.trade_rule_policy
        if (
            days >= 7
            and policy is not None
            and policy.ai_to_ai_trades
        ):
            proposals = propose_ai_trades(
                advanced.state,
                policy=policy,
                max_deals=1,
            )
            for packages in proposals:
                advanced = self._commit_trade(
                    advanced,
                    packages,
                    source="cpu-market-auto",
                )
        return self._franchise_response(advanced)

    def branch_franchise(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        save_id = str(payload.get("save_id", "")).strip()
        branch_name = str(payload.get("branch_name", "")).strip()
        if not save_id:
            raise ValueError("save_id is required")
        if not branch_name or len(branch_name) > 80:
            raise ValueError("branch name must be between 1 and 80 characters")
        return self._franchise_response(
            self.franchise_repository.branch(
                save_id,
                branch_name=branch_name,
                actor="user",
            )
        )

    def initialize_draft_ecosystem(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        save_id = str(payload.get("save_id", "")).strip()
        if not save_id:
            raise ValueError("save_id is required")
        loaded = self.franchise_repository.load(save_id)
        if loaded.state.draft_ecosystem is not None:
            raise ValueError("draft ecosystem is already initialized")
        draft, assets = generate_draft_ecosystem(
            teams=(item.team for item in loaded.state.franchises),
            draft_year=2027,
            season=loaded.state.season,
            seed=_seed(payload),
            as_of=loaded.state.calendar.current_date,
        )
        updated = self.franchise_repository.append_event(
            save_id,
            event_type=LeagueEventType.DRAFT_ECOSYSTEM_INITIALIZED,
            payload={
                "draft": draft.as_dict(),
                "assets": [item.as_dict() for item in assets],
                "model_version": DRAFT_MODEL_VERSION,
            },
            actor="league-office",
        )
        return self._franchise_response(updated)

    def run_draft_lottery(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        loaded = self._draft_loaded(payload)
        state = loaded.state
        assert state.draft_ecosystem is not None
        ratings = self._league_rating_profiles(state)
        strengths: dict[str, float] = {}
        for franchise in state.franchises:
            roster = sorted(
                (
                    (
                        float(ratings[player.player_id]["overall"]),
                        player.expected_minutes,
                    )
                    for player in state.roster(franchise.team)
                    if player.player_id in ratings
                ),
                reverse=True,
            )[:8]
            strengths[franchise.team] = (
                sum(overall * max(8.0, minutes) for overall, minutes in roster)
                / max(1.0, sum(max(8.0, minutes) for _, minutes in roster))
            )
        draft = run_321_lottery(
            state.draft_ecosystem,
            team_strengths=strengths,
            assets=state.draft_assets,
            seed=_seed(payload),
        )
        updated = self.franchise_repository.append_event(
            loaded.metadata.save_id,
            event_type=LeagueEventType.DRAFT_LOTTERY_COMPLETED,
            payload={"draft": draft.as_dict(), "format": "2027-3-2-1"},
            actor="league-office",
        )
        return self._franchise_response(updated)

    def run_draft_combine(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        loaded = self._draft_loaded(payload)
        assert loaded.state.draft_ecosystem is not None
        draft = run_draft_combine(
            loaded.state.draft_ecosystem,
            occurred_on=loaded.state.calendar.current_date,
            seed=loaded.state.seed,
        )
        updated = self.franchise_repository.append_event(
            loaded.metadata.save_id,
            event_type=LeagueEventType.DRAFT_COMBINE_COMPLETED,
            payload={"draft": draft.as_dict()},
            actor="league-office",
        )
        return self._franchise_response(updated)

    def scout_draft_prospect(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        loaded = self._draft_loaded(payload)
        state = loaded.state
        assert state.draft_ecosystem is not None
        department = next(
            (
                item for item in state.scouting_departments
                if item.team == state.user_team
            ),
            None,
        )
        quality = department.evaluation_quality if department else 55.0
        player_id = _integer(payload, "player_id", default=0, minimum=1)
        hours = _bounded_float(
            payload, "hours", default=16, minimum=1, maximum=120
        )
        draft = scout_prospect(
            state.draft_ecosystem,
            player_id=player_id,
            hours=hours,
            evaluation_quality=quality,
            occurred_on=state.calendar.current_date,
            seed=state.seed,
            namespace=(
                f"draft-workout:{state.user_team}:{player_id}:"
                f"{state.revision + 1}"
            ),
        )
        updated = self.franchise_repository.append_event(
            loaded.metadata.save_id,
            event_type=LeagueEventType.DRAFT_PROSPECT_SCOUTED,
            payload={
                "draft": draft.as_dict(),
                "player_id": player_id,
                "hours": hours,
            },
            actor=state.user_team,
        )
        return self._franchise_response(updated)

    def update_draft_board(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        loaded = self._draft_loaded(payload)
        assert loaded.state.draft_ecosystem is not None
        values = payload.get("player_ids")
        if not isinstance(values, list):
            raise ValueError("player_ids must be a list")
        draft = set_user_board(loaded.state.draft_ecosystem, values)
        updated = self.franchise_repository.append_event(
            loaded.metadata.save_id,
            event_type=LeagueEventType.DRAFT_BOARD_UPDATED,
            payload={"draft": draft.as_dict()},
            actor=loaded.state.user_team,
        )
        return self._franchise_response(updated)

    def make_draft_pick(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        loaded = self._draft_loaded(payload)
        state = loaded.state
        assert state.draft_ecosystem is not None
        player_id = (
            int(payload["player_id"])
            if payload.get("player_id") is not None
            else None
        )
        draft = make_next_pick(
            state.draft_ecosystem,
            user_team=state.user_team,
            player_id=player_id,
            seed=state.seed,
        )
        selection = draft.selections[-1]
        updated = self.franchise_repository.append_event(
            loaded.metadata.save_id,
            event_type=LeagueEventType.DRAFT_PICK_MADE,
            payload={
                "draft": draft.as_dict(),
                "selection": selection.as_dict(),
            },
            actor=selection.team,
        )
        return self._franchise_response(updated)

    def simulate_to_user_draft_pick(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        loaded = self._draft_loaded(payload)
        state = loaded.state
        draft = state.draft_ecosystem
        assert draft is not None
        made = []
        while (
            draft.order
            and len(draft.selections) < len(draft.order)
            and draft.order[len(draft.selections)].current_team != state.user_team
        ):
            draft = make_next_pick(
                draft,
                user_team=state.user_team,
                player_id=None,
                seed=state.seed,
            )
            made.append(draft.selections[-1].as_dict())
        if not made:
            if draft.status == "complete":
                raise ValueError("the draft is complete")
            raise ValueError("your team is already on the clock")
        updated = self.franchise_repository.append_event(
            loaded.metadata.save_id,
            event_type=LeagueEventType.DRAFT_PICK_MADE,
            payload={"draft": draft.as_dict(), "selections": made},
            actor="cpu-general-managers",
        )
        return self._franchise_response(updated)

    def _draft_loaded(self, payload: Mapping[str, Any]) -> LoadedFranchise:
        save_id = str(payload.get("save_id", "")).strip()
        if not save_id:
            raise ValueError("save_id is required")
        loaded = self.franchise_repository.load(save_id)
        if loaded.state.draft_ecosystem is None:
            raise ValueError("initialize the draft ecosystem first")
        return loaded

    def initialize_trade_center(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        save_id = str(payload.get("save_id", "")).strip()
        if not save_id:
            raise ValueError("save_id is required")
        loaded = self.franchise_repository.load(save_id)
        if loaded.state.trade_rule_policy is not None:
            return self._franchise_response(loaded)
        policy = TradeRulePolicy()
        assets = ensure_future_draft_assets(loaded.state)
        updated = self.franchise_repository.append_event(
            save_id,
            event_type=LeagueEventType.TRADE_CENTER_INITIALIZED,
            payload={
                "policy": policy.as_dict(),
                "assets": [item.as_dict() for item in assets],
                "model_version": TRADE_MODEL_VERSION,
            },
            actor="league-office",
        )
        return self._franchise_response(updated)

    def franchise_trade_board(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        loaded = self._trade_loaded(payload)
        return {
            "kind": "franchise_trade_board",
            "save_id": loaded.metadata.save_id,
            **trade_board_response(loaded.state),
        }

    def update_trade_rules(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        loaded = self._trade_loaded(payload)
        assert loaded.state.trade_rule_policy is not None
        values = loaded.state.trade_rule_policy.as_dict()
        for key in values:
            if key in payload and key != "model_version":
                values[key] = payload[key]
        policy = TradeRulePolicy.from_dict(values)
        updated = self.franchise_repository.append_event(
            loaded.metadata.save_id,
            event_type=LeagueEventType.TRADE_RULE_POLICY_UPDATED,
            payload={"policy": policy.as_dict()},
            actor=loaded.state.user_team,
        )
        return self._franchise_response(updated)

    def evaluate_franchise_trade(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        loaded = self._trade_loaded(payload)
        assert loaded.state.trade_rule_policy is not None
        packages = _trade_packages(payload)
        return {
            "kind": "franchise_trade_evaluation",
            "evaluation": evaluate_trade(
                loaded.state,
                packages,
                policy=loaded.state.trade_rule_policy,
            ),
        }

    def execute_franchise_trade(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        loaded = self._trade_loaded(payload)
        packages = _trade_packages(payload)
        updated = self._commit_trade(
            loaded,
            packages,
            source="user-negotiated",
        )
        response = self._franchise_response(updated)
        response["trade_completed"] = updated.state.transactions[-1].as_dict()
        return response

    def run_ai_trade_market(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        loaded = self._trade_loaded(payload)
        assert loaded.state.trade_rule_policy is not None
        max_deals = _integer(payload, "max_deals", default=3, minimum=1, maximum=12)
        proposals = propose_ai_trades(
            loaded.state,
            policy=loaded.state.trade_rule_policy,
            max_deals=max_deals,
        )
        completed = []
        for packages in proposals:
            loaded = self._commit_trade(
                loaded,
                packages,
                source="cpu-market",
            )
            completed.append(loaded.state.transactions[-1].as_dict())
        response = self._franchise_response(loaded)
        response["ai_trades_made"] = len(completed)
        response["ai_trade_records"] = completed
        return response

    def _commit_trade(
        self,
        loaded: LoadedFranchise,
        packages: tuple[TradeTeamPackage, TradeTeamPackage],
        *,
        source: str,
    ) -> LoadedFranchise:
        state = loaded.state
        if state.trade_rule_policy is None:
            raise ValueError("initialize the trade center first")
        evaluation = evaluate_trade(
            state,
            packages,
            policy=state.trade_rule_policy,
        )
        if not evaluation["legal"]:
            messages = "; ".join(
                str(item["message"]) for item in evaluation["blockers"]
            )
            raise ValueError(f"illegal trade: {messages}")
        if not evaluation["accepted"]:
            rejecting = [
                item["team"]
                for item in evaluation["teams"]
                if item["team"] != state.user_team and not item["accepts"]
            ]
            raise ValueError(
                f"trade rejected by {', '.join(str(item) for item in rejecting)}"
            )
        player_by_id = {item.player_id: item for item in state.players}
        asset_by_id = {item.asset_id: item for item in state.draft_assets}
        first, second = packages
        player_moves = [
            {
                "player_id": player_id,
                "from_team": package.team,
                "to_team": other.team,
            }
            for package, other in ((first, second), (second, first))
            for player_id in package.player_ids
        ]
        asset_moves = [
            {
                "asset_id": asset_id,
                "from_team": package.team,
                "to_team": other.team,
            }
            for package, other in ((first, second), (second, first))
            for asset_id in package.asset_ids
        ]
        pieces = []
        for package, other in ((first, second), (second, first)):
            names = [
                player_by_id[player_id].name
                for player_id in package.player_ids
            ]
            picks = [
                (
                    f"{asset_by_id[asset_id].draft_year} "
                    f"R{asset_by_id[asset_id].round} "
                    f"({asset_by_id[asset_id].original_team})"
                )
                for asset_id in package.asset_ids
            ]
            pieces.append(
                f"{package.team} sends {', '.join((*names, *picks)) or 'no assets'} "
                f"to {other.team}"
            )
        record = TransactionRecord(
            transaction_id=deterministic_trade_id(
                league_id=state.league_id,
                revision=state.revision + 1,
                packages=packages,
            ),
            transaction_type="trade",
            occurred_on=state.calendar.current_date,
            teams=(first.team, second.team),
            summary="; ".join(pieces),
            source=source,
            player_ids=tuple(
                player_id
                for package in packages
                for player_id in package.player_ids
            ),
            asset_ids=tuple(
                asset_id
                for package in packages
                for asset_id in package.asset_ids
            ),
        )
        return self.franchise_repository.append_event(
            loaded.metadata.save_id,
            event_type=LeagueEventType.TRADE_COMPLETED,
            payload={
                "record": record.as_dict(),
                "player_moves": player_moves,
                "asset_moves": asset_moves,
                "evaluation": evaluation,
            },
            occurred_on=state.calendar.current_date,
            actor=source,
        )

    def _trade_loaded(self, payload: Mapping[str, Any]) -> LoadedFranchise:
        save_id = str(payload.get("save_id", "")).strip()
        if not save_id:
            raise ValueError("save_id is required")
        loaded = self.franchise_repository.load(save_id)
        if loaded.state.trade_rule_policy is None:
            raise ValueError("initialize the trade center first")
        return loaded

    def franchise_cap_scenario(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        evaluation = evaluate_transaction(
            team_salary=_salary_amount(payload, "team_salary"),
            outgoing_salary=_salary_amount(
                payload,
                "outgoing_salary",
                default=0,
            ),
            incoming_salary=_salary_amount(
                payload,
                "incoming_salary",
                default=0,
            ),
            action=str(
                payload.get(
                    "action",
                    TransactionAction.STANDARD_TRADE.value,
                )
            ),
        )
        return {
            "kind": "franchise_cap_scenario",
            "rules": CBA_2026_27.as_dict(),
            "evaluation": evaluation.as_dict(),
        }

    def initialize_franchise_health(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        save_id = str(payload.get("save_id", "")).strip()
        if not save_id:
            raise ValueError("save_id is required")
        loaded = self.franchise_repository.load(save_id)
        if loaded.state.player_health:
            return self._franchise_response(loaded)
        lifecycle = {
            record.player_id: record
            for record in loaded.state.player_lifecycles
        }
        records = tuple(
            build_health_record(
                player,
                lifecycle=lifecycle.get(player.player_id),
                as_of=loaded.state.calendar.current_date,
            )
            for player in loaded.state.players
        )
        initialized = self.franchise_repository.append_event(
            save_id,
            event_type=LeagueEventType.PLAYER_HEALTH_INITIALIZED,
            payload={
                "records": [record.as_dict() for record in records],
                "model_version": HEALTH_MODEL_VERSION,
            },
            actor="user",
        )
        return self._franchise_response(initialized)

    def update_franchise_health(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        loaded, player_id = self._health_player(payload)
        record = next(
            item
            for item in loaded.state.player_health
            if item.player_id == player_id
        )
        expected_return = None
        if payload.get("expected_return"):
            try:
                expected_return = date.fromisoformat(
                    str(payload["expected_return"])
                )
            except ValueError as error:
                raise ValueError(
                    "expected_return must use YYYY-MM-DD"
                ) from error
        minute_limit = (
            _bounded_float(
                payload,
                "minute_limit",
                default=0.0,
                minimum=0.0,
                maximum=48.0,
            )
            if payload.get("minute_limit") not in {None, ""}
            else None
        )
        updated = update_health_status(
            record,
            occurred_on=loaded.state.calendar.current_date,
            availability=str(payload.get("availability", "available")),
            body_area=str(payload.get("body_area", ""))[:80],
            detail=str(payload.get("detail", ""))[:240],
            expected_return=expected_return,
            minute_limit=minute_limit,
        )
        result = self.franchise_repository.append_event(
            loaded.metadata.save_id,
            event_type=LeagueEventType.PLAYER_HEALTH_UPDATED,
            payload={"record": updated.as_dict()},
            actor="user",
        )
        return self._franchise_response(result)

    def record_franchise_workload(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        loaded, player_id = self._health_player(payload)
        record = next(
            item
            for item in loaded.state.player_health
            if item.player_id == player_id
        )
        minutes = _bounded_float(
            payload,
            "minutes",
            default=0.0,
            minimum=0.0,
            maximum=80.0,
        )
        intensity = _bounded_float(
            payload,
            "intensity",
            default=1.0,
            minimum=0.25,
            maximum=2.0,
        )
        updated = apply_workload(
            record,
            occurred_on=loaded.state.calendar.current_date,
            minutes=minutes,
            intensity=intensity,
        )
        result = self.franchise_repository.append_event(
            loaded.metadata.save_id,
            event_type=LeagueEventType.PLAYER_WORKLOAD_RECORDED,
            payload={
                "record": updated.as_dict(),
                "session": {
                    "minutes": minutes,
                    "intensity": intensity,
                    "kind": str(payload.get("kind", "game"))[:40],
                },
            },
            actor="user",
        )
        return self._franchise_response(result)

    def _health_player(
        self,
        payload: Mapping[str, Any],
    ) -> tuple[LoadedFranchise, int]:
        save_id = str(payload.get("save_id", "")).strip()
        if not save_id:
            raise ValueError("save_id is required")
        player_id = _integer(
            payload,
            "player_id",
            default=0,
            minimum=1,
        )
        loaded = self.franchise_repository.load(save_id)
        if not loaded.state.player_health:
            raise ValueError("player health is not initialized")
        roster_ids = {
            player.player_id
            for player in loaded.state.roster(loaded.state.user_team)
        }
        if player_id not in roster_ids:
            raise ValueError("player must be on your active roster")
        return loaded, player_id

    def initialize_team_environment(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        save_id = str(payload.get("save_id", "")).strip()
        loaded = self.franchise_repository.load(save_id)
        if loaded.state.team_chemistry and loaded.state.coaching_profiles:
            return self._franchise_response(loaded)
        teams = [franchise.team for franchise in loaded.state.franchises]
        chemistry = [
            default_team_chemistry(
                team,
                as_of=loaded.state.calendar.current_date,
            )
            for team in teams
        ]
        coaching = [
            default_coaching_profile(
                team,
                as_of=loaded.state.calendar.current_date,
            )
            for team in teams
        ]
        result = self.franchise_repository.append_event(
            save_id,
            event_type=LeagueEventType.TEAM_ENVIRONMENT_INITIALIZED,
            payload={
                "chemistry": [item.as_dict() for item in chemistry],
                "coaching": [item.as_dict() for item in coaching],
            },
            actor="user",
        )
        return self._franchise_response(result)

    def update_team_chemistry(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        loaded = self._environment_save(payload)
        current = next(
            item
            for item in loaded.state.team_chemistry
            if item.team == loaded.state.user_team
        )
        record = TeamChemistryRecord(
            team=current.team,
            as_of_date=loaded.state.calendar.current_date,
            cohesion=_bounded_float(payload, "cohesion", default=current.cohesion, minimum=0, maximum=100),
            role_clarity=_bounded_float(payload, "role_clarity", default=current.role_clarity, minimum=0, maximum=100),
            trust=_bounded_float(payload, "trust", default=current.trust, minimum=0, maximum=100),
            system_familiarity=_bounded_float(payload, "system_familiarity", default=current.system_familiarity, minimum=0, maximum=100),
            morale=_bounded_float(payload, "morale", default=current.morale, minimum=0, maximum=100),
            shared_sessions=current.shared_sessions,
            confidence="scenario",
            source="user-team-assessment",
            model_version=CHEMISTRY_MODEL_VERSION,
        )
        result = self.franchise_repository.append_event(
            loaded.metadata.save_id,
            event_type=LeagueEventType.TEAM_CHEMISTRY_UPDATED,
            payload={"record": record.as_dict()},
            actor="user",
        )
        return self._franchise_response(result)

    def update_coaching_profile(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        loaded = self._environment_save(payload)
        current = next(
            item
            for item in loaded.state.coaching_profiles
            if item.team == loaded.state.user_team
        )
        record = CoachingProfileRecord(
            team=current.team,
            as_of_date=loaded.state.calendar.current_date,
            coach_name=str(payload.get("coach_name", current.coach_name))[:80],
            offensive_system=str(payload.get("offensive_system", current.offensive_system)),
            defensive_system=str(payload.get("defensive_system", current.defensive_system)),
            pace_emphasis=_bounded_float(payload, "pace_emphasis", default=current.pace_emphasis, minimum=-1, maximum=1),
            rotation_depth=_integer(payload, "rotation_depth", default=current.rotation_depth, minimum=8, maximum=12),
            development_priority=str(payload.get("development_priority", current.development_priority)),
            adaptability=_bounded_float(payload, "adaptability", default=current.adaptability, minimum=0, maximum=100),
            confidence="scenario",
            source="user-coaching-plan",
            model_version=CHEMISTRY_MODEL_VERSION,
        )
        result = self.franchise_repository.append_event(
            loaded.metadata.save_id,
            event_type=LeagueEventType.COACHING_PROFILE_UPDATED,
            payload={"record": record.as_dict()},
            actor="user",
        )
        return self._franchise_response(result)

    def record_chemistry_session(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        loaded = self._environment_save(payload)
        current = next(
            item
            for item in loaded.state.team_chemistry
            if item.team == loaded.state.user_team
        )
        record = record_shared_session(
            current,
            occurred_on=loaded.state.calendar.current_date,
            emphasis=str(payload.get("emphasis", "system")),
            intensity=_bounded_float(payload, "intensity", default=1, minimum=0.25, maximum=2),
        )
        result = self.franchise_repository.append_event(
            loaded.metadata.save_id,
            event_type=LeagueEventType.CHEMISTRY_SESSION_RECORDED,
            payload={"record": record.as_dict()},
            actor="user",
        )
        return self._franchise_response(result)

    def _environment_save(self, payload: Mapping[str, Any]) -> LoadedFranchise:
        save_id = str(payload.get("save_id", "")).strip()
        if not save_id:
            raise ValueError("save_id is required")
        loaded = self.franchise_repository.load(save_id)
        if not loaded.state.team_chemistry or not loaded.state.coaching_profiles:
            raise ValueError("team environment is not initialized")
        return loaded

    def initialize_franchise_scouting(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        save_id = str(payload.get("save_id", "")).strip()
        if not save_id:
            raise ValueError("save_id is required")
        loaded = self.franchise_repository.load(save_id)
        if loaded.state.scouting_reports and loaded.state.scouting_departments:
            return self._franchise_response(loaded)
        if not loaded.state.player_lifecycles:
            raise ValueError("player lifecycle must be initialized first")
        lifecycle_by_id = {
            record.player_id: record
            for record in loaded.state.player_lifecycles
        }
        reports = [
            build_initial_scouting_report(
                player,
                lifecycle_by_id[player.player_id],
                as_of=loaded.state.calendar.current_date,
                seed=loaded.state.seed,
            )
            for player in loaded.state.players
        ]
        departments = [
            default_scouting_department(
                franchise.team,
                as_of=loaded.state.calendar.current_date,
            )
            for franchise in loaded.state.franchises
        ]
        result = self.franchise_repository.append_event(
            save_id,
            event_type=LeagueEventType.SCOUTING_INITIALIZED,
            payload={
                "reports": [item.as_dict() for item in reports],
                "departments": [item.as_dict() for item in departments],
                "model_version": SCOUTING_MODEL_VERSION,
            },
            actor="user",
        )
        return self._franchise_response(result)

    def franchise_scouting_board(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        save_id = str(payload.get("save_id", "")).strip()
        if not save_id:
            raise ValueError("save_id is required")
        loaded = self.franchise_repository.load(save_id)
        player_by_id = {
            player.player_id: player for player in loaded.state.players
        }
        ratings = self._league_rating_profiles(loaded.state)
        reports_by_id = {
            report.player_id: report
            for report in loaded.state.scouting_reports
        }
        rows = []
        for player in loaded.state.players:
            if player.roster_status == "active":
                rating = ratings[player.player_id]
                rows.append(
                    {
                        **rating,
                        "overall_mean": rating["overall"],
                        "overall_low": rating["overall"],
                        "overall_high": rating["overall"],
                        "potential_mean": rating["attributes"]["potential"],
                        "potential_low": rating["attributes"]["potential"],
                        "potential_high": rating["attributes"]["potential"],
                        "confidence": "known",
                        "evaluations": 0,
                        "observation_hours": 0,
                        "primary_archetype": rating["primary_role"],
                        "archetype_confidence": rating["primary_role_probability"],
                    }
                )
            else:
                report = reports_by_id.get(player.player_id)
                if report is None:
                    continue
                rows.append(
                    {
                        **report_summary(report),
                        "name": player.name,
                        "team": player.team,
                        "position": player.position,
                        "established_player": False,
                        "exact": False,
                    }
                )
        rows.sort(
            key=lambda row: (
                -float(row["overall_mean"]),
                -float(row.get("overall_sd", 0)),
                str(row["name"]),
            )
        )
        return {
            "kind": "franchise_scouting_board",
            "save_id": loaded.metadata.save_id,
            "records": rows,
            "model_version": SCOUTING_MODEL_VERSION,
        }

    def scout_franchise_player(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        loaded = self._scouting_save(payload)
        player_id = _integer(payload, "player_id", default=0, minimum=1)
        hours = _bounded_float(
            payload, "hours", default=12, minimum=1, maximum=120
        )
        report = next(
            (item for item in loaded.state.scouting_reports if item.player_id == player_id),
            None,
        )
        lifecycle = next(
            (item for item in loaded.state.player_lifecycles if item.player_id == player_id),
            None,
        )
        department = next(
            item for item in loaded.state.scouting_departments
            if item.team == loaded.state.user_team
        )
        if report is None or lifecycle is None:
            raise ValueError("unknown scouting player")
        player = next(
            item for item in loaded.state.players
            if item.player_id == player_id
        )
        if player.roster_status == "active":
            raise ValueError(
                "established NBA players have exact ratings and do not require scouting"
            )
        updated = scout_player(
            report,
            lifecycle,
            hours=hours,
            evaluation_quality=department.evaluation_quality,
            occurred_on=loaded.state.calendar.current_date,
            seed=loaded.state.seed,
            namespace=(
                f"manual-scout:{loaded.state.user_team}:"
                f"{player_id}:{report.evaluations + 1}"
            ),
        )
        result = self.franchise_repository.append_event(
            loaded.metadata.save_id,
            event_type=LeagueEventType.SCOUTING_REPORT_UPDATED,
            payload={
                "record": updated.as_dict(),
                "hours": hours,
            },
            actor="user",
        )
        return self._franchise_response(result)

    def run_franchise_scouting_cycle(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        loaded = self._scouting_save(payload)
        department = next(
            item for item in loaded.state.scouting_departments
            if item.team == loaded.state.user_team
        )
        draft = loaded.state.draft_ecosystem
        if draft is not None and draft.status != "complete":
            selected_ids = {item.player_id for item in draft.selections}
            prospects = tuple(
                item for item in draft.prospects
                if item.player_id not in selected_ids
            )
            updated_department, reports = run_automatic_scouting_cycle(
                department,
                tuple(item.report for item in prospects),
                tuple(
                    PlayerRecord(
                        player_id=item.player_id,
                        name=item.name,
                        team="DRAFT",
                        position=item.position,
                        roster_status="prospect",
                        expected_minutes=0.0,
                        profile_source="draft-class",
                    )
                    for item in prospects
                ),
                tuple(item.lifecycle(loaded.state.season) for item in prospects),
                occurred_on=loaded.state.calendar.current_date,
                seed=loaded.state.seed,
            )
            if reports:
                report_by_id = {item.player_id: item for item in reports}
                updated_draft = replace(
                    draft,
                    scouting_cycles=draft.scouting_cycles + 1,
                    prospects=tuple(
                        replace(
                            item,
                            report=report_by_id.get(item.player_id, item.report),
                        )
                        for item in draft.prospects
                    ),
                )
                result = self.franchise_repository.append_event(
                    loaded.metadata.save_id,
                    event_type=LeagueEventType.DRAFT_PROSPECT_SCOUTED,
                    payload={
                        "draft": updated_draft.as_dict(),
                        "department": updated_department.as_dict(),
                        "player_ids": sorted(report_by_id),
                        "automatic": True,
                    },
                    actor="scouting-department",
                )
                response = self._franchise_response(result)
                response["scouting_cycle_targets"] = len(reports)
                return response
        updated_department, reports = run_automatic_scouting_cycle(
            department,
            loaded.state.scouting_reports,
            loaded.state.players,
            loaded.state.player_lifecycles,
            occurred_on=loaded.state.calendar.current_date,
            seed=loaded.state.seed,
        )
        if not reports:
            response = self._franchise_response(loaded)
            response["scouting_cycle_targets"] = 0
            return response
        result = self.franchise_repository.append_event(
            loaded.metadata.save_id,
            event_type=LeagueEventType.SCOUTING_CYCLE_COMPLETED,
            payload={
                "department": updated_department.as_dict(),
                "reports": [item.as_dict() for item in reports],
                "targets": len(reports),
            },
            actor="scouting-department",
        )
        response = self._franchise_response(result)
        response["scouting_cycle_targets"] = len(reports)
        return response

    def update_franchise_scouting_department(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        loaded = self._scouting_save(payload)
        current = next(
            item for item in loaded.state.scouting_departments
            if item.team == loaded.state.user_team
        )
        automation_value = payload.get(
            "automation_enabled", current.automation_enabled
        )
        if isinstance(automation_value, str):
            automation_enabled = automation_value.lower() in {
                "1", "true", "yes", "on"
            }
        else:
            automation_enabled = bool(automation_value)
        record = ScoutingDepartmentRecord(
            team=current.team,
            as_of_date=loaded.state.calendar.current_date,
            automation_enabled=automation_enabled,
            weekly_hours=_integer(
                payload,
                "weekly_hours",
                default=current.weekly_hours,
                minimum=8,
                maximum=240,
            ),
            evaluation_quality=current.evaluation_quality,
            priority=str(payload.get("priority", current.priority)),
            risk_tolerance=str(
                payload.get("risk_tolerance", current.risk_tolerance)
            ),
            cycles_completed=current.cycles_completed,
            last_cycle_date=current.last_cycle_date,
            model_version=SCOUTING_MODEL_VERSION,
        )
        result = self.franchise_repository.append_event(
            loaded.metadata.save_id,
            event_type=LeagueEventType.SCOUTING_DEPARTMENT_UPDATED,
            payload={"record": record.as_dict()},
            actor="user",
        )
        return self._franchise_response(result)

    def _scouting_save(self, payload: Mapping[str, Any]) -> LoadedFranchise:
        save_id = str(payload.get("save_id", "")).strip()
        if not save_id:
            raise ValueError("save_id is required")
        loaded = self.franchise_repository.load(save_id)
        if not loaded.state.scouting_reports or not loaded.state.scouting_departments:
            raise ValueError("scouting is not initialized")
        return loaded

    def initialize_franchise_lifecycle(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        save_id = str(payload.get("save_id", "")).strip()
        if not save_id:
            raise ValueError("save_id is required")
        loaded = self.franchise_repository.load(save_id)
        if loaded.state.player_lifecycles:
            response = self._franchise_response(loaded)
            response["lifecycle_initialization_reused"] = True
            return response
        records = self._lifecycle_records_for_state(loaded)
        initialized = self.franchise_repository.append_event(
            save_id,
            event_type=LeagueEventType.PLAYER_LIFECYCLES_INITIALIZED,
            payload={
                "records": [record.as_dict() for record in records],
                "model_version": LIFECYCLE_MODEL_VERSION,
            },
            actor="user",
        )
        return self._franchise_response(initialized)

    def project_player_lifecycle(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        save_id = str(payload.get("save_id", "")).strip()
        if not save_id:
            raise ValueError("save_id is required")
        player_id = _integer(
            payload,
            "player_id",
            default=0,
            minimum=1,
        )
        loaded = self.franchise_repository.load(save_id)
        state = loaded.state
        roster = {player.player_id: player for player in state.roster(state.user_team)}
        player = roster.get(player_id)
        if player is None:
            raise ValueError("player must be on your active roster")
        record = next(
            (
                lifecycle
                for lifecycle in state.player_lifecycles
                if lifecycle.player_id == player_id
            ),
            None,
        )
        if record is None:
            raise ValueError(
                "player lifecycle is not initialized for this save"
            )
        rating = self._league_rating_profiles(state).get(player_id)
        if rating is not None:
            composites = lifecycle_composites(rating)
            attributes = rating["attributes"]
            record = replace(
                record,
                offense=composites["offense"],
                playmaking=composites["playmaking"],
                defense=composites["defense"],
                athleticism=composites["athleticism"],
                overall=composites["overall"],
                potential_mean=max(
                    composites["overall"],
                    float(attributes["potential"]),
                ),
            )
        config = LifecycleProjectionConfig(
            focus=str(payload.get("focus", "balanced")),
            planned_minutes=_bounded_float(
                payload,
                "planned_minutes",
                default=max(0.0, record.workload_minutes),
                minimum=0.0,
                maximum=3_500.0,
            ),
            injury_burden=_bounded_float(
                payload,
                "injury_burden",
                default=0.0,
                minimum=0.0,
                maximum=1.0,
            ),
            seasons=_integer(
                payload,
                "seasons",
                default=5,
                minimum=1,
                maximum=8,
            ),
            paths=_integer(
                payload,
                "paths",
                default=400,
                minimum=50,
                maximum=2_000,
            ),
        )
        response = project_lifecycle(
            record,
            seed=_seed(payload),
            config=config,
        )
        response.update(
            {
                "player_name": player.name,
                "team": player.team,
                "position": player.position,
            }
        )
        return response

    def _lifecycle_records_for_state(
        self,
        loaded: LoadedFranchise,
    ) -> tuple[object, ...]:
        state = loaded.state
        profiles_by_id = {
            player.player_id: player
            for team in state.franchises
            for player in self._team(team.team).roster
        }
        return tuple(
            build_lifecycle_record(
                player,
                profile=profiles_by_id.get(player.player_id),
                statistics=self.profile_repository.player_statistics(
                    player.player_id
                ),
                season=state.season,
            )
            for player in state.players
        )

    def _league_rating_profiles(
        self,
        state: object,
    ) -> dict[int, dict[str, object]]:
        profiles_by_id = {
            player.player_id: player
            for franchise in state.franchises
            for player in self._team(franchise.team).roster
        }
        lifecycles = {
            record.player_id: record
            for record in state.player_lifecycles
        }
        inputs = []
        for player in state.players:
            profile = profiles_by_id.get(player.player_id)
            if profile is None:
                continue
            inputs.append(
                RatingInput(
                    player=player,
                    profile=profile,
                    statistics=self.profile_repository.player_statistics(
                        player.player_id
                    ),
                    lifecycle=lifecycles.get(player.player_id),
                    historical_profile=self.repository.load_player(
                        player.player_id
                    ),
                )
            )
        return build_league_ratings(inputs)

    def _franchise_response(
        self,
        loaded: LoadedFranchise,
    ) -> dict[str, object]:
        state = loaded.state
        user_franchise = state.franchise(state.user_team)
        roster = state.roster(state.user_team)
        roster_ids = {player.player_id for player in roster}
        roster_by_id = {player.player_id: player for player in roster}
        rating_profiles = self._league_rating_profiles(state)
        lifecycle_rows = [
            {
                **record.as_dict(),
                **lifecycle_composites(rating_profiles[record.player_id]),
                "name": roster_by_id[record.player_id].name,
                "team": roster_by_id[record.player_id].team,
                "position": roster_by_id[record.player_id].position,
                "rating_profile": rating_profiles[record.player_id],
            }
            for record in state.player_lifecycles
            if record.player_id in roster_ids
        ]
        health_rows = [
            {
                **record.as_dict(),
                "name": roster_by_id[record.player_id].name,
                "team": roster_by_id[record.player_id].team,
                "position": roster_by_id[record.player_id].position,
            }
            for record in state.player_health
            if record.player_id in roster_ids
        ]
        chemistry = next(
            (item for item in state.team_chemistry if item.team == state.user_team),
            None,
        )
        coaching = next(
            (item for item in state.coaching_profiles if item.team == state.user_team),
            None,
        )
        scouting_department = next(
            (
                item for item in state.scouting_departments
                if item.team == state.user_team
            ),
            None,
        )
        scouting_persisted = (
            len(state.scouting_reports) == len(state.players)
            and len(state.scouting_departments) == len(state.franchises)
        )
        if scouting_department is None:
            scouting_department = default_scouting_department(
                state.user_team,
                as_of=state.calendar.current_date,
            )
        events = tuple(reversed(loaded.events[-50:]))
        cap_sheet = team_cap_sheet(state, state.user_team)
        return {
            "kind": "franchise",
            "save": loaded.metadata.as_dict(),
            "summary": state.summary_dict(),
            "calendar": state.calendar.as_dict(),
            "user_franchise": user_franchise.as_dict(),
            "roster": [player.as_dict() for player in roster],
            "player_ratings": {
                "scale": "2k-style-25-99",
                "exact_for_established_players": True,
                "records": [
                    rating_profiles[player.player_id]
                    for player in roster
                    if player.player_id in rating_profiles
                ],
            },
            "events": [event.as_dict() for event in events],
            "cba": CBA_2026_27.as_dict(),
            "cap_sheet": cap_sheet,
            "player_lifecycle": {
                "ready": len(state.player_lifecycles) == len(state.players),
                "model_version": LIFECYCLE_MODEL_VERSION,
                "records": lifecycle_rows,
                "coverage": {
                    "league_players": len(state.players),
                    "modeled_players": len(state.player_lifecycles),
                    "known_ages": sum(
                        record.age is not None
                        for record in state.player_lifecycles
                    ),
                    "team_players": len(roster),
                    "team_modeled": len(lifecycle_rows),
                },
            },
            "player_health": {
                "ready": len(state.player_health) == len(state.players),
                "model_version": HEALTH_MODEL_VERSION,
                "records": health_rows,
                "coverage": {
                    "league_players": len(state.players),
                    "modeled_players": len(state.player_health),
                    "team_players": len(roster),
                    "team_modeled": len(health_rows),
                    "restricted": sum(
                        record["availability"] != "available"
                        for record in health_rows
                    ),
                },
                "interpretation": (
                    "Load concern is a relative planning index, not an injury "
                    "probability or medical diagnosis."
                ),
            },
            "team_environment": {
                "ready": (
                    len(state.team_chemistry) == len(state.franchises)
                    and len(state.coaching_profiles) == len(state.franchises)
                ),
                "model_version": CHEMISTRY_MODEL_VERSION,
                "chemistry": chemistry.as_dict() if chemistry else None,
                "coaching": coaching.as_dict() if coaching else None,
                "interpretation": (
                    "Effects are bounded strategy priors, not measured causal "
                    "coach or chemistry ratings."
                ),
            },
            "scouting": {
                "ready": True,
                "prospect_scouting_ready": scouting_persisted,
                "model_version": SCOUTING_MODEL_VERSION,
                "department": (
                    scouting_department.as_dict()
                    if scouting_department is not None else None
                ),
                "coverage": {
                    "players": len(state.players),
                    "reports": len(state.scouting_reports),
                    "departments": len(state.scouting_departments),
                    "high_confidence": sum(
                        item.confidence == "high"
                        for item in state.scouting_reports
                    ),
                    "draft_prospects": (
                        sum(
                            item.player_id not in {
                                selection.player_id
                                for selection in state.draft_ecosystem.selections
                            }
                            for item in state.draft_ecosystem.prospects
                        )
                        if state.draft_ecosystem is not None
                        else 0
                    ),
                },
                "interpretation": (
                    "Established NBA players have exact current ratings. "
                    "Scouting uncertainty is reserved for draft prospects."
                ),
            },
            "draft": (
                draft_response(
                    state.draft_ecosystem,
                    user_team=state.user_team,
                )
                if state.draft_ecosystem is not None
                else {
                    "ready": False,
                    "draft_year": 2027,
                    "model_version": DRAFT_MODEL_VERSION,
                }
            ),
            "trade_center": {
                "ready": state.trade_rule_policy is not None,
                "policy": (
                    state.trade_rule_policy.as_dict()
                    if state.trade_rule_policy is not None
                    else TradeRulePolicy().as_dict()
                ),
                "rule_coverage": rule_coverage(),
                "recent_trades": [
                    item.as_dict()
                    for item in reversed(state.transactions)
                    if item.transaction_type == "trade"
                ][:20],
                "model_version": TRADE_MODEL_VERSION,
            },
            "coverage": {
                "franchises": {
                    "status": "loaded",
                    "records": len(state.franchises),
                },
                "players": {
                    "status": "loaded",
                    "records": len(state.players),
                },
                "player_lifecycle": {
                    "status": (
                        "loaded"
                        if state.player_lifecycles
                        else "schema_ready"
                    ),
                    "records": len(state.player_lifecycles),
                },
                "player_health": {
                    "status": (
                        "loaded" if state.player_health else "schema_ready"
                    ),
                    "records": len(state.player_health),
                },
                "team_chemistry": {
                    "status": "loaded" if state.team_chemistry else "schema_ready",
                    "records": len(state.team_chemistry),
                },
                "coaching_profiles": {
                    "status": "loaded" if state.coaching_profiles else "schema_ready",
                    "records": len(state.coaching_profiles),
                },
                "scouting_reports": {
                    "status": "loaded" if state.scouting_reports else "schema_ready",
                    "records": len(state.scouting_reports),
                },
                "scouting_departments": {
                    "status": "loaded" if state.scouting_departments else "schema_ready",
                    "records": len(state.scouting_departments),
                },
                "staff": {
                    "status": "schema_ready",
                    "records": len(state.staff),
                },
                "contracts": {
                    "status": "schema_ready",
                    "records": len(state.contracts),
                },
                "draft_assets": {
                    "status": (
                        "loaded" if state.draft_assets else "schema_ready"
                    ),
                    "records": len(state.draft_assets),
                },
                "draft_ecosystem": {
                    "status": (
                        "loaded"
                        if state.draft_ecosystem is not None
                        else "schema_ready"
                    ),
                    "records": (
                        len(state.draft_ecosystem.prospects)
                        if state.draft_ecosystem is not None
                        else 0
                    ),
                },
                "trade_center": {
                    "status": (
                        "loaded"
                        if state.trade_rule_policy is not None
                        else "schema_ready"
                    ),
                    "records": 1 if state.trade_rule_policy is not None else 0,
                },
                "cap_exceptions": {
                    "status": "schema_ready",
                    "records": len(state.cap_exceptions),
                },
                "injuries": {
                    "status": "schema_ready",
                    "records": len(state.injuries),
                },
                "transactions": {
                    "status": "loaded" if state.transactions else "schema_ready",
                    "records": len(state.transactions),
                },
            },
            "integrity": {
                "verified": True,
                "revision": state.revision,
                "head_hash": state.head_hash,
                "replayed_events": len(loaded.events),
            },
        }

    def run_validation(self, payload: Mapping[str, Any]) -> dict[str, object]:
        games_per_matchup = _integer(
            payload,
            "games_per_matchup",
            default=5,
            minimum=1,
            maximum=20,
        )
        seed = _integer(payload, "seed", default=2026, minimum=0)
        raw_totals = self.database_path.parent / "raw_data" / "league_roster_raw.json"
        report = evaluate_legacy_league_fidelity(
            self.profile_repository,
            raw_player_totals_path=raw_totals,
            games_per_matchup=games_per_matchup,
            seed=seed,
        )
        response = report.as_dict()
        response["gate"] = FidelityGate().evaluate(report).as_dict()
        response["profile_roster_season"] = self.profile_repository.season
        response["profile_stat_season"] = self.profile_repository.stat_season
        response["kind"] = "validation"
        return response

    def run_backtest(self, payload: Mapping[str, Any]) -> dict[str, object]:
        try:
            evaluation_start = date.fromisoformat(
                str(payload.get("evaluation_start", "2025-10-21"))
            )
            evaluation_end = date.fromisoformat(
                str(payload.get("evaluation_end", "2026-04-12"))
            )
        except ValueError as error:
            raise ValueError("backtest dates must use YYYY-MM-DD") from error
        bootstrap_samples = _integer(
            payload,
            "bootstrap_samples",
            default=2_000,
            minimum=100,
            maximum=20_000,
        )
        profiles = {
            abbreviation: self.repository.load_team(abbreviation)
            for abbreviation in self.repository.available_teams()
        }
        games = self.warehouse.games(end_date=evaluation_end)
        report = default_backtester(
            profiles,
            bootstrap_samples=bootstrap_samples,
            bootstrap_seed=_integer(
                payload,
                "seed",
                default=2026,
                minimum=0,
            ),
        ).run(
            games,
            evaluation_start=evaluation_start,
            evaluation_end=evaluation_end,
        )
        response = report.as_dict()
        response["kind"] = "backtest"
        return response

    def _team(self, abbreviation: str) -> TeamProfile:
        normalized = abbreviation.upper()
        if not normalized:
            raise ValueError("team abbreviation cannot be empty")
        if normalized not in self._team_cache:
            self._team_cache[normalized] = self.profile_repository.load_team(
                normalized
            )
        return self._team_cache[normalized]

    def _history(self) -> tuple[HistoricalGame, ...]:
        if self._historical_games is None:
            self._historical_games = self.warehouse.games()
        return self._historical_games

    def _ensure_game_day_models(self) -> None:
        if self._team_strength_model is not None:
            return
        historical = self._history()
        if len(historical) < 100:
            return
        teams = tuple(sorted(self.profile_repository.available_teams()))
        strength = CalibratedDynamicTeamModel(
            teams,
            home_court_points=1.5,
            process_standard_deviation_per_day=0.18,
            observation_standard_deviation=9.0,
        )
        for game in sorted(
            historical,
            key=lambda row: (row.game_date, row.game_id),
        ):
            strength.update(
                GameObservation(
                    game_date=game.game_date,
                    home_team=game.home_team,
                    away_team=game.away_team,
                    home_points=game.home_points,
                    away_points=game.away_points,
                    possessions=game.possessions,
                    neutral_site=game.neutral_site,
                )
            )
        self._team_strength_model = strength
        self._context_model = ScheduleContextModel().fit(historical)

    def _simulator(self, payload: Mapping[str, Any]) -> GameSimulator:
        home_abbreviation = str(payload.get("home", "")).upper()
        away_abbreviation = str(payload.get("away", "")).upper()
        home_health_out, home_health_limits = self._health_policy_for_team(
            payload,
            home_abbreviation,
        )
        away_health_out, away_health_limits = self._health_policy_for_team(
            payload,
            away_abbreviation,
        )
        home_manual_out = _player_ids(payload.get("home_out"))
        away_manual_out = _player_ids(payload.get("away_out"))
        home_manual_limits = _minute_limits(
            payload.get("home_minute_limits")
        )
        away_manual_limits = _minute_limits(
            payload.get("away_minute_limits")
        )
        home_inactive = tuple(sorted(set((*home_manual_out, *home_health_out))))
        away_inactive = tuple(sorted(set((*away_manual_out, *away_health_out))))
        home_limits = _merge_minute_limits(
            home_health_limits,
            home_manual_limits,
        )
        away_limits = _merge_minute_limits(
            away_health_limits,
            away_manual_limits,
        )
        for player_id in home_inactive:
            home_limits.pop(player_id, None)
        for player_id in away_inactive:
            away_limits.pop(player_id, None)
        home = condition_team_profile(
            self._team(home_abbreviation),
            inactive_player_ids=home_inactive,
            minute_limits=home_limits,
        )
        away = condition_team_profile(
            self._team(away_abbreviation),
            inactive_player_ids=away_inactive,
            minute_limits=away_limits,
        )
        home = self._apply_saved_environment(
            payload,
            team=home_abbreviation,
            profile=home,
        )
        away = self._apply_saved_environment(
            payload,
            team=away_abbreviation,
            profile=away,
        )
        return GameSimulator(home_team=home, away_team=away)

    def _apply_saved_environment(
        self,
        payload: Mapping[str, Any],
        *,
        team: str,
        profile: TeamProfile,
    ) -> TeamProfile:
        raw_save_id = payload.get("franchise_environment_save_id")
        if raw_save_id in {None, ""}:
            return profile
        loaded = self.franchise_repository.load(str(raw_save_id).strip())
        chemistry = next(
            (item for item in loaded.state.team_chemistry if item.team == team),
            None,
        )
        coaching = next(
            (item for item in loaded.state.coaching_profiles if item.team == team),
            None,
        )
        if chemistry is None or coaching is None:
            return profile
        return apply_team_environment(
            profile,
            chemistry=chemistry,
            coaching=coaching,
        )

    def _health_policy_for_team(
        self,
        payload: Mapping[str, Any],
        team: str,
    ) -> tuple[tuple[int, ...], dict[int, float]]:
        raw_save_id = payload.get("franchise_save_id")
        save_id = (
            str(raw_save_id).strip()
            if raw_save_id not in {None, ""}
            else ""
        )
        if not save_id:
            return (), {}
        loaded = self.franchise_repository.load(save_id)
        team_player_ids = {
            player.player_id
            for player in loaded.state.roster(team)
        }
        return availability_policy(
            record
            for record in loaded.state.player_health
            if record.player_id in team_player_ids
        )


def _integer(
    payload: Mapping[str, Any],
    key: str,
    *,
    default: int,
    minimum: int,
    maximum: int | None = None,
) -> int:
    try:
        value = int(payload.get(key, default))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{key} must be an integer") from error
    if value < minimum or (maximum is not None and value > maximum):
        bound = f"{minimum}..{maximum}" if maximum is not None else f">= {minimum}"
        raise ValueError(f"{key} must be {bound}")
    return value


def _scheduled_game_dict(game: ScheduledGame) -> dict[str, object]:
    return {
        "game_id": game.game_id,
        "season": game.season,
        "game_date": game.game_date.isoformat(),
        "scheduled_at": (
            game.scheduled_at.isoformat()
            if game.scheduled_at is not None
            else None
        ),
        "home_team": game.home_team,
        "away_team": game.away_team,
        "teams_identified": game.teams_identified,
        "status": game.status,
        "status_text": game.status_text,
        "game_label": game.game_label,
        "game_sub_label": game.game_sub_label,
        "arena_name": game.arena_name,
        "arena_city": game.arena_city,
        "arena_state": game.arena_state,
        "neutral_site": game.neutral_site,
        "if_necessary": game.if_necessary,
    }


def re_full_season(value: str) -> bool:
    return re.fullmatch(r"\d{4}-\d{2}", value) is not None


def _seed(payload: Mapping[str, Any]) -> int:
    value = payload.get("seed")
    if value is None or value == "":
        return secrets.randbelow(2**31)
    try:
        seed = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("seed must be an integer") from error
    if seed < 0:
        raise ValueError("seed must be >= 0")
    return seed


def _salary_amount(
    payload: Mapping[str, Any],
    key: str,
    *,
    default: int | None = None,
) -> int:
    value = payload.get(key, default)
    if value is None or value == "":
        if default is None:
            raise ValueError(f"{key} is required")
        return default
    if isinstance(value, bool):
        raise ValueError(f"{key} must be an integer number of dollars")
    try:
        amount = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{key} must be an integer number of dollars") from error
    if amount < 0 or amount > 1_000_000_000:
        raise ValueError(f"{key} must be between $0 and $1 billion")
    return amount


def _bounded_float(
    payload: Mapping[str, Any],
    key: str,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    value = payload.get(key, default)
    if value is None or value == "":
        value = default
    if isinstance(value, bool):
        raise ValueError(f"{key} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{key} must be a number") from error
    if not minimum <= number <= maximum:
        raise ValueError(
            f"{key} must be between {minimum:g} and {maximum:g}"
        )
    return number


def _team_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError("teams must be a list")
    teams = tuple(str(item).upper() for item in value if str(item).strip())
    if len(teams) != len(set(teams)):
        raise ValueError("teams must be unique")
    return teams


def _player_ids(value: Any) -> tuple[int, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("inactive players must be a list")
    try:
        return tuple(int(player_id) for player_id in value)
    except (TypeError, ValueError) as error:
        raise ValueError("inactive player IDs must be integers") from error


def _minute_limits(value: Any) -> dict[int, float]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("minute limits must be an object")
    try:
        return {
            int(player_id): float(minutes)
            for player_id, minutes in value.items()
            if str(minutes).strip()
        }
    except (TypeError, ValueError) as error:
        raise ValueError("minute limits must map player IDs to minutes") from error


def _merge_minute_limits(
    first: Mapping[int, float],
    second: Mapping[int, float],
) -> dict[int, float]:
    merged = dict(first)
    for player_id, minutes in second.items():
        merged[player_id] = min(merged.get(player_id, minutes), minutes)
    return merged


def _trade_packages(
    payload: Mapping[str, Any],
) -> tuple[TradeTeamPackage, TradeTeamPackage]:
    raw = payload.get("packages")
    if not isinstance(raw, list) or len(raw) != 2:
        raise ValueError("packages must contain exactly two trade teams")
    packages = []
    for value in raw:
        if not isinstance(value, Mapping):
            raise ValueError("trade package must be an object")
        player_values = value.get("player_ids", [])
        asset_values = value.get("asset_ids", [])
        consent_values = value.get("consent_player_ids", [])
        if not isinstance(player_values, list):
            raise ValueError("trade player_ids must be a list")
        if not isinstance(asset_values, list):
            raise ValueError("trade asset_ids must be a list")
        if not isinstance(consent_values, list):
            raise ValueError("trade consent_player_ids must be a list")
        packages.append(
            TradeTeamPackage(
                team=str(value.get("team", "")),
                player_ids=tuple(int(item) for item in player_values),
                asset_ids=tuple(str(item) for item in asset_values),
                consent_player_ids=tuple(int(item) for item in consent_values),
            )
        )
    return packages[0], packages[1]


def _handler(service: DashboardService) -> type[BaseHTTPRequestHandler]:
    class DashboardHandler(BaseHTTPRequestHandler):
        server_version = "NBASimLocal/0.1"

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/api/metadata":
                self._json(HTTPStatus.OK, service.metadata())
                return
            asset = _ASSETS.get(path)
            if asset is None:
                self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
                return
            file_path = _ASSET_DIRECTORY / asset
            content = file_path.read_bytes()
            content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError):
                return

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            actions = {
                "/api/matchup": service.run_matchup,
                "/api/game-day": service.run_game_day,
                "/api/sync-schedule": service.sync_schedule,
                "/api/league-season": service.run_league_season,
                "/api/league-season/start": service.start_league_season,
                "/api/league-season/progress": service.league_season_progress,
                "/api/league-season/cancel": service.cancel_league_season,
                "/api/league-game": service.league_game,
                "/api/franchise/saves": service.franchise_saves,
                "/api/franchise/create": service.create_franchise,
                "/api/franchise/load": service.load_franchise,
                "/api/franchise/advance-date": service.advance_franchise_date,
                "/api/franchise/branch": service.branch_franchise,
                "/api/franchise/cap-scenario": service.franchise_cap_scenario,
                "/api/franchise/initialize-lifecycle": (
                    service.initialize_franchise_lifecycle
                ),
                "/api/franchise/project-lifecycle": (
                    service.project_player_lifecycle
                ),
                "/api/franchise/initialize-health": (
                    service.initialize_franchise_health
                ),
                "/api/franchise/update-health": (
                    service.update_franchise_health
                ),
                "/api/franchise/record-workload": (
                    service.record_franchise_workload
                ),
                "/api/franchise/initialize-environment": (
                    service.initialize_team_environment
                ),
                "/api/franchise/update-chemistry": (
                    service.update_team_chemistry
                ),
                "/api/franchise/update-coaching": (
                    service.update_coaching_profile
                ),
                "/api/franchise/record-chemistry-session": (
                    service.record_chemistry_session
                ),
                "/api/franchise/initialize-scouting": (
                    service.initialize_franchise_scouting
                ),
                "/api/franchise/scouting-board": (
                    service.franchise_scouting_board
                ),
                "/api/franchise/scout-player": (
                    service.scout_franchise_player
                ),
                "/api/franchise/run-scouting-cycle": (
                    service.run_franchise_scouting_cycle
                ),
                "/api/franchise/update-scouting-department": (
                    service.update_franchise_scouting_department
                ),
                "/api/franchise/initialize-draft": (
                    service.initialize_draft_ecosystem
                ),
                "/api/franchise/run-draft-lottery": (
                    service.run_draft_lottery
                ),
                "/api/franchise/run-draft-combine": (
                    service.run_draft_combine
                ),
                "/api/franchise/scout-draft-prospect": (
                    service.scout_draft_prospect
                ),
                "/api/franchise/update-draft-board": (
                    service.update_draft_board
                ),
                "/api/franchise/make-draft-pick": (
                    service.make_draft_pick
                ),
                "/api/franchise/simulate-to-draft-pick": (
                    service.simulate_to_user_draft_pick
                ),
                "/api/franchise/initialize-trades": (
                    service.initialize_trade_center
                ),
                "/api/franchise/trade-board": (
                    service.franchise_trade_board
                ),
                "/api/franchise/update-trade-rules": (
                    service.update_trade_rules
                ),
                "/api/franchise/evaluate-trade": (
                    service.evaluate_franchise_trade
                ),
                "/api/franchise/execute-trade": (
                    service.execute_franchise_trade
                ),
                "/api/franchise/run-ai-trade-market": (
                    service.run_ai_trade_market
                ),
                "/api/season": service.run_season,
                "/api/series": service.run_series,
                "/api/validate": service.run_validation,
                "/api/backtest": service.run_backtest,
            }
            action = actions.get(path)
            if action is None:
                self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
                return
            try:
                payload = self._request_json()
                self._json(HTTPStatus.OK, action(payload))
            except (FileNotFoundError, KeyError, ValueError) as error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            except Exception:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"error": "The simulation failed unexpectedly."},
                )

        def _request_json(self) -> Mapping[str, Any]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as error:
                raise ValueError("invalid Content-Length") from error
            if length <= 0 or length > 1_000_000:
                raise ValueError("request body must be between 1 byte and 1 MB")
            try:
                payload = json.loads(self.rfile.read(length))
            except (json.JSONDecodeError, UnicodeDecodeError) as error:
                raise ValueError("request body must be valid JSON") from error
            if not isinstance(payload, dict):
                raise ValueError("request body must be a JSON object")
            return payload

        def _json(self, status: HTTPStatus, payload: Mapping[str, Any]) -> None:
            content = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError):
                return

        def log_message(self, format: str, *args: object) -> None:
            return

    return DashboardHandler


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local NBA Sim dashboard")
    parser.add_argument(
        "--db",
        type=Path,
        default=Path.cwd() / "ETL" / "nba_universe.db",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--warehouse",
        type=Path,
        default=Path.cwd() / "data" / "nba_sim.sqlite",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    service = DashboardService(args.db, warehouse_path=args.warehouse)
    server = ThreadingHTTPServer((args.host, args.port), _handler(service))
    print(f"NBA Sim dashboard: http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
