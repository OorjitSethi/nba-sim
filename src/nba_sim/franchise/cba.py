from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nba_sim.franchise.state import LeagueState


class CapBand(str, Enum):
    BELOW_CAP = "below_cap"
    OVER_CAP = "over_cap"
    TAX = "tax"
    FIRST_APRON = "first_apron"
    SECOND_APRON = "second_apron"


class TransactionAction(str, Enum):
    STANDARD_TRADE = "standard_trade"
    EXPANDED_TRADE = "expanded_trade"
    AGGREGATED_TRADE = "aggregated_trade"
    SIGN_AND_TRADE_ACQUISITION = "sign_and_trade_acquisition"
    NON_TAXPAYER_MLE = "non_taxpayer_mle"
    TAXPAYER_MLE = "taxpayer_mle"
    ROOM_MLE = "room_mle"
    SEND_CASH = "send_cash"


@dataclass(frozen=True)
class CBAYearRules:
    season: str
    salary_cap: int
    tax_level: int
    minimum_team_salary: int
    first_apron: int
    second_apron: int
    non_taxpayer_mle: int
    taxpayer_mle: int
    room_mle: int
    rules_version: str = "nba-nbpa-2023-cba/2026-27.v1"
    source_url: str = "https://www.nba.com/news/nba-salary-cap-2026-27-season"

    def __post_init__(self) -> None:
        thresholds = (
            self.minimum_team_salary,
            self.salary_cap,
            self.tax_level,
            self.first_apron,
            self.second_apron,
        )
        if tuple(sorted(thresholds)) != thresholds:
            raise ValueError("CBA thresholds must be strictly ordered")
        if min(
            self.non_taxpayer_mle,
            self.taxpayer_mle,
            self.room_mle,
        ) <= 0:
            raise ValueError("mid-level exceptions must be positive")

    def as_dict(self) -> dict[str, object]:
        return {
            "season": self.season,
            "salary_cap": self.salary_cap,
            "tax_level": self.tax_level,
            "minimum_team_salary": self.minimum_team_salary,
            "first_apron": self.first_apron,
            "second_apron": self.second_apron,
            "non_taxpayer_mle": self.non_taxpayer_mle,
            "taxpayer_mle": self.taxpayer_mle,
            "room_mle": self.room_mle,
            "rules_version": self.rules_version,
            "source_url": self.source_url,
        }


CBA_2026_27 = CBAYearRules(
    season="2026-27",
    salary_cap=164_961_000,
    tax_level=200_428_000,
    minimum_team_salary=148_465_000,
    first_apron=209_015_000,
    second_apron=221_686_000,
    non_taxpayer_mle=15_044_000,
    taxpayer_mle=6_064_000,
    room_mle=9_366_000,
)

_REFERENCE_2023_24_CAP = 136_021_000
_REFERENCE_EXPANDED_TPE_INCREMENT = 7_500_000
_TRADE_ALLOWANCE = 250_000

_ACTION_LABELS = {
    TransactionAction.STANDARD_TRADE: "Standard one-player trade matching",
    TransactionAction.EXPANDED_TRADE: "Expanded traded-player exception",
    TransactionAction.AGGREGATED_TRADE: "Aggregate two or more outgoing salaries",
    TransactionAction.SIGN_AND_TRADE_ACQUISITION: "Receive a signed-and-traded player",
    TransactionAction.NON_TAXPAYER_MLE: "Use the non-taxpayer mid-level exception",
    TransactionAction.TAXPAYER_MLE: "Use the taxpayer mid-level exception",
    TransactionAction.ROOM_MLE: "Use the room mid-level exception",
    TransactionAction.SEND_CASH: "Send cash in a trade",
}

_APPLICABLE_APRONS = {
    TransactionAction.EXPANDED_TRADE: "first_apron",
    TransactionAction.SIGN_AND_TRADE_ACQUISITION: "first_apron",
    TransactionAction.NON_TAXPAYER_MLE: "first_apron",
    TransactionAction.AGGREGATED_TRADE: "second_apron",
    TransactionAction.TAXPAYER_MLE: "second_apron",
    TransactionAction.SEND_CASH: "second_apron",
}


@dataclass(frozen=True)
class CapPosition:
    team_salary: int
    band: CapBand
    cap_room: int
    tax_room: int
    first_apron_room: int
    second_apron_room: int
    minimum_salary_shortfall: int

    def as_dict(self) -> dict[str, object]:
        return {
            "team_salary": self.team_salary,
            "band": self.band.value,
            "cap_room": self.cap_room,
            "tax_room": self.tax_room,
            "first_apron_room": self.first_apron_room,
            "second_apron_room": self.second_apron_room,
            "minimum_salary_shortfall": self.minimum_salary_shortfall,
        }


@dataclass(frozen=True)
class TransactionEvaluation:
    action: TransactionAction
    legal: bool
    before: CapPosition
    after: CapPosition
    outgoing_salary: int
    incoming_salary: int
    maximum_incoming_salary: int | None
    applicable_apron: str | None
    hard_cap_triggered: str | None
    blockers: tuple[str, ...]
    explanations: tuple[str, ...]
    assumptions: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "action": self.action.value,
            "action_label": _ACTION_LABELS[self.action],
            "legal": self.legal,
            "before": self.before.as_dict(),
            "after": self.after.as_dict(),
            "outgoing_salary": self.outgoing_salary,
            "incoming_salary": self.incoming_salary,
            "maximum_incoming_salary": self.maximum_incoming_salary,
            "applicable_apron": self.applicable_apron,
            "hard_cap_triggered": self.hard_cap_triggered,
            "blockers": list(self.blockers),
            "explanations": list(self.explanations),
            "assumptions": list(self.assumptions),
        }


def cap_position(
    team_salary: int,
    *,
    rules: CBAYearRules = CBA_2026_27,
) -> CapPosition:
    salary = int(team_salary)
    if salary < 0:
        raise ValueError("team salary cannot be negative")
    if salary < rules.salary_cap:
        band = CapBand.BELOW_CAP
    elif salary <= rules.tax_level:
        band = CapBand.OVER_CAP
    elif salary <= rules.first_apron:
        band = CapBand.TAX
    elif salary <= rules.second_apron:
        band = CapBand.FIRST_APRON
    else:
        band = CapBand.SECOND_APRON
    return CapPosition(
        team_salary=salary,
        band=band,
        cap_room=rules.salary_cap - salary,
        tax_room=rules.tax_level - salary,
        first_apron_room=rules.first_apron - salary,
        second_apron_room=rules.second_apron - salary,
        minimum_salary_shortfall=max(0, rules.minimum_team_salary - salary),
    )


def evaluate_transaction(
    *,
    team_salary: int,
    outgoing_salary: int,
    incoming_salary: int,
    action: TransactionAction | str,
    rules: CBAYearRules = CBA_2026_27,
) -> TransactionEvaluation:
    try:
        transaction = (
            action
            if isinstance(action, TransactionAction)
            else TransactionAction(str(action))
        )
    except ValueError as error:
        choices = ", ".join(item.value for item in TransactionAction)
        raise ValueError(f"unknown transaction action; choose one of: {choices}") from error

    salary = int(team_salary)
    outgoing = int(outgoing_salary)
    incoming = int(incoming_salary)
    if min(salary, outgoing, incoming) < 0:
        raise ValueError("salary inputs cannot be negative")
    if outgoing > salary:
        raise ValueError("outgoing salary cannot exceed current team salary")

    before = cap_position(salary, rules=rules)
    after = cap_position(salary - outgoing + incoming, rules=rules)
    blockers: list[str] = []
    explanations: list[str] = []
    assumptions = [
        "Amounts are apron team salary for one team and one cap year.",
        "No prior hard cap, exception use, bonuses, cap holds, trade kickers, or multi-team routing is assumed.",
        "This is a deterministic CBA gate, not a prediction that another team accepts the deal.",
    ]

    applicable_apron = _APPLICABLE_APRONS.get(transaction)
    hard_cap_triggered = applicable_apron
    if applicable_apron is not None:
        threshold = getattr(rules, applicable_apron)
        if after.team_salary > threshold:
            blockers.append(
                f"This action hard-caps the team at the {applicable_apron.replace('_', ' ')} "
                f"(${threshold / 1_000_000:.3f}M), but the resulting apron salary is "
                f"${after.team_salary / 1_000_000:.3f}M."
            )
        else:
            explanations.append(
                f"The action stays ${threshold - after.team_salary:,.0f} below the "
                f"{applicable_apron.replace('_', ' ')} and would hard-cap the team there "
                "for the rest of the cap year."
            )

    maximum_incoming = _maximum_incoming(
        transaction,
        team_salary=salary,
        outgoing_salary=outgoing,
        resulting_salary=after.team_salary,
        rules=rules,
    )
    if maximum_incoming is not None:
        explanations.append(
            f"This path permits at most ${maximum_incoming / 1_000_000:.3f}M "
            "in incoming salary under the selected matching rule."
        )
        if incoming > maximum_incoming:
            blockers.append(
                f"Incoming salary exceeds the selected matching limit by "
                f"${(incoming - maximum_incoming) / 1_000_000:.3f}M."
            )

    exception_limit = {
        TransactionAction.NON_TAXPAYER_MLE: rules.non_taxpayer_mle,
        TransactionAction.TAXPAYER_MLE: rules.taxpayer_mle,
        TransactionAction.ROOM_MLE: rules.room_mle,
    }.get(transaction)
    if exception_limit is not None:
        if outgoing:
            blockers.append("Mid-level exception use cannot include outgoing salary.")
        if incoming > exception_limit:
            blockers.append(
                f"The entered salary exceeds this exception's "
                f"${exception_limit / 1_000_000:.3f}M 2026–27 limit."
            )
        else:
            explanations.append(
                f"${incoming / 1_000_000:.3f}M fits inside the "
                f"${exception_limit / 1_000_000:.3f}M exception."
            )

    if transaction is TransactionAction.TAXPAYER_MLE:
        if after.team_salary <= rules.first_apron:
            blockers.append(
                "The taxpayer MLE is available only when apron salary immediately "
                "after its use exceeds the first apron."
            )
    elif transaction is TransactionAction.ROOM_MLE:
        if before.team_salary >= rules.salary_cap:
            blockers.append(
                "The room MLE requires the team to have operated below the salary cap."
            )

    if transaction is TransactionAction.STANDARD_TRADE and after.team_salary > rules.first_apron:
        explanations.append(
            "Because the result is above the first apron, the CBA removes the "
            "$250,000 traded-player allowance."
        )

    if not blockers:
        explanations.insert(
            0,
            f"The entered scenario clears the encoded 2026–27 {transaction.value.replace('_', ' ')} gates.",
        )

    return TransactionEvaluation(
        action=transaction,
        legal=not blockers,
        before=before,
        after=after,
        outgoing_salary=outgoing,
        incoming_salary=incoming,
        maximum_incoming_salary=maximum_incoming,
        applicable_apron=applicable_apron,
        hard_cap_triggered=hard_cap_triggered,
        blockers=tuple(blockers),
        explanations=tuple(explanations),
        assumptions=tuple(assumptions),
    )


def _maximum_incoming(
    action: TransactionAction,
    *,
    team_salary: int,
    outgoing_salary: int,
    resulting_salary: int,
    rules: CBAYearRules,
) -> int | None:
    allowance = 0 if resulting_salary > rules.first_apron else _TRADE_ALLOWANCE
    if action is TransactionAction.STANDARD_TRADE:
        if team_salary < rules.salary_cap:
            return (
                outgoing_salary
                + (rules.salary_cap - team_salary)
                + allowance
            )
        return outgoing_salary + allowance
    if action is TransactionAction.AGGREGATED_TRADE:
        return outgoing_salary + allowance
    if action is TransactionAction.EXPANDED_TRADE:
        scaled_increment = round(
            _REFERENCE_EXPANDED_TPE_INCREMENT
            * rules.salary_cap
            / _REFERENCE_2023_24_CAP
        )
        return max(
            min(
                2 * outgoing_salary + allowance,
                outgoing_salary + scaled_increment,
            ),
            round(1.25 * outgoing_salary) + allowance,
        )
    return None


def team_cap_sheet(
    state: "LeagueState",
    team: str,
    *,
    rules: CBAYearRules = CBA_2026_27,
) -> dict[str, object]:
    normalized = team.upper()
    roster = state.roster(normalized)
    current_contracts = {}
    for contract in state.contracts:
        if contract.team != normalized or contract.status.lower() not in {
            "active",
            "guaranteed",
        }:
            continue
        salary_year = next(
            (year for year in contract.years if year.season == state.season),
            None,
        )
        if salary_year is not None:
            current_contracts[contract.player_id] = (contract, salary_year)

    salary_rows = []
    known_salary = 0
    for player in roster:
        contract_year = current_contracts.get(player.player_id)
        salary = contract_year[1].salary if contract_year else None
        if salary is not None:
            known_salary += salary
        salary_rows.append(
            {
                "player_id": player.player_id,
                "name": player.name,
                "salary": salary,
                "option": contract_year[1].option if contract_year else None,
                "source": contract_year[0].source if contract_year else None,
                "status": "verified" if contract_year else "not_imported",
            }
        )

    covered = sum(row["salary"] is not None for row in salary_rows)
    complete = bool(roster) and covered == len(roster)
    return {
        "team": normalized,
        "season": state.season,
        "rules_version": rules.rules_version,
        "roster_players": len(roster),
        "players_with_salary": covered,
        "coverage": round(covered / len(roster), 6) if roster else 0.0,
        "complete": complete,
        "known_salary": known_salary,
        "cap_position": (
            cap_position(known_salary, rules=rules).as_dict()
            if complete
            else None
        ),
        "players": salary_rows,
        "warning": (
            None
            if complete
            else "Official contract salaries are incomplete. Known salary is not treated as total payroll or cap room."
        ),
    }
