from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Mapping

from nba_sim.franchise.season_cycle import FranchiseSeasonRecord

if TYPE_CHECKING:
    from nba_sim.franchise.state import LeagueState


OFFSEASON_MODEL_VERSION = "franchise-offseason-state-machine.v1"
OFFSEASON_STAGES = (
    "awards_and_lottery",
    "combine_and_scouting",
    "nba_draft",
    "contract_decisions",
    "free_agency",
    "player_progression",
    "training_camp",
    "ready_for_next_season",
)


@dataclass(frozen=True)
class OffseasonStageDefinition:
    key: str
    label: str
    description: str
    destination: str
    automatic: bool


_STAGE_DEFINITIONS = (
    OffseasonStageDefinition(
        "awards_and_lottery",
        "Awards & lottery",
        "Review the saved season honors and lock the complete two-round draft order.",
        "draft",
        True,
    ),
    OffseasonStageDefinition(
        "combine_and_scouting",
        "Combine & scouting",
        "Finish verified measurements and the final prospect information cycle.",
        "draft",
        True,
    ),
    OffseasonStageDefinition(
        "nba_draft",
        "NBA Draft",
        "Complete all 60 selections. CPU teams use only the information available to them.",
        "draft",
        False,
    ),
    OffseasonStageDefinition(
        "contract_decisions",
        "Contract decisions",
        "Resolve options, extensions, guarantees and expiring-player plans before the market opens.",
        "contracts",
        False,
    ),
    OffseasonStageDefinition(
        "free_agency",
        "Free agency",
        "Build legal rosters through the same cap, exception and player-interest rules as every CPU team.",
        "contracts",
        False,
    ),
    OffseasonStageDefinition(
        "player_progression",
        "Player progression",
        "Commit one seeded year of attribute-specific development and decline from actual workload and health.",
        "development",
        True,
    ),
    OffseasonStageDefinition(
        "training_camp",
        "Training camp",
        "Rebuild every depth chart, enforce roster limits and confirm a legal 240-minute rotation.",
        "roster",
        True,
    ),
    OffseasonStageDefinition(
        "ready_for_next_season",
        "Open next season",
        "Make final cuts, then archive this season and create the next 1,230-game calendar after every integrity check passes.",
        "contracts",
        False,
    ),
)


def next_season(season: str) -> str:
    try:
        start = int(season.split("-", 1)[0]) + 1
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid season: {season}") from error
    return f"{start}-{(start + 1) % 100:02d}"


def season_calendar_dates(season: str) -> dict[str, date]:
    start = int(season.split("-", 1)[0])
    return {
        "cap_year_start": date(start, 7, 1),
        "cap_year_end": date(start + 1, 6, 30),
        "regular_season_start": date(start, 10, 20),
        "regular_season_end": date(start + 1, 4, 12),
    }


def season_seed(league_seed: int, season: str) -> int:
    digest = hashlib.sha256(
        f"{league_seed}|franchise-season|{season}".encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFFFFFF


def offseason_stage_index(stage: str | None) -> int:
    normalized = stage or OFFSEASON_STAGES[0]
    if normalized not in OFFSEASON_STAGES:
        raise ValueError(f"unknown offseason stage: {normalized}")
    return OFFSEASON_STAGES.index(normalized)


def advance_offseason_cycle(
    cycle: FranchiseSeasonRecord,
    *,
    expected_stage: str,
) -> FranchiseSeasonRecord:
    if cycle.status != "offseason":
        raise ValueError("the offseason begins after the NBA Finals")
    current = cycle.offseason_stage or OFFSEASON_STAGES[0]
    if expected_stage != current:
        if (
            expected_stage in OFFSEASON_STAGES
            and offseason_stage_index(expected_stage) < offseason_stage_index(current)
        ):
            return cycle
        raise ValueError(
            f"offseason stage changed; refresh and continue from {current.replace('_', ' ')}"
        )
    index = offseason_stage_index(current)
    if index + 1 >= len(OFFSEASON_STAGES):
        raise ValueError("the league is ready to open the next season")
    from dataclasses import replace

    return replace(cycle, offseason_stage=OFFSEASON_STAGES[index + 1])


def offseason_hub_response(state: "LeagueState") -> dict[str, object]:
    cycle = state.season_cycle
    if cycle is None or cycle.status not in {"offseason", "complete"}:
        return {
            "ready": False,
            "active": False,
            "model_version": OFFSEASON_MODEL_VERSION,
        }
    current = cycle.offseason_stage or OFFSEASON_STAGES[0]
    index = offseason_stage_index(current)
    readiness = offseason_stage_readiness(state, current)
    rows = []
    for stage_index, definition in enumerate(_STAGE_DEFINITIONS):
        status = (
            "complete" if stage_index < index
            else "current" if stage_index == index
            else "upcoming"
        )
        row_readiness = (
            readiness
            if definition.key == current
            else {"can_advance": False, "blockers": [], "checks": []}
        )
        rows.append({
            "key": definition.key,
            "label": definition.label,
            "description": definition.description,
            "destination": definition.destination,
            "automatic": definition.automatic,
            "status": status,
            **row_readiness,
        })
    return {
        "ready": True,
        "active": cycle.status == "offseason",
        "season": cycle.season,
        "next_season": next_season(cycle.season),
        "current_stage": current,
        "current_label": _STAGE_DEFINITIONS[index].label,
        "current_destination": _STAGE_DEFINITIONS[index].destination,
        "can_advance": readiness["can_advance"],
        "blockers": readiness["blockers"],
        "checks": readiness["checks"],
        "completed_stages": index,
        "total_stages": len(OFFSEASON_STAGES),
        "progress": round(index / len(OFFSEASON_STAGES), 6),
        "stages": rows,
        "model_version": OFFSEASON_MODEL_VERSION,
        "integrity_rule": (
            "Each stage is a single replayable ledger transition. Retrying a "
            "completed stage cannot duplicate its work."
        ),
    }


def offseason_stage_readiness(
    state: "LeagueState",
    stage: str,
) -> dict[str, object]:
    checks: list[dict[str, object]] = []

    def check(label: str, passed: bool, detail: str) -> None:
        checks.append({"label": label, "passed": passed, "detail": detail})

    cycle = state.season_cycle
    if cycle is None:
        check("Completed season", False, "The Season Hub has not been initialized.")
    elif stage == "awards_and_lottery":
        check("NBA champion", bool(cycle.champion), "The Finals result must be saved.")
        check("Season honors", bool(cycle.honors), "The regular-season ballot must be frozen.")
        check(
            "Draft lottery",
            bool(state.draft_ecosystem and state.draft_ecosystem.order),
            "Generate the class and run the 3-2-1 lottery in Draft Room.",
        )
    elif stage == "combine_and_scouting":
        check(
            "Draft combine",
            bool(state.draft_ecosystem and state.draft_ecosystem.combine_complete),
            "Run the combine before locking final evaluations.",
        )
    elif stage == "nba_draft":
        drafted = len(state.draft_ecosystem.selections) if state.draft_ecosystem else 0
        total = len(state.draft_ecosystem.order) if state.draft_ecosystem else 60
        check(
            "All draft selections",
            bool(state.draft_ecosystem and state.draft_ecosystem.status == "complete"),
            f"{drafted} of {total} selections are saved.",
        )
    elif stage == "training_camp":
        teams = {item.team for item in state.franchises}
        plan_teams = {item.team for item in state.roster_plans}
        invalid = [
            team for team in teams
            if len(state.roster(team)) < 5
        ]
        check("League rotations", plan_teams == teams, "All 30 teams require a saved depth chart.")
        check("Training-camp player pool", not invalid, "Every team needs at least five active players before final cuts.")
    elif stage == "ready_for_next_season":
        teams = {item.team for item in state.franchises}
        invalid = [team for team in teams if not 5 <= len(state.roster(team)) <= 15]
        check("Regular-season rosters", not invalid, "Every team must carry 5–15 active players before opening night.")
        check("Thirty team plans", {item.team for item in state.roster_plans} == teams, "All depth charts must be present.")
        check("Complete schedule source", cycle is not None and cycle.champion is not None, "The previous season must remain complete.")
    else:
        check("Stage acknowledged", True, "This control room is ready for your decisions.")

    blockers = [str(item["detail"]) for item in checks if not item["passed"]]
    return {"can_advance": not blockers, "blockers": blockers, "checks": checks}


def definitions() -> tuple[Mapping[str, object], ...]:
    return tuple(definition.__dict__ for definition in _STAGE_DEFINITIONS)


__all__ = [
    "OFFSEASON_MODEL_VERSION",
    "OFFSEASON_STAGES",
    "advance_offseason_cycle",
    "next_season",
    "offseason_hub_response",
    "offseason_stage_readiness",
    "season_calendar_dates",
    "season_seed",
]
