from __future__ import annotations

from dataclasses import replace
import hashlib
from typing import TYPE_CHECKING, Iterable, Mapping

from nba_sim.franchise.cba import rules_for_season
from nba_sim.franchise.contracts import salary_for, team_payroll
from nba_sim.franchise.models import GeneralManagerPlanRecord, PlayerRecord
from nba_sim.franchise.season_cycle import standings

if TYPE_CHECKING:
    from nba_sim.franchise.state import LeagueState


GM_INTELLIGENCE_MODEL_VERSION = "general-manager-intelligence.v1"

_LARGE_MARKETS = {
    "BOS", "BKN", "CHI", "DAL", "GSW", "HOU", "LAC", "LAL", "MIA",
    "NYK", "PHI", "TOR",
}
_SMALL_MARKETS = {
    "CHA", "CLE", "IND", "MEM", "MIL", "MIN", "NOP", "OKC", "ORL",
    "POR", "SAC", "SAS", "UTA",
}
_DIRECTION_PRIORITIES = {
    "contend": (0.57, 0.10, 0.20, 0.13),
    "compete": (0.37, 0.23, 0.25, 0.15),
    "retool": (0.25, 0.27, 0.31, 0.17),
    "rebuild": (0.12, 0.38, 0.25, 0.25),
}


def build_league_general_manager_plans(
    state: "LeagueState",
    *,
    previous: Iterable[GeneralManagerPlanRecord] = (),
    reason: str = "initial league audit",
) -> tuple[GeneralManagerPlanRecord, ...]:
    prior = {item.team: item for item in previous}
    ranks = _strength_ranks(state)
    return tuple(
        build_general_manager_plan(
            state,
            franchise.team,
            strength_rank=ranks[franchise.team],
            previous=prior.get(franchise.team),
            reason=reason,
        )
        for franchise in sorted(state.franchises, key=lambda item: item.team)
    )


def build_general_manager_plan(
    state: "LeagueState",
    team: str,
    *,
    strength_rank: int,
    previous: GeneralManagerPlanRecord | None = None,
    reason: str,
) -> GeneralManagerPlanRecord:
    team = team.upper()
    if previous is not None and not previous.automation_enabled:
        return previous
    roster = list(state.roster(team))
    lifecycle = {item.player_id: item for item in state.player_lifecycles}
    ages = [
        float(lifecycle[item.player_id].age)
        for item in roster
        if item.player_id in lifecycle and lifecycle[item.player_id].age is not None
    ]
    average_age = sum(ages) / len(ages) if ages else 27.0
    season_row = _standing_row(state, team)
    games = int(season_row.get("games", 0))
    win_rate = float(season_row.get("win_percentage", 0.0)) if games else None
    recent_rate = _recent_win_rate(state, team)
    payroll = team_payroll(state, team)
    market_size = _market_size(team)
    personality = _unit_interval(state.league_id, team, "ownership")
    ownership_patience = _clamp(
        42 + personality * 38 + (8 if market_size == "small" else 0),
        20,
        92,
    )
    budget_willingness = _clamp(
        44
        + personality * 27
        + {"small": -7, "medium": 4, "large": 17}[market_size],
        25,
        96,
    )
    risk_tolerance = _clamp(
        0.27 + 0.43 * _unit_interval(state.league_id, team, "risk"),
        0.2,
        0.82,
    )

    direction = _direction(
        strength_rank=strength_rank,
        average_age=average_age,
        games=games,
        win_rate=win_rate,
        recent_rate=recent_rate,
        previous=previous,
        ownership_patience=ownership_patience,
    )
    expected_rate = _clamp(0.72 - (strength_rank - 1) * 0.0158, 0.25, 0.72)
    target_wins = round(82 * {
        "contend": max(0.59, expected_rate),
        "compete": max(0.45, expected_rate),
        "retool": min(0.49, max(0.36, expected_rate)),
        "rebuild": min(0.38, expected_rate),
    }[direction])
    performance_gap = (
        (win_rate - target_wins / 82) * 100
        if win_rate is not None and games >= 10
        else 0.0
    )
    job_security = _clamp(
        67 + (ownership_patience - 55) * 0.32 + performance_gap * 1.35,
        8,
        96,
    )
    horizon = {
        "contend": 1,
        "compete": 2,
        "retool": 2,
        "rebuild": 4,
    }[direction]
    if ownership_patience >= 78 and direction == "rebuild":
        horizon = 5
    payroll_ceiling = _payroll_ceiling(
        direction=direction,
        budget_willingness=budget_willingness,
        season=state.season,
    )
    priorities = _priorities(direction, risk_tolerance=risk_tolerance)
    ranked = sorted(
        roster,
        key=lambda player: _player_plan_value(player, lifecycle.get(player.player_id)),
        reverse=True,
    )
    core_count = 3 if direction == "contend" else 2 if direction in {"compete", "rebuild"} else 1
    core = tuple(
        item.player_id
        for item in ranked[:core_count]
        if _player_plan_value(item, lifecycle.get(item.player_id)) >= 62
    )
    trade_block = _trade_block(
        state,
        roster,
        lifecycle=lifecycle,
        direction=direction,
        core=set(core),
    )
    needs = _roster_needs(roster)
    triggers = _triggers(
        direction=direction,
        games=games,
        win_rate=win_rate,
        recent_rate=recent_rate,
        payroll=payroll,
        payroll_ceiling=payroll_ceiling,
        job_security=job_security,
        average_age=average_age,
    )
    rationale = _rationale(
        direction=direction,
        strength_rank=strength_rank,
        games=games,
        win_rate=win_rate,
        average_age=average_age,
        payroll=payroll,
        payroll_ceiling=payroll_ceiling,
        needs=needs,
    )
    return GeneralManagerPlanRecord(
        team=team,
        as_of_date=state.calendar.current_date,
        direction=direction,
        strength_rank=strength_rank,
        average_age=average_age,
        target_wins=target_wins,
        evaluation_horizon=horizon,
        automation_enabled=True if previous is None else previous.automation_enabled,
        job_security=job_security,
        ownership_patience=ownership_patience,
        budget_willingness=budget_willingness,
        market_size=market_size,
        payroll_ceiling=payroll_ceiling,
        risk_tolerance=risk_tolerance,
        win_now_weight=priorities[0],
        development_weight=priorities[1],
        flexibility_weight=priorities[2],
        draft_weight=priorities[3],
        core_player_ids=core,
        trade_block_player_ids=trade_block,
        needs=needs,
        triggers=triggers,
        rationale=rationale,
        last_review_reason=reason,
        model_version=GM_INTELLIGENCE_MODEL_VERSION,
    )


def update_general_manager_plan(
    state: "LeagueState",
    current: GeneralManagerPlanRecord,
    *,
    direction: str,
    evaluation_horizon: int,
    automation_enabled: bool,
    priorities: Mapping[str, object],
) -> GeneralManagerPlanRecord:
    if direction not in _DIRECTION_PRIORITIES:
        raise ValueError("direction must be contend, compete, retool, or rebuild")
    if not 1 <= evaluation_horizon <= 5:
        raise ValueError("planning horizon must be between one and five seasons")
    values = [
        max(0.0, float(priorities.get(key, 0.0)))
        for key in ("win_now", "development", "flexibility", "draft_capital")
    ]
    total = sum(values)
    if total <= 0:
        raise ValueError("at least one front-office priority must be positive")
    normalized = tuple(value / total for value in values)
    return replace(
        current,
        as_of_date=state.calendar.current_date,
        direction=direction,
        evaluation_horizon=evaluation_horizon,
        automation_enabled=automation_enabled,
        win_now_weight=normalized[0],
        development_weight=normalized[1],
        flexibility_weight=normalized[2],
        draft_weight=normalized[3],
        last_review_reason="user strategy decision",
    )


def general_manager_plan(
    state: "LeagueState",
    team: str,
) -> GeneralManagerPlanRecord | None:
    normalized = team.upper()
    return next((item for item in state.gm_plans if item.team == normalized), None)


def general_manager_response(state: "LeagueState") -> dict[str, object]:
    if not state.gm_plans:
        return {
            "ready": False,
            "model_version": GM_INTELLIGENCE_MODEL_VERSION,
        }
    names = {item.player_id: item.name for item in state.players}
    table = {str(item["team"]): item for item in standings(state.season_cycle)} if state.season_cycle else {}

    def row(plan: GeneralManagerPlanRecord) -> dict[str, object]:
        standing = table.get(plan.team, {})
        return {
            **plan.as_dict(),
            "record": (
                f"{standing.get('wins', 0)}-{standing.get('losses', 0)}"
                if standing.get("games", 0)
                else "Preseason"
            ),
            "win_percentage": standing.get("win_percentage"),
            "payroll": team_payroll(state, plan.team),
            "core": [names[item] for item in plan.core_player_ids if item in names],
            "trade_block": [
                names[item] for item in plan.trade_block_player_ids if item in names
            ],
        }

    league = [row(item) for item in sorted(state.gm_plans, key=lambda item: item.strength_rank)]
    user = next(item for item in league if item["team"] == state.user_team)
    directions = {
        direction: sum(item.direction == direction for item in state.gm_plans)
        for direction in _DIRECTION_PRIORITIES
    }
    return {
        "ready": True,
        "team": state.user_team,
        "user_plan": user,
        "league": league,
        "direction_counts": directions,
        "automatic_teams": sum(item.automation_enabled for item in state.gm_plans),
        "model_version": GM_INTELLIGENCE_MODEL_VERSION,
        "explanation": (
            "Every front office audits record, roster strength, age curve, health, "
            "payroll, depth and draft capital. Persistent plans directly condition "
            "trade valuation and negotiation behavior."
        ),
    }


def _strength_ranks(state: "LeagueState") -> dict[str, int]:
    lifecycle = {item.player_id: item for item in state.player_lifecycles}
    rows = []
    for franchise in state.franchises:
        values = sorted(
            (
                lifecycle[player.player_id].overall
                for player in state.roster(franchise.team)
                if player.player_id in lifecycle
            ),
            reverse=True,
        )[:8]
        score = sum(value * (1.0 if index < 5 else 0.62) for index, value in enumerate(values))
        rows.append((score, franchise.team))
    return {
        team: index + 1
        for index, (_, team) in enumerate(sorted(rows, key=lambda item: (-item[0], item[1])))
    }


def _direction(
    *,
    strength_rank: int,
    average_age: float,
    games: int,
    win_rate: float | None,
    recent_rate: float | None,
    previous: GeneralManagerPlanRecord | None,
    ownership_patience: float,
) -> str:
    if games >= 20 and win_rate is not None:
        if win_rate >= 0.58 or (win_rate >= 0.54 and strength_rank <= 8):
            candidate = "contend"
        elif win_rate >= 0.43:
            candidate = "compete"
        elif average_age >= 28.4 or strength_rank <= 18:
            candidate = "retool"
        else:
            candidate = "rebuild"
        if recent_rate is not None and recent_rate <= 0.25 and candidate == "compete":
            candidate = "retool"
    elif strength_rank <= 8:
        candidate = "contend"
    elif strength_rank <= 17:
        candidate = "compete"
    elif strength_rank <= 22 or average_age >= 28.8:
        candidate = "retool"
    else:
        candidate = "rebuild"
    if (
        previous is not None
        and previous.direction != candidate
        and games < 32
        and ownership_patience >= 66
        and abs(previous.strength_rank - strength_rank) <= 4
    ):
        return previous.direction
    return candidate


def _player_plan_value(player: PlayerRecord, lifecycle: object | None) -> float:
    if lifecycle is None:
        return 50 + player.expected_minutes * 0.7
    overall = float(getattr(lifecycle, "overall"))
    potential = float(getattr(lifecycle, "potential_mean"))
    age = getattr(lifecycle, "age")
    youth = max(-4.0, min(5.0, (27.0 - float(age)) * 0.7)) if age is not None else 0.0
    return overall * 0.72 + potential * 0.22 + youth + player.expected_minutes * 0.12


def _trade_block(
    state: "LeagueState",
    roster: list[PlayerRecord],
    *,
    lifecycle: Mapping[int, object],
    direction: str,
    core: set[int],
) -> tuple[int, ...]:
    candidates = []
    for player in roster:
        if player.player_id in core:
            continue
        record = lifecycle.get(player.player_id)
        age = getattr(record, "age", None)
        age_value = float(age) if age is not None else 27.0
        contract = next(
            (
                item for item in state.contracts
                if item.player_id == player.player_id
                and item.team == player.team
                and item.status == "active"
            ),
            None,
        )
        salary = salary_for(contract, state.season) if contract is not None else 0
        mismatch = (
            direction == "rebuild" and age_value >= 28.5
        ) or (
            direction == "contend" and age_value <= 23 and player.expected_minutes < 13
        )
        burden = salary >= 18_000_000 and player.expected_minutes < 24
        fringe = player.expected_minutes < 10
        if mismatch or burden or fringe:
            score = (12 if mismatch else 0) + (8 if burden else 0) + max(0, 14 - player.expected_minutes)
            candidates.append((score, player.player_id))
    return tuple(item[1] for item in sorted(candidates, reverse=True)[:6])


def _roster_needs(roster: list[PlayerRecord]) -> tuple[str, ...]:
    minutes = {"guard": 0.0, "wing": 0.0, "big": 0.0}
    for player in roster:
        minutes[_position_bucket(player.position)] += min(36.0, player.expected_minutes)
    targets = {"guard": 90.0, "wing": 96.0, "big": 54.0}
    ordered = sorted(targets, key=lambda item: (minutes[item] / targets[item], item))
    needs = [item for item in ordered if minutes[item] < targets[item] * 0.94]
    return tuple((needs or ordered[:1])[:2])


def _standing_row(state: "LeagueState", team: str) -> Mapping[str, object]:
    if state.season_cycle is None:
        return {}
    return next((item for item in standings(state.season_cycle) if item["team"] == team), {})


def _recent_win_rate(state: "LeagueState", team: str) -> float | None:
    if state.season_cycle is None:
        return None
    games = [
        item for item in state.season_cycle.games
        if item.completed and item.stage == "regular_season" and team in {item.home_team, item.away_team}
    ][-10:]
    if not games:
        return None
    return sum(item.winner == team for item in games) / len(games)


def _payroll_ceiling(*, direction: str, budget_willingness: float, season: str) -> int:
    rules = rules_for_season(season)
    lower = rules.salary_cap
    upper = rules.second_apron
    willingness = budget_willingness / 100
    direction_boost = {"contend": 0.24, "compete": 0.08, "retool": -0.04, "rebuild": -0.14}[direction]
    share = _clamp(willingness + direction_boost, 0.08, 1.0)
    return round(lower + (upper - lower) * share)


def _priorities(direction: str, *, risk_tolerance: float) -> tuple[float, float, float, float]:
    values = list(_DIRECTION_PRIORITIES[direction])
    shift = (risk_tolerance - 0.5) * 0.08
    values[3] += shift
    values[2] -= shift
    total = sum(values)
    rounded = [round(value / total, 6) for value in values]
    rounded[-1] = round(1.0 - sum(rounded[:-1]), 6)
    return tuple(rounded)  # type: ignore[return-value]


def _triggers(
    *,
    direction: str,
    games: int,
    win_rate: float | None,
    recent_rate: float | None,
    payroll: int,
    payroll_ceiling: int,
    job_security: float,
    average_age: float,
) -> tuple[str, ...]:
    values = []
    if games >= 20 and win_rate is not None and win_rate < 0.38:
        values.append("Record is below the competitive floor")
    if recent_rate is not None and recent_rate <= 0.3:
        values.append("Last-ten performance is forcing a direction review")
    # Payroll ceilings are computed against the active cap year. This trigger
    # compares the club to its ownership budget rather than a frozen base-year
    # apron so it remains meaningful across long saves.
    if payroll > payroll_ceiling and direction != "contend":
        values.append("Payroll is above the ownership ceiling without contender results")
    if job_security < 42:
        values.append("Front-office job security is under pressure")
    if average_age >= 29 and direction in {"compete", "retool"}:
        values.append("The current core is approaching its decline window")
    if not values:
        values.append("No emergency trigger; continue the current evaluation window")
    return tuple(values[:4])


def _rationale(
    *,
    direction: str,
    strength_rank: int,
    games: int,
    win_rate: float | None,
    average_age: float,
    payroll: int,
    payroll_ceiling: int,
    needs: tuple[str, ...],
) -> tuple[str, ...]:
    record = (
        f"The club is playing at a {win_rate:.3f} win rate through {games} games."
        if games and win_rate is not None
        else "The direction is based on the current roster-strength forecast before a meaningful sample."
    )
    return (
        f"The roster ranks {strength_rank}th in modeled present strength and has a {average_age:.1f} average known age.",
        record,
        f"The {direction} plan carries ${payroll / 1_000_000:.1f}M payroll against a ${payroll_ceiling / 1_000_000:.1f}M ownership ceiling.",
        f"The roster audit prioritizes {', '.join(needs)} depth.",
    )


def _market_size(team: str) -> str:
    if team in _LARGE_MARKETS:
        return "large"
    if team in _SMALL_MARKETS:
        return "small"
    return "medium"


def _position_bucket(position: str) -> str:
    normalized = position.upper().replace(" ", "")
    if "C" in normalized and "G" not in normalized:
        return "big"
    if "G" in normalized and "F" not in normalized and "C" not in normalized:
        return "guard"
    return "wing"


def _unit_interval(*parts: object) -> float:
    digest = hashlib.sha256("|".join(map(str, parts)).encode()).digest()
    return int.from_bytes(digest[:8], "big") / (2**64 - 1)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


__all__ = [
    "GM_INTELLIGENCE_MODEL_VERSION",
    "build_league_general_manager_plans",
    "general_manager_plan",
    "general_manager_response",
    "update_general_manager_plan",
]
