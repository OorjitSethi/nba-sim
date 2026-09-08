from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import TYPE_CHECKING

from nba_sim.franchise.cba import CBA_2026_27, TransactionAction, evaluate_transaction
from nba_sim.franchise.models import FranchiseExperienceRecord

if TYPE_CHECKING:
    from nba_sim.franchise.state import LeagueState


PUBLIC_EXPERIENCE_MODEL_VERSION = "public-playtest-experience.v1"


def default_experience(*, as_of: date) -> FranchiseExperienceRecord:
    return FranchiseExperienceRecord(
        configured_on=as_of,
        preset="guided",
        difficulty="pro",
        contextual_help=True,
        confirm_consequential_moves=True,
        show_advanced_by_default=False,
        onboarding_complete=False,
        model_version=PUBLIC_EXPERIENCE_MODEL_VERSION,
    )


def configured_experience(
    state: "LeagueState",
    *,
    preset: str,
    difficulty: str,
    contextual_help: bool,
    confirm_consequential_moves: bool,
    show_advanced_by_default: bool,
    onboarding_complete: bool = True,
) -> FranchiseExperienceRecord:
    current = state.experience or default_experience(as_of=state.calendar.current_date)
    return replace(
        current,
        configured_on=state.calendar.current_date,
        preset=preset,
        difficulty=difficulty,
        contextual_help=contextual_help,
        confirm_consequential_moves=confirm_consequential_moves,
        show_advanced_by_default=show_advanced_by_default,
        onboarding_complete=onboarding_complete,
        model_version=PUBLIC_EXPERIENCE_MODEL_VERSION,
    )


def experience_response(state: "LeagueState") -> dict[str, object]:
    experience = state.experience or default_experience(
        as_of=state.calendar.current_date
    )
    return {
        "ready": state.experience is not None,
        **experience.as_dict(),
        "preset_copy": {
            "guided": "Staff automates specialist work and explains every consequential decision.",
            "balanced": "Staff recommends; you approve the major roster and strategy choices.",
            "full_control": "Manual control is exposed by default while the same league rules remain active.",
        }[experience.preset],
        "difficulty_copy": {
            "rookie": "Maximum explanation and a wider CPU negotiation tolerance.",
            "pro": "Complete information with baseline negotiation tolerance.",
            "expert": "Front-office information fog and tighter negotiation tolerance.",
        }[experience.difficulty],
        "accuracy_contract": (
            "Difficulty never modifies player ratings, possession probabilities, "
            "injuries, schedule context, or simulation seeds."
        ),
    }


def public_release_audit(
    state: "LeagueState",
    *,
    integrity_verified: bool,
) -> dict[str, object]:
    checks: list[dict[str, object]] = []

    def check(
        key: str,
        label: str,
        passed: bool,
        detail: str,
        *,
        required: bool = True,
        waiting: bool = False,
    ) -> None:
        checks.append({
            "key": key,
            "label": label,
            "status": "waiting" if waiting else "pass" if passed else "fail",
            "required": required,
            "detail": detail,
        })

    teams = {item.team for item in state.franchises}
    player_ids = [item.player_id for item in state.players]
    check(
        "league_shape",
        "30-team league shape",
        len(teams) == 30,
        f"{len(teams)} unique franchises are loaded.",
    )
    check(
        "player_ownership",
        "Canonical player ownership",
        len(player_ids) == len(set(player_ids))
        and all(item.team in teams for item in state.players),
        f"{len(player_ids)} players have one canonical identity and team.",
    )
    check(
        "replay_integrity",
        "Hash-chain replay integrity",
        integrity_verified,
        "Genesis state and every saved event replay to the current head hash.",
    )
    check(
        "ratings_coverage",
        "Established-player ratings coverage",
        len(state.player_lifecycles) == len(state.players),
        f"{len(state.player_lifecycles)} of {len(state.players)} lifecycle/rating baselines are present.",
    )
    check(
        "health_coverage",
        "Health and workload coverage",
        len(state.player_health) == len(state.players),
        f"{len(state.player_health)} of {len(state.players)} players have durable health state.",
    )
    check(
        "front_office_coverage",
        "General-manager intelligence",
        len(state.gm_plans) == len(state.franchises),
        f"{len(state.gm_plans)} of {len(state.franchises)} teams have persistent plans.",
    )
    rotations_valid = len(state.roster_plans) == len(state.franchises) and all(
        not [
            item for item in plan.assignments
            if item.designation not in {"g_league", "inactive"}
            and item.target_minutes > 0
        ]
        or (
            sum(item.starter for item in plan.assignments) == 5
            and abs(sum(item.target_minutes for item in plan.assignments) - 240) <= 0.2
        )
        for plan in state.roster_plans
    )
    check(
        "rotation_invariants",
        "League rotation invariants",
        rotations_valid,
        f"{len(state.roster_plans)} plans checked for five starters and 240 minutes.",
    )
    cycle = state.season_cycle
    schedule_valid = False
    if cycle is not None:
        regular = [item for item in cycle.games if item.stage == "regular_season"]
        counts = {team: 0 for team in teams}
        home = {team: 0 for team in teams}
        dates: set[tuple[str, date]] = set()
        duplicate_date = False
        for game in regular:
            counts[game.home_team] += 1
            counts[game.away_team] += 1
            home[game.home_team] += 1
            for team in (game.home_team, game.away_team):
                identity = (team, game.game_date)
                duplicate_date = duplicate_date or identity in dates
                dates.add(identity)
        schedule_valid = (
            len(regular) == 1_230
            and set(counts.values()) == {82}
            and set(home.values()) == {41}
            and not duplicate_date
        )
    check(
        "schedule_invariants",
        "NBA schedule invariants",
        schedule_valid,
        "1,230 games, 82 per team, 41 home, and no team scheduled twice in one day.",
    )
    completed = [item for item in cycle.games if item.completed] if cycle else []
    boxes_valid = all(
        sum(item.points for item in game.box_scores if item.team == game.home_team)
        == game.home_score
        and sum(item.points for item in game.box_scores if item.team == game.away_team)
        == game.away_score
        for game in completed
    )
    check(
        "box_score_integrity",
        "Saved game and box-score integrity",
        boxes_valid,
        f"{len(completed)} completed games reconcile player points to final scores.",
    )
    check(
        "contract_coverage",
        "Contract ledger coverage",
        len({item.player_id for item in state.contracts}) == len(state.players),
        f"{len(state.contracts)} modeled or sourced contract records are loaded.",
    )
    legal_fixture = evaluate_transaction(
        team_salary=CBA_2026_27.salary_cap + 5_000_000,
        outgoing_salary=10_000_000,
        incoming_salary=10_000_000,
        action=TransactionAction.STANDARD_TRADE,
    )
    apron_fixture = evaluate_transaction(
        team_salary=CBA_2026_27.first_apron,
        outgoing_salary=0,
        incoming_salary=2_000_000,
        action=TransactionAction.NON_TAXPAYER_MLE,
    )
    check(
        "cba_fixtures",
        "CBA transaction fixtures",
        legal_fixture.legal and not apron_fixture.legal,
        "A legal salary match clears and a first-apron hard-cap breach is rejected.",
    )
    trade_ready = state.trade_rule_policy is not None
    check(
        "trade_market",
        "Trade market initialized",
        trade_ready,
        "All rule toggles and CPU market controls are available."
        if trade_ready
        else "Initialize Trade Center before testing offers and CPU-to-CPU trades.",
        required=False,
        waiting=not trade_ready,
    )
    if len(completed) >= 30:
        mean_total = sum(int(item.home_score) + int(item.away_score) for item in completed) / len(completed)
        mean_possessions = sum(float(item.possessions or 0) for item in completed) / len(completed)
        plausible = 180 <= mean_total <= 270 and 78 <= mean_possessions <= 118
        detail = f"{len(completed)} games average {mean_total:.1f} points and {mean_possessions:.1f} possessions."
        check("season_plausibility", "Season plausibility sample", plausible, detail)
    else:
        check(
            "season_plausibility",
            "Season plausibility sample",
            True,
            f"Play at least 30 games to unlock the save-specific ecology check ({len(completed)} complete).",
            required=False,
            waiting=True,
        )
    required = [item for item in checks if item["required"]]
    passed = sum(item["status"] == "pass" for item in required)
    failures = [item for item in required if item["status"] == "fail"]
    return {
        "kind": "public_release_audit",
        "ready_for_playtest": not failures,
        "score": round(passed / len(required), 6) if required else 1.0,
        "passed": passed,
        "required": len(required),
        "warnings": sum(item["status"] == "waiting" for item in checks),
        "checks": checks,
        "model_version": PUBLIC_EXPERIENCE_MODEL_VERSION,
    }


def recovery_guidance(message: str) -> str:
    value = message.lower()
    if "initialize" in value or "not initialized" in value:
        return "Open the named Franchise workspace and use its setup button; your save was not changed."
    if "unknown player" in value or "ownership" in value:
        return "Reload the active save so the screen uses the latest roster and asset ownership."
    if "illegal trade" in value or "blocked" in value:
        return "Open the Trade Center explanation to see the exact active rule and a legal counteroffer path."
    if "no regular-season games" in value or "regular season is complete" in value:
        return "Open Season Hub and continue to the postseason or offseason stage shown there."
    if "roster" in value or "minutes" in value or "starter" in value:
        return "Use Roster & Rotation to restore five starters and a 240-minute active rotation."
    return "Nothing was saved. Review the highlighted setup, or create a branch before trying a different decision."


__all__ = [
    "PUBLIC_EXPERIENCE_MODEL_VERSION",
    "configured_experience",
    "default_experience",
    "experience_response",
    "public_release_audit",
    "recovery_guidance",
]
