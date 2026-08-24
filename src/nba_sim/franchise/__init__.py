"""Event-sourced franchise simulation kernel."""

from nba_sim.franchise.bootstrap import build_current_league_state
from nba_sim.franchise.cba import (
    CBA_2026_27,
    CapBand,
    TransactionAction,
    cap_position,
    evaluate_transaction,
    team_cap_sheet,
)
from nba_sim.franchise.events import LeagueEvent, LeagueEventType
from nba_sim.franchise.lifecycle import (
    DEVELOPMENT_FOCUSES,
    LIFECYCLE_MODEL_VERSION,
    LifecycleProjectionConfig,
    build_lifecycle_record,
    lifecycle_stage,
    project_lifecycle,
)
from nba_sim.franchise.health import (
    AVAILABILITY_STATES,
    HEALTH_MODEL_VERSION,
    advance_health_record,
    apply_workload,
    availability_policy,
    build_health_record,
    load_concern_index,
    update_health_status,
)
from nba_sim.franchise.repository import FranchiseSaveRepository
from nba_sim.franchise.state import LeagueState, apply_league_event

__all__ = [
    "FranchiseSaveRepository",
    "CBA_2026_27",
    "CapBand",
    "LeagueEvent",
    "LeagueEventType",
    "LeagueState",
    "LifecycleProjectionConfig",
    "HEALTH_MODEL_VERSION",
    "TransactionAction",
    "apply_league_event",
    "advance_health_record",
    "apply_workload",
    "availability_policy",
    "build_health_record",
    "build_lifecycle_record",
    "build_current_league_state",
    "cap_position",
    "evaluate_transaction",
    "lifecycle_stage",
    "load_concern_index",
    "project_lifecycle",
    "team_cap_sheet",
    "update_health_status",
    "AVAILABILITY_STATES",
    "DEVELOPMENT_FOCUSES",
    "LIFECYCLE_MODEL_VERSION",
]
