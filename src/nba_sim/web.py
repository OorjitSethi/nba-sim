from __future__ import annotations

import argparse
import copy
import json
import logging
import mimetypes
import os
import re
import secrets
import threading
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse
from itertools import groupby


LOGGER = logging.getLogger("nba_sim.web")

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
from nba_sim.domain.profiles import PlayerProfile, TeamProfile
from nba_sim.domain.events import EventType
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
    rules_for_season,
    team_cap_sheet,
)
from nba_sim.franchise.events import LeagueEventType
from nba_sim.franchise.lifecycle import (
    LIFECYCLE_MODEL_VERSION,
    LifecycleProjectionConfig,
    advance_lifecycle_record,
    build_lifecycle_record,
    project_lifecycle,
)
from nba_sim.franchise.careers import (
    CAREER_MODEL_VERSION,
    advance_career_state,
    career_history_response,
)
from nba_sim.franchise.health import (
    HEALTH_MODEL_VERSION,
    INJURY_MODEL_VERSION,
    apply_workload,
    availability_policy,
    build_health_record,
    reconcile_injury_history,
    sample_game_injuries,
    update_health_status,
)
from nba_sim.franchise.health import advance_health_records
from nba_sim.franchise.chemistry import (
    CHEMISTRY_MODEL_VERSION,
    apply_team_environment,
    default_coaching_profile,
    default_team_chemistry,
    record_shared_session,
)
from nba_sim.franchise.models import (
    CoachingProfileRecord,
    InjuryRecord,
    LeagueCalendar,
    PlayerRecord,
    TeamChemistryRecord,
    TransactionRecord,
)
from nba_sim.franchise.offseason import (
    OFFSEASON_MODEL_VERSION,
    OFFSEASON_STAGES,
    advance_offseason_cycle,
    next_season,
    offseason_hub_response,
    offseason_stage_readiness,
    season_calendar_dates,
    season_seed,
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
    generated_rating_profile,
    lifecycle_composites,
)
from nba_sim.franchise.generated_profiles import generated_player_profile
from nba_sim.franchise.draft import (
    DRAFT_MODEL_VERSION,
    draft_response,
    generate_draft_ecosystem,
    make_next_pick,
    materialize_draft_intake,
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
    find_trade_offers,
    generate_counteroffer,
    propose_ai_trades,
    resolve_trade_routes,
    rule_coverage,
    trade_board_response,
)
from nba_sim.franchise.contracts import (
    CONTRACT_MODEL_VERSION,
    active_contract,
    build_modeled_contracts,
    contract_market_response,
    cpu_waiver_candidates,
    extended_contract,
    extension_evaluation,
    free_agent_contract,
    free_agent_evaluation,
    option_decision,
    transaction_record as contract_transaction_record,
    waived_contract,
)
from nba_sim.franchise.roster_operations import (
    ROSTER_OPERATIONS_MODEL_VERSION,
    apply_roster_plan,
    build_league_roster_plans,
    build_roster_plan,
    roster_inactive_player_ids,
    roster_operations_response,
    roster_plan,
    update_roster_plan,
)
from nba_sim.franchise.season_cycle import (
    POSTSEASON_ROUNDS,
    SEASON_CYCLE_MODEL_VERSION,
    FranchiseSeasonRecord,
    SeasonBoxScoreRecord,
    SeasonGameRecord,
    games_to_simulate,
    initialize_season_cycle,
    season_cycle_response,
    standings,
)
from nba_sim.franchise.honors import (
    build_regular_season_honors,
    postseason_performance,
    postseason_round_mvp,
)
from nba_sim.franchise.gm import (
    GM_INTELLIGENCE_MODEL_VERSION,
    build_league_general_manager_plans,
    general_manager_plan,
    general_manager_response,
    update_general_manager_plan,
)
from nba_sim.franchise.public_experience import (
    PUBLIC_EXPERIENCE_MODEL_VERSION,
    configured_experience,
    experience_response,
    public_release_audit,
    recovery_guidance,
)
from nba_sim.randomness import RandomStreamFactory
from nba_sim.franchise.repository import (
    FranchiseSaveRepository,
    LoadedFranchise,
)


_ASSET_DIRECTORY = Path(__file__).with_name("web_assets")
_ASSETS = {
    "/favicon.ico": "favicon.svg",
    "/favicon.svg": "favicon.svg",
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


@dataclass
class FranchiseSeasonSimulationJob:
    job_id: str
    save_id: str
    scope: str
    total_games: int
    status: str = "preparing"
    completed_games: int = 0
    current_game_id: str | None = None
    current_game_date: date | None = None
    current_home_team: str | None = None
    current_away_team: str | None = None
    started_at: float = field(default_factory=time.monotonic)
    cancel_requested: bool = False
    error: str | None = None
    result: dict[str, object] | None = None


def _simulate_prepared_franchise_game(
    arguments: tuple[SeasonGameRecord, GameSimulator, int],
) -> SeasonGameRecord:
    game, simulator, game_seed = arguments
    result = simulator.simulate(seed=game_seed)
    possessions = sum(
        event.event_type is EventType.POSSESSION_STARTED
        for event in result.events
    ) / 2.0
    boxes = tuple(
        SeasonBoxScoreRecord.from_dict(item.as_dict())
        for item in result.box_scores.values()
        if item.minutes > 0
    )
    return replace(
        game,
        completed=True,
        home_score=result.home_score,
        away_score=result.away_score,
        possessions=round(possessions, 2),
        seed=game_seed,
        box_scores=boxes,
    )


class DashboardService:
    """Small application layer shared by the local HTTP API and tests."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        warehouse_path: str | Path | None = None,
        deployment_mode: str = "local",
        matchup_trial_limit: int = 10_000,
        franchise_repository: FranchiseSaveRepository | None = None,
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
        self._player_profile_cache: dict[int, PlayerProfile] | None = None
        self._historical_games: tuple[HistoricalGame, ...] | None = None
        self._team_strength_model: CalibratedDynamicTeamModel | None = None
        self._context_model: ScheduleContextModel | None = None
        self._league_seasons: dict[str, LeagueSeasonResult] = {}
        self._league_jobs: dict[str, LeagueSimulationJob] = {}
        self._league_job_lock = threading.RLock()
        self._franchise_season_jobs: dict[str, FranchiseSeasonSimulationJob] = {}
        self._franchise_season_job_lock = threading.RLock()
        self.franchise_repository = franchise_repository or FranchiseSaveRepository(
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
                "home": "LAL" if any(team["abbreviation"] == "LAL" for team in teams) else teams[0]["abbreviation"],
                "away": "OKC" if any(team["abbreviation"] == "OKC" for team in teams) else teams[1]["abbreviation"],
                "seed": 7,
                "trials": min(100, self.matchup_trial_limit),
            },
            "deployment": {
                "mode": self.deployment_mode,
                "matchup_trial_limit": self.matchup_trial_limit,
                "persistent_storage": self.deployment_mode in {"local", "vercel-full"},
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

        if self.deployment_mode == "vercel-full":
            self._run_league_job(job.job_id)
            return self._league_job_snapshot(job, include_result=True)

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

    def initialize_gm_intelligence(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        save_id = str(payload.get("save_id", "")).strip()
        if not save_id:
            raise ValueError("save_id is required")
        loaded = self.franchise_repository.load(save_id)
        if loaded.state.gm_plans:
            return self._franchise_response(loaded)
        plans = build_league_general_manager_plans(
            loaded.state,
            reason="initial league audit",
        )
        updated = self.franchise_repository.append_event(
            save_id,
            event_type=LeagueEventType.GM_INTELLIGENCE_INITIALIZED,
            payload={
                "plans": [item.as_dict() for item in plans],
                "model_version": GM_INTELLIGENCE_MODEL_VERSION,
            },
            actor="league-front-offices",
        )
        return self._franchise_response(updated)

    def review_gm_intelligence(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        save_id = str(payload.get("save_id", "")).strip()
        if not save_id:
            raise ValueError("save_id is required")
        loaded = self.franchise_repository.load(save_id)
        if not loaded.state.gm_plans:
            raise ValueError("initialize Front Office AI first")
        reviewed = self._refresh_gm_plans(
            loaded,
            reason=str(payload.get("reason", "manual league review")),
            force=True,
        )
        response = self._franchise_response(reviewed)
        response["gm_review"] = {
            "teams_reviewed": sum(
                item.automation_enabled for item in reviewed.state.gm_plans
            ),
            "reason": str(payload.get("reason", "manual league review")),
        }
        return response

    def update_user_gm_plan(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        save_id = str(payload.get("save_id", "")).strip()
        if not save_id:
            raise ValueError("save_id is required")
        loaded = self.franchise_repository.load(save_id)
        current = general_manager_plan(loaded.state, loaded.state.user_team)
        if current is None:
            raise ValueError("initialize Front Office AI first")
        priorities = payload.get("priorities", {})
        if not isinstance(priorities, Mapping):
            raise ValueError("priorities must be an object")
        plan = update_general_manager_plan(
            loaded.state,
            current,
            direction=str(payload.get("direction", current.direction)),
            evaluation_horizon=_integer(
                payload,
                "evaluation_horizon",
                default=current.evaluation_horizon,
                minimum=1,
                maximum=5,
            ),
            automation_enabled=bool(
                payload.get("automation_enabled", current.automation_enabled)
            ),
            priorities=priorities,
        )
        updated = self.franchise_repository.append_event(
            save_id,
            event_type=LeagueEventType.GM_PLAN_UPDATED,
            payload={"plan": plan.as_dict(), "manual": True},
            actor=loaded.state.user_team,
        )
        return self._franchise_response(updated)

    def configure_franchise_experience(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        save_id = str(payload.get("save_id", "")).strip()
        if not save_id:
            raise ValueError("save_id is required")
        loaded = self.franchise_repository.load(save_id)
        experience = configured_experience(
            loaded.state,
            preset=str(payload.get("preset", "guided")),
            difficulty=str(payload.get("difficulty", "pro")),
            contextual_help=bool(payload.get("contextual_help", True)),
            confirm_consequential_moves=bool(
                payload.get("confirm_consequential_moves", True)
            ),
            show_advanced_by_default=bool(
                payload.get("show_advanced_by_default", False)
            ),
        )
        loaded = self.franchise_repository.append_event(
            save_id,
            event_type=LeagueEventType.EXPERIENCE_CONFIGURED,
            payload={
                "experience": experience.as_dict(),
                "model_version": PUBLIC_EXPERIENCE_MODEL_VERSION,
            },
            actor="user-experience",
        )
        preset = experience.preset
        gm = general_manager_plan(loaded.state, loaded.state.user_team)
        gm_automatic = preset != "full_control"
        if gm is not None and gm.automation_enabled != gm_automatic:
            gm = replace(
                gm,
                automation_enabled=gm_automatic,
                as_of_date=loaded.state.calendar.current_date,
                last_review_reason=f"{preset} experience preset",
            )
            loaded = self.franchise_repository.append_event(
                save_id,
                event_type=LeagueEventType.GM_PLAN_UPDATED,
                payload={"plan": gm.as_dict(), "experience_preset": preset},
                actor="user-experience",
            )
        roster = roster_plan(loaded.state, loaded.state.user_team)
        roster_delegation = {
            "guided": "automatic",
            "balanced": "recommend",
            "full_control": "manual",
        }[preset]
        if roster is not None and roster.delegation != roster_delegation:
            roster = replace(
                roster,
                delegation=roster_delegation,
                as_of_date=loaded.state.calendar.current_date,
                source=f"{preset}-experience-preset",
            )
            loaded = self.franchise_repository.append_event(
                save_id,
                event_type=LeagueEventType.ROSTER_PLAN_UPDATED,
                payload={"plan": roster.as_dict(), "experience_preset": preset},
                actor="user-experience",
            )
        department = next(
            (
                item for item in loaded.state.scouting_departments
                if item.team == loaded.state.user_team
            ),
            None,
        )
        scouting_automatic = preset != "full_control"
        if department is not None and department.automation_enabled != scouting_automatic:
            department = replace(
                department,
                automation_enabled=scouting_automatic,
                as_of_date=loaded.state.calendar.current_date,
            )
            loaded = self.franchise_repository.append_event(
                save_id,
                event_type=LeagueEventType.SCOUTING_DEPARTMENT_UPDATED,
                payload={"record": department.as_dict(), "experience_preset": preset},
                actor="user-experience",
            )
        response = self._franchise_response(loaded)
        response["experience_configuration"] = {
            "preset": preset,
            "difficulty": experience.difficulty,
            "ratings_modified": False,
            "resulting_revision": loaded.state.revision,
        }
        return response

    def franchise_playtest_audit(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        save_id = str(payload.get("save_id", "")).strip()
        if not save_id:
            raise ValueError("save_id is required")
        loaded = self.franchise_repository.load(save_id)
        audit = public_release_audit(
            loaded.state,
            integrity_verified=True,
        )
        audit["save_id"] = save_id
        audit["save_name"] = loaded.metadata.name
        audit["revision"] = loaded.state.revision
        audit["tester_report"] = self._tester_report(loaded, audit)
        return audit

    @staticmethod
    def _tester_report(
        loaded: LoadedFranchise,
        audit: Mapping[str, object],
    ) -> str:
        checks = audit.get("checks", [])
        check_lines = [
            f"- [{str(item.get('status', '')).upper()}] {item.get('label')}: {item.get('detail')}"
            for item in checks
            if isinstance(item, Mapping)
        ]
        return "\n".join((
            "NBA Sim external playtest report",
            f"Save: {loaded.metadata.name} / {loaded.metadata.branch_name}",
            f"Team: {loaded.state.user_team}",
            f"Season: {loaded.state.season}",
            f"Revision: {loaded.state.revision}",
            f"Seed: {loaded.state.seed}",
            f"Readiness: {'READY' if audit.get('ready_for_playtest') else 'NEEDS ATTENTION'}",
            "",
            *check_lines,
            "",
            "Reproduction: include the save name, branch, revision, seed, action, and visible error text.",
        ))

    def _refresh_gm_plans(
        self,
        loaded: LoadedFranchise,
        *,
        reason: str,
        force: bool = False,
    ) -> LoadedFranchise:
        if not loaded.state.gm_plans:
            return loaded
        plans = build_league_general_manager_plans(
            loaded.state,
            previous=loaded.state.gm_plans,
            reason=reason,
        )
        if not force and plans == loaded.state.gm_plans:
            return loaded
        return self.franchise_repository.append_event(
            loaded.metadata.save_id,
            event_type=LeagueEventType.GM_PLANS_REVIEWED,
            payload={
                "plans": [item.as_dict() for item in plans],
                "reason": reason,
                "automatic": not force,
                "model_version": GM_INTELLIGENCE_MODEL_VERSION,
            },
            actor="league-front-offices",
        )

    def initialize_roster_operations(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        save_id = str(payload.get("save_id", "")).strip()
        if not save_id:
            raise ValueError("save_id is required")
        loaded = self.franchise_repository.load(save_id)
        if loaded.state.roster_plans:
            return self._franchise_response(loaded)
        initialized = self.franchise_repository.append_event(
            save_id,
            event_type=LeagueEventType.ROSTER_OPERATIONS_INITIALIZED,
            payload={
                "plans": [
                    item.as_dict()
                    for item in build_league_roster_plans(loaded.state)
                ],
                "model_version": ROSTER_OPERATIONS_MODEL_VERSION,
            },
            actor="basketball-operations",
        )
        return self._franchise_response(initialized)

    def optimize_roster_plan(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        loaded = self._roster_operations_loaded(payload)
        current = roster_plan(loaded.state, loaded.state.user_team)
        assert current is not None
        delegation = str(payload.get("delegation", current.delegation))
        objective = str(payload.get("objective", current.objective))
        optimized = build_roster_plan(
            loaded.state,
            loaded.state.user_team,
            delegation=delegation,
            objective=objective,
            preserve=current,
        )
        updated = self.franchise_repository.append_event(
            loaded.metadata.save_id,
            event_type=LeagueEventType.ROSTER_PLAN_UPDATED,
            payload={"plan": optimized.as_dict(), "automatic": False},
            actor="coaching-staff",
        )
        return self._franchise_response(updated)

    def save_roster_plan(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        loaded = self._roster_operations_loaded(payload)
        current = roster_plan(loaded.state, loaded.state.user_team)
        assert current is not None
        assignments = payload.get("assignments")
        if not isinstance(assignments, list):
            raise ValueError("assignments must be a list")
        plan = update_roster_plan(
            loaded.state,
            current,
            assignments=assignments,
            delegation=str(payload.get("delegation", current.delegation)),
            objective=str(payload.get("objective", current.objective)),
        )
        updated = self.franchise_repository.append_event(
            loaded.metadata.save_id,
            event_type=LeagueEventType.ROSTER_PLAN_UPDATED,
            payload={"plan": plan.as_dict(), "automatic": False},
            actor="user",
        )
        return self._franchise_response(updated)

    def _roster_operations_loaded(
        self,
        payload: Mapping[str, Any],
    ) -> LoadedFranchise:
        save_id = str(payload.get("save_id", "")).strip()
        if not save_id:
            raise ValueError("save_id is required")
        loaded = self.franchise_repository.load(save_id)
        if not loaded.state.roster_plans:
            raise ValueError("initialize Roster & Rotation first")
        return loaded

    def _restore_roster_operations(
        self,
        loaded: LoadedFranchise,
    ) -> LoadedFranchise:
        if loaded.state.roster_plans:
            return loaded
        return self.franchise_repository.append_event(
            loaded.metadata.save_id,
            event_type=LeagueEventType.ROSTER_OPERATIONS_INITIALIZED,
            payload={
                "plans": [
                    item.as_dict()
                    for item in build_league_roster_plans(loaded.state)
                ],
                "model_version": ROSTER_OPERATIONS_MODEL_VERSION,
                "reason": "roster movement",
            },
            actor="basketball-operations",
        )

    def _refresh_automatic_roster_plan(
        self,
        loaded: LoadedFranchise,
    ) -> LoadedFranchise:
        current = roster_plan(loaded.state, loaded.state.user_team)
        if current is None or current.delegation != "automatic":
            return loaded
        optimized = build_roster_plan(
            loaded.state,
            loaded.state.user_team,
            delegation=current.delegation,
            objective=current.objective,
            preserve=current,
        )
        return self.franchise_repository.append_event(
            loaded.metadata.save_id,
            event_type=LeagueEventType.ROSTER_PLAN_UPDATED,
            payload={"plan": optimized.as_dict(), "automatic": True},
            actor="coaching-staff",
        )

    def initialize_franchise_season(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        save_id = str(payload.get("save_id", "")).strip()
        if not save_id:
            raise ValueError("save_id is required")
        loaded = self.franchise_repository.load(save_id)
        if loaded.state.season_cycle is not None:
            return self._franchise_response(loaded)
        cycle = initialize_season_cycle(
            season=loaded.state.season,
            start=loaded.state.calendar.regular_season_start,
            end=loaded.state.calendar.regular_season_end,
            seed=loaded.state.seed,
            current=loaded.state.calendar.current_date,
        )
        initialized = self.franchise_repository.append_event(
            save_id,
            event_type=LeagueEventType.SEASON_CYCLE_INITIALIZED,
            payload={
                "season_cycle": cycle.as_dict(),
                "model_version": SEASON_CYCLE_MODEL_VERSION,
            },
            actor="league-office",
        )
        return self._franchise_response(initialized)

    def simulate_franchise_games(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        save_id = str(payload.get("save_id", "")).strip()
        if not save_id:
            raise ValueError("save_id is required")
        loaded = self.franchise_repository.load(save_id)
        cycle = loaded.state.season_cycle
        if cycle is None:
            raise ValueError("initialize the Season Hub first")
        if cycle.status in {"postseason", "offseason", "complete"}:
            raise ValueError("the regular season is complete")
        scope = str(payload.get("scope", "next_user_game"))
        scheduled = games_to_simulate(
            cycle,
            user_team=loaded.state.user_team,
            scope=scope,
        )
        if not scheduled:
            raise ValueError("there are no regular-season games left to simulate")

        completed, health, injuries = self._execute_franchise_game_batch(
            loaded,
            scheduled,
            workers=1 if getattr(self, "deployment_mode", "local") == "vercel-full" else None,
        )
        target = max(item.game_date for item in completed)
        updated = self.franchise_repository.append_event(
            save_id,
            event_type=LeagueEventType.SEASON_GAMES_SIMULATED,
            payload={
                "games": [item.as_dict() for item in completed],
                "scope": scope,
                "to_date": target.isoformat(),
                "health_records": [item.as_dict() for item in health.values()],
                "injury_records": [item.as_dict() for item in injuries],
                "model_version": SEASON_CYCLE_MODEL_VERSION,
            },
            occurred_on=target,
            actor="league-simulator",
        )
        updated = self._refresh_gm_plans(
            updated,
            reason="season checkpoint",
        )
        updated = self._refresh_automatic_roster_plan(updated)
        response = self._franchise_response(updated)
        response["season_simulation"] = {
            "games_completed": len(completed),
            "through_date": target.isoformat(),
            "new_injuries": [
                item.as_dict()
                for item in injuries
                if item.injury_id not in {value.injury_id for value in loaded.state.injuries}
            ],
            "user_games": [
                item.as_dict(include_box_score=False)
                for item in completed
                if loaded.state.user_team in {item.home_team, item.away_team}
            ],
        }
        return response

    def start_franchise_season_simulation(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        save_id = str(payload.get("save_id", "")).strip()
        if not save_id:
            raise ValueError("save_id is required")
        loaded = self.franchise_repository.load(save_id)
        cycle = loaded.state.season_cycle
        if cycle is None:
            raise ValueError("initialize the Season Hub first")
        if cycle.status in {"postseason", "offseason", "complete"}:
            raise ValueError("the regular season is complete")
        scope = str(payload.get("scope", "next_user_game"))
        scheduled = games_to_simulate(
            cycle,
            user_team=loaded.state.user_team,
            scope=scope,
        )
        if not scheduled:
            raise ValueError("there are no regular-season games left to simulate")
        with self._franchise_season_job_lock:
            active = next(
                (
                    item for item in self._franchise_season_jobs.values()
                    if item.save_id == save_id
                    and item.status in {"preparing", "running", "saving"}
                ),
                None,
            )
            if active is not None:
                return self._franchise_season_job_response(active)
            job = FranchiseSeasonSimulationJob(
                job_id=f"franchise-season-{secrets.token_hex(10)}",
                save_id=save_id,
                scope=scope,
                total_games=len(scheduled),
            )
            self._franchise_season_jobs[job.job_id] = job
        threading.Thread(
            target=self._run_franchise_season_job,
            args=(job.job_id, loaded, scheduled),
            daemon=True,
            name=f"nba-franchise-season-{job.job_id[-6:]}",
        ).start()
        return self._franchise_season_job_response(job)

    def start_franchise_postseason_simulation(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        save_id = str(payload.get("save_id", "")).strip()
        if not save_id:
            raise ValueError("save_id is required")
        scope = str(payload.get("scope", "next_round")).strip().lower()
        if scope not in {"next_round", "all"}:
            raise ValueError("scope must be next_round or all")
        loaded = self.franchise_repository.load(save_id)
        cycle = loaded.state.season_cycle
        if cycle is None or cycle.status != "postseason":
            raise ValueError("complete the regular season before starting the postseason")
        previous_index = POSTSEASON_ROUNDS.index(cycle.postseason_round) if cycle.postseason_round else -1
        remaining = POSTSEASON_ROUNDS[previous_index + 1:]
        if scope == "next_round":
            remaining = remaining[:1]
        maximum_games = {
            "play_in": 6,
            "first_round": 56,
            "conference_semifinals": 28,
            "conference_finals": 14,
            "nba_finals": 7,
        }
        with self._franchise_season_job_lock:
            active = next(
                (
                    item for item in self._franchise_season_jobs.values()
                    if item.save_id == save_id
                    and item.status in {"preparing", "running", "saving"}
                ),
                None,
            )
            if active is not None:
                return self._franchise_season_job_response(active)
            job = FranchiseSeasonSimulationJob(
                job_id=f"franchise-postseason-{secrets.token_hex(10)}",
                save_id=save_id,
                scope=f"postseason:{scope}",
                total_games=sum(maximum_games[item] for item in remaining),
            )
            self._franchise_season_jobs[job.job_id] = job
        threading.Thread(
            target=self._run_franchise_postseason_job,
            args=(job.job_id, loaded, scope),
            daemon=True,
            name=f"nba-franchise-postseason-{job.job_id[-6:]}",
        ).start()
        return self._franchise_season_job_response(job)

    def franchise_season_simulation_progress(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        job_id = str(payload.get("job_id", "")).strip()
        with self._franchise_season_job_lock:
            job = self._franchise_season_jobs.get(job_id)
            if job is None:
                raise KeyError("franchise season job is no longer loaded")
            return self._franchise_season_job_response(job, include_result=True)

    def cancel_franchise_season_simulation(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        job_id = str(payload.get("job_id", "")).strip()
        with self._franchise_season_job_lock:
            job = self._franchise_season_jobs.get(job_id)
            if job is None:
                raise KeyError("franchise season job is no longer loaded")
            if job.status in {"preparing", "running"}:
                job.cancel_requested = True
            return self._franchise_season_job_response(job)

    def _run_franchise_season_job(
        self,
        job_id: str,
        loaded: LoadedFranchise,
        scheduled: tuple[SeasonGameRecord, ...],
    ) -> None:
        with self._franchise_season_job_lock:
            job = self._franchise_season_jobs[job_id]
            job.status = "running"

        def progress(completed_count: int, game: SeasonGameRecord) -> None:
            with self._franchise_season_job_lock:
                current = self._franchise_season_jobs[job_id]
                current.completed_games = completed_count
                current.current_game_id = game.game_id
                current.current_game_date = game.game_date
                current.current_home_team = game.home_team
                current.current_away_team = game.away_team

        def cancelled() -> bool:
            with self._franchise_season_job_lock:
                return self._franchise_season_jobs[job_id].cancel_requested

        try:
            completed, health, injuries = self._execute_franchise_game_batch(
                loaded,
                scheduled,
                progress=progress,
                cancelled=cancelled,
                workers=1 if getattr(self, "deployment_mode", "local") == "vercel-full" else None,
            )
            if cancelled():
                with self._franchise_season_job_lock:
                    self._franchise_season_jobs[job_id].status = "cancelled"
                return
            with self._franchise_season_job_lock:
                self._franchise_season_jobs[job_id].status = "saving"
            target = max(item.game_date for item in completed)
            updated = self.franchise_repository.append_event(
                loaded.metadata.save_id,
                event_type=LeagueEventType.SEASON_GAMES_SIMULATED,
                payload={
                    "games": [item.as_dict() for item in completed],
                    "scope": self._franchise_season_jobs[job_id].scope,
                    "to_date": target.isoformat(),
                    "health_records": [item.as_dict() for item in health.values()],
                    "injury_records": [item.as_dict() for item in injuries],
                    "model_version": SEASON_CYCLE_MODEL_VERSION,
                },
                occurred_on=target,
                actor="league-simulator",
            )
            updated = self._refresh_gm_plans(
                updated,
                reason="season checkpoint",
            )
            updated = self._refresh_automatic_roster_plan(updated)
            response = self._franchise_response(updated)
            response["season_simulation"] = {
                "games_completed": len(completed),
                "through_date": target.isoformat(),
                "new_injuries": [
                    item.as_dict()
                    for item in injuries
                    if item.injury_id not in {value.injury_id for value in loaded.state.injuries}
                ],
                "user_games": [
                    item.as_dict(include_box_score=False)
                    for item in completed
                    if loaded.state.user_team in {item.home_team, item.away_team}
                ],
            }
            with self._franchise_season_job_lock:
                job = self._franchise_season_jobs[job_id]
                job.completed_games = len(completed)
                job.status = "completed"
                job.result = response
        except Exception as error:
            if str(error) == "franchise season simulation cancelled":
                with self._franchise_season_job_lock:
                    self._franchise_season_jobs[job_id].status = "cancelled"
                return
            LOGGER.exception(
                "franchise season job failed",
                extra={
                    "job_id": job_id,
                    "save_id": getattr(getattr(loaded, "metadata", None), "save_id", None),
                },
            )
            with self._franchise_season_job_lock:
                job = self._franchise_season_jobs[job_id]
                job.status = "failed"
                job.error = str(error)

    def _run_franchise_postseason_job(
        self,
        job_id: str,
        loaded: LoadedFranchise,
        scope: str,
    ) -> None:
        with self._franchise_season_job_lock:
            self._franchise_season_jobs[job_id].status = "running"
        completed_count = 0
        rounds: list[dict[str, object]] = []

        def progress(_: int, game: SeasonGameRecord) -> None:
            nonlocal completed_count
            completed_count += 1
            with self._franchise_season_job_lock:
                current = self._franchise_season_jobs[job_id]
                current.completed_games = completed_count
                current.current_game_id = game.game_id
                current.current_game_date = game.game_date
                current.current_home_team = game.home_team
                current.current_away_team = game.away_team

        def cancelled() -> bool:
            with self._franchise_season_job_lock:
                return self._franchise_season_jobs[job_id].cancel_requested

        try:
            while loaded.state.season_cycle is not None and loaded.state.season_cycle.status == "postseason":
                loaded, summary = self._simulate_franchise_postseason_round(
                    loaded,
                    progress=progress,
                    cancelled=cancelled,
                )
                rounds.append(summary)
                if cancelled() or scope == "next_round":
                    break
            if cancelled():
                with self._franchise_season_job_lock:
                    self._franchise_season_jobs[job_id].status = "cancelled"
                return
            response = self._franchise_response(loaded)
            response["postseason_simulation"] = {
                "rounds": rounds,
                "games_completed": completed_count,
                "champion": loaded.state.season_cycle.champion if loaded.state.season_cycle else None,
                "awards": dict(loaded.state.season_cycle.awards) if loaded.state.season_cycle else {},
            }
            with self._franchise_season_job_lock:
                job = self._franchise_season_jobs[job_id]
                job.total_games = completed_count
                job.completed_games = completed_count
                job.status = "completed"
                job.result = response
        except RuntimeError as error:
            if str(error) == "franchise postseason simulation cancelled":
                with self._franchise_season_job_lock:
                    self._franchise_season_jobs[job_id].status = "cancelled"
                return
            with self._franchise_season_job_lock:
                job = self._franchise_season_jobs[job_id]
                job.status = "failed"
                job.error = str(error)
        except Exception as error:
            with self._franchise_season_job_lock:
                job = self._franchise_season_jobs[job_id]
                job.status = "failed"
                job.error = str(error)
        except Exception as error:
            with self._franchise_season_job_lock:
                job = self._franchise_season_jobs[job_id]
                job.status = "failed"
                job.error = str(error)

    def _execute_franchise_game_batch(
        self,
        loaded: LoadedFranchise,
        scheduled: tuple[SeasonGameRecord, ...],
        *,
        progress: Any | None = None,
        cancelled: Any | None = None,
        workers: int | None = None,
    ) -> tuple[
        list[SeasonGameRecord],
        dict[int, object],
        tuple[InjuryRecord, ...],
    ]:
        health = {item.player_id: item for item in loaded.state.player_health}
        injuries: tuple[InjuryRecord, ...] = loaded.state.injuries
        players = {item.player_id: item for item in loaded.state.players}
        lifecycles = {item.player_id: item for item in loaded.state.player_lifecycles}
        health_date = loaded.state.calendar.current_date
        streams = RandomStreamFactory(loaded.state.seed)
        completed: list[SeasonGameRecord] = []
        worker_count = max(
            1,
            min(
                workers if workers is not None else (os.cpu_count() or 1),
                8,
                len(scheduled),
            ),
        )
        executor = (
            ProcessPoolExecutor(max_workers=worker_count)
            if worker_count > 1
            else None
        )
        try:
            for game_date, dated_iter in groupby(
                scheduled,
                key=lambda item: item.game_date,
            ):
                if cancelled is not None and cancelled():
                    raise RuntimeError("franchise season simulation cancelled")
                dated_games = tuple(dated_iter)
                if game_date > health_date and health:
                    health = {
                        item.player_id: item
                        for item in advance_health_records(
                            tuple(health.values()), target=game_date
                        )
                    }
                    health_date = game_date
                tasks = []
                for game in dated_games:
                    simulator = self._franchise_season_simulator(
                        loaded,
                        home_team=game.home_team,
                        away_team=game.away_team,
                        health=tuple(health.values()),
                    )
                    tasks.append((
                        game,
                        simulator,
                        streams.seed_for(f"franchise-season:{game.game_id}"),
                    ))
                day_results: list[SeasonGameRecord] = []
                if executor is None:
                    for task in tasks:
                        result = _simulate_prepared_franchise_game(task)
                        day_results.append(result)
                        if progress is not None:
                            progress(len(completed) + len(day_results), result)
                else:
                    futures = {
                        executor.submit(_simulate_prepared_franchise_game, task): task[0]
                        for task in tasks
                    }
                    for future in as_completed(futures):
                        result = future.result()
                        day_results.append(result)
                        if progress is not None:
                            progress(len(completed) + len(day_results), result)
                        if cancelled is not None and cancelled():
                            for pending in futures:
                                pending.cancel()
                            raise RuntimeError("franchise season simulation cancelled")
                day_results.sort(key=lambda item: item.game_id)
                for result in day_results:
                    for box in result.box_scores:
                        if box.player_id in health:
                            health[box.player_id] = apply_workload(
                                health[box.player_id],
                                occurred_on=result.game_date,
                                minutes=box.minutes,
                                intensity=1.0,
                            )
                    health_updates, new_injuries = sample_game_injuries(
                        game_id=result.game_id,
                        occurred_on=result.game_date,
                        player_minutes={box.player_id: box.minutes for box in result.box_scores},
                        players=players,
                        lifecycles=lifecycles,
                        health=health,  # type: ignore[arg-type]
                        injury_history=injuries,
                        seed=loaded.state.seed,
                    )
                    for item in health_updates:
                        health[item.player_id] = item
                    injuries = (*injuries, *new_injuries)
                completed.extend(day_results)
                injuries = reconcile_injury_history(
                    injuries,
                    health=health,  # type: ignore[arg-type]
                    games=day_results,
                )
        finally:
            if executor is not None:
                executor.shutdown(wait=True, cancel_futures=True)
        return completed, health, injuries

    def _franchise_season_job_response(
        self,
        job: FranchiseSeasonSimulationJob,
        *,
        include_result: bool = False,
    ) -> dict[str, object]:
        elapsed = max(0.0, time.monotonic() - job.started_at)
        rate = job.completed_games / elapsed if elapsed > 0 else 0.0
        remaining = max(0, job.total_games - job.completed_games)
        eta = remaining / rate if rate > 0 else None
        response: dict[str, object] = {
            "kind": "franchise_season_job",
            "job_id": job.job_id,
            "save_id": job.save_id,
            "scope": job.scope,
            "status": job.status,
            "cancel_requested": job.cancel_requested,
            "completed_games": job.completed_games,
            "total_games": job.total_games,
            "progress": (
                job.completed_games / job.total_games
                if job.total_games
                else 0.0
            ),
            "elapsed_seconds": round(elapsed, 2),
            "games_per_second": round(rate, 3),
            "eta_seconds": round(eta, 2) if eta is not None else None,
            "current_game": (
                {
                    "game_id": job.current_game_id,
                    "date": job.current_game_date.isoformat() if job.current_game_date else None,
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

    def franchise_season_game(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        save_id = str(payload.get("save_id", "")).strip()
        game_id = str(payload.get("game_id", "")).strip()
        if not save_id or not game_id:
            raise ValueError("save_id and game_id are required")
        loaded = self.franchise_repository.load(save_id)
        if loaded.state.season_cycle is None:
            raise ValueError("initialize the Season Hub first")
        game = next(
            (item for item in loaded.state.season_cycle.games if item.game_id == game_id),
            None,
        )
        if game is None:
            raise KeyError(f"unknown franchise game: {game_id}")
        return {"kind": "franchise_season_game", **game.as_dict()}

    def franchise_statistics(self, payload: Mapping[str, Any]) -> dict[str, object]:
        from nba_sim.franchise.statistics import season_statistics
        save_id = str(payload.get("save_id", "")).strip()
        if not save_id:
            raise ValueError("save_id is required")
        loaded = self.franchise_repository.load(save_id)
        cycles = [*loaded.state.season_history]
        if loaded.state.season_cycle is not None:
            cycles.append(loaded.state.season_cycle)
        season = str(payload.get("season") or (cycles[-1].season if cycles else ""))
        cycle = next((item for item in cycles if item.season == season), None)
        if cycles and cycle is None:
            raise ValueError("Season is not available in this save")
        result = season_statistics(cycle, stage=str(payload.get("stage", "regular_season")),
                                  player_id=int(payload["player_id"]) if payload.get("player_id") is not None else None)
        return {**result, "seasons": [item.season for item in reversed(cycles)], "user_team": loaded.state.user_team}

    def simulate_franchise_postseason(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        save_id = str(payload.get("save_id", "")).strip()
        if not save_id:
            raise ValueError("save_id is required")
        scope = str(payload.get("scope", "all")).strip().lower()
        if scope not in {"next_round", "all"}:
            raise ValueError("scope must be next_round or all")
        loaded = self.franchise_repository.load(save_id)
        if loaded.state.season_cycle is None or loaded.state.season_cycle.status != "postseason":
            raise ValueError("complete the regular season before starting the postseason")
        rounds: list[dict[str, object]] = []
        while loaded.state.season_cycle is not None and loaded.state.season_cycle.status == "postseason":
            loaded, summary = self._simulate_franchise_postseason_round(loaded)
            rounds.append(summary)
            if scope == "next_round":
                break
        response = self._franchise_response(loaded)
        response["postseason_simulation"] = {
            "rounds": rounds,
            "games_completed": sum(int(item["games_completed"]) for item in rounds),
            "champion": loaded.state.season_cycle.champion if loaded.state.season_cycle else None,
            "awards": dict(loaded.state.season_cycle.awards) if loaded.state.season_cycle else {},
        }
        return response

    def advance_franchise_offseason(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        save_id = str(payload.get("save_id", "")).strip()
        expected_stage = str(payload.get("expected_stage", "")).strip()
        if not save_id or not expected_stage:
            raise ValueError("save_id and expected_stage are required")
        if expected_stage not in OFFSEASON_STAGES:
            raise ValueError("unknown offseason stage")
        loaded = self.franchise_repository.load(save_id)
        cycle = loaded.state.season_cycle
        if cycle is None or cycle.status != "offseason":
            raise ValueError("the offseason begins after the NBA Finals")
        current = cycle.offseason_stage or OFFSEASON_STAGES[0]
        if current != expected_stage:
            if OFFSEASON_STAGES.index(expected_stage) < OFFSEASON_STAGES.index(current):
                response = self._franchise_response(loaded)
                response["offseason_transition"] = {
                    "idempotent": True,
                    "completed_stage": expected_stage,
                    "current_stage": current,
                }
                return response
            raise ValueError(
                f"offseason stage changed; refresh and continue from {current.replace('_', ' ')}"
            )

        loaded = self._prepare_automatic_offseason_stage(loaded, current)
        readiness = offseason_stage_readiness(loaded.state, current)
        if not readiness["can_advance"]:
            raise ValueError(" ".join(str(item) for item in readiness["blockers"]))
        if current == "ready_for_next_season":
            return self._roll_franchise_season(loaded)

        assert loaded.state.season_cycle is not None
        advanced_cycle = advance_offseason_cycle(
            loaded.state.season_cycle,
            expected_stage=current,
        )
        event_payload: dict[str, object] = {
            "completed_stage": current,
            "season_cycle": advanced_cycle.as_dict(),
            "model_version": OFFSEASON_MODEL_VERSION,
        }
        if current == "player_progression":
            career = self._advanced_offseason_careers(loaded)
            event_payload["player_lifecycles"] = [
                item.as_dict() for item in career.lifecycles
            ]
            event_payload["players"] = [item.as_dict() for item in career.players]
            event_payload["contracts"] = [item.as_dict() for item in career.contracts]
            event_payload["career_decisions"] = [
                item.as_dict() for item in career.decisions
            ]
            event_payload["career_transactions"] = [
                item.as_dict() for item in career.transactions
            ]
        elif current == "training_camp":
            camp_state, plans, cuts = self._training_camp_state(loaded)
            event_payload["players"] = [item.as_dict() for item in camp_state.players]
            event_payload["contracts"] = [item.as_dict() for item in camp_state.contracts]
            event_payload["roster_plans"] = [item.as_dict() for item in plans]
            event_payload["training_camp_cuts"] = cuts

        updated = self.franchise_repository.append_event(
            save_id,
            event_type=LeagueEventType.OFFSEASON_STAGE_ADVANCED,
            payload=event_payload,
            actor=(
                "league-office"
                if current in {"awards_and_lottery", "combine_and_scouting"}
                else "basketball-operations"
            ),
        )
        response = self._franchise_response(updated)
        response["offseason_transition"] = {
            "idempotent": False,
            "completed_stage": current,
            "current_stage": advanced_cycle.offseason_stage,
        }
        return response

    def _prepare_automatic_offseason_stage(
        self,
        loaded: LoadedFranchise,
        stage: str,
    ) -> LoadedFranchise:
        if stage == "awards_and_lottery":
            if loaded.state.draft_ecosystem is None:
                self.initialize_draft_ecosystem({
                    "save_id": loaded.metadata.save_id,
                    "seed": season_seed(loaded.state.seed, loaded.state.season),
                })
                loaded = self.franchise_repository.load(loaded.metadata.save_id)
            if loaded.state.draft_ecosystem and not loaded.state.draft_ecosystem.order:
                self.run_draft_lottery({
                    "save_id": loaded.metadata.save_id,
                    "seed": season_seed(loaded.state.seed, f"{loaded.state.season}:lottery"),
                })
                loaded = self.franchise_repository.load(loaded.metadata.save_id)
        elif stage == "combine_and_scouting":
            if loaded.state.draft_ecosystem and not loaded.state.draft_ecosystem.combine_complete:
                self.run_draft_combine({"save_id": loaded.metadata.save_id})
                loaded = self.franchise_repository.load(loaded.metadata.save_id)
        return loaded

    def _advanced_offseason_careers(
        self,
        loaded: LoadedFranchise,
    ) -> object:
        cycle = loaded.state.season_cycle
        assert cycle is not None
        minutes: dict[int, float] = {}
        games: dict[int, int] = {}
        for game in cycle.games:
            if not game.completed:
                continue
            for box in game.box_scores:
                minutes[box.player_id] = minutes.get(box.player_id, 0.0) + box.minutes
                games[box.player_id] = games.get(box.player_id, 0) + 1
        missed = {item.player_id: item.games_missed for item in loaded.state.injuries}
        return advance_career_state(
            loaded.state,
            season_minutes=minutes,
            season_games=games,
            games_missed=missed,
        )

    def _advanced_offseason_lifecycles(
        self,
        loaded: LoadedFranchise,
    ) -> tuple[object, ...]:
        """Compatibility helper retained for callers that inspect progression."""
        return self._advanced_offseason_careers(loaded).lifecycles

    def _training_camp_state(
        self,
        loaded: LoadedFranchise,
    ) -> tuple[object, tuple[object, ...], list[dict[str, object]]]:
        lifecycle = {
            item.player_id: item for item in loaded.state.player_lifecycles
        }
        cut_ids: set[int] = set()
        cuts: list[dict[str, object]] = []
        guided = (
            loaded.state.experience is None
            or loaded.state.experience.preset == "guided"
        )
        for franchise in loaded.state.franchises:
            if franchise.team == loaded.state.user_team and not guided:
                continue
            roster = list(loaded.state.roster(franchise.team))
            roster.sort(
                key=lambda player: (
                    float(lifecycle[player.player_id].overall)
                    if player.player_id in lifecycle
                    else 50.0,
                    player.expected_minutes,
                    -player.player_id,
                ),
                reverse=True,
            )
            for player in roster[15:]:
                cut_ids.add(player.player_id)
                cuts.append({
                    "player_id": player.player_id,
                    "name": player.name,
                    "team": player.team,
                    "reason": "outside the 15-player regular-season roster",
                })
        players = tuple(
            replace(item, roster_status="free_agent")
            if item.player_id in cut_ids
            else item
            for item in loaded.state.players
        )
        contracts = tuple(
            replace(
                item,
                status="waived",
                source=f"{item.source}; training-camp-cut",
            )
            if item.player_id in cut_ids and item.status == "active"
            else item
            for item in loaded.state.contracts
        )
        camp_state = replace(
            loaded.state,
            players=players,
            contracts=contracts,
            roster_plans=(),
        )
        plans = build_league_roster_plans(camp_state)
        return camp_state, plans, cuts

    def _roll_franchise_season(
        self,
        loaded: LoadedFranchise,
    ) -> dict[str, object]:
        cycle = loaded.state.season_cycle
        assert cycle is not None
        next_value = next_season(loaded.state.season)
        dates = season_calendar_dates(next_value)
        calendar = LeagueCalendar(
            season=next_value,
            current_date=dates["cap_year_start"],
            **dates,
        )
        new_cycle = initialize_season_cycle(
            season=next_value,
            start=calendar.regular_season_start,
            end=calendar.regular_season_end,
            seed=season_seed(loaded.state.seed, next_value),
            current=calendar.current_date,
        )
        health = (
            advance_health_records(
                loaded.state.player_health,
                target=calendar.current_date,
            )
            if loaded.state.player_health
            else ()
        )
        updated = self.franchise_repository.append_event(
            loaded.metadata.save_id,
            event_type=LeagueEventType.SEASON_ROLLED_OVER,
            payload={
                "season": next_value,
                "archived_season": cycle.as_dict(),
                "calendar": calendar.as_dict(),
                "season_cycle": new_cycle.as_dict(),
                "player_health": [item.as_dict() for item in health],
                "model_version": OFFSEASON_MODEL_VERSION,
            },
            occurred_on=calendar.current_date,
            actor="league-office",
        )
        updated = self._refresh_gm_plans(
            updated,
            reason="new season organizational review",
            force=True,
        )
        response = self._franchise_response(updated)
        response["offseason_transition"] = {
            "idempotent": False,
            "completed_stage": "ready_for_next_season",
            "opened_season": next_value,
            "archived_seasons": len(updated.state.season_history),
        }
        return response

    def _simulate_franchise_postseason_round(
        self,
        loaded: LoadedFranchise,
        *,
        progress: Any | None = None,
        cancelled: Any | None = None,
    ) -> tuple[LoadedFranchise, dict[str, object]]:
        cycle = loaded.state.season_cycle
        if cycle is None or cycle.status != "postseason":
            raise ValueError("postseason is not active")
        previous_index = POSTSEASON_ROUNDS.index(cycle.postseason_round) if cycle.postseason_round else -1
        if previous_index + 1 >= len(POSTSEASON_ROUNDS):
            raise ValueError("postseason is already complete")
        round_name = POSTSEASON_ROUNDS[previous_index + 1]
        table = standings(cycle)
        seed_by_team = {
            str(row["team"]): index + 1
            for conference in ("East", "West")
            for index, row in enumerate(item for item in table if item["conference"] == conference)
        }
        health = {item.player_id: item for item in loaded.state.player_health}
        injuries: tuple[InjuryRecord, ...] = loaded.state.injuries
        initial_injury_ids = {item.injury_id for item in injuries}
        players = {item.player_id: item for item in loaded.state.players}
        lifecycles = {item.player_id: item for item in loaded.state.player_lifecycles}
        streams = RandomStreamFactory(loaded.state.seed)
        postseason: list[SeasonGameRecord] = []
        sequence = 1 + sum(item.stage in {"play_in", "playoffs"} for item in cycle.games)
        postseason_start = loaded.state.calendar.regular_season_end + timedelta(days=2)
        starts = {
            "play_in": postseason_start,
            "first_round": postseason_start + timedelta(days=6),
            "conference_semifinals": postseason_start + timedelta(days=22),
            "conference_finals": postseason_start + timedelta(days=38),
            "nba_finals": postseason_start + timedelta(days=54),
        }

        def play(
            home: str,
            away: str,
            stage: str,
            game_date: date,
            series_id: str,
            series_game_number: int,
        ) -> SeasonGameRecord:
            nonlocal sequence, health, injuries
            if cancelled is not None and cancelled():
                raise RuntimeError("franchise postseason simulation cancelled")
            participant_ids = {
                item.player_id
                for team in (home, away)
                for item in loaded.state.roster(team)
            }
            participants = tuple(item for player_id, item in health.items() if player_id in participant_ids)
            if participants:
                for item in advance_health_records(participants, target=game_date):
                    health[item.player_id] = item
            game = SeasonGameRecord(
                game_id=f"POST-{game_date.year}-{sequence:03d}",
                game_date=game_date,
                home_team=home,
                away_team=away,
                stage=stage,
                round_name=round_name,
                series_id=series_id,
                series_game_number=series_game_number,
            )
            simulator = self._franchise_season_simulator(
                loaded,
                home_team=home,
                away_team=away,
                health=tuple(health.values()),
            )
            game_seed = streams.seed_for(f"franchise-postseason:{game.game_id}")
            result = simulator.simulate(seed=game_seed)
            possessions = sum(event.event_type is EventType.POSSESSION_STARTED for event in result.events) / 2.0
            boxes = tuple(
                SeasonBoxScoreRecord.from_dict(item.as_dict())
                for item in result.box_scores.values()
                if item.minutes > 0
            )
            completed = replace(
                game,
                completed=True,
                home_score=result.home_score,
                away_score=result.away_score,
                possessions=round(possessions, 2),
                seed=game_seed,
                box_scores=boxes,
            )
            postseason.append(completed)
            if progress is not None:
                progress(len(postseason), completed)
            for box in boxes:
                if box.player_id in health:
                    health[box.player_id] = apply_workload(
                        health[box.player_id],
                        occurred_on=game_date,
                        minutes=box.minutes,
                        intensity=1.08,
                    )
            health_updates, new_injuries = sample_game_injuries(
                game_id=completed.game_id,
                occurred_on=completed.game_date,
                player_minutes={box.player_id: box.minutes for box in boxes},
                players=players,
                lifecycles=lifecycles,
                health=health,
                injury_history=injuries,
                seed=loaded.state.seed,
            )
            for item in health_updates:
                health[item.player_id] = item
            injuries = reconcile_injury_history(
                (*injuries, *new_injuries),
                health=health,
                games=(completed,),
            )
            sequence += 1
            return completed

        def play_in_game(home: str, away: str, series_id: str, offset: int) -> str:
            result = play(home, away, "play_in", starts[round_name] + timedelta(days=offset), series_id, 1)
            assert result.winner is not None
            return result.winner

        def series(
            first: tuple[str, int],
            second: tuple[str, int],
            series_id: str,
            *,
            home_court_team: str | None = None,
        ) -> tuple[str, int]:
            if home_court_team is not None:
                high, low = (first, second) if first[0] == home_court_team else (second, first)
            else:
                high, low = (first, second) if first[1] < second[1] else (second, first)
            wins = {high[0]: 0, low[0]: 0}
            pattern = (high[0], high[0], low[0], low[0], high[0], low[0], high[0])
            index = 0
            while max(wins.values()) < 4:
                home = pattern[index]
                away = low[0] if home == high[0] else high[0]
                result = play(
                    home, away, "playoffs",
                    starts[round_name] + timedelta(days=index * 2),
                    series_id, index + 1,
                )
                assert result.winner is not None
                wins[result.winner] += 1
                index += 1
            return high if wins[high[0]] == 4 else low

        def prior_winner(series_id: str) -> tuple[str, int]:
            games = [item for item in cycle.games if item.series_id == series_id]
            if not games:
                raise ValueError(f"missing prerequisite playoff series: {series_id}")
            wins = {
                team: sum(item.winner == team for item in games)
                for team in {value for item in games for value in (item.home_team, item.away_team)}
            }
            winner = max(wins, key=wins.get)
            return winner, seed_by_team[winner]

        if round_name == "play_in":
            for conference, prefix in (("East", "E"), ("West", "W")):
                seeds = [item for item in table if item["conference"] == conference]
                seven = str(seeds[6]["team"]); eight = str(seeds[7]["team"])
                nine = str(seeds[8]["team"]); ten = str(seeds[9]["team"])
                seventh = play_in_game(seven, eight, f"{prefix}-PI-78", 0)
                lower = play_in_game(nine, ten, f"{prefix}-PI-910", 0)
                loser = eight if seventh == seven else seven
                play_in_game(loser, lower, f"{prefix}-PI-8", 2)
        elif round_name == "first_round":
            for conference, prefix in (("East", "E"), ("West", "W")):
                seeds = [item for item in table if item["conference"] == conference]
                seventh = prior_winner(f"{prefix}-PI-78")[0]
                eighth = prior_winner(f"{prefix}-PI-8")[0]
                seeded = {index + 1: (str(row["team"]), index + 1) for index, row in enumerate(seeds[:6])}
                seeded[7] = (seventh, 7); seeded[8] = (eighth, 8)
                for first, second, suffix in ((1, 8, "18"), (4, 5, "45"), (3, 6, "36"), (2, 7, "27")):
                    series(seeded[first], seeded[second], f"{prefix}-R1-{suffix}")
        elif round_name == "conference_semifinals":
            for prefix in ("E", "W"):
                series(prior_winner(f"{prefix}-R1-18"), prior_winner(f"{prefix}-R1-45"), f"{prefix}-SF-A")
                series(prior_winner(f"{prefix}-R1-36"), prior_winner(f"{prefix}-R1-27"), f"{prefix}-SF-B")
        elif round_name == "conference_finals":
            for prefix in ("E", "W"):
                series(prior_winner(f"{prefix}-SF-A"), prior_winner(f"{prefix}-SF-B"), f"{prefix}-CF")
        else:
            east, west = prior_winner("E-CF"), prior_winner("W-CF")
            table_by_team = {str(row["team"]): row for row in table}
            home_court = max(
                (east[0], west[0]),
                key=lambda team: (
                    float(table_by_team[team]["win_percentage"]),
                    int(table_by_team[team]["point_differential"]),
                ),
            )
            series(east, west, "NBA-F", home_court_team=home_court)

        completed_cycle = replace(cycle, games=(*cycle.games, *postseason), postseason_round=round_name)
        honors = cycle.honors or build_regular_season_honors(loaded.state, completed_cycle)
        awards = dict(cycle.awards)
        for honor in honors:
            if honor.kind != "honors_team" and honor.recipients:
                awards.setdefault(honor.key, honor.recipients[0].name)
        champion = None
        status = "postseason"
        offseason_stage = cycle.offseason_stage
        if round_name == "conference_finals":
            for prefix, label, champion_key in (
                ("E", "eastern_conference_finals_mvp", "eastern_conference_champion"),
                ("W", "western_conference_finals_mvp", "western_conference_champion"),
            ):
                games = [item for item in completed_cycle.games if item.series_id == f"{prefix}-CF"]
                teams = {team for item in games for team in (item.home_team, item.away_team)}
                winner = max(
                    teams,
                    key=lambda team: sum(item.winner == team for item in games),
                )
                awards[champion_key] = winner
                mvp = postseason_round_mvp(completed_cycle, round_name, teams={winner})
                if mvp:
                    awards[label] = str(mvp["name"])
        elif round_name == "nba_finals":
            final_games = [item for item in completed_cycle.games if item.series_id == "NBA-F"]
            teams = {team for item in final_games for team in (item.home_team, item.away_team)}
            champion = max(teams, key=lambda team: sum(item.winner == team for item in final_games))
            awards["champion"] = champion
            mvp = postseason_round_mvp(completed_cycle, round_name, teams={champion})
            if mvp:
                awards["finals_mvp"] = str(mvp["name"])
            status = "offseason"
            offseason_stage = "awards_and_lottery"
        completed_cycle = replace(
            completed_cycle,
            status=status,
            champion=champion or cycle.champion,
            offseason_stage=offseason_stage,
            awards=tuple(awards.items()),
            honors=honors,
        )
        target = max(item.game_date for item in postseason)
        updated = self.franchise_repository.append_event(
            loaded.metadata.save_id,
            event_type=LeagueEventType.SEASON_STAGE_ADVANCED,
            payload={
                "season_cycle": completed_cycle.as_dict(),
                "to_date": target.isoformat(),
                "health_records": [item.as_dict() for item in health.values()],
                "injury_records": [item.as_dict() for item in injuries],
                "model_version": SEASON_CYCLE_MODEL_VERSION,
            },
            occurred_on=target,
            actor="league-simulator",
        )
        if round_name == "nba_finals":
            updated = self._refresh_gm_plans(updated, reason="postseason and ownership review")
        return updated, {
            "round": round_name,
            "games_completed": len(postseason),
            "champion": champion,
            "new_injuries": sum(
                item.injury_id not in initial_injury_ids for item in injuries
            ),
        }

    def _franchise_season_simulator(
        self,
        loaded: LoadedFranchise,
        *,
        home_team: str,
        away_team: str,
        health: tuple[object, ...],
    ) -> GameSimulator:
        health_by_team = {}
        for team in (home_team, away_team):
            player_ids = {item.player_id for item in loaded.state.roster(team)}
            health_by_team[team] = availability_policy(
                item for item in health if item.player_id in player_ids
            )

        def prepared(team: str) -> TeamProfile:
            plan = roster_plan(loaded.state, team)
            profile = apply_roster_plan(
                self._franchise_team_profile(loaded, team),
                plan,
            )
            medical_out, limits = health_by_team[team]
            inactive = tuple(sorted(set((*medical_out, *roster_inactive_player_ids(plan)))))
            profile = condition_team_profile(
                profile,
                inactive_player_ids=inactive,
                minute_limits={player_id: limit for player_id, limit in limits.items() if player_id not in inactive},
            )
            chemistry = next((item for item in loaded.state.team_chemistry if item.team == team), None)
            coaching = next((item for item in loaded.state.coaching_profiles if item.team == team), None)
            if chemistry is not None and coaching is not None:
                profile = apply_team_environment(profile, chemistry=chemistry, coaching=coaching)
            return profile

        return GameSimulator(home_team=prepared(home_team), away_team=prepared(away_team))

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
        if days >= 7:
            advanced = self._refresh_gm_plans(
                advanced,
                reason="weekly roster, cap, health and market audit",
            )
        advanced = self._restore_roster_operations(advanced)
        advanced = self._refresh_automatic_roster_plan(advanced)
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
            draft_year=int(loaded.state.season.split("-", 1)[0]) + 1,
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
        scouting_quality, position_needs, risk_tolerance = self._draft_cpu_context(state)
        draft = make_next_pick(
            state.draft_ecosystem,
            user_team=state.user_team,
            player_id=player_id,
            seed=state.seed,
            team_scouting_quality=scouting_quality,
            team_position_needs=position_needs,
            team_risk_tolerance=risk_tolerance,
        )
        selection = draft.selections[-1]
        event_payload: dict[str, object] = {
            "draft": draft.as_dict(),
            "selection": selection.as_dict(),
        }
        if draft.status == "complete":
            event_payload["draft_intake"] = self._draft_intake_payload(
                state,
                draft,
            )
        updated = self.franchise_repository.append_event(
            loaded.metadata.save_id,
            event_type=LeagueEventType.DRAFT_PICK_MADE,
            payload=event_payload,
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
        scouting_quality, position_needs, risk_tolerance = self._draft_cpu_context(state)
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
                team_scouting_quality=scouting_quality,
                team_position_needs=position_needs,
                team_risk_tolerance=risk_tolerance,
            )
            made.append(draft.selections[-1].as_dict())
        if not made:
            if draft.status == "complete":
                raise ValueError("the draft is complete")
            raise ValueError("your team is already on the clock")
        event_payload: dict[str, object] = {"draft": draft.as_dict(), "selections": made}
        if draft.status == "complete":
            event_payload["draft_intake"] = self._draft_intake_payload(
                state,
                draft,
            )
        updated = self.franchise_repository.append_event(
            loaded.metadata.save_id,
            event_type=LeagueEventType.DRAFT_PICK_MADE,
            payload=event_payload,
            actor="cpu-general-managers",
        )
        return self._franchise_response(updated)

    def _draft_intake_payload(
        self,
        state: object,
        draft: object,
    ) -> dict[str, object]:
        intake = materialize_draft_intake(
            draft,
            teams=(item.team for item in state.franchises),
            incoming_season=next_season(state.season),
            occurred_on=state.calendar.current_date,
        )
        return {
            "players": [item.as_dict() for item in intake.players],
            "player_lifecycles": [item.as_dict() for item in intake.lifecycles],
            "player_health": [item.as_dict() for item in intake.health],
            "scouting_reports": [item.as_dict() for item in intake.scouting_reports],
            "contracts": [item.as_dict() for item in intake.contracts],
            "draft_year": draft.draft_year,
        }

    def _draft_cpu_context(
        self,
        state: object,
    ) -> tuple[dict[str, float], dict[str, dict[str, float]], dict[str, str]]:
        lifecycles = {item.player_id: item for item in state.player_lifecycles}
        position_needs: dict[str, dict[str, float]] = {}
        for franchise in state.franchises:
            roster = state.roster(franchise.team)
            needs: dict[str, float] = {}
            for position in ("PG", "SG", "SF", "PF", "C"):
                marker = "G" if position in {"PG", "SG"} else "F" if position in {"SF", "PF"} else "C"
                values = sorted(
                    (
                        lifecycles[player.player_id].overall
                        for player in roster
                        if marker in player.position.upper()
                        and player.player_id in lifecycles
                    ),
                    reverse=True,
                )[:2]
                position_strength = sum(values) / len(values) if values else 60.0
                needs[position] = max(0.0, min(3.0, (79.0 - position_strength) / 6.5))
            position_needs[franchise.team] = needs
        return (
            {item.team: item.evaluation_quality for item in state.scouting_departments},
            position_needs,
            {item.team: item.risk_tolerance for item in state.scouting_departments},
        )

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

    def find_franchise_trades(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        loaded = self._trade_loaded(payload)
        assert loaded.state.trade_rule_policy is not None
        player_id = (
            _integer(payload, "player_id", default=0, minimum=1)
            if payload.get("player_id") not in {None, ""}
            else None
        )
        asset_id = (
            str(payload["asset_id"]).strip()
            if payload.get("asset_id") not in {None, ""}
            else None
        )
        raw_player_ids = payload.get("player_ids", [])
        raw_asset_ids = payload.get("asset_ids", [])
        if not isinstance(raw_player_ids, list) or not isinstance(raw_asset_ids, list):
            raise ValueError("Trade Finder package assets must be lists")
        result = find_trade_offers(
            loaded.state,
            policy=loaded.state.trade_rule_policy,
            mode=str(payload.get("mode", "shop")),
            player_id=player_id,
            asset_id=asset_id,
            player_ids=tuple(int(item) for item in raw_player_ids),
            asset_ids=tuple(str(item) for item in raw_asset_ids),
            objective=str(payload.get("objective", "balanced")),
            max_offers=_integer(
                payload,
                "max_offers",
                default=8,
                minimum=1,
                maximum=12,
            ),
        )
        return {
            "kind": "franchise_trade_finder",
            "save_id": loaded.metadata.save_id,
            **result,
        }

    def counter_franchise_trade(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        loaded = self._trade_loaded(payload)
        assert loaded.state.trade_rule_policy is not None
        return {
            "kind": "franchise_trade_counteroffer",
            **generate_counteroffer(
                loaded.state,
                _trade_packages(payload),
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
        packages: tuple[TradeTeamPackage, ...],
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
        player_routes, asset_routes = resolve_trade_routes(packages)
        player_moves = [
            {
                "player_id": player_id,
                "from_team": source,
                "to_team": destination,
            }
            for player_id, (source, destination) in sorted(player_routes.items())
        ]
        asset_moves = [
            {
                "asset_id": asset_id,
                "from_team": source,
                "to_team": destination,
            }
            for asset_id, (source, destination) in sorted(asset_routes.items())
        ]
        pieces = []
        for package in packages:
            by_destination: dict[str, list[str]] = {}
            for player_id in package.player_ids:
                destination = player_routes[player_id][1]
                by_destination.setdefault(destination, []).append(player_by_id[player_id].name)
            for asset_id in package.asset_ids:
                destination = asset_routes[asset_id][1]
                asset = asset_by_id[asset_id]
                by_destination.setdefault(destination, []).append(
                    f"{asset.draft_year} R{asset.round} ({asset.original_team})"
                )
            pieces.extend(
                f"{package.team} sends {', '.join(items)} to {destination}"
                for destination, items in sorted(by_destination.items())
            )
        record = TransactionRecord(
            transaction_id=deterministic_trade_id(
                league_id=state.league_id,
                revision=state.revision + 1,
                packages=packages,
            ),
            transaction_type="trade",
            occurred_on=state.calendar.current_date,
            teams=tuple(package.team for package in packages),
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
        traded = self.franchise_repository.append_event(
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
        restored = self._restore_roster_operations(traded)
        return self._refresh_gm_plans(
            restored,
            reason="completed trade and asset-ledger audit",
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
        rules = rules_for_season(str(payload.get("season", CBA_2026_27.season)))
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
            rules=rules,
        )
        return {
            "kind": "franchise_cap_scenario",
            "rules": rules.as_dict(),
            "evaluation": evaluation.as_dict(),
        }

    def initialize_contract_market(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        save_id = str(payload.get("save_id", "")).strip()
        if not save_id:
            raise ValueError("save_id is required")
        loaded = self.franchise_repository.load(save_id)
        if loaded.state.contracts:
            return self._franchise_response(loaded)
        contracts = build_modeled_contracts(loaded.state)
        updated = self.franchise_repository.append_event(
            save_id,
            event_type=LeagueEventType.CONTRACT_MARKET_INITIALIZED,
            payload={
                "contracts": [item.as_dict() for item in contracts],
                "model_version": CONTRACT_MODEL_VERSION,
                "official_salary_data": False,
            },
            actor="league-office",
        )
        return self._franchise_response(updated)

    def evaluate_contract_extension(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        loaded = self._contract_loaded(payload)
        return {
            "kind": "contract_extension_evaluation",
            "evaluation": extension_evaluation(
                loaded.state,
                player_id=_integer(payload, "player_id", default=0, minimum=1),
                years=_integer(payload, "years", default=3, minimum=1, maximum=4),
                annual_salary=_salary_amount(payload, "annual_salary"),
                role=str(payload.get("role", "rotation")),
            ),
        }

    def sign_contract_extension(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        loaded = self._contract_loaded(payload)
        evaluation = extension_evaluation(
            loaded.state,
            player_id=_integer(payload, "player_id", default=0, minimum=1),
            years=_integer(payload, "years", default=3, minimum=1, maximum=4),
            annual_salary=_salary_amount(payload, "annual_salary"),
            role=str(payload.get("role", "rotation")),
        )
        if not evaluation["can_sign"]:
            raise ValueError(str(evaluation["explanation"]))
        contract = extended_contract(loaded.state, evaluation)
        record = contract_transaction_record(
            loaded.state,
            kind="extension",
            team=loaded.state.user_team,
            player_id=int(evaluation["player_id"]),
            summary=(
                f"{evaluation['player_name']} agreed to a "
                f"{evaluation['years']}-year extension starting at "
                f"${int(evaluation['annual_salary']) / 1_000_000:.2f}M."
            ),
            source="user-negotiated",
        )
        updated = self.franchise_repository.append_event(
            loaded.metadata.save_id,
            event_type=LeagueEventType.CONTRACT_UPDATED,
            payload={"contract": contract.as_dict(), "record": record.as_dict(), "evaluation": evaluation},
            actor=loaded.state.user_team,
        )
        response = self._franchise_response(updated)
        response["contract_decision"] = record.as_dict()
        return response

    def decide_contract_option(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        loaded = self._contract_loaded(payload)
        player_id = _integer(payload, "player_id", default=0, minimum=1)
        requested = bool(payload.get("exercise", True))
        contract, option_year = option_decision(
            loaded.state,
            player_id=player_id,
            exercise=requested,
        )
        player = next(item for item in loaded.state.players if item.player_id == player_id)
        exercised = any(
            year.season == option_year.season and year.option == "exercised"
            for year in contract.years
        )
        record = contract_transaction_record(
            loaded.state,
            kind="option",
            team=player.team,
            player_id=player_id,
            summary=(
                f"{option_year.option.title()} option for {player.name} was "
                f"{'exercised' if exercised else 'declined'} for {option_year.season}."
            ),
            source="player-decision" if option_year.option == "player" else "user-decision",
        )
        updated = self.franchise_repository.append_event(
            loaded.metadata.save_id,
            event_type=LeagueEventType.CONTRACT_OPTION_DECIDED,
            payload={"contract": contract.as_dict(), "record": record.as_dict()},
            actor=record.source,
        )
        return self._franchise_response(updated)

    def waive_franchise_player(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        loaded = self._contract_loaded(payload)
        player_id = _integer(payload, "player_id", default=0, minimum=1)
        player = next((item for item in loaded.state.players if item.player_id == player_id), None)
        if player is None or player.team != loaded.state.user_team:
            raise ValueError("you can only waive a player on your roster")
        contract = waived_contract(loaded.state, player_id)
        record = contract_transaction_record(
            loaded.state,
            kind="waiver",
            team=player.team,
            player_id=player_id,
            summary=f"{player.team} waived {player.name}; guaranteed salary remains on the cap sheet.",
            source="user-decision",
        )
        updated = self.franchise_repository.append_event(
            loaded.metadata.save_id,
            event_type=LeagueEventType.PLAYER_WAIVED,
            payload={"contract": contract.as_dict(), "record": record.as_dict()},
            actor=loaded.state.user_team,
        )
        updated = self._restore_roster_operations(updated)
        return self._franchise_response(updated)

    def franchise_free_agent_board(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        loaded = self._contract_loaded(payload)
        market = contract_market_response(loaded.state)
        return {"kind": "free_agent_board", "save_id": loaded.metadata.save_id, **market}

    def evaluate_free_agent_offer(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        loaded = self._contract_loaded(payload)
        evaluation = free_agent_evaluation(
            loaded.state,
            player_id=_integer(payload, "player_id", default=0, minimum=1),
            team=loaded.state.user_team,
            years=_integer(payload, "years", default=2, minimum=1, maximum=5),
            annual_salary=_salary_amount(payload, "annual_salary"),
            role=str(payload.get("role", "rotation")),
        )
        return {"kind": "free_agent_offer_evaluation", "evaluation": evaluation}

    def sign_free_agent(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        loaded = self._contract_loaded(payload)
        evaluation = free_agent_evaluation(
            loaded.state,
            player_id=_integer(payload, "player_id", default=0, minimum=1),
            team=loaded.state.user_team,
            years=_integer(payload, "years", default=2, minimum=1, maximum=5),
            annual_salary=_salary_amount(payload, "annual_salary"),
            role=str(payload.get("role", "rotation")),
        )
        if not evaluation["can_sign"]:
            blockers = "; ".join(str(item) for item in evaluation["blockers"])
            raise ValueError(blockers or str(evaluation["explanation"]))
        contract = free_agent_contract(loaded.state, evaluation)
        record = contract_transaction_record(
            loaded.state,
            kind="free_agent_signing",
            team=loaded.state.user_team,
            player_id=int(evaluation["player_id"]),
            summary=(
                f"{loaded.state.user_team} signed {evaluation['player_name']} for "
                f"{evaluation['years']} years starting at "
                f"${int(evaluation['annual_salary']) / 1_000_000:.2f}M."
            ),
            source="user-negotiated",
        )
        updated = self.franchise_repository.append_event(
            loaded.metadata.save_id,
            event_type=LeagueEventType.FREE_AGENT_SIGNED,
            payload={"contract": contract.as_dict(), "record": record.as_dict(), "evaluation": evaluation},
            actor=loaded.state.user_team,
        )
        updated = self._restore_roster_operations(updated)
        return self._franchise_response(updated)

    def run_cpu_contract_market(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, object]:
        loaded = self._contract_loaded(payload)
        max_moves = _integer(payload, "max_moves", default=3, minimum=1, maximum=10)
        completed = []
        for player_id in cpu_waiver_candidates(loaded.state, max_players=max_moves):
            player = next(item for item in loaded.state.players if item.player_id == player_id)
            contract = waived_contract(loaded.state, player_id)
            record = contract_transaction_record(
                loaded.state,
                kind="waiver",
                team=player.team,
                player_id=player_id,
                summary=f"{player.team} waived {player.name} during its autonomous roster review.",
                source="cpu-roster-management",
            )
            loaded = self.franchise_repository.append_event(
                loaded.metadata.save_id,
                event_type=LeagueEventType.PLAYER_WAIVED,
                payload={"contract": contract.as_dict(), "record": record.as_dict()},
                actor=f"{player.team}-cpu",
            )
            completed.append(record.as_dict())
        loaded = self._restore_roster_operations(loaded)
        response = self._franchise_response(loaded)
        response["cpu_contract_moves"] = completed
        return response

    def _contract_loaded(self, payload: Mapping[str, Any]) -> LoadedFranchise:
        save_id = str(payload.get("save_id", "")).strip()
        if not save_id:
            raise ValueError("save_id is required")
        loaded = self.franchise_repository.load(save_id)
        if not loaded.state.contracts:
            raise ValueError("initialize Contracts & Free Agency first")
        return loaded

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
        result = self._refresh_automatic_roster_plan(result)
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
        result = self._refresh_automatic_roster_plan(result)
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
        result = self._refresh_automatic_roster_plan(result)
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
        result = self._refresh_automatic_roster_plan(result)
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
        generated = []
        prospect_by_id = {
            prospect.player_id: prospect
            for draft in (
                *state.draft_history,
                *((state.draft_ecosystem,) if state.draft_ecosystem is not None else ()),
            )
            for prospect in draft.prospects
        }
        for player in state.players:
            profile = profiles_by_id.get(player.player_id)
            if profile is None and player.profile_source.startswith("generated-draft-"):
                lifecycle = lifecycles.get(player.player_id)
                if lifecycle is not None:
                    generated.append((
                        player,
                        generated_player_profile(
                            player,
                            lifecycle,
                            prospect_by_id.get(player.player_id),
                        ),
                        lifecycle,
                    ))
                continue
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
        result = build_league_ratings(inputs)
        for player, profile, lifecycle in generated:
            result[player.player_id] = generated_rating_profile(
                player,
                profile,
                lifecycle,
                league_size=len(state.players),
            )
        ordered = sorted(
            result,
            key=lambda player_id: (
                int(result[player_id]["overall"]),
                player_id,
            ),
            reverse=True,
        )
        for rank, player_id in enumerate(ordered, 1):
            result[player_id]["league_rank"] = rank
            result[player_id]["league_size"] = len(result)
        return result

    def _franchise_response(
        self,
        loaded: LoadedFranchise,
    ) -> dict[str, object]:
        state = loaded.state
        user_franchise = state.franchise(state.user_team)
        roster = state.roster(state.user_team)
        roster_ids = {player.player_id for player in roster}
        roster_by_id = {player.player_id: player for player in roster}
        all_players_by_id = {player.player_id: player for player in state.players}
        active_injury_by_player = {
            item.player_id: item
            for item in state.injuries
            if item.status in {"active", "recovering", "out", "questionable"}
        }
        rating_profiles = self._league_rating_profiles(state)
        lifecycle_rows = [
            {
                **record.as_dict(),
                **lifecycle_composites(rating_profiles[record.player_id]),
                "name": roster_by_id[record.player_id].name,
                "team": roster_by_id[record.player_id].team,
                "position": roster_by_id[record.player_id].position,
                "injury": (
                    active_injury_by_player[record.player_id].as_dict()
                    if record.player_id in active_injury_by_player
                    else None
                ),
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
                "injury": (
                    active_injury_by_player[record.player_id].as_dict()
                    if record.player_id in active_injury_by_player
                    else None
                ),
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
        events = tuple(reversed([
            event for event in loaded.events[-60:]
            if not (
                event.event_type is LeagueEventType.ROSTER_OPERATIONS_INITIALIZED
                and event.payload.get("reason") == "roster movement"
            )
        ][-50:]))
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
            "cba": rules_for_season(state.season).as_dict(),
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
            "player_careers": career_history_response(state),
            "player_health": {
                "ready": len(state.player_health) == len(state.players),
                "model_version": HEALTH_MODEL_VERSION,
                "injury_model_version": INJURY_MODEL_VERSION,
                "records": health_rows,
                "injuries": [
                    {
                        **item.as_dict(),
                        "name": (
                            all_players_by_id[item.player_id].name
                            if item.player_id in all_players_by_id
                            else f"Player {item.player_id}"
                        ),
                    }
                    for item in sorted(
                        (
                            value for value in state.injuries
                            if value.team == state.user_team
                        ),
                        key=lambda value: (value.started_on, value.injury_id),
                        reverse=True,
                    )
                ],
                "coverage": {
                    "league_players": len(state.players),
                    "modeled_players": len(state.player_health),
                    "team_players": len(roster),
                    "team_modeled": len(health_rows),
                    "restricted": sum(
                        record["availability"] != "available"
                        for record in health_rows
                    ),
                    "active_injuries": sum(
                        item.status in {"active", "recovering", "out", "questionable"}
                        for item in state.injuries
                    ),
                    "season_injuries": len(state.injuries),
                    "games_missed": sum(item.games_missed for item in state.injuries),
                },
                "interpretation": (
                    "Injury occurrence is a seeded availability model using exposure, "
                    "age, workload, fatigue and prior history—not a medical diagnosis."
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
                    "draft_year": int(state.season.split("-", 1)[0]) + 1,
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
            "general_manager": general_manager_response(state),
            "experience": experience_response(state),
            "roster_operations": roster_operations_response(state),
            "season_hub": {
                **season_cycle_response(
                    state.season_cycle,
                    user_team=state.user_team,
                ),
                "playoff_performance": (
                    postseason_performance(state.season_cycle)
                    if state.season_cycle is not None
                    else {"method": "", "risers": [], "fallers": [], "all": []}
                ),
            },
            "offseason_hub": offseason_hub_response(state),
            "season_history": [
                {
                    "season": item.season,
                    "champion": item.champion,
                    "awards": dict(item.awards),
                    "games": sum(game.completed for game in item.games),
                }
                for item in reversed(state.season_history)
            ],
            "draft_history": [
                {
                    "draft_year": item.draft_year,
                    "class_label": item.public_class_label,
                    "public_class_strength": item.public_class_strength,
                    "selections": [selection.as_dict() for selection in item.selections],
                    "class_size": len(item.prospects),
                    "model_version": item.model_version,
                }
                for item in reversed(state.draft_history)
            ],
            "contract_market": contract_market_response(state),
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
                "roster_plans": {
                    "status": "loaded" if state.roster_plans else "schema_ready",
                    "records": len(state.roster_plans),
                },
                "season_cycle": {
                    "status": "loaded" if state.season_cycle is not None else "schema_ready",
                    "records": (
                        len(state.season_cycle.games)
                        if state.season_cycle is not None
                        else 0
                    ),
                },
                "gm_plans": {
                    "status": "loaded" if state.gm_plans else "schema_ready",
                    "records": len(state.gm_plans),
                },
                "experience": {
                    "status": "loaded" if state.experience is not None else "schema_ready",
                    "records": 1 if state.experience is not None else 0,
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
                    "status": "loaded" if state.contracts else "schema_ready",
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
                    "status": "loaded" if state.player_health else "schema_ready",
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
        home_base, home_plan_out = self._roster_profile_for_team(
            payload, home_abbreviation
        )
        away_base, away_plan_out = self._roster_profile_for_team(
            payload, away_abbreviation
        )
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
        home_inactive = tuple(
            sorted(set((*home_manual_out, *home_health_out, *home_plan_out)))
        )
        away_inactive = tuple(
            sorted(set((*away_manual_out, *away_health_out, *away_plan_out)))
        )
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
            home_base,
            inactive_player_ids=home_inactive,
            minute_limits=home_limits,
        )
        away = condition_team_profile(
            away_base,
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

    def _roster_profile_for_team(
        self,
        payload: Mapping[str, Any],
        team: str,
    ) -> tuple[TeamProfile, tuple[int, ...]]:
        profile = self._team(team)
        raw_save_id = payload.get("franchise_save_id")
        if raw_save_id in {None, ""}:
            return profile, ()
        loaded = self.franchise_repository.load(str(raw_save_id).strip())
        profile = self._franchise_team_profile(loaded, team)
        plan = roster_plan(loaded.state, team)
        return apply_roster_plan(profile, plan), roster_inactive_player_ids(plan)

    def _franchise_team_profile(
        self,
        loaded: LoadedFranchise,
        team: str,
    ) -> TeamProfile:
        """Materialize current saved ownership onto immutable player profiles."""
        normalized = team.upper()
        base = self._team(normalized)
        if self._player_profile_cache is None:
            self._player_profile_cache = {
                player.player_id: player
                for abbreviation in self.profile_repository.available_teams()
                for player in self._team(abbreviation).roster
            }
        source_profiles = self._player_profile_cache
        fallback = min(base.roster, key=lambda item: item.expected_minutes)
        lifecycles = {
            item.player_id: item for item in loaded.state.player_lifecycles
        }
        prospect_by_id = {
            prospect.player_id: prospect
            for draft in (
                *loaded.state.draft_history,
                *((loaded.state.draft_ecosystem,) if loaded.state.draft_ecosystem is not None else ()),
            )
            for prospect in draft.prospects
        }
        roster = []
        for record in loaded.state.roster(normalized):
            source = source_profiles.get(record.player_id)
            if (
                source is None
                and record.profile_source.startswith("generated-draft-")
                and record.player_id in lifecycles
            ):
                source = generated_player_profile(
                    record,
                    lifecycles[record.player_id],
                    prospect_by_id.get(record.player_id),
                )
            if source is None:
                source = fallback
            roster.append(
                replace(
                    source,
                    player_id=record.player_id,
                    name=record.name,
                    team_abbreviation=normalized,
                    position=record.position or source.position,
                    expected_minutes=record.expected_minutes,
                )
            )
        if len(roster) < 5:
            raise ValueError(
                f"{normalized} has fewer than five active Franchise players"
            )
        return replace(base, roster=tuple(roster), minute_limits={})

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
) -> tuple[TradeTeamPackage, ...]:
    raw = payload.get("packages")
    if not isinstance(raw, list) or not 2 <= len(raw) <= 4:
        raise ValueError("packages must contain two to four trade teams")
    packages = []
    for value in raw:
        if not isinstance(value, Mapping):
            raise ValueError("trade package must be an object")
        player_values = value.get("player_ids", [])
        asset_values = value.get("asset_ids", [])
        consent_values = value.get("consent_player_ids", [])
        player_destinations = value.get("player_destinations", {})
        asset_destinations = value.get("asset_destinations", {})
        if not isinstance(player_values, list):
            raise ValueError("trade player_ids must be a list")
        if not isinstance(asset_values, list):
            raise ValueError("trade asset_ids must be a list")
        if not isinstance(consent_values, list):
            raise ValueError("trade consent_player_ids must be a list")
        if not isinstance(player_destinations, Mapping):
            raise ValueError("trade player_destinations must be an object")
        if not isinstance(asset_destinations, Mapping):
            raise ValueError("trade asset_destinations must be an object")
        packages.append(
            TradeTeamPackage(
                team=str(value.get("team", "")),
                player_ids=tuple(int(item) for item in player_values),
                asset_ids=tuple(str(item) for item in asset_values),
                consent_player_ids=tuple(int(item) for item in consent_values),
                player_destinations=tuple(
                    (int(player_id), str(team))
                    for player_id, team in player_destinations.items()
                ),
                asset_destinations=tuple(
                    (str(asset_id), str(team))
                    for asset_id, team in asset_destinations.items()
                ),
            )
        )
    return tuple(packages)


def _handler(service_source: DashboardService | Any) -> type[BaseHTTPRequestHandler]:
    class DashboardHandler(BaseHTTPRequestHandler):
        server_version = "NBASimLocal/0.1"

        def do_GET(self) -> None:
            service = (
                service_source(self)
                if callable(service_source)
                else service_source
            )
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
            service = (
                service_source(self)
                if callable(service_source)
                else service_source
            )
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
                "/api/franchise/initialize-gm": (
                    service.initialize_gm_intelligence
                ),
                "/api/franchise/review-gm": service.review_gm_intelligence,
                "/api/franchise/update-gm-plan": service.update_user_gm_plan,
                "/api/franchise/configure-experience": (
                    service.configure_franchise_experience
                ),
                "/api/franchise/playtest-audit": service.franchise_playtest_audit,
                "/api/franchise/advance-date": service.advance_franchise_date,
                "/api/franchise/branch": service.branch_franchise,
                "/api/franchise/initialize-season": (
                    service.initialize_franchise_season
                ),
                "/api/franchise/simulate-games": (
                    service.simulate_franchise_games
                ),
                "/api/franchise/simulate-games/start": (
                    service.start_franchise_season_simulation
                ),
                "/api/franchise/simulate-games/progress": (
                    service.franchise_season_simulation_progress
                ),
                "/api/franchise/simulate-games/cancel": (
                    service.cancel_franchise_season_simulation
                ),
                "/api/franchise/season-game": service.franchise_season_game,
                "/api/franchise/stats": service.franchise_statistics,
                "/api/franchise/simulate-postseason": (
                    service.simulate_franchise_postseason
                ),
                "/api/franchise/simulate-postseason/start": (
                    service.start_franchise_postseason_simulation
                ),
                "/api/franchise/advance-offseason": (
                    service.advance_franchise_offseason
                ),
                "/api/franchise/initialize-roster-operations": (
                    service.initialize_roster_operations
                ),
                "/api/franchise/optimize-roster-plan": (
                    service.optimize_roster_plan
                ),
                "/api/franchise/save-roster-plan": service.save_roster_plan,
                "/api/franchise/cap-scenario": service.franchise_cap_scenario,
                "/api/franchise/initialize-contracts": (
                    service.initialize_contract_market
                ),
                "/api/franchise/evaluate-extension": (
                    service.evaluate_contract_extension
                ),
                "/api/franchise/sign-extension": service.sign_contract_extension,
                "/api/franchise/decide-option": service.decide_contract_option,
                "/api/franchise/waive-player": service.waive_franchise_player,
                "/api/franchise/free-agent-board": (
                    service.franchise_free_agent_board
                ),
                "/api/franchise/evaluate-free-agent": (
                    service.evaluate_free_agent_offer
                ),
                "/api/franchise/sign-free-agent": service.sign_free_agent,
                "/api/franchise/run-contract-market": (
                    service.run_cpu_contract_market
                ),
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
                "/api/franchise/find-trades": (
                    service.find_franchise_trades
                ),
                "/api/franchise/counter-trade": (
                    service.counter_franchise_trade
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
                self._json(
                    HTTPStatus.BAD_REQUEST,
                    {
                        "error": str(error),
                        "guidance": recovery_guidance(str(error)),
                        "recoverable": True,
                    },
                )
            except Exception as error:
                LOGGER.exception(
                    "dashboard request failed",
                    extra={"request_path": path, "error_type": type(error).__name__},
                )
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
