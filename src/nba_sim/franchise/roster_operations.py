from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Iterable, Mapping

from nba_sim.domain.profiles import TeamProfile
from nba_sim.franchise.models import RotationAssignmentRecord, RosterPlanRecord

if TYPE_CHECKING:
    from nba_sim.franchise.state import LeagueState


ROSTER_OPERATIONS_MODEL_VERSION = "roster-operations-coach-medical.v1"
MAX_STANDARD_CONTRACTS = 15
MAX_TWO_WAY_CONTRACTS = 3


def roster_plan(state: "LeagueState", team: str) -> RosterPlanRecord | None:
    normalized = team.upper()
    return next((item for item in state.roster_plans if item.team == normalized), None)


def _player_context(state: "LeagueState", player_id: int) -> dict[str, float | str | None]:
    lifecycle = next(
        (item for item in state.player_lifecycles if item.player_id == player_id),
        None,
    )
    health = next(
        (item for item in state.player_health if item.player_id == player_id),
        None,
    )
    return {
        "overall": lifecycle.overall if lifecycle else 65.0,
        "potential": lifecycle.potential_mean if lifecycle else 67.0,
        "age": lifecycle.age if lifecycle else None,
        "readiness": health.readiness if health else 100.0,
        "load_concern": health.load_concern if health else 0.0,
        "availability": health.availability if health else "available",
        "minute_limit": health.minute_limit if health else None,
    }


def _rotation_score(
    context: Mapping[str, float | str | None],
    *,
    expected_minutes: float,
    objective: str,
) -> float:
    overall = float(context["overall"] or 65)
    potential = float(context["potential"] or overall)
    age = context["age"]
    readiness = float(context["readiness"] or 0)
    if objective == "win_now":
        score = overall * 1.34 + expected_minutes * 0.42
        if age is not None and 25 <= float(age) <= 32:
            score += 2.0
    elif objective == "development":
        youth = max(-5.0, min(8.0, (27 - float(age)) * 0.8)) if age is not None else 0
        score = overall * 0.92 + potential * 0.34 + youth + expected_minutes * 0.22
    else:
        score = overall * 1.16 + potential * 0.14 + expected_minutes * 0.32
    score += (readiness - 80) * 0.09
    score -= float(context["load_concern"] or 0) * 5.0
    if context["availability"] == "questionable":
        score -= 6.0
    elif context["availability"] in {"doubtful", "out"}:
        score -= 100.0
    return score


def _allocate_minutes(
    player_ids: tuple[int, ...],
    weights: Mapping[int, float],
    caps: Mapping[int, float],
) -> dict[int, float]:
    if len(player_ids) < 5:
        raise ValueError("a game plan requires at least five available players")
    if sum(caps[player_id] for player_id in player_ids) < 240 - 1e-8:
        raise ValueError("health and roster assignments leave fewer than 240 available minutes")
    remaining = 240.0
    allocations = {player_id: 0.0 for player_id in player_ids}
    available = set(player_ids)
    while available and remaining > 1e-8:
        denominator = sum(max(0.1, weights[player_id]) for player_id in available)
        capped: list[int] = []
        for player_id in available:
            proposed = remaining * max(0.1, weights[player_id]) / denominator
            room = caps[player_id] - allocations[player_id]
            if proposed >= room - 1e-8:
                capped.append(player_id)
        if not capped:
            for player_id in available:
                allocations[player_id] += remaining * max(0.1, weights[player_id]) / denominator
            remaining = 0.0
            break
        for player_id in capped:
            addition = caps[player_id] - allocations[player_id]
            allocations[player_id] += addition
            remaining -= addition
            available.remove(player_id)
    rounded = {player_id: round(value, 1) for player_id, value in allocations.items()}
    delta = round(240.0 - sum(rounded.values()), 1)
    if abs(delta) > 0:
        for player_id in sorted(player_ids, key=lambda item: rounded[item], reverse=True):
            proposed = rounded[player_id] + delta
            if 0 <= proposed <= caps[player_id] + 1e-8:
                rounded[player_id] = round(proposed, 1)
                break
    return rounded


def build_roster_plan(
    state: "LeagueState",
    team: str,
    *,
    delegation: str = "recommend",
    objective: str = "balanced",
    preserve: RosterPlanRecord | None = None,
) -> RosterPlanRecord:
    normalized = team.upper()
    players = state.roster(normalized)
    if len(players) < 5:
        raise ValueError(f"{normalized} needs at least five active roster players")
    coaching = next(
        (item for item in state.coaching_profiles if item.team == normalized),
        None,
    )
    depth = min(len(players), coaching.rotation_depth if coaching else 10)
    previous = {
        item.player_id: item for item in preserve.assignments
    } if preserve is not None else {}
    ranked: list[tuple[float, object, dict[str, float | str | None]]] = []
    for player in players:
        context = _player_context(state, player.player_id)
        ranked.append(
            (
                _rotation_score(
                    context,
                    expected_minutes=player.expected_minutes,
                    objective=objective,
                ),
                player,
                context,
            )
        )
    ranked.sort(key=lambda item: (-item[0], -item[1].expected_minutes, item[1].name))

    eligible = []
    for score, player, context in ranked:
        old = previous.get(player.player_id)
        designation = old.designation if old is not None else "standard"
        # Medical inactives created by the optimizer are re-evaluated each time.
        # Explicit user/G League assignments remain durable.
        if (
            old is not None
            and preserve is not None
            and preserve.source == "coach-medical-optimizer"
            and designation == "inactive"
        ):
            designation = "standard"
        if designation in {"g_league", "inactive"}:
            continue
        if context["availability"] in {"doubtful", "out"}:
            continue
        eligible.append((score, player, context, designation))
    rotation = eligible[:depth]
    if len(rotation) < 5:
        raise ValueError("medical and assignment restrictions leave fewer than five available players")
    rotation_ids = tuple(item[1].player_id for item in rotation)
    starters = set(item[1].player_id for item in rotation[:5])
    weights = {}
    caps = {}
    for index, (_, player, context, _) in enumerate(rotation):
        overall = float(context["overall"] or 65)
        weights[player.player_id] = max(
            5.0,
            player.expected_minutes * 0.58
            + max(0.0, overall - 60) * 0.72
            + (5.0 if player.player_id in starters else 0.0)
            + (2.0 if objective == "development" and (context["age"] or 99) < 24 else 0.0),
        )
        medical_cap = context["minute_limit"]
        if medical_cap is None and context["availability"] == "questionable":
            medical_cap = 30.0
        if medical_cap is None and float(context["load_concern"] or 0) >= 0.55:
            medical_cap = 30.0
        caps[player.player_id] = min(48.0, float(medical_cap) if medical_cap is not None else 48.0)
        if index >= 8:
            caps[player.player_id] = min(caps[player.player_id], 24.0)
    minutes = _allocate_minutes(rotation_ids, weights, caps)

    assignments = []
    rotation_order = {player_id: index for index, player_id in enumerate(rotation_ids)}
    for slot, (_, player, context) in enumerate(ranked, start=1):
        old = previous.get(player.player_id)
        designation = old.designation if old is not None else "standard"
        if (
            old is not None
            and preserve is not None
            and preserve.source == "coach-medical-optimizer"
            and designation == "inactive"
        ):
            designation = "standard"
        is_rotation = player.player_id in rotation_order
        is_starter = player.player_id in starters
        overall = float(context["overall"] or 65)
        age = context["age"]
        index = rotation_order.get(player.player_id, 99)
        if not is_rotation:
            role = "development" if age is not None and float(age) < 24 else "bench"
        elif overall >= 91:
            role = "franchise"
        elif overall >= 86:
            role = "star"
        elif is_starter:
            role = "starter"
        elif index == 5:
            role = "sixth"
        else:
            role = "rotation"
        if context["availability"] in {"doubtful", "out"}:
            designation = "inactive"
        assignments.append(
            RotationAssignmentRecord(
                player_id=player.player_id,
                depth_slot=slot,
                role=role,
                designation=designation,
                target_minutes=minutes.get(player.player_id, 0.0),
                starter=is_starter,
                role_promise=old.role_promise if old is not None else None,
            )
        )
    return RosterPlanRecord(
        team=normalized,
        as_of_date=state.calendar.current_date,
        delegation=delegation,
        objective=objective,
        assignments=tuple(assignments),
        source="coach-medical-optimizer",
        model_version=ROSTER_OPERATIONS_MODEL_VERSION,
    )


def build_league_roster_plans(state: "LeagueState") -> tuple[RosterPlanRecord, ...]:
    return tuple(
        build_roster_plan(state, franchise.team)
        for franchise in state.franchises
    )


def update_roster_plan(
    state: "LeagueState",
    current: RosterPlanRecord,
    *,
    assignments: Iterable[Mapping[str, object]],
    delegation: str,
    objective: str,
) -> RosterPlanRecord:
    existing = {item.player_id: item for item in current.assignments}
    overrides = {int(item["player_id"]): item for item in assignments}
    if set(overrides) != set(existing):
        raise ValueError("rotation update must include every player on the current plan")
    if sum(str(item.get("designation", "standard")) == "two_way" for item in overrides.values()) > MAX_TWO_WAY_CONTRACTS:
        raise ValueError("an NBA roster can carry at most three two-way players")
    provisional = []
    for player_id, old in existing.items():
        value = overrides[player_id]
        designation = str(value.get("designation", old.designation))
        target = float(value.get("target_minutes", old.target_minutes))
        starter = bool(value.get("starter", old.starter))
        if designation in {"g_league", "inactive"}:
            target = 0.0
            starter = False
        provisional.append(
            replace(
                old,
                depth_slot=int(value.get("depth_slot", old.depth_slot)),
                role=str(value.get("role", old.role)),
                designation=designation,
                target_minutes=max(0.0, min(48.0, target)),
                starter=starter,
                role_promise=(
                    str(value["role_promise"])
                    if value.get("role_promise") not in {None, "", "none"}
                    else None
                ),
            )
        )
    eligible = [
        item for item in provisional
        if item.designation not in {"g_league", "inactive"}
    ]
    if len(eligible) < 5:
        raise ValueError("at least five players must remain available")
    weights = {item.player_id: max(0.1, item.target_minutes) for item in eligible}
    contexts = {item.player_id: _player_context(state, item.player_id) for item in eligible}
    caps = {
        item.player_id: min(
            48.0,
            float(contexts[item.player_id]["minute_limit"])
            if contexts[item.player_id]["minute_limit"] is not None
            else 48.0,
        )
        for item in eligible
    }
    minutes = _allocate_minutes(tuple(item.player_id for item in eligible), weights, caps)
    starter_ids = {item.player_id for item in eligible if item.starter}
    if len(starter_ids) != 5:
        starter_ids = {
            item.player_id
            for item in sorted(eligible, key=lambda row: (-minutes[row.player_id], row.depth_slot))[:5]
        }
    normalized = tuple(
        replace(
            item,
            target_minutes=minutes.get(item.player_id, 0.0),
            starter=item.player_id in starter_ids,
        )
        for item in sorted(provisional, key=lambda row: row.depth_slot)
    )
    return RosterPlanRecord(
        team=current.team,
        as_of_date=state.calendar.current_date,
        delegation=delegation,
        objective=objective,
        assignments=normalized,
        source="user-rotation-plan",
        model_version=ROSTER_OPERATIONS_MODEL_VERSION,
    )


def roster_recommendations(state: "LeagueState", plan: RosterPlanRecord) -> list[dict[str, object]]:
    players = {item.player_id: item for item in state.players}
    recommendations: list[dict[str, object]] = []
    role_rank = {
        "development": 0, "bench": 1, "rotation": 2, "sixth": 3,
        "starter": 4, "star": 5, "franchise": 6,
    }
    for assignment in plan.assignments:
        player = players[assignment.player_id]
        context = _player_context(state, assignment.player_id)
        if context["availability"] in {"doubtful", "out"} and assignment.designation != "inactive":
            recommendations.append({
                "severity": "required",
                "player_id": player.player_id,
                "title": f"Sit {player.name}",
                "detail": f"Medical status is {context['availability']}; remove him from the active game plan.",
            })
        elif float(context["load_concern"] or 0) >= 0.55 and assignment.target_minutes > 30:
            recommendations.append({
                "severity": "medical",
                "player_id": player.player_id,
                "title": f"Reduce {player.name}'s load",
                "detail": f"Load concern is {float(context['load_concern']):.0%}; the staff plan should stay near 30 minutes.",
            })
        if assignment.role_promise is not None and role_rank.get(assignment.role, 0) < role_rank.get(assignment.role_promise, 0):
            recommendations.append({
                "severity": "relationship",
                "player_id": player.player_id,
                "title": f"Role promise at risk: {player.name}",
                "detail": f"Promised {assignment.role_promise}, currently assigned {assignment.role} at {assignment.target_minutes:.1f} minutes.",
            })
    if not recommendations:
        recommendations.append({
            "severity": "clear",
            "player_id": None,
            "title": "Rotation is internally consistent",
            "detail": "Five starters, 240 minutes, medical restrictions and role promises all clear the current checks.",
        })
    return recommendations


def roster_operations_response(state: "LeagueState") -> dict[str, object]:
    plan = roster_plan(state, state.user_team)
    if plan is None:
        return {"ready": False, "model_version": ROSTER_OPERATIONS_MODEL_VERSION}
    players = {item.player_id: item for item in state.players}
    lifecycles = {item.player_id: item for item in state.player_lifecycles}
    health = {item.player_id: item for item in state.player_health}
    rows = []
    for item in plan.assignments:
        player = players[item.player_id]
        lifecycle = lifecycles.get(item.player_id)
        medical = health.get(item.player_id)
        rows.append({
            **item.as_dict(),
            "name": player.name,
            "position": player.position,
            "overall": round(lifecycle.overall, 1) if lifecycle else None,
            "potential": round(lifecycle.potential_mean, 1) if lifecycle else None,
            "age": round(lifecycle.age, 1) if lifecycle and lifecycle.age is not None else None,
            "availability": medical.availability if medical else "available",
            "readiness": round(medical.readiness, 1) if medical else 100.0,
            "load_concern": round(medical.load_concern, 4) if medical else 0.0,
        })
    available = [item for item in plan.assignments if item.target_minutes > 0]
    return {
        "ready": True,
        "team": plan.team,
        "as_of_date": plan.as_of_date.isoformat(),
        "delegation": plan.delegation,
        "objective": plan.objective,
        "assignments": rows,
        "recommendations": roster_recommendations(state, plan),
        "metrics": {
            "starters": sum(item.starter for item in available),
            "rotation_players": len(available),
            "target_minutes": round(sum(item.target_minutes for item in available), 1),
            "two_way_players": sum(item.designation == "two_way" for item in plan.assignments),
            "g_league_assignments": sum(item.designation == "g_league" for item in plan.assignments),
            "inactive": sum(item.designation == "inactive" for item in plan.assignments),
            "role_promises": sum(item.role_promise is not None for item in plan.assignments),
        },
        "limits": {
            "standard_contracts": MAX_STANDARD_CONTRACTS,
            "two_way_contracts": MAX_TWO_WAY_CONTRACTS,
            "two_way_active_games": 50,
        },
        "model_version": ROSTER_OPERATIONS_MODEL_VERSION,
        "interpretation": (
            "Automatic plans optimize current ability, upside, readiness, workload, coaching depth and the selected team objective. "
            "Medical status is a scenario input, not a diagnosis."
        ),
    }


def apply_roster_plan(profile: TeamProfile, plan: RosterPlanRecord | None) -> TeamProfile:
    if plan is None:
        return profile
    assignments = {item.player_id: item for item in plan.assignments}
    return replace(
        profile,
        roster=tuple(
            replace(
                player,
                expected_minutes=(
                    assignments[player.player_id].target_minutes
                    if player.player_id in assignments
                    else player.expected_minutes
                ),
            )
            for player in profile.roster
        ),
    )


def roster_inactive_player_ids(plan: RosterPlanRecord | None) -> tuple[int, ...]:
    if plan is None:
        return ()
    return tuple(sorted(
        item.player_id for item in plan.assignments
        if item.designation in {"g_league", "inactive"} or item.target_minutes <= 0
    ))
