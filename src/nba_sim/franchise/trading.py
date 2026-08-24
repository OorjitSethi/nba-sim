from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
import hashlib
from typing import TYPE_CHECKING, Iterable, Mapping

from nba_sim.franchise.cba import CBA_2026_27, cap_position
from nba_sim.franchise.models import (
    DraftAssetRecord,
    PlayerLifecycleRecord,
    PlayerRecord,
)
from nba_sim.randomness import RandomStreamFactory

if TYPE_CHECKING:
    from nba_sim.franchise.state import LeagueState


TRADE_MODEL_VERSION = "trade-market-cba-2026-27.v1"
PROJECTED_2027_TRADE_DEADLINE = date(2027, 2, 11)


@dataclass(frozen=True)
class TradeRulePolicy:
    salary_matching: bool = True
    first_apron: bool = True
    second_apron: bool = True
    stepien_rule: bool = True
    seven_year_pick_limit: bool = True
    recently_signed: bool = True
    recently_acquired_aggregation: bool = True
    extension_restrictions: bool = True
    no_trade_consent: bool = True
    reacquisition: bool = True
    consideration_required: bool = True
    roster_limits: bool = True
    trade_deadline: bool = True
    injury_house_rule: bool = False
    ai_acceptance: bool = True
    ai_to_ai_trades: bool = True
    ai_aggressiveness: float = 0.45
    model_version: str = TRADE_MODEL_VERSION

    def __post_init__(self) -> None:
        if not 0 <= self.ai_aggressiveness <= 1:
            raise ValueError("AI trade aggressiveness must be between 0 and 1")

    def as_dict(self) -> dict[str, object]:
        return {
            "salary_matching": self.salary_matching,
            "first_apron": self.first_apron,
            "second_apron": self.second_apron,
            "stepien_rule": self.stepien_rule,
            "seven_year_pick_limit": self.seven_year_pick_limit,
            "recently_signed": self.recently_signed,
            "recently_acquired_aggregation": self.recently_acquired_aggregation,
            "extension_restrictions": self.extension_restrictions,
            "no_trade_consent": self.no_trade_consent,
            "reacquisition": self.reacquisition,
            "consideration_required": self.consideration_required,
            "roster_limits": self.roster_limits,
            "trade_deadline": self.trade_deadline,
            "injury_house_rule": self.injury_house_rule,
            "ai_acceptance": self.ai_acceptance,
            "ai_to_ai_trades": self.ai_to_ai_trades,
            "ai_aggressiveness": round(self.ai_aggressiveness, 4),
            "model_version": self.model_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "TradeRulePolicy":
        defaults = cls()
        return cls(
            salary_matching=bool(value.get("salary_matching", defaults.salary_matching)),
            first_apron=bool(value.get("first_apron", defaults.first_apron)),
            second_apron=bool(value.get("second_apron", defaults.second_apron)),
            stepien_rule=bool(value.get("stepien_rule", defaults.stepien_rule)),
            seven_year_pick_limit=bool(
                value.get("seven_year_pick_limit", defaults.seven_year_pick_limit)
            ),
            recently_signed=bool(value.get("recently_signed", defaults.recently_signed)),
            recently_acquired_aggregation=bool(
                value.get(
                    "recently_acquired_aggregation",
                    defaults.recently_acquired_aggregation,
                )
            ),
            extension_restrictions=bool(
                value.get("extension_restrictions", defaults.extension_restrictions)
            ),
            no_trade_consent=bool(
                value.get("no_trade_consent", defaults.no_trade_consent)
            ),
            reacquisition=bool(value.get("reacquisition", defaults.reacquisition)),
            consideration_required=bool(
                value.get(
                    "consideration_required",
                    defaults.consideration_required,
                )
            ),
            roster_limits=bool(value.get("roster_limits", defaults.roster_limits)),
            trade_deadline=bool(value.get("trade_deadline", defaults.trade_deadline)),
            injury_house_rule=bool(
                value.get("injury_house_rule", defaults.injury_house_rule)
            ),
            ai_acceptance=bool(value.get("ai_acceptance", defaults.ai_acceptance)),
            ai_to_ai_trades=bool(
                value.get("ai_to_ai_trades", defaults.ai_to_ai_trades)
            ),
            ai_aggressiveness=float(
                value.get("ai_aggressiveness", defaults.ai_aggressiveness)
            ),
            model_version=str(value.get("model_version", TRADE_MODEL_VERSION)),
        )


@dataclass(frozen=True)
class TradeTeamPackage:
    team: str
    player_ids: tuple[int, ...] = ()
    asset_ids: tuple[str, ...] = ()
    consent_player_ids: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "team", self.team.upper())
        if not self.team:
            raise ValueError("trade package team is required")
        if len(set(self.player_ids)) != len(self.player_ids):
            raise ValueError("trade package repeats a player")
        if len(set(self.asset_ids)) != len(self.asset_ids):
            raise ValueError("trade package repeats a draft asset")


def ensure_future_draft_assets(
    state: "LeagueState",
    *,
    start_year: int = 2027,
    end_year: int = 2033,
) -> tuple[DraftAssetRecord, ...]:
    existing = {
        (item.draft_year, item.round, item.original_team): item
        for item in state.draft_assets
    }
    for year in range(start_year, end_year + 1):
        for round_number in (1, 2):
            for franchise in state.franchises:
                key = (year, round_number, franchise.team)
                existing.setdefault(
                    key,
                    DraftAssetRecord(
                        asset_id=f"{year}-r{round_number}-{franchise.team}",
                        original_team=franchise.team,
                        current_team=franchise.team,
                        draft_year=year,
                        round=round_number,
                        protection=None,
                        source="simulated-future-rights",
                    ),
                )
    return tuple(
        sorted(
            existing.values(),
            key=lambda item: (
                item.draft_year,
                item.round,
                item.original_team,
                item.asset_id,
            ),
        )
    )


def trade_board_response(state: "LeagueState") -> dict[str, object]:
    lifecycle = {item.player_id: item for item in state.player_lifecycles}
    health = {item.player_id: item for item in state.player_health}
    rows = []
    for player in state.players:
        if player.roster_status != "active":
            continue
        salary, salary_source = player_cap_charge(state, player.player_id)
        record = lifecycle.get(player.player_id)
        rows.append(
            {
                "player_id": player.player_id,
                "name": player.name,
                "team": player.team,
                "position": player.position,
                "expected_minutes": player.expected_minutes,
                "overall": round(record.overall, 1) if record else None,
                "potential": round(record.potential_mean, 1) if record else None,
                "age": round(record.age, 1) if record and record.age is not None else None,
                "salary": salary,
                "salary_source": salary_source,
                "health": (
                    health[player.player_id].availability
                    if player.player_id in health
                    else "unknown"
                ),
                "trade_value": round(
                    player_trade_value(state, player.player_id, receiving_team=player.team),
                    2,
                ),
            }
        )
    assets = [
        {
            **item.as_dict(),
            "trade_value": round(draft_asset_value(item), 2),
        }
        for item in state.draft_assets
        if _draft_asset_is_available(state, item)
    ]
    strategies = {
        franchise.team: team_strategy(state, franchise.team)
        for franchise in state.franchises
    }
    return {
        "players": rows,
        "assets": assets,
        "strategies": strategies,
        "salary_note": (
            "Authoritative contract values are used when present. Missing contracts "
            "receive an explicitly labeled modeled cap charge so the trade engine "
            "can still evaluate salary matching."
        ),
        "model_version": TRADE_MODEL_VERSION,
    }


def evaluate_trade(
    state: "LeagueState",
    packages: tuple[TradeTeamPackage, TradeTeamPackage],
    *,
    policy: TradeRulePolicy,
) -> dict[str, object]:
    if len(packages) != 2 or packages[0].team == packages[1].team:
        raise ValueError("a trade requires two different teams")
    teams = {item.team for item in state.franchises}
    if any(package.team not in teams for package in packages):
        raise ValueError("trade references an unknown team")
    if not any(package.player_ids or package.asset_ids for package in packages):
        raise ValueError("trade must include at least one asset")
    player_by_id = {item.player_id: item for item in state.players}
    asset_by_id = {item.asset_id: item for item in state.draft_assets}
    all_players = [
        player_id for package in packages for player_id in package.player_ids
    ]
    all_assets = [asset_id for package in packages for asset_id in package.asset_ids]
    if len(all_players) != len(set(all_players)):
        raise ValueError("a player cannot appear on both sides of a trade")
    if len(all_assets) != len(set(all_assets)):
        raise ValueError("a pick cannot appear on both sides of a trade")

    blockers: list[dict[str, str]] = []
    warnings: list[str] = []
    team_results: list[dict[str, object]] = []
    now = state.calendar.current_date
    if policy.trade_deadline and (
        state.calendar.regular_season_start <= now <= state.calendar.regular_season_end
        and now > PROJECTED_2027_TRADE_DEADLINE
    ):
        blockers.append(
            _block(
                "trade_deadline",
                "The league date is after the projected 2027 trade deadline.",
            )
        )
    if not policy.trade_deadline:
        warnings.append("Trade-deadline enforcement is disabled.")
    if (
        policy.consideration_required
        and any(
            not package.player_ids and not package.asset_ids
            for package in packages
        )
    ):
        blockers.append(
            _block(
                "consideration_required",
                "Each team must send at least one player or draft asset.",
            )
        )

    for package, other in ((packages[0], packages[1]), (packages[1], packages[0])):
        outgoing_players = []
        for player_id in package.player_ids:
            player = player_by_id.get(player_id)
            if player is None or player.team != package.team:
                blockers.append(
                    _block(
                        "asset_ownership",
                        f"{package.team} does not control player {player_id}.",
                    )
                )
                continue
            outgoing_players.append(player)
        outgoing_assets = []
        for asset_id in package.asset_ids:
            asset = asset_by_id.get(asset_id)
            if asset is None or asset.current_team != package.team:
                blockers.append(
                    _block(
                        "asset_ownership",
                        f"{package.team} does not control draft asset {asset_id}.",
                    )
                )
                continue
            if not _draft_asset_is_available(state, asset):
                blockers.append(
                    _block(
                        "asset_ownership",
                        f"Draft asset {asset_id} has already been exercised.",
                    )
                )
                continue
            outgoing_assets.append(asset)

        incoming_players = [
            player_by_id[player_id]
            for player_id in other.player_ids
            if player_id in player_by_id
        ]
        outgoing_salary_rows = [
            player_cap_charge(state, player.player_id) for player in outgoing_players
        ]
        incoming_salary_rows = [
            player_cap_charge(state, player.player_id) for player in incoming_players
        ]
        outgoing_salary = sum(item[0] for item in outgoing_salary_rows)
        incoming_salary = sum(item[0] for item in incoming_salary_rows)
        team_salary = sum(
            player_cap_charge(state, item.player_id)[0]
            for item in state.roster(package.team)
        )
        after_salary = team_salary - outgoing_salary + incoming_salary
        unknown_salary_count = sum(
            source != "authoritative-contract"
            for _, source in (*outgoing_salary_rows, *incoming_salary_rows)
        )

        if policy.salary_matching:
            maximum = maximum_trade_incoming(
                team_salary=team_salary,
                outgoing_salary=outgoing_salary,
                incoming_salary=incoming_salary,
            )
            if incoming_salary > maximum:
                blockers.append(
                    _block(
                        "salary_matching",
                        f"{package.team} receives {_money(incoming_salary)} but its "
                        f"matching limit is {_money(maximum)}.",
                    )
                )
        else:
            maximum = None
            warnings.append(f"Salary matching is disabled for {package.team}.")

        if policy.first_apron and team_salary > CBA_2026_27.first_apron:
            if incoming_salary > outgoing_salary:
                blockers.append(
                    _block(
                        "first_apron",
                        f"{package.team} is above the first apron and cannot take "
                        "back more salary than it sends.",
                    )
                )
        if policy.second_apron and team_salary > CBA_2026_27.second_apron:
            if len(outgoing_players) > 1:
                blockers.append(
                    _block(
                        "second_apron",
                        f"{package.team} is above the second apron and cannot "
                        "aggregate outgoing player salaries.",
                    )
                )
        if policy.roster_limits:
            before_count = len(state.roster(package.team))
            after_count = before_count - len(outgoing_players) + len(incoming_players)
            maximum_roster = max(15, before_count)
            if after_count > maximum_roster:
                blockers.append(
                    _block(
                        "roster_limits",
                        f"{package.team} would have {after_count} active players; "
                        f"this save's allowed ceiling is {maximum_roster}.",
                    )
                )

        _apply_player_restrictions(
            state,
            package,
            outgoing_players,
            destination_team=other.team,
            policy=policy,
            blockers=blockers,
            warnings=warnings,
        )
        if policy.seven_year_pick_limit:
            too_distant = [
                item for item in outgoing_assets
                if item.draft_year > now.year + 7
            ]
            if too_distant:
                blockers.append(
                    _block(
                        "seven_year_pick_limit",
                        f"{package.team} includes a pick more than seven drafts away.",
                    )
                )
        if policy.stepien_rule and _violates_stepien(
            state,
            team=package.team,
            outgoing_asset_ids=set(package.asset_ids),
        ):
            blockers.append(
                _block(
                    "stepien_rule",
                    f"{package.team} would be left without a first-round selection "
                    "in consecutive future drafts.",
                )
            )

        outgoing_value = sum(
            player_trade_value(state, item.player_id, receiving_team=other.team)
            for item in outgoing_players
        ) + sum(draft_asset_value(item) for item in outgoing_assets)
        incoming_value = sum(
            player_trade_value(state, item.player_id, receiving_team=package.team)
            for item in incoming_players
        ) + sum(
            draft_asset_value(asset_by_id[asset_id])
            for asset_id in other.asset_ids
            if asset_id in asset_by_id
        )
        strategy = team_strategy(state, package.team)
        acceptance_margin = incoming_value - outgoing_value
        threshold = max(1.5, outgoing_value * 0.035)
        accepts = (
            not policy.ai_acceptance
            or package.team == state.user_team
            or acceptance_margin >= -threshold
        )
        team_results.append(
            {
                "team": package.team,
                "strategy": strategy,
                "before_salary": team_salary,
                "after_salary": after_salary,
                "outgoing_salary": outgoing_salary,
                "incoming_salary": incoming_salary,
                "maximum_incoming": maximum,
                "salary_band_before": cap_position(team_salary).band.value,
                "salary_band_after": cap_position(after_salary).band.value,
                "modeled_salary_rows": unknown_salary_count,
                "outgoing_value": round(outgoing_value, 2),
                "incoming_value": round(incoming_value, 2),
                "value_delta": round(acceptance_margin, 2),
                "accepts": accepts,
                "acceptance_copy": _acceptance_copy(
                    package.team,
                    state.user_team,
                    accepts,
                    acceptance_margin,
                    policy.ai_acceptance,
                ),
            }
        )

    cpu_rejections = [
        item for item in team_results
        if item["team"] != state.user_team and not item["accepts"]
    ]
    legal = not blockers
    accepted = legal and not cpu_rejections
    return {
        "legal": legal,
        "accepted": accepted,
        "can_execute": accepted,
        "blockers": blockers,
        "warnings": sorted(set(warnings)),
        "teams": team_results,
        "policy": policy.as_dict(),
        "rule_coverage": rule_coverage(),
        "model_version": TRADE_MODEL_VERSION,
    }


def player_cap_charge(state: "LeagueState", player_id: int) -> tuple[int, str]:
    for contract in state.contracts:
        if (
            contract.player_id == player_id
            and contract.status == "active"
            and contract.team
        ):
            year = next(
                (item for item in contract.years if item.season == state.season),
                None,
            )
            if year is not None:
                return year.salary, "authoritative-contract"
    lifecycle = next(
        (item for item in state.player_lifecycles if item.player_id == player_id),
        None,
    )
    player = next(item for item in state.players if item.player_id == player_id)
    overall = lifecycle.overall if lifecycle else 62 + player.expected_minutes * 0.5
    if overall < 69:
        salary = 1_400_000 + (overall - 50) * 90_000
    elif overall < 75:
        salary = 3_100_000 + (overall - 69) * 650_000
    elif overall < 80:
        salary = 7_000_000 + (overall - 75) * 1_500_000
    elif overall < 85:
        salary = 14_500_000 + (overall - 80) * 2_300_000
    elif overall < 90:
        salary = 26_000_000 + (overall - 85) * 3_100_000
    else:
        salary = 41_500_000 + (overall - 90) * 1_650_000
    return int(max(1_400_000, min(58_000_000, round(salary)))), "modeled-cap-charge"


def maximum_trade_incoming(
    *,
    team_salary: int,
    outgoing_salary: int,
    incoming_salary: int,
) -> int:
    if team_salary < CBA_2026_27.salary_cap:
        return outgoing_salary + max(0, CBA_2026_27.salary_cap - team_salary) + 250_000
    if team_salary > CBA_2026_27.first_apron:
        return outgoing_salary
    scaled_increment = round(
        7_500_000 * CBA_2026_27.salary_cap / 136_021_000
    )
    return max(
        min(2 * outgoing_salary + 250_000, outgoing_salary + scaled_increment),
        round(1.25 * outgoing_salary) + 250_000,
    )


def player_trade_value(
    state: "LeagueState",
    player_id: int,
    *,
    receiving_team: str,
) -> float:
    player = next(item for item in state.players if item.player_id == player_id)
    lifecycle = next(
        (item for item in state.player_lifecycles if item.player_id == player_id),
        None,
    )
    if lifecycle is None:
        return max(4.0, player.expected_minutes * 0.8)
    age = lifecycle.age if lifecycle.age is not None else 27.0
    strategy = team_strategy(state, receiving_team)
    present = max(0.0, lifecycle.overall - 58) * 1.25
    upside = max(0.0, lifecycle.potential_mean - lifecycle.overall)
    age_curve = max(-12.0, min(10.0, (27.0 - age) * 1.3))
    if strategy == "contender":
        age_curve *= 0.25
        upside *= 0.35
    elif strategy == "rebuilding":
        age_curve *= 1.35
        upside *= 1.25
    health = next(
        (item for item in state.player_health if item.player_id == player_id),
        None,
    )
    health_discount = {
        "available": 0,
        "managed": 2,
        "questionable": 4,
        "doubtful": 8,
        "out": 10,
    }.get(health.availability if health else "available", 0)
    salary, _ = player_cap_charge(state, player_id)
    salary_drag = max(0.0, salary / 1_000_000 - max(2, present * 0.58)) * 0.22
    return max(
        1.0,
        present + upside * 1.35 + age_curve - health_discount - salary_drag,
    )


def draft_asset_value(asset: DraftAssetRecord) -> float:
    years_out = max(0, asset.draft_year - 2027)
    base = 24.0 if asset.round == 1 else 6.5
    uncertainty_bonus = min(5.0, years_out * 0.8) if asset.round == 1 else 0
    protection_discount = 4.0 if asset.protection else 0
    return max(
        1.0,
        (base + uncertainty_bonus - protection_discount) * (0.94 ** years_out),
    )


def team_strategy(state: "LeagueState", team: str) -> str:
    lifecycles = {item.player_id: item for item in state.player_lifecycles}
    strengths = []
    for franchise in state.franchises:
        roster = sorted(
            (
                lifecycles[player.player_id].overall
                for player in state.roster(franchise.team)
                if player.player_id in lifecycles
            ),
            reverse=True,
        )[:8]
        strengths.append(
            (sum(strengths_for_player for strengths_for_player in roster), franchise.team)
        )
    ordered = [
        item[1] for item in sorted(strengths, key=lambda item: (-item[0], item[1]))
    ]
    rank = ordered.index(team) if team in ordered else 15
    if rank < 10:
        return "contender"
    if rank >= 20:
        return "rebuilding"
    return "balanced"


def rule_coverage() -> list[dict[str, object]]:
    return [
        _rule("salary_matching", "Salary matching", True, "CBA"),
        _rule("first_apron", "First-apron incoming salary restrictions", True, "CBA"),
        _rule("second_apron", "Second-apron aggregation restriction", True, "CBA"),
        _rule("stepien_rule", "Consecutive future first-round pick restriction", True, "NBA rule"),
        _rule("seven_year_pick_limit", "Seven-draft-year pick horizon", True, "CBA"),
        _rule("recently_signed", "New-contract waiting periods", True, "CBA"),
        _rule(
            "recently_acquired_aggregation",
            "Recently acquired player aggregation",
            True,
            "CBA",
        ),
        _rule("extension_restrictions", "Extension-and-trade waiting period", True, "CBA"),
        _rule("no_trade_consent", "No-trade and one-year Bird consent", True, "CBA"),
        _rule("reacquisition", "Former-team reacquisition restriction", True, "CBA"),
        _rule("consideration_required", "Asset consideration on both sides", True, "Transaction rule"),
        _rule("roster_limits", "Active roster ceiling", True, "Roster rule"),
        _rule("trade_deadline", "Trade deadline", True, "League calendar"),
        _rule(
            "injury_house_rule",
            "Block injured-player trades",
            False,
            "Optional house rule; injury alone is not an NBA trade ban",
        ),
        _rule("ai_acceptance", "CPU front-office consent", True, "Simulation"),
        _rule("ai_to_ai_trades", "CPU-to-CPU market", True, "Simulation"),
    ]


def _apply_player_restrictions(
    state: "LeagueState",
    package: TradeTeamPackage,
    players: Iterable[PlayerRecord],
    *,
    destination_team: str,
    policy: TradeRulePolicy,
    blockers: list[dict[str, str]],
    warnings: list[str],
) -> None:
    now = state.calendar.current_date
    health = {item.player_id: item for item in state.player_health}
    contracts = {item.player_id: item for item in state.contracts if item.status == "active"}
    for player in players:
        contract = contracts.get(player.player_id)
        if policy.recently_signed and contract is not None:
            salary_year_start = now.year if now.month >= 7 else now.year - 1
            eligible_on = max(
                contract.signed_on + timedelta(days=92),
                date(salary_year_start, 12, 15),
            )
            if now < eligible_on:
                blockers.append(
                    _block(
                        "recently_signed",
                        f"{player.name} cannot be traded until {eligible_on.isoformat()} "
                        "under the new-contract waiting period.",
                    )
                )
        if policy.recently_acquired_aggregation and len(package.player_ids) > 1:
            latest_trade = max(
                (
                    item.occurred_on
                    for item in state.transactions
                    if player.player_id in item.player_ids
                    and item.transaction_type == "trade"
                ),
                default=None,
            )
            if latest_trade is not None and (now - latest_trade).days < 60:
                blockers.append(
                    _block(
                        "recently_acquired_aggregation",
                        f"{player.name} was acquired fewer than 60 days ago and "
                        "cannot be aggregated in this construction.",
                    )
                )
        if policy.injury_house_rule:
            status = health.get(player.player_id)
            if status is not None and status.availability in {"doubtful", "out"}:
                blockers.append(
                    _block(
                        "injury_house_rule",
                        f"{player.name} is {status.availability}; the optional "
                        "injured-player house restriction is enabled.",
                    )
                )
        if policy.no_trade_consent and contract is not None:
            needs_consent = "no-trade" in contract.source.lower() or (
                len(contract.years) == 1 and "bird" in contract.source.lower()
            )
            if needs_consent and player.player_id not in package.consent_player_ids:
                blockers.append(
                    _block(
                        "no_trade_consent",
                        f"{player.name} requires player consent for this trade.",
                    )
                )
        if policy.extension_restrictions and contract is not None:
            if "extended" in contract.source.lower() and (
                now - contract.signed_on
            ).days < 183:
                blockers.append(
                    _block(
                        "extension_restrictions",
                        f"{player.name} is inside the six-month extension-and-trade "
                        "waiting period.",
                    )
                )
        if policy.reacquisition:
            prior_between_teams = next(
                (
                    item
                    for item in reversed(state.transactions)
                    if item.transaction_type == "trade"
                    and player.player_id in item.player_ids
                    and package.team in item.teams
                    and destination_team in item.teams
                    and item.occurred_on >= state.calendar.cap_year_start
                ),
                None,
            )
            if prior_between_teams is not None:
                blockers.append(
                    _block(
                        "reacquisition",
                        f"{player.name} cannot return to {destination_team} during "
                        "the same cap year after the clubs previously traded him.",
                    )
                )
    if policy.no_trade_consent and not contracts:
        warnings.append(
            "No authoritative clause ledger is loaded; consent rules can only "
            "enforce clauses present in contract records."
        )


def _violates_stepien(
    state: "LeagueState",
    *,
    team: str,
    outgoing_asset_ids: set[str],
) -> bool:
    future_years = range(max(2027, state.calendar.current_date.year), 2034)
    has_first: dict[int, bool] = {}
    for year in future_years:
        has_first[year] = any(
            item.round == 1
            and item.draft_year == year
            and item.current_team == team
            and item.asset_id not in outgoing_asset_ids
            for item in state.draft_assets
        )
    years = sorted(has_first)
    return any(
        not has_first[first] and not has_first[second]
        for first, second in zip(years, years[1:])
    )


def _draft_asset_is_available(
    state: "LeagueState",
    asset: DraftAssetRecord,
) -> bool:
    draft = state.draft_ecosystem
    if draft is None or asset.draft_year != draft.draft_year or not draft.order:
        return True
    slot = next(
        (
            item
            for item in draft.order
            if item.round == asset.round
            and item.original_team == asset.original_team
        ),
        None,
    )
    if slot is None:
        return True
    return slot.overall_pick > len(draft.selections)


def _block(rule: str, message: str) -> dict[str, str]:
    return {"rule": rule, "message": message}


def _rule(key: str, label: str, default: bool, authority: str) -> dict[str, object]:
    return {
        "key": key,
        "label": label,
        "default": default,
        "authority": authority,
    }


def _money(value: int) -> str:
    return f"${value / 1_000_000:.3f}M"


def _acceptance_copy(
    team: str,
    user_team: str,
    accepts: bool,
    delta: float,
    enabled: bool,
) -> str:
    if team == user_team:
        return "User-controlled front office."
    if not enabled:
        return "CPU acceptance is disabled by league settings."
    if accepts:
        return f"{team} values the return within its acceptable range ({delta:+.1f})."
    return f"{team} wants approximately {abs(delta):.1f} more value."


def deterministic_trade_id(
    *,
    league_id: str,
    revision: int,
    packages: tuple[TradeTeamPackage, TradeTeamPackage],
) -> str:
    encoded = "|".join(
        (
            league_id,
            str(revision),
            *(
                f"{item.team}:{','.join(map(str, item.player_ids))}:"
                f"{','.join(item.asset_ids)}"
                for item in packages
            ),
        )
    )
    return f"trade-{hashlib.sha256(encoded.encode()).hexdigest()[:16]}"


def propose_ai_trades(
    state: "LeagueState",
    *,
    policy: TradeRulePolicy,
    max_deals: int,
) -> tuple[tuple[TradeTeamPackage, TradeTeamPackage], ...]:
    if not policy.ai_to_ai_trades:
        raise ValueError("CPU-to-CPU trading is disabled")
    if not 1 <= max_deals <= 12:
        raise ValueError("AI trade cycle must request between 1 and 12 deals")
    teams = [
        item.team for item in state.franchises if item.team != state.user_team
    ]
    rng = RandomStreamFactory(state.seed).generator(
        f"ai-trade-market:{state.calendar.current_date}:{state.revision}"
    )
    proposals: list[tuple[TradeTeamPackage, TradeTeamPackage]] = []
    used_players: set[int] = set()
    shuffled = list(teams)
    rng.shuffle(shuffled)
    for seller in shuffled:
        if len(proposals) >= max_deals:
            break
        seller_strategy = team_strategy(state, seller)
        candidate_buyers = [
            team for team in teams
            if team != seller
            and team_strategy(state, team) != seller_strategy
        ]
        rng.shuffle(candidate_buyers)
        for buyer in candidate_buyers[:8]:
            seller_roster = [
                item for item in state.roster(seller)
                if item.player_id not in used_players
            ]
            buyer_roster = [
                item for item in state.roster(buyer)
                if item.player_id not in used_players
            ]
            if not seller_roster or not buyer_roster:
                continue
            if seller_strategy == "rebuilding":
                seller_player = max(
                    seller_roster,
                    key=lambda item: (
                        (next(
                            (
                                life.age for life in state.player_lifecycles
                                if life.player_id == item.player_id
                            ),
                            27,
                        ) or 27),
                        player_trade_value(state, item.player_id, receiving_team=buyer),
                    ),
                )
                buyer_player = min(
                    buyer_roster,
                    key=lambda item: abs(
                        player_trade_value(state, item.player_id, receiving_team=seller)
                        - player_trade_value(
                            state,
                            seller_player.player_id,
                            receiving_team=buyer,
                        )
                    ),
                )
            else:
                seller_player = min(
                    seller_roster,
                    key=lambda item: player_trade_value(
                        state,
                        item.player_id,
                        receiving_team=buyer,
                    ),
                )
                buyer_player = min(
                    buyer_roster,
                    key=lambda item: abs(
                        player_trade_value(state, item.player_id, receiving_team=seller)
                        - player_trade_value(
                            state,
                            seller_player.player_id,
                            receiving_team=buyer,
                        )
                    ),
                )
            buyer_asset_ids: tuple[str, ...] = ()
            if seller_strategy == "rebuilding":
                value_gap = (
                    player_trade_value(
                        state,
                        seller_player.player_id,
                        receiving_team=buyer,
                    )
                    - player_trade_value(
                        state,
                        buyer_player.player_id,
                        receiving_team=seller,
                    )
                )
                if value_gap > 7:
                    available_firsts = sorted(
                        (
                            item for item in state.draft_assets
                            if item.current_team == buyer
                            and item.round == 1
                            and item.draft_year >= 2029
                            and _draft_asset_is_available(state, item)
                        ),
                        key=lambda item: (
                            abs(draft_asset_value(item) - value_gap),
                            -item.draft_year,
                            item.asset_id,
                        ),
                    )
                    if available_firsts:
                        buyer_asset_ids = (available_firsts[0].asset_id,)
            proposal = (
                TradeTeamPackage(seller, (seller_player.player_id,)),
                TradeTeamPackage(
                    buyer,
                    (buyer_player.player_id,),
                    buyer_asset_ids,
                ),
            )
            evaluation = evaluate_trade(state, proposal, policy=policy)
            chance = 0.08 + policy.ai_aggressiveness * 0.24
            if (
                evaluation["can_execute"]
                and float(rng.random()) < chance
            ):
                proposals.append(proposal)
                used_players.update(
                    (seller_player.player_id, buyer_player.player_id)
                )
                break
    return tuple(proposals)
