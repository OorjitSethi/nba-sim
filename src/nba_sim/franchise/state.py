from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import date
from typing import Mapping

from nba_sim.franchise.events import LeagueEvent, LeagueEventType
from nba_sim.franchise.draft import DraftEcosystemRecord
from nba_sim.franchise.trading import TradeRulePolicy
from nba_sim.franchise.models import (
    CapExceptionRecord,
    CareerDecisionRecord,
    CoachingProfileRecord,
    ContractRecord,
    DraftAssetRecord,
    FranchiseRecord,
    FranchiseExperienceRecord,
    GeneralManagerPlanRecord,
    InjuryRecord,
    LeagueCalendar,
    PlayerHealthRecord,
    PlayerLifecycleRecord,
    PlayerRecord,
    RosterPlanRecord,
    ScoutingDepartmentRecord,
    ScoutingReportRecord,
    StaffRecord,
    TeamChemistryRecord,
    TransactionRecord,
)
from nba_sim.franchise.health import advance_health_records, reconcile_injury_history
from nba_sim.franchise.season_cycle import (
    FranchiseSeasonRecord,
    SeasonGameRecord,
    replace_games,
)


@dataclass(frozen=True)
class LeagueState:
    schema_version: int
    league_id: str
    league_name: str
    season: str
    seed: int
    user_team: str
    calendar: LeagueCalendar
    franchises: tuple[FranchiseRecord, ...]
    players: tuple[PlayerRecord, ...]
    player_lifecycles: tuple[PlayerLifecycleRecord, ...] = ()
    career_decisions: tuple[CareerDecisionRecord, ...] = ()
    player_health: tuple[PlayerHealthRecord, ...] = ()
    team_chemistry: tuple[TeamChemistryRecord, ...] = ()
    coaching_profiles: tuple[CoachingProfileRecord, ...] = ()
    scouting_reports: tuple[ScoutingReportRecord, ...] = ()
    scouting_departments: tuple[ScoutingDepartmentRecord, ...] = ()
    staff: tuple[StaffRecord, ...] = ()
    contracts: tuple[ContractRecord, ...] = ()
    roster_plans: tuple[RosterPlanRecord, ...] = ()
    draft_assets: tuple[DraftAssetRecord, ...] = ()
    cap_exceptions: tuple[CapExceptionRecord, ...] = ()
    injuries: tuple[InjuryRecord, ...] = ()
    transactions: tuple[TransactionRecord, ...] = ()
    draft_ecosystem: DraftEcosystemRecord | None = None
    draft_history: tuple[DraftEcosystemRecord, ...] = ()
    trade_rule_policy: TradeRulePolicy | None = None
    season_cycle: FranchiseSeasonRecord | None = None
    season_history: tuple[FranchiseSeasonRecord, ...] = ()
    gm_plans: tuple[GeneralManagerPlanRecord, ...] = ()
    experience: FranchiseExperienceRecord | None = None
    revision: int = 0
    head_hash: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported franchise state schema")
        if not self.league_id or not self.league_name:
            raise ValueError("league identity cannot be empty")
        if self.seed < 0:
            raise ValueError("league seed must be non-negative")
        teams = [franchise.team for franchise in self.franchises]
        if len(teams) < 2 or len(teams) != len(set(teams)):
            raise ValueError("league franchises must contain unique teams")
        if self.user_team not in teams:
            raise ValueError("user team is not part of the league")
        player_ids = [player.player_id for player in self.players]
        if len(player_ids) != len(set(player_ids)):
            raise ValueError("league contains duplicate player IDs")
        unknown_player_teams = {
            player.team for player in self.players if player.team not in teams
        }
        if unknown_player_teams:
            raise ValueError(
                f"players reference unknown teams: {sorted(unknown_player_teams)}"
            )
        _unique(
            self.player_lifecycles,
            "player_id",
            "player lifecycle",
        )
        unknown_lifecycle_players = {
            record.player_id
            for record in self.player_lifecycles
            if record.player_id not in player_ids
        }
        if unknown_lifecycle_players:
            raise ValueError(
                "player lifecycle references an unknown player"
            )
        if (
            self.player_lifecycles
            and {
                record.player_id
                for record in self.player_lifecycles
            }
            != set(player_ids)
        ):
            raise ValueError(
                "player lifecycle coverage must be empty or complete"
            )
        _unique(self.career_decisions, "decision_id", "career decision")
        if {
            record.player_id for record in self.career_decisions
        } - set(player_ids):
            raise ValueError("career decision references an unknown player")
        _unique(self.player_health, "player_id", "player health")
        if (
            self.player_health
            and {record.player_id for record in self.player_health}
            != set(player_ids)
        ):
            raise ValueError("player health coverage must be empty or complete")
        _unique(self.team_chemistry, "team", "team chemistry")
        _unique(self.coaching_profiles, "team", "coaching profile")
        if self.team_chemistry and {
            record.team for record in self.team_chemistry
        } != set(teams):
            raise ValueError("team chemistry coverage must be empty or complete")
        if self.coaching_profiles and {
            record.team for record in self.coaching_profiles
        } != set(teams):
            raise ValueError("coaching coverage must be empty or complete")
        _unique(self.scouting_reports, "player_id", "scouting report")
        _unique(self.scouting_departments, "team", "scouting department")
        if self.scouting_reports and {
            record.player_id for record in self.scouting_reports
        } != set(player_ids):
            raise ValueError("scouting report coverage must be empty or complete")
        if self.scouting_departments and {
            record.team for record in self.scouting_departments
        } != set(teams):
            raise ValueError("scouting department coverage must be empty or complete")
        self._validate_references(set(teams), set(player_ids))
        _unique(self.staff, "staff_id", "staff")
        _unique(self.contracts, "contract_id", "contract")
        _unique(self.roster_plans, "team", "roster plan")
        _unique(self.draft_assets, "asset_id", "draft asset")
        _unique(self.cap_exceptions, "exception_id", "cap exception")
        _unique(self.injuries, "injury_id", "injury")
        _unique(self.transactions, "transaction_id", "transaction")
        draft_years = [item.draft_year for item in self.draft_history]
        if len(draft_years) != len(set(draft_years)):
            raise ValueError("draft history contains a duplicate year")
        if (
            self.draft_ecosystem is not None
            and self.draft_ecosystem.draft_year in draft_years
        ):
            raise ValueError("active draft is already archived")
        _unique(self.gm_plans, "team", "general-manager plan")
        history_seasons = [item.season for item in self.season_history]
        if len(history_seasons) != len(set(history_seasons)):
            raise ValueError("league history contains a duplicate season")
        if (
            self.season_cycle is not None
            and self.season_cycle.season in history_seasons
        ):
            raise ValueError("active season is already archived")
        if self.gm_plans and {item.team for item in self.gm_plans} != set(teams):
            raise ValueError("general-manager plans must be empty or cover every team")
        if any(
            set((*item.core_player_ids, *item.trade_block_player_ids)) - set(player_ids)
            for item in self.gm_plans
        ):
            raise ValueError("general-manager plan references an unknown player")
        if self.revision < 0:
            raise ValueError("league revision cannot be negative")
        if not self.head_hash:
            object.__setattr__(self, "head_hash", self.genesis_hash())
        elif (
            self.revision == 0
            and self.head_hash != self.genesis_hash()
            and self.head_hash not in self._compatible_legacy_genesis_hashes()
        ):
            raise ValueError("league genesis state hash is invalid")

    def _validate_references(
        self,
        teams: set[str],
        player_ids: set[int],
    ) -> None:
        for staff in self.staff:
            if staff.team not in teams:
                raise ValueError(f"staff references unknown team: {staff.team}")
        for contract in self.contracts:
            if contract.team not in teams or contract.player_id not in player_ids:
                raise ValueError("contract references an unknown team or player")
        for plan in self.roster_plans:
            if plan.team not in teams:
                raise ValueError("roster plan references an unknown team")
            if {item.player_id for item in plan.assignments} - player_ids:
                raise ValueError("roster plan references an unknown player")
        for asset in self.draft_assets:
            if asset.original_team not in teams or asset.current_team not in teams:
                raise ValueError("draft asset references an unknown team")
        for exception in self.cap_exceptions:
            if exception.team not in teams:
                raise ValueError("cap exception references an unknown team")
        for injury in self.injuries:
            if injury.team not in teams or injury.player_id not in player_ids:
                raise ValueError("injury references an unknown team or player")
        for transaction in self.transactions:
            if set(transaction.teams) - teams:
                raise ValueError("transaction references an unknown team")

    def genesis_hash(self) -> str:
        value = self.as_dict()
        value["revision"] = 0
        value["head_hash"] = ""
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _compatible_legacy_genesis_hashes(self) -> set[str]:
        """Hash older state shapes so every prior franchise phase still replays."""
        hashes: set[str] = set()
        original_omissions = (
            ("scouting_reports", "scouting_departments"),
            (
                "scouting_reports",
                "scouting_departments",
                "team_chemistry",
                "coaching_profiles",
            ),
            (
                "scouting_reports",
                "scouting_departments",
                "team_chemistry",
                "coaching_profiles",
                "player_health",
            ),
            (
                "scouting_reports",
                "scouting_departments",
                "team_chemistry",
                "coaching_profiles",
                "player_health",
                "player_lifecycles",
            ),
            ("team_chemistry", "coaching_profiles"),
            ("team_chemistry", "coaching_profiles", "player_health"),
            (
                "team_chemistry",
                "coaching_profiles",
                "player_health",
                "player_lifecycles",
            ),
        )
        prior_shapes = (("roster_plans",), *original_omissions, *(
            (*items, "roster_plans") for items in original_omissions
        ))
        legacy_shapes_without_history = (
            (),
            ("season_cycle",),
            *prior_shapes,
            *((*items, "season_cycle") for items in prior_shapes),
        )
        legacy_shapes_before_careers = (
            *legacy_shapes_without_history,
            *(
                (*items, "season_history")
                for items in legacy_shapes_without_history
            ),
        )
        legacy_shapes_before_drafts = (
            *legacy_shapes_before_careers,
            *((*items, "career_decisions") for items in legacy_shapes_before_careers),
        )
        legacy_shapes = (
            *legacy_shapes_before_drafts,
            *((*items, "draft_history") for items in legacy_shapes_before_drafts),
        )
        for omitted in legacy_shapes:
            for shape in (
                omitted,
                (*omitted, "gm_plans"),
                (*omitted, "experience"),
                (*omitted, "gm_plans", "experience"),
            ):
                value = self.as_dict()
                for key in shape:
                    value.pop(key, None)
                value["revision"] = 0
                value["head_hash"] = ""
                encoded = json.dumps(
                    value,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
                hashes.add(hashlib.sha256(encoded).hexdigest())
        return hashes

    def franchise(self, team: str) -> FranchiseRecord:
        normalized = team.upper()
        for franchise in self.franchises:
            if franchise.team == normalized:
                return franchise
        raise KeyError(team)

    def roster(self, team: str) -> tuple[PlayerRecord, ...]:
        normalized = team.upper()
        return tuple(
            sorted(
                (
                    player
                    for player in self.players
                    if player.team == normalized
                    and player.roster_status == "active"
                ),
                key=lambda player: (-player.expected_minutes, player.name),
            )
        )

    def summary_dict(self) -> dict[str, object]:
        user_franchise = self.franchise(self.user_team)
        return {
            "league_id": self.league_id,
            "league_name": self.league_name,
            "season": self.season,
            "seed": self.seed,
            "user_team": self.user_team,
            "user_franchise": user_franchise.as_dict(),
            "current_date": self.calendar.current_date.isoformat(),
            "phase": self.calendar.phase,
            "revision": self.revision,
            "head_hash": self.head_hash,
            "counts": {
                "franchises": len(self.franchises),
                "players": len(self.players),
                "player_lifecycles": len(self.player_lifecycles),
                "career_decisions": len(self.career_decisions),
                "player_health": len(self.player_health),
                "team_chemistry": len(self.team_chemistry),
                "coaching_profiles": len(self.coaching_profiles),
                "scouting_reports": len(self.scouting_reports),
                "scouting_departments": len(self.scouting_departments),
                "staff": len(self.staff),
                "contracts": len(self.contracts),
                "roster_plans": len(self.roster_plans),
                "draft_assets": len(self.draft_assets),
                "draft_prospects": (
                    len(self.draft_ecosystem.prospects)
                    if self.draft_ecosystem is not None
                    else 0
                ),
                "draft_history": len(self.draft_history),
                "trade_center": 1 if self.trade_rule_policy is not None else 0,
                "season_cycle": 1 if self.season_cycle is not None else 0,
                "season_history": len(self.season_history),
                "gm_plans": len(self.gm_plans),
                "experience": 1 if self.experience is not None else 0,
                "cap_exceptions": len(self.cap_exceptions),
                "injuries": len(self.injuries),
                "transactions": len(self.transactions),
            },
        }

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "league_id": self.league_id,
            "league_name": self.league_name,
            "season": self.season,
            "seed": self.seed,
            "user_team": self.user_team,
            "calendar": self.calendar.as_dict(),
            "franchises": [
                franchise.as_dict() for franchise in self.franchises
            ],
            "players": [player.as_dict() for player in self.players],
            "player_lifecycles": [
                record.as_dict() for record in self.player_lifecycles
            ],
            "career_decisions": [
                record.as_dict() for record in self.career_decisions
            ],
            "player_health": [
                record.as_dict() for record in self.player_health
            ],
            "team_chemistry": [
                record.as_dict() for record in self.team_chemistry
            ],
            "coaching_profiles": [
                record.as_dict() for record in self.coaching_profiles
            ],
            "scouting_reports": [
                record.as_dict() for record in self.scouting_reports
            ],
            "scouting_departments": [
                record.as_dict() for record in self.scouting_departments
            ],
            "staff": [record.as_dict() for record in self.staff],
            "contracts": [record.as_dict() for record in self.contracts],
            "roster_plans": [record.as_dict() for record in self.roster_plans],
            "draft_assets": [record.as_dict() for record in self.draft_assets],
            "cap_exceptions": [
                record.as_dict() for record in self.cap_exceptions
            ],
            "injuries": [record.as_dict() for record in self.injuries],
            "transactions": [
                record.as_dict() for record in self.transactions
            ],
            **(
                {"draft_ecosystem": self.draft_ecosystem.as_dict()}
                if self.draft_ecosystem is not None
                else {}
            ),
            "draft_history": [item.as_dict() for item in self.draft_history],
            **(
                {"trade_rule_policy": self.trade_rule_policy.as_dict()}
                if self.trade_rule_policy is not None
                else {}
            ),
            **(
                {"season_cycle": self.season_cycle.as_dict()}
                if self.season_cycle is not None
                else {}
            ),
            "season_history": [
                item.as_dict() for item in self.season_history
            ],
            "gm_plans": [item.as_dict() for item in self.gm_plans],
            **(
                {"experience": self.experience.as_dict()}
                if self.experience is not None
                else {}
            ),
            "revision": self.revision,
            "head_hash": self.head_hash,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "LeagueState":
        calendar = value.get("calendar")
        if not isinstance(calendar, Mapping):
            raise ValueError("league state calendar must be an object")
        return cls(
            schema_version=int(value["schema_version"]),
            league_id=str(value["league_id"]),
            league_name=str(value["league_name"]),
            season=str(value["season"]),
            seed=int(value["seed"]),
            user_team=str(value["user_team"]),
            calendar=LeagueCalendar.from_dict(calendar),
            franchises=tuple(
                FranchiseRecord.from_dict(item)
                for item in value.get("franchises", [])  # type: ignore[arg-type]
            ),
            players=tuple(
                PlayerRecord.from_dict(item)
                for item in value.get("players", [])  # type: ignore[arg-type]
            ),
            player_lifecycles=tuple(
                PlayerLifecycleRecord.from_dict(item)
                for item in value.get("player_lifecycles", [])  # type: ignore[arg-type]
            ),
            career_decisions=tuple(
                CareerDecisionRecord.from_dict(item)
                for item in value.get("career_decisions", [])  # type: ignore[arg-type]
            ),
            player_health=tuple(
                PlayerHealthRecord.from_dict(item)
                for item in value.get("player_health", [])  # type: ignore[arg-type]
            ),
            team_chemistry=tuple(
                TeamChemistryRecord.from_dict(item)
                for item in value.get("team_chemistry", [])  # type: ignore[arg-type]
            ),
            coaching_profiles=tuple(
                CoachingProfileRecord.from_dict(item)
                for item in value.get("coaching_profiles", [])  # type: ignore[arg-type]
            ),
            scouting_reports=tuple(
                ScoutingReportRecord.from_dict(item)
                for item in value.get("scouting_reports", [])  # type: ignore[arg-type]
            ),
            scouting_departments=tuple(
                ScoutingDepartmentRecord.from_dict(item)
                for item in value.get("scouting_departments", [])  # type: ignore[arg-type]
            ),
            staff=tuple(
                StaffRecord.from_dict(item)
                for item in value.get("staff", [])  # type: ignore[arg-type]
            ),
            contracts=tuple(
                ContractRecord.from_dict(item)
                for item in value.get("contracts", [])  # type: ignore[arg-type]
            ),
            roster_plans=tuple(
                RosterPlanRecord.from_dict(item)
                for item in value.get("roster_plans", [])  # type: ignore[arg-type]
            ),
            draft_assets=tuple(
                DraftAssetRecord.from_dict(item)
                for item in value.get("draft_assets", [])  # type: ignore[arg-type]
            ),
            cap_exceptions=tuple(
                CapExceptionRecord.from_dict(item)
                for item in value.get("cap_exceptions", [])  # type: ignore[arg-type]
            ),
            injuries=tuple(
                InjuryRecord.from_dict(item)
                for item in value.get("injuries", [])  # type: ignore[arg-type]
            ),
            transactions=tuple(
                TransactionRecord.from_dict(item)
                for item in value.get("transactions", [])  # type: ignore[arg-type]
            ),
            draft_ecosystem=(
                DraftEcosystemRecord.from_dict(value["draft_ecosystem"])
                if isinstance(value.get("draft_ecosystem"), Mapping)
                else None
            ),
            draft_history=tuple(
                DraftEcosystemRecord.from_dict(item)
                for item in value.get("draft_history", [])  # type: ignore[arg-type]
                if isinstance(item, Mapping)
            ),
            trade_rule_policy=(
                TradeRulePolicy.from_dict(value["trade_rule_policy"])
                if isinstance(value.get("trade_rule_policy"), Mapping)
                else None
            ),
            season_cycle=(
                FranchiseSeasonRecord.from_dict(value["season_cycle"])
                if isinstance(value.get("season_cycle"), Mapping)
                else None
            ),
            season_history=tuple(
                FranchiseSeasonRecord.from_dict(item)
                for item in value.get("season_history", [])  # type: ignore[arg-type]
                if isinstance(item, Mapping)
            ),
            gm_plans=tuple(
                GeneralManagerPlanRecord.from_dict(item)
                for item in value.get("gm_plans", [])  # type: ignore[arg-type]
            ),
            experience=(
                FranchiseExperienceRecord.from_dict(value["experience"])
                if isinstance(value.get("experience"), Mapping)
                else None
            ),
            revision=int(value.get("revision", 0)),
            head_hash=str(value.get("head_hash", "")),
        )


def _unique(values: tuple[object, ...], attribute: str, label: str) -> None:
    identities = [getattr(value, attribute) for value in values]
    if len(identities) != len(set(identities)):
        raise ValueError(f"duplicate {label} identity")


def apply_league_event(state: LeagueState, event: LeagueEvent) -> LeagueState:
    if event.sequence != state.revision + 1:
        raise ValueError(
            f"expected league event {state.revision + 1}, got {event.sequence}"
        )
    if event.previous_hash != state.head_hash:
        raise ValueError("league event hash chain is broken")

    changes: dict[str, object] = {}
    if event.event_type is LeagueEventType.DATE_ADVANCED:
        target = str(event.payload.get("to_date", ""))
        target_date = date.fromisoformat(target)
        changes["calendar"] = state.calendar.advance_to(target_date)
        if state.player_health:
            advanced_health = advance_health_records(
                state.player_health,
                target=target_date,
            )
            changes["player_health"] = advanced_health
            if state.injuries:
                changes["injuries"] = reconcile_injury_history(
                    state.injuries,
                    health={item.player_id: item for item in advanced_health},
                    games=(),
                )
    elif event.event_type is LeagueEventType.STAFF_REGISTERED:
        record = StaffRecord.from_dict(_record(event))
        updated = (*state.staff, record)
        _unique(updated, "staff_id", "staff")
        changes["staff"] = updated
    elif event.event_type is LeagueEventType.CONTRACT_REGISTERED:
        record = ContractRecord.from_dict(_record(event))
        updated = (*state.contracts, record)
        _unique(updated, "contract_id", "contract")
        changes["contracts"] = updated
    elif event.event_type is LeagueEventType.ROSTER_OPERATIONS_INITIALIZED:
        if state.roster_plans:
            raise ValueError("roster operations are already initialized")
        values = event.payload.get("plans")
        if not isinstance(values, list):
            raise ValueError("roster operations require a plans list")
        plans = tuple(
            RosterPlanRecord.from_dict(item)
            for item in values
            if isinstance(item, Mapping)
        )
        if len(plans) != len(values):
            raise ValueError("roster plan must be an object")
        if {item.team for item in plans} != {item.team for item in state.franchises}:
            raise ValueError("roster initialization must cover every team")
        changes["roster_plans"] = plans
    elif event.event_type is LeagueEventType.ROSTER_PLAN_UPDATED:
        plan_value = event.payload.get("plan")
        if not isinstance(plan_value, Mapping):
            raise ValueError("roster update requires a plan")
        plan = RosterPlanRecord.from_dict(plan_value)
        if plan.team not in {item.team for item in state.roster_plans}:
            raise ValueError("roster update references an uninitialized team")
        changes["roster_plans"] = tuple(
            plan if item.team == plan.team else item
            for item in state.roster_plans
        )
    elif event.event_type is LeagueEventType.SEASON_CYCLE_INITIALIZED:
        if state.season_cycle is not None:
            raise ValueError("season cycle is already initialized")
        cycle_value = event.payload.get("season_cycle")
        if not isinstance(cycle_value, Mapping):
            raise ValueError("season initialization requires season_cycle")
        changes["season_cycle"] = FranchiseSeasonRecord.from_dict(cycle_value)
    elif event.event_type is LeagueEventType.SEASON_GAMES_SIMULATED:
        if state.season_cycle is None:
            raise ValueError("season cycle is not initialized")
        games_value = event.payload.get("games")
        if not isinstance(games_value, list):
            raise ValueError("game simulation requires a games list")
        completed = tuple(
            SeasonGameRecord.from_dict(item)
            for item in games_value
            if isinstance(item, Mapping)
        )
        if len(completed) != len(games_value) or not all(item.completed for item in completed):
            raise ValueError("simulated games must be completed game records")
        changes["season_cycle"] = replace_games(state.season_cycle, completed)
        target = event.payload.get("to_date")
        if target is not None:
            target_date = date.fromisoformat(str(target))
            changes["calendar"] = state.calendar.advance_to(target_date)
        health_values = event.payload.get("health_records")
        if health_values is not None:
            if not isinstance(health_values, list):
                raise ValueError("health_records must be a list")
            changes["player_health"] = tuple(
                PlayerHealthRecord.from_dict(item)
                for item in health_values
                if isinstance(item, Mapping)
            )
        injury_values = event.payload.get("injury_records")
        if injury_values is not None:
            if not isinstance(injury_values, list):
                raise ValueError("injury_records must be a list")
            injuries = tuple(
                InjuryRecord.from_dict(item)
                for item in injury_values
                if isinstance(item, Mapping)
            )
            if len(injuries) != len(injury_values):
                raise ValueError("injury record must be an object")
            _unique(injuries, "injury_id", "injury")
            changes["injuries"] = injuries
    elif event.event_type is LeagueEventType.SEASON_STAGE_ADVANCED:
        if state.season_cycle is None:
            raise ValueError("season cycle is not initialized")
        cycle_value = event.payload.get("season_cycle")
        if isinstance(cycle_value, Mapping):
            cycle = FranchiseSeasonRecord.from_dict(cycle_value)
        else:
            postseason_values = event.payload.get("postseason_games", [])
            if not isinstance(postseason_values, list):
                raise ValueError("postseason_games must be a list")
            postseason = tuple(
                SeasonGameRecord.from_dict(item)
                for item in postseason_values
                if isinstance(item, Mapping)
            )
            if len(postseason) != len(postseason_values):
                raise ValueError("postseason game must be an object")
            awards_value = event.payload.get("awards", {})
            awards = tuple(
                (str(key), str(value))
                for key, value in (
                    awards_value.items()
                    if isinstance(awards_value, Mapping)
                    else ()
                )
            )
            cycle = replace(
                state.season_cycle,
                games=(*state.season_cycle.games, *postseason),
                status=str(event.payload.get("status", "offseason")),
                champion=(
                    str(event.payload["champion"])
                    if event.payload.get("champion")
                    else None
                ),
                offseason_stage=(
                    str(event.payload["offseason_stage"])
                    if event.payload.get("offseason_stage")
                    else None
                ),
                awards=awards,
            )
        if cycle.season != state.season_cycle.season:
            raise ValueError("season event references the wrong season")
        changes["season_cycle"] = cycle
        target = event.payload.get("to_date")
        if target is not None:
            target_date = date.fromisoformat(str(target))
            changes["calendar"] = state.calendar.advance_to(target_date)
        health_values = event.payload.get("health_records")
        if health_values is not None:
            if not isinstance(health_values, list):
                raise ValueError("health_records must be a list")
            changes["player_health"] = tuple(
                PlayerHealthRecord.from_dict(item)
                for item in health_values
                if isinstance(item, Mapping)
            )
        injury_values = event.payload.get("injury_records")
        if injury_values is not None:
            if not isinstance(injury_values, list):
                raise ValueError("injury_records must be a list")
            injuries = tuple(
                InjuryRecord.from_dict(item)
                for item in injury_values
                if isinstance(item, Mapping)
            )
            if len(injuries) != len(injury_values):
                raise ValueError("injury record must be an object")
            _unique(injuries, "injury_id", "injury")
            changes["injuries"] = injuries
    elif event.event_type is LeagueEventType.OFFSEASON_STAGE_ADVANCED:
        if state.season_cycle is None or state.season_cycle.status != "offseason":
            raise ValueError("the offseason is not active")
        cycle_value = event.payload.get("season_cycle")
        if not isinstance(cycle_value, Mapping):
            raise ValueError("offseason transition requires a season_cycle")
        cycle = FranchiseSeasonRecord.from_dict(cycle_value)
        if cycle.season != state.season_cycle.season:
            raise ValueError("offseason transition references the wrong season")
        changes["season_cycle"] = cycle
        lifecycle_values = event.payload.get("player_lifecycles")
        if lifecycle_values is not None:
            if not isinstance(lifecycle_values, list):
                raise ValueError("player_lifecycles must be a list")
            lifecycles = tuple(
                PlayerLifecycleRecord.from_dict(item)
                for item in lifecycle_values
                if isinstance(item, Mapping)
            )
            if len(lifecycles) != len(lifecycle_values):
                raise ValueError("player lifecycle must be an object")
            if {item.player_id for item in lifecycles} != {
                item.player_id for item in state.players
            }:
                raise ValueError("offseason lifecycle coverage must be complete")
            changes["player_lifecycles"] = lifecycles
        career_values = event.payload.get("career_decisions")
        if career_values is not None:
            if not isinstance(career_values, list):
                raise ValueError("career_decisions must be a list")
            career_decisions = tuple(
                CareerDecisionRecord.from_dict(item)
                for item in career_values
                if isinstance(item, Mapping)
            )
            if len(career_decisions) != len(career_values):
                raise ValueError("career decision must be an object")
            combined_decisions = (*state.career_decisions, *career_decisions)
            _unique(combined_decisions, "decision_id", "career decision")
            changes["career_decisions"] = combined_decisions
        transaction_values = event.payload.get("career_transactions")
        if transaction_values is not None:
            if not isinstance(transaction_values, list):
                raise ValueError("career_transactions must be a list")
            career_transactions = tuple(
                TransactionRecord.from_dict(item)
                for item in transaction_values
                if isinstance(item, Mapping)
            )
            if len(career_transactions) != len(transaction_values):
                raise ValueError("career transaction must be an object")
            combined_transactions = (*state.transactions, *career_transactions)
            _unique(combined_transactions, "transaction_id", "transaction")
            changes["transactions"] = combined_transactions
        plan_values = event.payload.get("roster_plans")
        if plan_values is not None:
            if not isinstance(plan_values, list):
                raise ValueError("roster_plans must be a list")
            plans = tuple(
                RosterPlanRecord.from_dict(item)
                for item in plan_values
                if isinstance(item, Mapping)
            )
            if len(plans) != len(plan_values):
                raise ValueError("roster plan must be an object")
            if {item.team for item in plans} != {
                item.team for item in state.franchises
            }:
                raise ValueError("offseason roster plans must cover every team")
            changes["roster_plans"] = plans
        player_values = event.payload.get("players")
        contract_values = event.payload.get("contracts")
        if player_values is not None or contract_values is not None:
            if not isinstance(player_values, list) or not isinstance(contract_values, list):
                raise ValueError("offseason transition requires complete player and contract lists")
            players = tuple(
                PlayerRecord.from_dict(item)
                for item in player_values
                if isinstance(item, Mapping)
            )
            contracts = tuple(
                ContractRecord.from_dict(item)
                for item in contract_values
                if isinstance(item, Mapping)
            )
            if {item.player_id for item in players} != {
                item.player_id for item in state.players
            }:
                raise ValueError("training camp player coverage must be complete")
            if {item.contract_id for item in contracts} != {
                item.contract_id for item in state.contracts
            }:
                raise ValueError("training camp contract coverage must be complete")
            changes["players"] = players
            changes["contracts"] = contracts
    elif event.event_type is LeagueEventType.SEASON_ROLLED_OVER:
        if state.season_cycle is None or state.season_cycle.status != "offseason":
            raise ValueError("the offseason is not ready to roll over")
        archived_value = event.payload.get("archived_season")
        calendar_value = event.payload.get("calendar")
        cycle_value = event.payload.get("season_cycle")
        if not isinstance(archived_value, Mapping):
            raise ValueError("season rollover requires an archived season")
        if not isinstance(calendar_value, Mapping) or not isinstance(cycle_value, Mapping):
            raise ValueError("season rollover requires a calendar and season cycle")
        archived = FranchiseSeasonRecord.from_dict(archived_value)
        calendar = LeagueCalendar.from_dict(calendar_value)
        cycle = FranchiseSeasonRecord.from_dict(cycle_value)
        next_season_value = str(event.payload.get("season", ""))
        if archived.as_dict() != state.season_cycle.as_dict():
            raise ValueError("archived season does not match the active season")
        if calendar.season != next_season_value or cycle.season != next_season_value:
            raise ValueError("season rollover records disagree")
        if len(state.season_history) >= 99:
            raise ValueError("this franchise has reached its 100-season limit")
        changes.update({
            "season": next_season_value,
            "calendar": calendar,
            "season_cycle": cycle,
            "season_history": (*state.season_history, archived),
            "draft_history": (
                (*state.draft_history, state.draft_ecosystem)
                if state.draft_ecosystem is not None
                and state.draft_ecosystem.status == "complete"
                else state.draft_history
            ),
            "draft_ecosystem": None,
        })
        health_values = event.payload.get("player_health")
        if health_values is not None:
            if not isinstance(health_values, list):
                raise ValueError("player_health must be a list")
            changes["player_health"] = tuple(
                PlayerHealthRecord.from_dict(item)
                for item in health_values
                if isinstance(item, Mapping)
            )
    elif event.event_type is LeagueEventType.CONTRACT_MARKET_INITIALIZED:
        if state.contracts:
            raise ValueError("contract market is already initialized")
        values = event.payload.get("contracts")
        if not isinstance(values, list):
            raise ValueError("contract market requires a contracts list")
        contracts = tuple(
            ContractRecord.from_dict(item)
            for item in values
            if isinstance(item, Mapping)
        )
        if len(contracts) != len(values):
            raise ValueError("contract market record must be an object")
        if {item.player_id for item in contracts} != {item.player_id for item in state.players}:
            raise ValueError("contract market initialization must cover every player")
        _unique(contracts, "contract_id", "contract")
        changes["contracts"] = contracts
    elif event.event_type in {
        LeagueEventType.CONTRACT_UPDATED,
        LeagueEventType.CONTRACT_OPTION_DECIDED,
    }:
        contract_value = event.payload.get("contract")
        transaction_value = event.payload.get("record")
        if not isinstance(contract_value, Mapping) or not isinstance(transaction_value, Mapping):
            raise ValueError("contract decision requires contract and transaction records")
        contract = ContractRecord.from_dict(contract_value)
        if contract.contract_id not in {item.contract_id for item in state.contracts}:
            raise ValueError("contract decision references an unknown contract")
        transaction = TransactionRecord.from_dict(transaction_value)
        changes["contracts"] = tuple(
            contract if item.contract_id == contract.contract_id else item
            for item in state.contracts
        )
        changes["transactions"] = (*state.transactions, transaction)
    elif event.event_type is LeagueEventType.PLAYER_WAIVED:
        contract_value = event.payload.get("contract")
        transaction_value = event.payload.get("record")
        if not isinstance(contract_value, Mapping) or not isinstance(transaction_value, Mapping):
            raise ValueError("waiver requires contract and transaction records")
        contract = ContractRecord.from_dict(contract_value)
        player = next((item for item in state.players if item.player_id == contract.player_id), None)
        if player is None or player.roster_status != "active":
            raise ValueError("waiver player is not active")
        transaction = TransactionRecord.from_dict(transaction_value)
        changes["contracts"] = tuple(
            contract if item.contract_id == contract.contract_id else item
            for item in state.contracts
        )
        changes["players"] = tuple(
            replace(item, roster_status="free_agent")
            if item.player_id == player.player_id
            else item
            for item in state.players
        )
        changes["transactions"] = (*state.transactions, transaction)
        changes["roster_plans"] = ()
    elif event.event_type is LeagueEventType.FREE_AGENT_SIGNED:
        contract_value = event.payload.get("contract")
        transaction_value = event.payload.get("record")
        if not isinstance(contract_value, Mapping) or not isinstance(transaction_value, Mapping):
            raise ValueError("free-agent signing requires contract and transaction records")
        contract = ContractRecord.from_dict(contract_value)
        player = next((item for item in state.players if item.player_id == contract.player_id), None)
        if player is None or player.roster_status != "free_agent":
            raise ValueError("free-agent signing player is unavailable")
        if contract.contract_id in {item.contract_id for item in state.contracts}:
            raise ValueError("free-agent contract already exists")
        transaction = TransactionRecord.from_dict(transaction_value)
        changes["contracts"] = (*state.contracts, contract)
        changes["players"] = tuple(
            replace(item, team=contract.team, roster_status="active")
            if item.player_id == player.player_id
            else item
            for item in state.players
        )
        changes["transactions"] = (*state.transactions, transaction)
        changes["roster_plans"] = ()
    elif event.event_type is LeagueEventType.DRAFT_ASSET_REGISTERED:
        record = DraftAssetRecord.from_dict(_record(event))
        updated = (*state.draft_assets, record)
        _unique(updated, "asset_id", "draft asset")
        changes["draft_assets"] = updated
    elif event.event_type is LeagueEventType.CAP_EXCEPTION_REGISTERED:
        record = CapExceptionRecord.from_dict(_record(event))
        updated = (*state.cap_exceptions, record)
        _unique(updated, "exception_id", "cap exception")
        changes["cap_exceptions"] = updated
    elif event.event_type is LeagueEventType.INJURY_RECORDED:
        record = InjuryRecord.from_dict(_record(event))
        updated = (*state.injuries, record)
        _unique(updated, "injury_id", "injury")
        changes["injuries"] = updated
    elif event.event_type is LeagueEventType.TRANSACTION_RECORDED:
        record = TransactionRecord.from_dict(_record(event))
        updated = (*state.transactions, record)
        _unique(updated, "transaction_id", "transaction")
        changes["transactions"] = updated
    elif event.event_type is LeagueEventType.TRADE_CENTER_INITIALIZED:
        if state.trade_rule_policy is not None:
            raise ValueError("trade center is already initialized")
        policy_value = event.payload.get("policy")
        assets_value = event.payload.get("assets")
        if not isinstance(policy_value, Mapping):
            raise ValueError("trade center requires a rule policy")
        if not isinstance(assets_value, list):
            raise ValueError("trade center requires draft assets")
        assets = tuple(
            DraftAssetRecord.from_dict(item)
            for item in assets_value
            if isinstance(item, Mapping)
        )
        if len(assets) != len(assets_value):
            raise ValueError("trade center draft asset must be an object")
        _unique(assets, "asset_id", "draft asset")
        changes["trade_rule_policy"] = TradeRulePolicy.from_dict(policy_value)
        changes["draft_assets"] = assets
    elif event.event_type is LeagueEventType.TRADE_RULE_POLICY_UPDATED:
        policy_value = event.payload.get("policy")
        if not isinstance(policy_value, Mapping):
            raise ValueError("trade rule event requires a policy")
        changes["trade_rule_policy"] = TradeRulePolicy.from_dict(policy_value)
    elif event.event_type is LeagueEventType.TRADE_COMPLETED:
        if state.trade_rule_policy is None:
            raise ValueError("trade center is not initialized")
        player_moves = event.payload.get("player_moves")
        asset_moves = event.payload.get("asset_moves")
        record_value = event.payload.get("record")
        if not isinstance(player_moves, list) or not isinstance(asset_moves, list):
            raise ValueError("trade event requires movement lists")
        if not isinstance(record_value, Mapping):
            raise ValueError("trade event requires a transaction record")
        players = {item.player_id: item for item in state.players}
        contracts = {item.contract_id: item for item in state.contracts}
        injuries = {item.injury_id: item for item in state.injuries}
        assets = {item.asset_id: item for item in state.draft_assets}
        for move in player_moves:
            if not isinstance(move, Mapping):
                raise ValueError("player movement must be an object")
            player_id = int(move["player_id"])
            from_team = str(move["from_team"]).upper()
            to_team = str(move["to_team"]).upper()
            player = players.get(player_id)
            if player is None or player.team != from_team:
                raise ValueError("trade player ownership changed before execution")
            players[player_id] = replace(player, team=to_team)
            contracts = {
                key: (
                    replace(contract, team=to_team)
                    if contract.player_id == player_id
                    and contract.team == from_team
                    and contract.status == "active"
                    else contract
                )
                for key, contract in contracts.items()
            }
            injuries = {
                key: (
                    replace(injury, team=to_team)
                    if injury.player_id == player_id and injury.team == from_team
                    else injury
                )
                for key, injury in injuries.items()
            }
        for move in asset_moves:
            if not isinstance(move, Mapping):
                raise ValueError("asset movement must be an object")
            asset_id = str(move["asset_id"])
            from_team = str(move["from_team"]).upper()
            to_team = str(move["to_team"]).upper()
            asset = assets.get(asset_id)
            if asset is None or asset.current_team != from_team:
                raise ValueError("trade asset ownership changed before execution")
            assets[asset_id] = replace(asset, current_team=to_team)
        transaction = TransactionRecord.from_dict(record_value)
        transactions = (*state.transactions, transaction)
        _unique(transactions, "transaction_id", "transaction")
        changes["players"] = tuple(players.values())
        changes["contracts"] = tuple(contracts.values())
        changes["injuries"] = tuple(injuries.values())
        changes["draft_assets"] = tuple(assets.values())
        changes["transactions"] = transactions
        changes["roster_plans"] = ()
    elif event.event_type is LeagueEventType.PLAYER_LIFECYCLES_INITIALIZED:
        if state.player_lifecycles:
            raise ValueError("player lifecycles are already initialized")
        records = event.payload.get("records")
        if not isinstance(records, list):
            raise ValueError(
                "player_lifecycles_initialized requires a records payload"
            )
        lifecycles = tuple(
            PlayerLifecycleRecord.from_dict(record)
            for record in records
            if isinstance(record, Mapping)
        )
        if len(lifecycles) != len(records):
            raise ValueError("player lifecycle record must be an object")
        _unique(lifecycles, "player_id", "player lifecycle")
        player_ids = {player.player_id for player in state.players}
        if any(
            lifecycle.player_id not in player_ids
            for lifecycle in lifecycles
        ):
            raise ValueError(
                "player lifecycle references an unknown player"
            )
        if {record.player_id for record in lifecycles} != player_ids:
            raise ValueError(
                "player lifecycle initialization must cover every player"
            )
        changes["player_lifecycles"] = lifecycles
    elif event.event_type is LeagueEventType.PLAYER_HEALTH_INITIALIZED:
        if state.player_health:
            raise ValueError("player health is already initialized")
        records = event.payload.get("records")
        if not isinstance(records, list):
            raise ValueError(
                "player_health_initialized requires a records payload"
            )
        health = tuple(
            PlayerHealthRecord.from_dict(record)
            for record in records
            if isinstance(record, Mapping)
        )
        if len(health) != len(records):
            raise ValueError("player health record must be an object")
        _unique(health, "player_id", "player health")
        player_ids = {player.player_id for player in state.players}
        if {record.player_id for record in health} != player_ids:
            raise ValueError(
                "player health initialization must cover every player"
            )
        changes["player_health"] = health
    elif event.event_type in {
        LeagueEventType.PLAYER_HEALTH_UPDATED,
        LeagueEventType.PLAYER_WORKLOAD_RECORDED,
    }:
        record = PlayerHealthRecord.from_dict(_record(event))
        if not state.player_health:
            raise ValueError("player health is not initialized")
        current_ids = {item.player_id for item in state.player_health}
        if record.player_id not in current_ids:
            raise ValueError("health update references an unknown player")
        updated_health = tuple(
            record if item.player_id == record.player_id else item
            for item in state.player_health
        )
        changes["player_health"] = updated_health
        if state.injuries:
            changes["injuries"] = reconcile_injury_history(
                state.injuries,
                health={item.player_id: item for item in updated_health},
                games=(),
            )
    elif event.event_type is LeagueEventType.TEAM_ENVIRONMENT_INITIALIZED:
        if state.team_chemistry or state.coaching_profiles:
            raise ValueError("team environment is already initialized")
        chemistry = tuple(
            TeamChemistryRecord.from_dict(item)
            for item in event.payload.get("chemistry", [])  # type: ignore[arg-type]
        )
        coaching = tuple(
            CoachingProfileRecord.from_dict(item)
            for item in event.payload.get("coaching", [])  # type: ignore[arg-type]
        )
        teams = {franchise.team for franchise in state.franchises}
        if {item.team for item in chemistry} != teams:
            raise ValueError("chemistry initialization must cover every team")
        if {item.team for item in coaching} != teams:
            raise ValueError("coaching initialization must cover every team")
        changes["team_chemistry"] = chemistry
        changes["coaching_profiles"] = coaching
    elif event.event_type in {
        LeagueEventType.TEAM_CHEMISTRY_UPDATED,
        LeagueEventType.CHEMISTRY_SESSION_RECORDED,
    }:
        record = TeamChemistryRecord.from_dict(_record(event))
        changes["team_chemistry"] = tuple(
            record if item.team == record.team else item
            for item in state.team_chemistry
        )
    elif event.event_type is LeagueEventType.COACHING_PROFILE_UPDATED:
        record = CoachingProfileRecord.from_dict(_record(event))
        changes["coaching_profiles"] = tuple(
            record if item.team == record.team else item
            for item in state.coaching_profiles
        )
    elif event.event_type in {
        LeagueEventType.GM_INTELLIGENCE_INITIALIZED,
        LeagueEventType.GM_PLANS_REVIEWED,
    }:
        if (
            event.event_type is LeagueEventType.GM_INTELLIGENCE_INITIALIZED
            and state.gm_plans
        ):
            raise ValueError("general-manager intelligence is already initialized")
        if (
            event.event_type is LeagueEventType.GM_PLANS_REVIEWED
            and not state.gm_plans
        ):
            raise ValueError("general-manager intelligence is not initialized")
        values = event.payload.get("plans")
        if not isinstance(values, list):
            raise ValueError("general-manager event requires a plans list")
        plans = tuple(
            GeneralManagerPlanRecord.from_dict(item)
            for item in values
            if isinstance(item, Mapping)
        )
        if len(plans) != len(values):
            raise ValueError("general-manager plan must be an object")
        teams = {item.team for item in state.franchises}
        if {item.team for item in plans} != teams:
            raise ValueError("general-manager plans must cover every team")
        changes["gm_plans"] = plans
    elif event.event_type is LeagueEventType.GM_PLAN_UPDATED:
        value = event.payload.get("plan")
        if not isinstance(value, Mapping):
            raise ValueError("general-manager update requires a plan")
        plan = GeneralManagerPlanRecord.from_dict(value)
        if plan.team not in {item.team for item in state.gm_plans}:
            raise ValueError("general-manager update references an unknown plan")
        changes["gm_plans"] = tuple(
            plan if item.team == plan.team else item
            for item in state.gm_plans
        )
    elif event.event_type is LeagueEventType.EXPERIENCE_CONFIGURED:
        value = event.payload.get("experience")
        if not isinstance(value, Mapping):
            raise ValueError("experience event requires an experience record")
        changes["experience"] = FranchiseExperienceRecord.from_dict(value)
    elif event.event_type is LeagueEventType.SCOUTING_INITIALIZED:
        if state.scouting_reports or state.scouting_departments:
            raise ValueError("scouting is already initialized")
        reports = tuple(
            ScoutingReportRecord.from_dict(item)
            for item in event.payload.get("reports", [])  # type: ignore[arg-type]
        )
        departments = tuple(
            ScoutingDepartmentRecord.from_dict(item)
            for item in event.payload.get("departments", [])  # type: ignore[arg-type]
        )
        player_ids = {player.player_id for player in state.players}
        teams = {franchise.team for franchise in state.franchises}
        if {item.player_id for item in reports} != player_ids:
            raise ValueError("scouting initialization must cover every player")
        if {item.team for item in departments} != teams:
            raise ValueError("scouting initialization must cover every team")
        changes["scouting_reports"] = reports
        changes["scouting_departments"] = departments
    elif event.event_type is LeagueEventType.SCOUTING_REPORT_UPDATED:
        record = ScoutingReportRecord.from_dict(_record(event))
        if not state.scouting_reports:
            raise ValueError("scouting is not initialized")
        changes["scouting_reports"] = tuple(
            record if item.player_id == record.player_id else item
            for item in state.scouting_reports
        )
    elif event.event_type is LeagueEventType.SCOUTING_DEPARTMENT_UPDATED:
        record = ScoutingDepartmentRecord.from_dict(_record(event))
        if not state.scouting_departments:
            raise ValueError("scouting is not initialized")
        changes["scouting_departments"] = tuple(
            record if item.team == record.team else item
            for item in state.scouting_departments
        )
    elif event.event_type is LeagueEventType.SCOUTING_CYCLE_COMPLETED:
        department_value = event.payload.get("department")
        report_values = event.payload.get("reports")
        if not isinstance(department_value, Mapping) or not isinstance(report_values, list):
            raise ValueError("scouting cycle payload is invalid")
        department = ScoutingDepartmentRecord.from_dict(department_value)
        updated_reports = {
            report.player_id: report
            for report in (
                ScoutingReportRecord.from_dict(item)
                for item in report_values
                if isinstance(item, Mapping)
            )
        }
        if len(updated_reports) != len(report_values):
            raise ValueError("scouting cycle report must be an object")
        changes["scouting_reports"] = tuple(
            updated_reports.get(item.player_id, item)
            for item in state.scouting_reports
        )
        changes["scouting_departments"] = tuple(
            department if item.team == department.team else item
            for item in state.scouting_departments
        )
    elif event.event_type in {
        LeagueEventType.DRAFT_ECOSYSTEM_INITIALIZED,
        LeagueEventType.DRAFT_LOTTERY_COMPLETED,
        LeagueEventType.DRAFT_COMBINE_COMPLETED,
        LeagueEventType.DRAFT_PROSPECT_SCOUTED,
        LeagueEventType.DRAFT_BOARD_UPDATED,
        LeagueEventType.DRAFT_PICK_MADE,
    }:
        value = event.payload.get("draft")
        if not isinstance(value, Mapping):
            raise ValueError("draft event requires a draft payload")
        draft = DraftEcosystemRecord.from_dict(value)
        if (
            event.event_type is LeagueEventType.DRAFT_ECOSYSTEM_INITIALIZED
            and state.draft_ecosystem is not None
        ):
            raise ValueError("draft ecosystem is already initialized")
        if event.event_type is not LeagueEventType.DRAFT_ECOSYSTEM_INITIALIZED:
            if state.draft_ecosystem is None:
                raise ValueError("draft ecosystem is not initialized")
            if draft.draft_year != state.draft_ecosystem.draft_year:
                raise ValueError("draft event year does not match")
        changes["draft_ecosystem"] = draft
        department_value = event.payload.get("department")
        if department_value is not None:
            if not isinstance(department_value, Mapping):
                raise ValueError("draft scouting department must be an object")
            department = ScoutingDepartmentRecord.from_dict(department_value)
            changes["scouting_departments"] = tuple(
                department if item.team == department.team else item
                for item in state.scouting_departments
            )
        if event.event_type is LeagueEventType.DRAFT_ECOSYSTEM_INITIALIZED:
            assets = event.payload.get("assets", [])
            if not isinstance(assets, list):
                raise ValueError("draft assets payload must be a list")
            generated = tuple(
                DraftAssetRecord.from_dict(item)
                for item in assets
                if isinstance(item, Mapping)
            )
            if len(generated) != len(assets):
                raise ValueError("draft asset must be an object")
            existing = {
                (item.draft_year, item.round, item.original_team): item
                for item in state.draft_assets
            }
            for item in generated:
                existing.setdefault(
                    (item.draft_year, item.round, item.original_team),
                    item,
                )
            changes["draft_assets"] = tuple(existing.values())
        intake_value = event.payload.get("draft_intake")
        if intake_value is not None:
            if event.event_type is not LeagueEventType.DRAFT_PICK_MADE:
                raise ValueError("draft intake can only accompany a completed pick")
            if draft.status != "complete" or not isinstance(intake_value, Mapping):
                raise ValueError("draft intake requires a completed draft")
            player_values = intake_value.get("players")
            lifecycle_values = intake_value.get("player_lifecycles")
            health_values = intake_value.get("player_health")
            report_values = intake_value.get("scouting_reports")
            contract_values = intake_value.get("contracts")
            if not all(isinstance(item, list) for item in (
                player_values, lifecycle_values, health_values,
                report_values, contract_values,
            )):
                raise ValueError("draft intake lists are incomplete")
            new_players = tuple(PlayerRecord.from_dict(item) for item in player_values)
            new_lifecycles = tuple(PlayerLifecycleRecord.from_dict(item) for item in lifecycle_values)
            new_health = tuple(PlayerHealthRecord.from_dict(item) for item in health_values)
            new_reports = tuple(ScoutingReportRecord.from_dict(item) for item in report_values)
            new_contracts = tuple(ContractRecord.from_dict(item) for item in contract_values)
            prospect_ids = {item.player_id for item in draft.prospects}
            if {item.player_id for item in new_players} != prospect_ids:
                raise ValueError("draft intake must materialize every prospect")
            if any(item.player_id in {player.player_id for player in state.players} for item in new_players):
                raise ValueError("draft intake player already exists")
            if not state.player_lifecycles or not state.player_health or not state.scouting_reports:
                raise ValueError("initialize lifecycle, health, and scouting before the draft")
            if {item.player_id for item in new_lifecycles} != prospect_ids:
                raise ValueError("draft lifecycle coverage is incomplete")
            if {item.player_id for item in new_health} != prospect_ids:
                raise ValueError("draft health coverage is incomplete")
            if {item.player_id for item in new_reports} != prospect_ids:
                raise ValueError("draft scouting coverage is incomplete")
            selected_ids = {item.player_id for item in draft.selections}
            if {item.player_id for item in new_contracts} != selected_ids:
                raise ValueError("rookie contracts must cover all drafted players")
            changes["players"] = (*state.players, *new_players)
            changes["player_lifecycles"] = (*state.player_lifecycles, *new_lifecycles)
            changes["player_health"] = (*state.player_health, *new_health)
            changes["scouting_reports"] = (*state.scouting_reports, *new_reports)
            changes["contracts"] = (*state.contracts, *new_contracts)
    elif event.event_type not in {
        LeagueEventType.LEAGUE_CREATED,
        LeagueEventType.BRANCH_CREATED,
    }:
        raise ValueError(f"unsupported league event: {event.event_type.value}")

    return replace(
        state,
        **changes,
        revision=event.sequence,
        head_hash=event.event_hash,
    )


def _record(event: LeagueEvent) -> Mapping[str, object]:
    value = event.payload.get("record")
    if not isinstance(value, Mapping):
        raise ValueError(f"{event.event_type.value} requires a record payload")
    return value
