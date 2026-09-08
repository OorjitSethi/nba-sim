from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import date
from typing import TYPE_CHECKING

from nba_sim.franchise.cba import CBA_2026_27, cap_position, rules_for_season
from nba_sim.franchise.models import ContractRecord, ContractYear, TransactionRecord

if TYPE_CHECKING:
    from nba_sim.franchise.models import PlayerRecord
    from nba_sim.franchise.state import LeagueState


CONTRACT_MODEL_VERSION = "contract-market-cba-2026-27.v1"
MAX_OFFSEASON_ROSTER = 21
MAX_REGULAR_ROSTER = 15


def _unit_interval(*parts: object) -> float:
    digest = hashlib.sha256("|".join(map(str, parts)).encode()).digest()
    return int.from_bytes(digest[:8], "big") / (2**64 - 1)


def _season(start_year: int) -> str:
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def _season_start(value: str) -> int:
    return int(value.split("-", 1)[0])


def projected_rules(season: str) -> dict[str, int | str]:
    rules = rules_for_season(season)
    return rules.as_dict()


def modeled_market_salary(overall: float, age: float | None) -> int:
    rating = max(45.0, min(99.0, float(overall)))
    if rating < 68:
        amount = 1_400_000 + (rating - 50) * 85_000
    elif rating < 74:
        amount = 2_930_000 + (rating - 68) * 620_000
    elif rating < 79:
        amount = 6_650_000 + (rating - 74) * 1_430_000
    elif rating < 84:
        amount = 13_800_000 + (rating - 79) * 2_250_000
    elif rating < 89:
        amount = 25_050_000 + (rating - 84) * 3_050_000
    else:
        amount = 40_300_000 + (rating - 89) * 2_000_000
    if age is not None and age >= 33:
        amount *= max(0.68, 1 - (age - 32) * 0.055)
    return int(max(1_400_000, min(58_000_000, round(amount / 10_000) * 10_000)))


def _lifecycle(state: "LeagueState", player_id: int):
    return next(
        (item for item in state.player_lifecycles if item.player_id == player_id),
        None,
    )


def build_modeled_contracts(state: "LeagueState") -> tuple[ContractRecord, ...]:
    """Create a complete, explicitly modeled ledger when licensed salaries are absent."""
    contracts: list[ContractRecord] = []
    start_year = _season_start(state.season)
    for player in state.players:
        lifecycle = _lifecycle(state, player.player_id)
        overall = lifecycle.overall if lifecycle else 62 + player.expected_minutes * 0.5
        age = lifecycle.age if lifecycle else None
        if age is None:
            remaining = 2
        elif age <= 22:
            remaining = 4
        elif age <= 26:
            remaining = 3
        elif age <= 30:
            remaining = 2 + int(overall >= 82)
        elif age <= 34:
            remaining = 2
        else:
            remaining = 1
        remaining = min(5, max(1, remaining))
        first_salary = modeled_market_salary(overall, age)
        years: list[ContractYear] = []
        option_roll = _unit_interval(state.seed, player.player_id, "option")
        for offset in range(remaining):
            option = None
            if offset == remaining - 1 and remaining > 1:
                if age is not None and age <= 23 and option_roll < 0.72:
                    option = "team"
                elif option_roll < 0.24:
                    option = "team"
                elif option_roll > 0.84:
                    option = "player"
            years.append(
                ContractYear(
                    season=_season(start_year + offset),
                    salary=round(first_salary * (1.05**offset) / 10_000) * 10_000,
                    option=option,
                )
            )
        bird_years = 3 if _unit_interval(state.seed, player.player_id, "bird") > 0.26 else 2
        contracts.append(
            ContractRecord(
                contract_id=f"modeled-{state.league_id}-{player.player_id}",
                player_id=player.player_id,
                team=player.team,
                # Existing deals predate the simulated cap year. This avoids
                # falsely applying the Dec. 15 new-signing trade restriction
                # to every player when the ledger is first modeled.
                signed_on=date(start_year - 1, 7, 1),
                years=tuple(years),
                status="active",
                source="modeled-player-value; not an official salary record",
                rights="bird" if bird_years >= 3 else "early_bird",
                contract_kind="standard",
            )
        )
    return tuple(sorted(contracts, key=lambda item: item.player_id))


def active_contract(state: "LeagueState", player_id: int) -> ContractRecord | None:
    return next(
        (
            item
            for item in reversed(state.contracts)
            if item.player_id == player_id and item.status == "active"
        ),
        None,
    )


def salary_for(contract: ContractRecord, season: str) -> int:
    year = next((item for item in contract.years if item.season == season), None)
    return year.salary if year is not None else 0


def team_payroll(state: "LeagueState", team: str, season: str | None = None) -> int:
    target = season or state.season
    return sum(
        salary_for(contract, target)
        for contract in state.contracts
        if contract.team == team.upper() and contract.status in {"active", "waived"}
    )


def _player_value(state: "LeagueState", player: "PlayerRecord") -> tuple[float, float | None]:
    lifecycle = _lifecycle(state, player.player_id)
    return (
        lifecycle.overall if lifecycle else 62 + player.expected_minutes * 0.5,
        lifecycle.age if lifecycle else None,
    )


def _team_strength(state: "LeagueState", team: str) -> float:
    values = sorted(
        (_player_value(state, player)[0] for player in state.roster(team)),
        reverse=True,
    )[:10]
    return sum(values) / max(1, len(values))


def _asking_salary(state: "LeagueState", player: "PlayerRecord") -> int:
    overall, age = _player_value(state, player)
    base = modeled_market_salary(overall, age)
    upside = 1.0
    lifecycle = _lifecycle(state, player.player_id)
    if lifecycle is not None:
        upside += max(0.0, lifecycle.potential_mean - overall) * 0.012
    rules = rules_for_season(state.season)
    maximum = round(
        rules.salary_cap
        * (0.35 if overall >= 90 else 0.30 if overall >= 85 else 0.25)
    )
    inflation = rules.salary_cap / CBA_2026_27.salary_cap
    return min(maximum, round(58_000_000 * inflation), round(base * inflation * upside / 50_000) * 50_000)


def extension_evaluation(
    state: "LeagueState",
    *,
    player_id: int,
    years: int,
    annual_salary: int,
    role: str = "rotation",
) -> dict[str, object]:
    if not 1 <= years <= 4:
        raise ValueError("an extension must be between 1 and 4 new seasons")
    if annual_salary <= 0:
        raise ValueError("extension salary must be positive")
    player = next((item for item in state.players if item.player_id == player_id), None)
    if player is None or player.team != state.user_team or player.roster_status != "active":
        raise ValueError("extensions can only be offered to an active player on your team")
    contract = active_contract(state, player_id)
    if contract is None:
        raise ValueError("this player does not have an active contract")
    if contract.source == "negotiated-extension":
        raise ValueError("this player has already signed an extension in this contract cycle")
    asking = _asking_salary(state, player)
    overall, age = _player_value(state, player)
    security = min(12.0, years * (2.2 if (age or 27) >= 30 else 1.5))
    salary_score = max(0.0, min(88.0, 62 * annual_salary / max(asking, 1)))
    role_bonus = {"star": 9.0, "starter": 5.0, "rotation": 1.0, "bench": -5.0}.get(role, 0.0)
    contender_bonus = max(-4.0, min(6.0, (_team_strength(state, state.user_team) - 73) * 0.8))
    interest = max(0.0, min(100.0, salary_score + security + role_bonus + contender_bonus))
    threshold = 58 + 15 * _unit_interval(state.seed, state.revision, player_id, "extension")
    max_salary = round(
        rules_for_season(state.season).salary_cap
        * (0.35 if overall >= 90 else 0.30 if overall >= 85 else 0.25)
    )
    blockers = []
    if annual_salary > max_salary:
        blockers.append(f"The modeled maximum first-year salary is ${max_salary / 1_000_000:.1f}M.")
    accepted = not blockers and interest >= threshold
    return {
        "kind": "extension",
        "player_id": player_id,
        "player_name": player.name,
        "team": player.team,
        "years": years,
        "annual_salary": annual_salary,
        "asking_salary": asking,
        "max_salary": max_salary,
        "role": role,
        "interest": round(interest, 1),
        "accepted": accepted,
        "can_sign": accepted,
        "blockers": blockers,
        "explanation": (
            "The player is ready to sign this extension."
            if accepted
            else "The offer needs more salary, security, or a stronger role promise."
        ),
        "model_version": CONTRACT_MODEL_VERSION,
    }


def extended_contract(
    state: "LeagueState",
    evaluation: dict[str, object],
) -> ContractRecord:
    contract = active_contract(state, int(evaluation["player_id"]))
    if contract is None:
        raise ValueError("active contract disappeared before signing")
    last_start = max(_season_start(item.season) for item in contract.years)
    annual = int(evaluation["annual_salary"])
    new_years = tuple(
        ContractYear(
            season=_season(last_start + offset),
            salary=round(annual * (1.08 ** (offset - 1)) / 10_000) * 10_000,
        )
        for offset in range(1, int(evaluation["years"]) + 1)
    )
    return replace(
        contract,
        signed_on=state.calendar.current_date,
        years=(*contract.years, *new_years),
        source="negotiated-extension",
    )


def option_decision(
    state: "LeagueState",
    *,
    player_id: int,
    exercise: bool,
) -> tuple[ContractRecord, ContractYear]:
    contract = active_contract(state, player_id)
    if contract is None:
        raise ValueError("this player does not have an active contract")
    option_year = next((item for item in contract.years if item.option in {"team", "player"}), None)
    if option_year is None:
        raise ValueError("this player has no undecided option")
    if option_year.option == "player":
        player = next(item for item in state.players if item.player_id == player_id)
        ask = _asking_salary(state, player)
        exercise = option_year.salary >= 0.92 * ask
    years = tuple(
        replace(item, option="exercised") if item == option_year else item
        for item in contract.years
        if item != option_year or exercise
    )
    return replace(contract, years=years), option_year


def waived_contract(state: "LeagueState", player_id: int) -> ContractRecord:
    contract = active_contract(state, player_id)
    if contract is None:
        raise ValueError("this player does not have an active contract")
    return replace(contract, status="waived", rights=None, source=f"{contract.source}; waived")


def free_agent_evaluation(
    state: "LeagueState",
    *,
    player_id: int,
    team: str,
    years: int,
    annual_salary: int,
    role: str = "rotation",
) -> dict[str, object]:
    normalized = team.upper()
    if normalized not in {item.team for item in state.franchises}:
        raise ValueError("unknown signing team")
    player = next((item for item in state.players if item.player_id == player_id), None)
    if player is None or player.roster_status != "free_agent":
        raise ValueError("this player is not currently a free agent")
    prior = next(
        (
            item
            for item in reversed(state.contracts)
            if item.player_id == player_id and item.team == normalized and item.status != "active"
        ),
        None,
    )
    max_years = 5 if prior is not None and prior.rights == "bird" else 4
    if not 1 <= years <= max_years:
        raise ValueError(f"this signing path permits between 1 and {max_years} seasons")
    asking = _asking_salary(state, player)
    payroll = team_payroll(state, normalized)
    rules = rules_for_season(state.season)
    after = payroll + annual_salary
    blockers: list[str] = []
    mechanism = "cap_room"
    cap_room = max(0, rules.salary_cap - payroll)
    if annual_salary > cap_room:
        prior_salary = salary_for(prior, state.season) if prior is not None else 0
        if prior is not None and prior.rights == "bird":
            mechanism = "bird_exception"
        elif (
            prior is not None
            and prior.rights == "early_bird"
            and annual_salary <= max(round(prior_salary * 1.75), round(rules.salary_cap * 0.105))
        ):
            mechanism = "early_bird_exception"
        elif (
            prior is not None
            and prior.rights == "non_bird"
            and annual_salary <= round(prior_salary * 1.20)
        ):
            mechanism = "non_bird_exception"
        elif annual_salary <= 3_000_000:
            mechanism = "minimum_exception"
        elif annual_salary <= rules.non_taxpayer_mle and after <= rules.first_apron:
            mechanism = "non_taxpayer_mle"
        elif annual_salary <= rules.taxpayer_mle and after <= rules.second_apron:
            mechanism = "taxpayer_mle"
        else:
            blockers.append("The team lacks cap room or a large enough usable exception for this offer.")
    roster_limit = MAX_OFFSEASON_ROSTER if state.calendar.phase == "offseason" else MAX_REGULAR_ROSTER
    if len(state.roster(normalized)) >= roster_limit:
        blockers.append(f"The {normalized} roster is already at its {roster_limit}-player limit.")
    if annual_salary <= 0:
        blockers.append("Offer salary must be positive.")
    salary_score = max(0.0, min(82.0, 63 * annual_salary / max(asking, 1)))
    role_bonus = {"star": 10.0, "starter": 6.0, "rotation": 2.0, "bench": -5.0}.get(role, 0.0)
    strength_bonus = max(-5.0, min(7.0, (_team_strength(state, normalized) - 73) * 0.8))
    security = min(10.0, years * 2.1)
    interest = max(0.0, min(100.0, salary_score + role_bonus + strength_bonus + security))
    threshold = 56 + 18 * _unit_interval(state.seed, state.revision, player_id, normalized, "fa")
    accepted = not blockers and interest >= threshold
    return {
        "kind": "free_agent_offer",
        "player_id": player_id,
        "player_name": player.name,
        "team": normalized,
        "years": years,
        "annual_salary": annual_salary,
        "asking_salary": asking,
        "role": role,
        "mechanism": mechanism,
        "interest": round(interest, 1),
        "accepted": accepted,
        "can_sign": accepted,
        "blockers": blockers,
        "cap_before": cap_position(payroll, rules=rules).as_dict(),
        "cap_after": cap_position(after, rules=rules).as_dict(),
        "explanation": (
            "The player accepts and the contract fits the team's available signing path."
            if accepted
            else "The player or the cap system does not clear this offer yet."
        ),
        "model_version": CONTRACT_MODEL_VERSION,
    }


def free_agent_contract(state: "LeagueState", evaluation: dict[str, object]) -> ContractRecord:
    player_id = int(evaluation["player_id"])
    team = str(evaluation["team"])
    annual = int(evaluation["annual_salary"])
    start = _season_start(state.season)
    years = tuple(
        ContractYear(
            season=_season(start + offset),
            salary=round(annual * (1.05**offset) / 10_000) * 10_000,
        )
        for offset in range(int(evaluation["years"]))
    )
    identity = hashlib.sha256(
        f"{state.league_id}|{state.revision + 1}|{player_id}|{team}|fa".encode()
    ).hexdigest()[:18]
    return ContractRecord(
        contract_id=f"fa-{identity}",
        player_id=player_id,
        team=team,
        signed_on=state.calendar.current_date,
        years=years,
        status="active",
        source=f"negotiated-free-agent; {evaluation['mechanism']}",
        rights="non_bird",
        contract_kind="standard",
    )


def transaction_record(
    state: "LeagueState",
    *,
    kind: str,
    team: str,
    player_id: int,
    summary: str,
    source: str,
) -> TransactionRecord:
    identity = hashlib.sha256(
        f"{state.league_id}|{state.revision + 1}|{kind}|{team}|{player_id}".encode()
    ).hexdigest()[:20]
    return TransactionRecord(
        transaction_id=f"{kind}-{identity}",
        transaction_type=kind,
        occurred_on=state.calendar.current_date,
        teams=(team,),
        summary=summary,
        source=source,
        player_ids=(player_id,),
    )


def contract_market_response(state: "LeagueState") -> dict[str, object]:
    if not state.contracts:
        return {
            "ready": False,
            "model_version": CONTRACT_MODEL_VERSION,
            "official_salary_data": False,
        }
    player_by_id = {item.player_id: item for item in state.players}
    roster = state.roster(state.user_team)
    rows = []
    for player in roster:
        contract = active_contract(state, player.player_id)
        if contract is None:
            continue
        overall, age = _player_value(state, player)
        option = next((year for year in contract.years if year.option in {"team", "player"}), None)
        rows.append(
            {
                "player_id": player.player_id,
                "name": player.name,
                "position": player.position,
                "overall": round(overall, 1),
                "age": round(age, 1) if age is not None else None,
                "rights": contract.rights,
                "source": contract.source,
                "years": [year.as_dict() for year in contract.years],
                "current_salary": salary_for(contract, state.season),
                "expires_after": contract.years[-1].season,
                "extension_eligible": contract.source != "negotiated-extension",
                "asking_salary": _asking_salary(state, player),
                "option": option.as_dict() if option else None,
            }
        )
    projections = []
    start = _season_start(state.season)
    for offset in range(5):
        season = _season(start + offset)
        rules = projected_rules(season)
        payroll = team_payroll(state, state.user_team, season)
        projections.append(
            {
                **rules,
                "payroll": payroll,
                "cap_room": int(rules["salary_cap"]) - payroll,
                "committed_players": sum(
                    salary_for(contract, season) > 0
                    for contract in state.contracts
                    if contract.team == state.user_team and contract.status == "active"
                ),
            }
        )
    free_agents = []
    for player in state.players:
        if player.roster_status != "free_agent":
            continue
        overall, age = _player_value(state, player)
        interested = sorted(
            (
                (-_team_strength(state, franchise.team), franchise.team)
                for franchise in state.franchises
                if len(state.roster(franchise.team)) < MAX_OFFSEASON_ROSTER
            )
        )[:4]
        free_agents.append(
            {
                "player_id": player.player_id,
                "name": player.name,
                "position": player.position,
                "former_team": player.team,
                "overall": round(overall, 1),
                "age": round(age, 1) if age is not None else None,
                "asking_salary": _asking_salary(state, player),
                "interested_teams": [team for _, team in interested],
            }
        )
    free_agents.sort(key=lambda item: (-float(item["overall"]), str(item["name"])))
    expiring = sum(row["expires_after"] == state.season for row in rows)
    options = sum(row["option"] is not None for row in rows)
    recommendations = []
    if options:
        recommendations.append(f"Resolve {options} contract option{'s' if options != 1 else ''} before planning cap room.")
    if expiring:
        recommendations.append(f"Open extension talks with {expiring} expiring player{'s' if expiring != 1 else ''}.")
    if len(roster) > MAX_REGULAR_ROSTER:
        recommendations.append(f"Trim {len(roster) - MAX_REGULAR_ROSTER} standard roster spots before opening night.")
    if not recommendations:
        recommendations.append("The current ledger has no urgent contract deadline. Review the five-year outlook before your next trade.")
    recent = [
        item.as_dict()
        for item in reversed(state.transactions)
        if item.transaction_type in {"extension", "option", "waiver", "free_agent_signing"}
    ][:12]
    current_rules = rules_for_season(state.season)
    return {
        "ready": True,
        "model_version": CONTRACT_MODEL_VERSION,
        "official_salary_data": False,
        "data_label": "Modeled contract ledger — these are estimates, not official salaries, until a licensed contract feed is connected.",
        "rules_source": current_rules.source_url,
        "team": state.user_team,
        "season": state.season,
        "payroll": team_payroll(state, state.user_team),
        "cap_position": cap_position(team_payroll(state, state.user_team), rules=current_rules).as_dict(),
        "projections": projections,
        "contracts": sorted(rows, key=lambda item: -int(item["current_salary"])),
        "free_agents": free_agents,
        "recommendations": recommendations,
        "recent_transactions": recent,
        "assumptions": [
            "2026–27 thresholds are official NBA figures; later seasons are clearly labeled projections.",
            "Future cap lines and exceptions grow 8% per season for planning and are not official forecasts.",
            "Player salaries and existing contract lengths are modeled from current value and age, not represented as real contracts.",
            "Player decisions use seeded money, role, security, team-quality, age and upside preferences.",
        ],
    }


def cpu_waiver_candidates(state: "LeagueState", *, max_players: int = 3) -> tuple[int, ...]:
    candidates: list[tuple[float, int]] = []
    for franchise in state.franchises:
        if franchise.team == state.user_team:
            continue
        roster = state.roster(franchise.team)
        # Current point-in-time feeds carry a compact ten-player rotation rather
        # than every camp invite. A manually triggered market cycle therefore
        # lets one low-minute CPU player enter waivers from a ten-plus roster.
        surplus = max(0, len(roster) - 9)
        for player in sorted(roster, key=lambda item: (item.expected_minutes, item.name))[:surplus]:
            overall, _ = _player_value(state, player)
            candidates.append((overall + player.expected_minutes * 0.1, player.player_id))
    return tuple(player_id for _, player_id in sorted(candidates)[:max_players])
