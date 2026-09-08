from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Mapping

from nba_sim.franchise.lifecycle import advance_lifecycle_record
from nba_sim.franchise.models import (
    CareerDecisionRecord,
    ContractRecord,
    PlayerLifecycleRecord,
    PlayerRecord,
    TransactionRecord,
)
from nba_sim.randomness import RandomStreamFactory

if TYPE_CHECKING:
    from nba_sim.franchise.state import LeagueState


CAREER_MODEL_VERSION = "nba-career-decisions.v1"


@dataclass(frozen=True)
class CareerTransition:
    lifecycles: tuple[PlayerLifecycleRecord, ...]
    players: tuple[PlayerRecord, ...]
    contracts: tuple[ContractRecord, ...]
    decisions: tuple[CareerDecisionRecord, ...]
    transactions: tuple[TransactionRecord, ...]


def career_history_response(state: "LeagueState") -> dict[str, object]:
    """Build permanent career totals from archived and active season ledgers."""
    players = {item.player_id: item for item in state.players}
    lifecycles = {item.player_id: item for item in state.player_lifecycles}
    totals: dict[int, dict[str, object]] = {}
    seasons: dict[int, dict[str, dict[str, object]]] = {}
    awards: dict[int, list[dict[str, object]]] = {}
    cycles = (*state.season_history, *((state.season_cycle,) if state.season_cycle else ()))
    stat_names = (
        "minutes", "points", "field_goals_made", "field_goals_attempted",
        "threes_made", "threes_attempted", "free_throws_made",
        "free_throws_attempted", "offensive_rebounds", "defensive_rebounds",
        "assists", "steals", "blocks", "turnovers", "personal_fouls",
    )
    for cycle in cycles:
        for game in cycle.games:
            if not game.completed:
                continue
            for box in game.box_scores:
                total = totals.setdefault(box.player_id, {"games": 0, **{name: 0.0 for name in stat_names}})
                total["games"] = int(total["games"]) + 1
                for name in stat_names:
                    total[name] = float(total[name]) + float(getattr(box, name))
                player_seasons = seasons.setdefault(box.player_id, {})
                row = player_seasons.setdefault(
                    cycle.season,
                    {"season": cycle.season, "games": 0, "teams": set(), "points": 0, "minutes": 0.0},
                )
                row["games"] = int(row["games"]) + 1
                row["points"] = int(row["points"]) + box.points
                row["minutes"] = float(row["minutes"]) + box.minutes
                row["teams"].add(box.team)  # type: ignore[union-attr]
        for honor in cycle.honors:
            for recipient in honor.recipients:
                awards.setdefault(recipient.player_id, []).append({
                    "season": cycle.season,
                    "key": honor.key,
                    "label": honor.label,
                    "rank": recipient.rank,
                })

    decisions_by_player: dict[int, list[CareerDecisionRecord]] = {}
    for item in state.career_decisions:
        decisions_by_player.setdefault(item.player_id, []).append(item)
    records: list[dict[str, object]] = []
    for player in state.players:
        total = totals.get(player.player_id, {"games": 0, **{name: 0.0 for name in stat_names}})
        game_count = int(total["games"])
        season_rows = []
        for row in seasons.get(player.player_id, {}).values():
            season_rows.append({
                **row,
                "teams": sorted(row["teams"]),
                "minutes": round(float(row["minutes"]), 1),
            })
        lifecycle = lifecycles.get(player.player_id)
        player_decisions = decisions_by_player.get(player.player_id, [])
        retirement = next(
            (item for item in reversed(player_decisions) if item.outcome == "retired"),
            None,
        )
        records.append({
            "player_id": player.player_id,
            "name": player.name,
            "last_team": player.team,
            "position": player.position,
            "status": player.roster_status,
            "overall": lifecycle.overall if lifecycle else None,
            "age": lifecycle.age if lifecycle else None,
            "seasons_played": len(season_rows),
            "career_totals": {
                "games": game_count,
                **{
                    name: round(float(total[name]), 1 if name == "minutes" else 0)
                    for name in stat_names
                },
            },
            "career_per_game": {
                "points": round(float(total["points"]) / game_count, 1) if game_count else 0.0,
                "rebounds": round(
                    (float(total["offensive_rebounds"]) + float(total["defensive_rebounds"])) / game_count,
                    1,
                ) if game_count else 0.0,
                "assists": round(float(total["assists"]) / game_count, 1) if game_count else 0.0,
            },
            "seasons": sorted(season_rows, key=lambda item: str(item["season"])),
            "awards": awards.get(player.player_id, []),
            "retirement": retirement.as_dict() if retirement else None,
            "decisions": [item.as_dict() for item in player_decisions],
        })
    records.sort(
        key=lambda item: (
            item["status"] != "retired",
            -int(item["career_totals"]["games"]),  # type: ignore[index]
            str(item["name"]),
        )
    )
    recent = []
    for decision in reversed(state.career_decisions[-50:]):
        if decision.outcome not in {"retired", "returned"}:
            continue
        player = players[decision.player_id]
        recent.append({**decision.as_dict(), "name": player.name})
    return {
        "model_version": CAREER_MODEL_VERSION,
        "permanent_records": True,
        "retired_players": sum(item.roster_status == "retired" for item in state.players),
        "career_decisions": len(state.career_decisions),
        "recent_decisions": recent[:20],
        "records": records,
    }


def retirement_probability(
    *,
    age: float | None,
    overall: float,
    season_minutes: float,
    injury_burden: float,
    has_active_contract: bool,
    roster_status: str,
    role_satisfaction: float = 0.5,
    team_stability: float = 0.5,
) -> float | None:
    """Estimate an offseason retirement hazard without a fixed age cutoff."""
    if age is None:
        return None
    if age >= 49:
        return 1.0
    age_hazard = 0.76 / (1.0 + math.exp(-(age - 38.7) / 1.35))
    ability_multiplier = _clamp(1.18 - (overall - 55.0) / 105.0, 0.48, 1.3)
    opportunity_multiplier = _clamp(1.24 - season_minutes / 5_500.0, 0.72, 1.24)
    contract_multiplier = 0.78 if has_active_contract else 1.12
    market_multiplier = 1.22 if roster_status != "active" else 1.0
    return _clamp(
        age_hazard
        * ability_multiplier
        * opportunity_multiplier
        * contract_multiplier
        * market_multiplier
        + 0.13 * injury_burden
        + 0.055 * (0.5 - _clamp(role_satisfaction, 0.0, 1.0))
        + 0.025 * (0.5 - _clamp(team_stability, 0.0, 1.0)),
        0.002,
        0.985,
    )


def comeback_probability(
    *,
    age: float | None,
    overall: float,
    seasons_retired: int,
) -> float:
    if age is None or age > 40 or overall < 65 or seasons_retired not in {1, 2}:
        return 0.0
    ability = _clamp((overall - 65.0) / 22.0, 0.0, 1.0)
    age_factor = _clamp((41.0 - age) / 8.0, 0.15, 1.0)
    time_factor = 1.0 if seasons_retired == 1 else 0.55
    return _clamp((0.012 + 0.07 * ability) * age_factor * time_factor, 0.0, 0.09)


def advance_career_state(
    state: "LeagueState",
    *,
    season_minutes: Mapping[int, float],
    season_games: Mapping[int, int],
    games_missed: Mapping[int, int],
) -> CareerTransition:
    players = {item.player_id: item for item in state.players}
    contracts = {item.contract_id: item for item in state.contracts}
    active_contract_players = {
        item.player_id for item in state.contracts if item.status == "active"
    }
    team_stability = {
        item.team: (item.cohesion + item.role_clarity + item.trust + item.morale) / 400.0
        for item in state.team_chemistry
    }
    previous_decisions = tuple(state.career_decisions)
    latest_retirement = {
        item.player_id: item
        for item in previous_decisions
        if item.outcome == "retired"
    }
    decisions: list[CareerDecisionRecord] = []
    transactions: list[TransactionRecord] = []
    lifecycles: list[PlayerLifecycleRecord] = []
    streams = RandomStreamFactory(state.seed)

    for lifecycle in state.player_lifecycles:
        player = players[lifecycle.player_id]
        burden = _clamp(games_missed.get(player.player_id, 0) / 41.0, 0.0, 1.0)
        minutes = max(0.0, season_minutes.get(player.player_id, lifecycle.workload_minutes))
        games = max(0, season_games.get(player.player_id, lifecycle.games_played))
        rng = streams.generator(
            f"career-decision:{state.season}:{player.player_id}:{player.roster_status}"
        )

        if player.roster_status == "retired":
            retired = latest_retirement.get(player.player_id)
            if retired is None:
                lifecycles.append(lifecycle)
                continue
            seasons_retired = _season_start(state.season) - _season_start(retired.season)
            effective_age = (
                min(50.0, retired.age + seasons_retired)
                if retired.age is not None else None
            )
            probability = comeback_probability(
                age=effective_age,
                overall=lifecycle.overall,
                seasons_retired=seasons_retired,
            )
            if probability <= 0:
                lifecycles.append(lifecycle)
                continue
            draw = float(rng.random())
            returned = draw < probability
            decisions.append(_decision(
                state,
                player=player,
                lifecycle=replace(lifecycle, age=effective_age),
                outcome="returned" if returned else "remained_retired",
                reason="comeback_attempt",
                probability=probability,
                draw=draw,
                games=0,
                minutes=0.0,
                burden=0.0,
            ))
            if returned:
                players[player.player_id] = replace(
                    player,
                    roster_status="free_agent",
                    expected_minutes=0.0,
                )
                returned_lifecycle = replace(lifecycle, age=effective_age)
                if effective_age is None or effective_age < 50:
                    returned_lifecycle = advance_lifecycle_record(
                        returned_lifecycle,
                        seed=state.seed,
                        planned_minutes=450.0,
                        injury_burden=0.0,
                    )
                lifecycles.append(returned_lifecycle)
                transactions.append(_transaction(
                    state,
                    player,
                    "comeback",
                    f"{player.name} filed for reinstatement and entered free agency.",
                ))
            else:
                lifecycles.append(lifecycle)
            continue

        # Draft intake is born with an incoming-season baseline. Do not age or
        # develop a rookie once before that rookie has played an NBA season.
        if lifecycle.as_of_season != state.season:
            lifecycles.append(lifecycle)
            continue

        if lifecycle.age is not None and lifecycle.age >= 49:
            advanced = lifecycle
        else:
            advanced = advance_lifecycle_record(
                lifecycle,
                seed=state.seed,
                planned_minutes=minutes,
                injury_burden=burden,
            )
        lifecycles.append(advanced)
        probability = retirement_probability(
            age=advanced.age,
            overall=advanced.overall,
            season_minutes=minutes,
            injury_burden=burden,
            has_active_contract=player.player_id in active_contract_players,
            roster_status=player.roster_status,
            role_satisfaction=(
                _clamp(
                    minutes / max(player.expected_minutes * max(games, 1), 1.0),
                    0.0,
                    1.0,
                )
                if games > 0 and player.expected_minutes > 0 else 0.5
            ),
            team_stability=team_stability.get(player.team, 0.5),
        )
        if probability is None or advanced.age is None or advanced.age < 33:
            continue
        draw = float(rng.random())
        retired_now = draw < probability
        reason = _retirement_reason(
            age=advanced.age,
            minutes=minutes,
            injury_burden=burden,
            roster_status=player.roster_status,
        )
        decisions.append(_decision(
            state,
            player=player,
            lifecycle=advanced,
            outcome="retired" if retired_now else "continued",
            reason=reason,
            probability=probability,
            draw=draw,
            games=games,
            minutes=minutes,
            burden=burden,
        ))
        if not retired_now:
            continue
        players[player.player_id] = replace(
            player,
            roster_status="retired",
            expected_minutes=0.0,
        )
        contracts = {
            key: (
                replace(contract, status="retired")
                if contract.player_id == player.player_id and contract.status == "active"
                else contract
            )
            for key, contract in contracts.items()
        }
        transactions.append(_transaction(
            state,
            player,
            "retirement",
            f"{player.name} retired after the {state.season} season.",
        ))

    return CareerTransition(
        lifecycles=tuple(lifecycles),
        players=tuple(players[item.player_id] for item in state.players),
        contracts=tuple(contracts[item.contract_id] for item in state.contracts),
        decisions=tuple(decisions),
        transactions=tuple(transactions),
    )


def _decision(
    state: "LeagueState",
    *,
    player: PlayerRecord,
    lifecycle: PlayerLifecycleRecord,
    outcome: str,
    reason: str,
    probability: float,
    draw: float,
    games: int,
    minutes: float,
    burden: float,
) -> CareerDecisionRecord:
    return CareerDecisionRecord(
        decision_id=f"career-{state.season}-{player.player_id}",
        player_id=player.player_id,
        season=state.season,
        decided_on=state.calendar.current_date,
        outcome=outcome,
        reason=reason,
        last_team=player.team,
        age=lifecycle.age,
        overall=lifecycle.overall,
        probability=probability,
        random_draw=draw,
        season_games=games,
        season_minutes=minutes,
        injury_burden=burden,
        model_version=CAREER_MODEL_VERSION,
    )


def _transaction(
    state: "LeagueState",
    player: PlayerRecord,
    transaction_type: str,
    summary: str,
) -> TransactionRecord:
    digest = hashlib.sha256(
        f"{state.league_id}:{state.season}:{transaction_type}:{player.player_id}".encode()
    ).hexdigest()[:16]
    return TransactionRecord(
        transaction_id=f"career-{digest}",
        transaction_type=transaction_type,
        occurred_on=state.calendar.current_date,
        teams=(player.team,),
        summary=summary,
        source=CAREER_MODEL_VERSION,
        player_ids=(player.player_id,),
    )


def _retirement_reason(
    *, age: float, minutes: float, injury_burden: float, roster_status: str
) -> str:
    if injury_burden >= 0.55:
        return "health_and_recovery"
    if roster_status != "active" or minutes < 400:
        return "market_opportunity"
    if age >= 39:
        return "career_completion"
    return "personal_decision"


def _season_start(season: str) -> int:
    try:
        return int(season.split("-", 1)[0])
    except (TypeError, ValueError):
        return 0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
