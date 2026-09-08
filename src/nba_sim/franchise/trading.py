from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
import hashlib
from itertools import combinations
from typing import TYPE_CHECKING, Iterable, Mapping, Sequence

from nba_sim.franchise.cba import CBA_2026_27, CBAYearRules, cap_position, rules_for_season
from nba_sim.franchise.models import (
    DraftAssetRecord,
    PlayerLifecycleRecord,
    PlayerRecord,
)
from nba_sim.randomness import RandomStreamFactory

if TYPE_CHECKING:
    from nba_sim.franchise.state import LeagueState


TRADE_MODEL_VERSION = "trade-market-front-office.v3"
PROJECTED_2027_TRADE_DEADLINE = date(2027, 2, 11)
_FRONT_OFFICE_CACHE: dict[tuple[str, int, str], "FrontOfficeProfile"] = {}
_STRENGTH_ORDER_CACHE: dict[tuple[str, int], tuple[str, ...]] = {}


@dataclass(frozen=True)
class FrontOfficeProfile:
    team: str
    strategy: str
    strength_rank: int
    average_age: float
    urgency: float
    patience: float
    risk_tolerance: float
    needs: tuple[str, ...]
    surplus: tuple[str, ...]
    untouchable_player_ids: tuple[int, ...]
    trade_block_player_ids: tuple[int, ...]

    def as_dict(self, *, player_names: Mapping[int, str] | None = None) -> dict[str, object]:
        names = player_names or {}
        return {
            "team": self.team,
            "strategy": self.strategy,
            "strength_rank": self.strength_rank,
            "average_age": round(self.average_age, 2),
            "urgency": round(self.urgency, 4),
            "patience": round(self.patience, 4),
            "risk_tolerance": round(self.risk_tolerance, 4),
            "needs": list(self.needs),
            "surplus": list(self.surplus),
            "untouchable_player_ids": list(self.untouchable_player_ids),
            "untouchables": [
                names[player_id]
                for player_id in self.untouchable_player_ids
                if player_id in names
            ],
            "trade_block_player_ids": list(self.trade_block_player_ids),
            "trade_block": [
                names[player_id]
                for player_id in self.trade_block_player_ids
                if player_id in names
            ],
        }


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
    player_destinations: tuple[tuple[int, str], ...] = ()
    asset_destinations: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "team", self.team.upper())
        if not self.team:
            raise ValueError("trade package team is required")
        if len(set(self.player_ids)) != len(self.player_ids):
            raise ValueError("trade package repeats a player")
        if len(set(self.asset_ids)) != len(self.asset_ids):
            raise ValueError("trade package repeats a draft asset")
        player_routes = dict(self.player_destinations)
        asset_routes = dict(self.asset_destinations)
        if len(player_routes) != len(self.player_destinations):
            raise ValueError("trade package repeats a player destination")
        if len(asset_routes) != len(self.asset_destinations):
            raise ValueError("trade package repeats a draft-asset destination")
        if any(player_id not in self.player_ids for player_id in player_routes):
            raise ValueError("player destination references an unselected player")
        if any(asset_id not in self.asset_ids for asset_id in asset_routes):
            raise ValueError("draft destination references an unselected asset")
        normalized_players = tuple(
            sorted((int(player_id), str(team).upper()) for player_id, team in player_routes.items())
        )
        normalized_assets = tuple(
            sorted((str(asset_id), str(team).upper()) for asset_id, team in asset_routes.items())
        )
        object.__setattr__(self, "player_destinations", normalized_players)
        object.__setattr__(self, "asset_destinations", normalized_assets)


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
    player_names = {item.player_id: item.name for item in state.players}
    front_offices = {
        franchise.team: front_office_profile(state, franchise.team)
        for franchise in state.franchises
    }
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
                "market_status": _player_market_status(
                    player.player_id,
                    front_offices[player.team],
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
        team: profile.strategy for team, profile in front_offices.items()
    }
    return {
        "players": rows,
        "assets": assets,
        "strategies": strategies,
        "front_offices": {
            team: profile.as_dict(player_names=player_names)
            for team, profile in front_offices.items()
        },
        "salary_note": (
            "Authoritative contract values are used when present. Missing contracts "
            "receive an explicitly labeled modeled cap charge so the trade engine "
            "can still evaluate salary matching."
        ),
        "model_version": TRADE_MODEL_VERSION,
    }


def resolve_trade_routes(
    packages: Sequence[TradeTeamPackage],
) -> tuple[dict[int, tuple[str, str]], dict[str, tuple[str, str]]]:
    teams = tuple(package.team for package in packages)
    if not 2 <= len(teams) <= 4 or len(set(teams)) != len(teams):
        raise ValueError("a trade requires two to four different teams")
    player_routes: dict[int, tuple[str, str]] = {}
    asset_routes: dict[str, tuple[str, str]] = {}
    for package in packages:
        player_destinations = dict(package.player_destinations)
        asset_destinations = dict(package.asset_destinations)
        default_destination = next(
            (team for team in teams if team != package.team),
            None,
        ) if len(teams) == 2 else None
        for player_id in package.player_ids:
            destination = player_destinations.get(player_id, default_destination)
            if destination not in teams or destination == package.team:
                raise ValueError(
                    f"choose a receiving team for player {player_id} from {package.team}"
                )
            player_routes[player_id] = package.team, str(destination)
        for asset_id in package.asset_ids:
            destination = asset_destinations.get(asset_id, default_destination)
            if destination not in teams or destination == package.team:
                raise ValueError(
                    f"choose a receiving team for draft asset {asset_id} from {package.team}"
                )
            asset_routes[asset_id] = package.team, str(destination)
    return player_routes, asset_routes


def evaluate_trade(
    state: "LeagueState",
    packages: Sequence[TradeTeamPackage],
    *,
    policy: TradeRulePolicy,
) -> dict[str, object]:
    packages = tuple(packages)
    cba_rules = rules_for_season(state.season)
    player_routes, asset_routes = resolve_trade_routes(packages)
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
        and now > projected_trade_deadline(state.season)
    ):
        blockers.append(
            _block(
                "trade_deadline",
                f"The league date is after the projected {projected_trade_deadline(state.season).year} trade deadline.",
            )
        )
    if not policy.trade_deadline:
        warnings.append("Trade-deadline enforcement is disabled.")
    incoming_player_ids = {package.team: [] for package in packages}
    incoming_asset_ids = {package.team: [] for package in packages}
    for player_id, (_, destination) in player_routes.items():
        incoming_player_ids[destination].append(player_id)
    for asset_id, (_, destination) in asset_routes.items():
        incoming_asset_ids[destination].append(asset_id)
    if policy.consideration_required:
        for package in packages:
            if not package.player_ids and not package.asset_ids:
                blockers.append(_block(
                    "consideration_required",
                    f"{package.team} must send at least one player or draft asset.",
                ))
            if not incoming_player_ids[package.team] and not incoming_asset_ids[package.team]:
                blockers.append(_block(
                    "consideration_required",
                    f"{package.team} must receive at least one player or draft asset.",
                ))

    for package in packages:
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
            for player_id in incoming_player_ids[package.team]
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
                rules=cba_rules,
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

        if policy.first_apron and team_salary > cba_rules.first_apron:
            if incoming_salary > outgoing_salary:
                blockers.append(
                    _block(
                        "first_apron",
                        f"{package.team} is above the first apron and cannot take "
                        "back more salary than it sends.",
                    )
                )
        if policy.second_apron and team_salary > cba_rules.second_apron:
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

        for destination in sorted({
            player_routes[player.player_id][1]
            for player in outgoing_players
            if player.player_id in player_routes
        }):
            _apply_player_restrictions(
                state,
                package,
                [
                    player for player in outgoing_players
                    if player_routes[player.player_id][1] == destination
                ],
                destination_team=destination,
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
            incoming_asset_ids=set(incoming_asset_ids[package.team]),
        ):
            blockers.append(
                _block(
                    "stepien_rule",
                    f"{package.team} would be left without a first-round selection "
                    "in consecutive future drafts.",
                )
            )

        outgoing_value = _package_value_for_team(
            state,
            TradeTeamPackage(
                package.team,
                tuple(item.player_id for item in outgoing_players),
                tuple(item.asset_id for item in outgoing_assets),
            ),
            team=package.team,
        )
        incoming_value = _package_value_for_team(
            state,
            TradeTeamPackage(
                package.team,
                tuple(item.player_id for item in incoming_players),
                tuple(
                    asset_id for asset_id in incoming_asset_ids[package.team]
                    if asset_id in asset_by_id
                ),
            ),
            team=package.team,
        )
        front_office = front_office_profile(state, package.team)
        strategy = front_office.strategy
        acceptance_margin = incoming_value - outgoing_value
        core_outgoing = [
            player for player in outgoing_players
            if player.player_id in front_office.untouchable_player_ids
        ]
        available_outgoing = [
            player for player in outgoing_players
            if player.player_id in front_office.trade_block_player_ids
        ]
        lifecycle_by_id = {item.player_id: item for item in state.player_lifecycles}
        core_premium = sum(
            player_trade_value(state, player.player_id, receiving_team=package.team)
            * (
                0.30
                if lifecycle_by_id.get(player.player_id)
                and lifecycle_by_id[player.player_id].overall >= 92
                else 0.20
            )
            for player in core_outgoing
        )
        premium_rate = (
            0.012
            + 0.028 * front_office.patience
            - 0.025 * front_office.urgency
            - 0.025 * min(1, len(available_outgoing))
        )
        required_margin = max(0.0, core_premium + outgoing_value * premium_rate)
        negotiation_band = max(
            0.8,
            outgoing_value
            * (0.018 + 0.025 * front_office.risk_tolerance),
        )
        if state.experience is not None:
            negotiation_band *= state.experience.negotiation_tolerance
        accepts = (
            not policy.ai_acceptance
            or package.team == state.user_team
            or acceptance_margin >= required_margin - negotiation_band
        )
        factors = _decision_factors(
            state,
            team=package.team,
            incoming_players=incoming_players,
            outgoing_players=outgoing_players,
            incoming_asset_ids=tuple(incoming_asset_ids[package.team]),
            core_outgoing=core_outgoing,
            available_outgoing=available_outgoing,
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
                "salary_band_before": cap_position(team_salary, rules=cba_rules).band.value,
                "salary_band_after": cap_position(after_salary, rules=cba_rules).band.value,
                "modeled_salary_rows": unknown_salary_count,
                "outgoing_value": round(outgoing_value, 2),
                "incoming_value": round(incoming_value, 2),
                "value_delta": round(acceptance_margin, 2),
                "required_value_delta": round(required_margin, 2),
                "negotiation_band": round(negotiation_band, 2),
                "difficulty": (
                    state.experience.difficulty
                    if state.experience is not None
                    else "pro"
                ),
                "accepts": accepts,
                "acceptance_copy": _acceptance_copy(
                    package.team,
                    state.user_team,
                    accepts,
                    acceptance_margin,
                    policy.ai_acceptance,
                    required_margin - negotiation_band,
                ),
                "decision_factors": factors,
                "front_office": front_office.as_dict(
                    player_names={item.player_id: item.name for item in state.players}
                ),
            }
        )

    cpu_rejections = [
        item for item in team_results
        if item["team"] != state.user_team and not item["accepts"]
    ]
    legal = not blockers
    accepted = legal and not cpu_rejections
    for rule in rule_coverage():
        key = str(rule["key"])
        if bool(rule["default"]) and not bool(getattr(policy, key)):
            warnings.append(f"{rule['label']} is disabled by this branch's house rules.")
    return {
        "legal": legal,
        "accepted": accepted,
        "can_execute": accepted,
        "blockers": blockers,
        "warnings": sorted(set(warnings)),
        "teams": team_results,
        "team_count": len(packages),
        "trade_type": "multi_team" if len(packages) > 2 else "two_team",
        "routes": {
            "players": [
                {"player_id": player_id, "from_team": source, "to_team": destination}
                for player_id, (source, destination) in sorted(player_routes.items())
            ],
            "assets": [
                {"asset_id": asset_id, "from_team": source, "to_team": destination}
                for asset_id, (source, destination) in sorted(asset_routes.items())
            ],
        },
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
    inflation = rules_for_season(state.season).salary_cap / CBA_2026_27.salary_cap
    return int(
        max(
            round(1_400_000 * inflation),
            min(round(58_000_000 * inflation), round(salary * inflation)),
        )
    ), "modeled-cap-charge"


def maximum_trade_incoming(
    *,
    team_salary: int,
    outgoing_salary: int,
    incoming_salary: int,
    rules: CBAYearRules = CBA_2026_27,
) -> int:
    if team_salary < rules.salary_cap:
        return outgoing_salary + max(0, rules.salary_cap - team_salary) + 250_000
    if team_salary > rules.first_apron:
        return outgoing_salary
    scaled_increment = round(
        7_500_000 * rules.salary_cap / 136_021_000
    )
    return max(
        min(2 * outgoing_salary + 250_000, outgoing_salary + scaled_increment),
        round(1.25 * outgoing_salary) + 250_000,
    )


def projected_trade_deadline(season: str) -> date:
    """Move the planning deadline with the cap year instead of freezing 2027."""
    start = int(season.split("-", 1)[0])
    if start == 2026:
        return PROJECTED_2027_TRADE_DEADLINE
    return date(start + 1, 2, 11)


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
        return _player_base_value(state, player_id)
    age = lifecycle.age if lifecycle.age is not None else 27.0
    profile = front_office_profile(state, receiving_team)
    strategy = profile.strategy
    overall = lifecycle.overall
    present = max(0.0, overall - 55) * 1.15
    scarcity = max(0.0, overall - 82) ** 1.65 * 1.05
    upside = max(0.0, lifecycle.potential_mean - lifecycle.overall)
    age_curve = max(-16.0, min(12.0, (27.0 - age) * 1.25))
    if strategy == "contender":
        age_curve *= 0.2
        upside *= 0.38
    elif strategy == "rebuilding":
        age_curve *= 1.4
        upside *= 1.5
    position = _position_bucket(player.position)
    need_bonus = 0.0
    if position in profile.needs:
        need_bonus = 2.5 + min(2.5, player.expected_minutes / 14)
    elif position in profile.surplus:
        need_bonus = -1.75
    role_bonus = min(4.0, max(0.0, player.expected_minutes - 22) * 0.18)
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
    expected_salary = max(
        2.0,
        min(62.0, (overall - 62) * 1.95 + max(0.0, overall - 87) * 2.1),
    )
    salary_drag = max(0.0, salary / 1_000_000 - expected_salary) * 0.42
    surplus_value = max(0.0, expected_salary - salary / 1_000_000) * 0.30
    contract = next(
        (
            item for item in state.contracts
            if item.player_id == player_id and item.status == "active"
        ),
        None,
    )
    remaining_years = (
        sum(item.season >= state.season for item in contract.years)
        if contract is not None else 1
    )
    control_value = min(8.0, max(0, remaining_years - 1) * 1.6)
    if contract is not None and any(
        year.option and "player" in year.option.lower()
        for year in contract.years
    ):
        control_value -= 1.5
    return max(
        1.0,
        present
        + scarcity
        + upside * 1.25
        + age_curve
        + need_bonus
        + role_bonus
        + surplus_value
        + control_value
        - health_discount
        - salary_drag,
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


def draft_asset_value_for_team(
    state: "LeagueState",
    asset: DraftAssetRecord,
    *,
    team: str,
) -> float:
    profile = front_office_profile(state, team)
    multiplier = {
        "contender": 0.78,
        "balanced": 1.0,
        "rebuilding": 1.24,
    }[profile.strategy]
    years_out = max(0, asset.draft_year - state.calendar.current_date.year)
    uncertainty = 1 + (profile.risk_tolerance - 0.45) * min(0.25, years_out * 0.035)
    if asset.round == 1:
        original = front_office_profile(state, asset.original_team)
        projected_slot = 1 + (original.strength_rank - 1) * 29 / 29
        slot_value = 58.0 - (projected_slot - 1) * 1.42
        time_regression = min(0.72, years_out * 0.12)
        slot_value = slot_value * (1 - time_regression) + 25.0 * time_regression
        if asset.protection:
            protection = asset.protection.lower()
            discount = 0.78 if "lottery" in protection else 0.84
            slot_value *= discount
        base = slot_value * (0.95 ** years_out)
    else:
        base = draft_asset_value(asset)
    return max(1.0, base * multiplier * uncertainty)


def _decision_factors(
    state: "LeagueState",
    *,
    team: str,
    incoming_players: Sequence[PlayerRecord],
    outgoing_players: Sequence[PlayerRecord],
    incoming_asset_ids: Sequence[str],
    core_outgoing: Sequence[PlayerRecord],
    available_outgoing: Sequence[PlayerRecord],
) -> list[dict[str, str]]:
    profile = front_office_profile(state, team)
    factors: list[dict[str, str]] = []
    need_fits = sorted(
        {
            _position_bucket(player.position)
            for player in incoming_players
            if _position_bucket(player.position) in profile.needs
        }
    )
    if need_fits:
        factors.append(
            {
                "tone": "positive",
                "label": "Roster fit",
                "detail": f"Adds needed {', '.join(need_fits)} depth.",
            }
        )
    if core_outgoing:
        factors.append(
            {
                "tone": "negative",
                "label": "Core-player premium",
                "detail": (
                    f"{', '.join(player.name for player in core_outgoing)} "
                    "is part of this front office's protected core."
                ),
            }
        )
    if available_outgoing:
        factors.append(
            {
                "tone": "positive",
                "label": "Available asset",
                "detail": (
                    f"{', '.join(player.name for player in available_outgoing)} "
                    "is movable for the right return."
                ),
            }
        )
    if incoming_asset_ids:
        factors.append(
            {
                "tone": "positive" if profile.strategy == "rebuilding" else "neutral",
                "label": "Draft capital",
                "detail": (
                    "Future picks support the rebuild."
                    if profile.strategy == "rebuilding"
                    else "Draft capital preserves future flexibility."
                ),
            }
        )
    incoming_ages = []
    lifecycle = {item.player_id: item for item in state.player_lifecycles}
    for player in incoming_players:
        record = lifecycle.get(player.player_id)
        if record and record.age is not None:
            incoming_ages.append(record.age)
    if incoming_ages and profile.strategy == "rebuilding" and min(incoming_ages) <= 23:
        factors.append(
            {
                "tone": "positive",
                "label": "Timeline",
                "detail": "The return adds a young player who can grow with the next core.",
            }
        )
    if not factors:
        factors.append(
            {
                "tone": "neutral",
                "label": "Market value",
                "detail": "The decision is driven primarily by asset value and salary structure.",
            }
        )
    return factors[:4]


def team_strategy(state: "LeagueState", team: str) -> str:
    return front_office_profile(state, team).strategy


def front_office_profile(state: "LeagueState", team: str) -> FrontOfficeProfile:
    team = team.upper()
    cache_key = (state.head_hash, state.revision, team)
    cached = _FRONT_OFFICE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    lifecycles = {item.player_id: item for item in state.player_lifecycles}
    ordered = _strength_order(state)
    rank = ordered.index(team) if team in ordered else 15
    gm_plan = next((item for item in state.gm_plans if item.team == team), None)
    if gm_plan is not None:
        strategy = {
            "contend": "contender",
            "compete": "balanced",
            "retool": "balanced",
            "rebuild": "rebuilding",
        }[gm_plan.direction]
        rank = gm_plan.strength_rank - 1
    elif rank < 10:
        strategy = "contender"
    elif rank >= 20:
        strategy = "rebuilding"
    else:
        strategy = "balanced"

    roster = list(state.roster(team))
    known_ages = [
        lifecycles[player.player_id].age
        for player in roster
        if player.player_id in lifecycles
        and lifecycles[player.player_id].age is not None
    ]
    average_age = (
        sum(float(item) for item in known_ages) / len(known_ages)
        if known_ages else 27.0
    )
    if gm_plan is not None:
        average_age = gm_plan.average_age
    position_minutes = {"guard": 0.0, "wing": 0.0, "big": 0.0}
    for player in roster:
        position_minutes[_position_bucket(player.position)] += min(
            36.0, player.expected_minutes
        )
    targets = {"guard": 90.0, "wing": 96.0, "big": 54.0}
    ordered_needs = sorted(
        targets,
        key=lambda position: (
            position_minutes[position] / targets[position],
            position,
        ),
    )
    needs = tuple(
        position for position in ordered_needs
        if position_minutes[position] < targets[position] * 0.9
    )[:2]
    if not needs:
        needs = (ordered_needs[0],)
    if gm_plan is not None:
        needs = gm_plan.needs
    surplus = tuple(
        position for position in targets
        if position_minutes[position] > targets[position] * 1.18
    )

    ranked_roster = sorted(
        roster,
        key=lambda player: (
            _player_base_value(state, player.player_id),
            player.expected_minutes,
            -player.player_id,
        ),
        reverse=True,
    )
    protected_count = 2 if strategy != "rebuilding" else 1
    untouchables = tuple(
        player.player_id for player in ranked_roster[:protected_count]
        if _player_base_value(state, player.player_id) >= 34
    )
    trade_block: list[int] = []
    for player in ranked_roster:
        life = lifecycles.get(player.player_id)
        age = life.age if life and life.age is not None else 27.0
        salary, _ = player_cap_charge(state, player.player_id)
        expensive_role = salary >= 18_000_000 and player.expected_minutes < 24
        timeline_mismatch = (
            strategy == "rebuilding" and age >= 29 and player.expected_minutes >= 18
        ) or (
            strategy == "contender" and age <= 23 and player.expected_minutes < 14
        )
        if (
            player.player_id not in untouchables
            and (expensive_role or timeline_mismatch or player.expected_minutes < 10)
        ):
            trade_block.append(player.player_id)
    personality = int(
        hashlib.sha256(f"{state.league_id}:{team}:front-office".encode()).hexdigest()[:8],
        16,
    )
    risk = (
        gm_plan.risk_tolerance
        if gm_plan is not None
        else 0.32 + (personality % 3100) / 10_000
    )
    urgency = {
        "contender": 0.72,
        "balanced": 0.5,
        "rebuilding": 0.34,
    }[strategy]
    if state.calendar.phase == "regular_season":
        days_to_deadline = (PROJECTED_2027_TRADE_DEADLINE - state.calendar.current_date).days
        if 0 <= days_to_deadline <= 35:
            urgency = min(0.95, urgency + (35 - days_to_deadline) / 100)
    patience = {
        "contender": 0.38,
        "balanced": 0.56,
        "rebuilding": 0.76,
    }[strategy]
    if gm_plan is not None:
        urgency = max(
            0.18,
            min(
                0.96,
                0.34
                + (100 - gm_plan.job_security) / 180
                + gm_plan.win_now_weight * 0.32,
            ),
        )
        patience = gm_plan.ownership_patience / 100
        untouchables = gm_plan.core_player_ids
        trade_block = list(gm_plan.trade_block_player_ids)
    result = FrontOfficeProfile(
        team=team,
        strategy=strategy,
        strength_rank=rank + 1,
        average_age=average_age,
        urgency=urgency,
        patience=patience,
        risk_tolerance=risk,
        needs=needs,
        surplus=surplus,
        untouchable_player_ids=untouchables,
        trade_block_player_ids=tuple(trade_block[:6]),
    )
    if len(_FRONT_OFFICE_CACHE) >= 480:
        _FRONT_OFFICE_CACHE.clear()
    _FRONT_OFFICE_CACHE[cache_key] = result
    return result


def _strength_order(state: "LeagueState") -> tuple[str, ...]:
    cache_key = (state.head_hash, state.revision)
    cached = _STRENGTH_ORDER_CACHE.get(cache_key)
    if cached is not None:
        return cached
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
        strengths.append((sum(roster), franchise.team))
    result = tuple(
        item[1] for item in sorted(strengths, key=lambda item: (-item[0], item[1]))
    )
    if len(_STRENGTH_ORDER_CACHE) >= 32:
        _STRENGTH_ORDER_CACHE.clear()
    _STRENGTH_ORDER_CACHE[cache_key] = result
    return result


def _player_base_value(state: "LeagueState", player_id: int) -> float:
    player = next(item for item in state.players if item.player_id == player_id)
    lifecycle = next(
        (item for item in state.player_lifecycles if item.player_id == player_id),
        None,
    )
    if lifecycle is None:
        return max(3.0, player.expected_minutes * 0.82)
    age = lifecycle.age if lifecycle.age is not None else 27.0
    present = max(0.0, lifecycle.overall - 60) * 1.55
    star_curve = max(0.0, lifecycle.overall - 84) ** 1.42 * 0.8
    upside = max(0.0, lifecycle.potential_mean - lifecycle.overall) * 1.2
    youth = max(-9.0, min(8.0, (27.0 - age) * 0.95))
    role = min(5.0, player.expected_minutes * 0.13)
    return max(1.0, present + star_curve + upside + youth + role)


def _position_bucket(position: str) -> str:
    normalized = position.upper().replace(" ", "")
    if "C" in normalized and "G" not in normalized:
        return "big"
    if "G" in normalized and "F" not in normalized and "C" not in normalized:
        return "guard"
    return "wing"


def _player_market_status(player_id: int, profile: FrontOfficeProfile) -> str:
    if player_id in profile.untouchable_player_ids:
        return "core"
    if player_id in profile.trade_block_player_ids:
        return "available"
    return "listening"


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
            cap_year_start = date(salary_year_start, 7, 1)
            eligible_on = max(
                contract.signed_on + timedelta(days=92),
                date(salary_year_start, 12, 15),
            )
            if contract.signed_on >= cap_year_start and now < eligible_on:
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
    incoming_asset_ids: set[str] | None = None,
) -> bool:
    incoming_asset_ids = incoming_asset_ids or set()
    assets = {item.asset_id: item for item in state.draft_assets}
    future_years = range(max(2027, state.calendar.current_date.year), 2034)
    has_first: dict[int, bool] = {}
    for year in future_years:
        has_first[year] = any(
            item.round == 1
            and item.draft_year == year
            and item.current_team == team
            and item.asset_id not in outgoing_asset_ids
            for item in state.draft_assets
        ) or any(
            asset_id in assets
            and assets[asset_id].round == 1
            and assets[asset_id].draft_year == year
            for asset_id in incoming_asset_ids
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
    minimum_delta: float,
) -> str:
    if team == user_team:
        return "User-controlled front office."
    if not enabled:
        return "CPU acceptance is disabled by league settings."
    if accepts:
        return f"{team} values the return within its acceptable range ({delta:+.1f})."
    shortfall = max(0.1, minimum_delta - delta)
    return f"{team} wants approximately {shortfall:.1f} more value."


def find_trade_offers(
    state: "LeagueState",
    *,
    policy: TradeRulePolicy,
    mode: str,
    player_id: int | None = None,
    asset_id: str | None = None,
    player_ids: Sequence[int] = (),
    asset_ids: Sequence[str] = (),
    objective: str = "balanced",
    max_offers: int = 8,
) -> dict[str, object]:
    if mode not in {"shop", "acquire"}:
        raise ValueError("trade finder mode must be shop or acquire")
    if objective not in {"balanced", "win_now", "youth", "cap_relief", "draft_capital"}:
        raise ValueError("unknown trade finder objective")
    if not 1 <= max_offers <= 12:
        raise ValueError("trade finder must request between 1 and 12 offers")
    selected_players = tuple(int(item) for item in player_ids)
    selected_assets = tuple(str(item) for item in asset_ids)
    if player_id is not None:
        selected_players = (*selected_players, player_id)
    if asset_id is not None:
        selected_assets = (*selected_assets, asset_id)
    fixed = _package_for_assets(
        state,
        player_ids=selected_players,
        asset_ids=selected_assets,
    )
    if mode == "shop" and fixed.team != state.user_team:
        raise ValueError("shop mode requires an asset controlled by your team")
    if mode == "acquire" and fixed.team == state.user_team:
        raise ValueError("acquire mode requires an asset controlled by another team")

    partners = (
        [fixed.team]
        if mode == "acquire"
        else [
            franchise.team for franchise in state.franchises
            if franchise.team != state.user_team
        ]
    )
    offers: list[dict[str, object]] = []
    for partner in partners:
        counterparty = state.user_team if mode == "acquire" else partner
        candidates = _offers_for_fixed_package(
            state,
            fixed=fixed,
            counterparty_team=counterparty,
            policy=policy,
            objective=objective,
            limit=4 if mode == "shop" else max_offers * 2,
        )
        for packages, evaluation in candidates:
            offers.append(
                _trade_offer_response(
                    state,
                    packages=packages,
                    evaluation=evaluation,
                    objective=objective,
                    mode=mode,
                )
            )
    offers.sort(
        key=lambda item: (
            -float(item["finder_score"]),
            str(item["partner"]),
            str(item["offer_id"]),
        )
    )
    deduplicated = []
    seen: set[str] = set()
    seen_partners: set[str] = set()
    for offer in offers:
        signature = str(offer["signature"])
        if signature in seen:
            continue
        partner = str(offer["partner"])
        if mode == "shop" and partner in seen_partners:
            continue
        seen.add(signature)
        seen_partners.add(partner)
        deduplicated.append(offer)
        if len(deduplicated) >= max_offers:
            break
    for rank, offer in enumerate(deduplicated, start=1):
        offer["rank"] = rank
    return {
        "mode": mode,
        "objective": objective,
        "query_asset": _describe_package(state, fixed),
        "offers": deduplicated,
        "teams_searched": len(partners),
        "model_version": TRADE_MODEL_VERSION,
        "empty_message": (
            "No team produced a legal, mutually acceptable offer. Change the goal, "
            "try another asset, or use the manual builder."
        ),
    }


def generate_counteroffer(
    state: "LeagueState",
    packages: tuple[TradeTeamPackage, TradeTeamPackage],
    *,
    policy: TradeRulePolicy,
) -> dict[str, object]:
    if len(packages) != 2:
        raise ValueError("automatic counteroffers currently require a two-team proposal")
    current = evaluate_trade(state, packages, policy=policy)
    if not current["legal"]:
        raise ValueError("fix league-rule blockers before asking for a counteroffer")
    if current["accepted"]:
        return {
            "changed": False,
            "message": "The current proposal is already accepted.",
            "packages": [_package_dict(item) for item in packages],
            "evaluation": current,
        }
    user_package = next((item for item in packages if item.team == state.user_team), None)
    cpu_package = next((item for item in packages if item.team != state.user_team), None)
    if user_package is None or cpu_package is None:
        raise ValueError("counteroffers require the user-controlled team")
    candidates = _candidate_packages(
        state,
        team=state.user_team,
        receiving_team=cpu_package.team,
        exclude_players=set(user_package.player_ids),
        exclude_assets=set(user_package.asset_ids),
        objective="balanced",
    )
    best: tuple[tuple[TradeTeamPackage, TradeTeamPackage], dict[str, object]] | None = None
    accepted_additions: list[
        tuple[
            float,
            tuple[TradeTeamPackage, TradeTeamPackage],
            dict[str, object],
        ]
    ] = []
    for addition in candidates:
        augmented = TradeTeamPackage(
            team=user_package.team,
            player_ids=tuple((*user_package.player_ids, *addition.player_ids)),
            asset_ids=tuple((*user_package.asset_ids, *addition.asset_ids)),
        )
        proposal = (augmented, cpu_package)
        evaluation = evaluate_trade(state, proposal, policy=policy)
        if evaluation["can_execute"]:
            accepted_additions.append(
                (
                    _package_value_for_team(
                        state,
                        addition,
                        team=cpu_package.team,
                    ),
                    proposal,
                    evaluation,
                )
            )
    if accepted_additions:
        _, proposal, evaluation = min(
            accepted_additions,
            key=lambda item: (
                item[0],
                sum(
                    len(package.player_ids) + len(package.asset_ids)
                    for package in item[1]
                ),
                _package_signature(item[1][0]),
            ),
        )
        best = proposal, evaluation
    if best is None and len(cpu_package.player_ids) + len(cpu_package.asset_ids) > 1:
        reduced_options = [
            TradeTeamPackage(cpu_package.team, tuple(player_ids), cpu_package.asset_ids)
            for size in range(len(cpu_package.player_ids) - 1, -1, -1)
            for player_ids in combinations(cpu_package.player_ids, size)
        ]
        reduced_options.extend(
            TradeTeamPackage(cpu_package.team, cpu_package.player_ids, tuple(asset_ids))
            for size in range(len(cpu_package.asset_ids) - 1, -1, -1)
            for asset_ids in combinations(cpu_package.asset_ids, size)
        )
        for reduced in reduced_options:
            if not reduced.player_ids and not reduced.asset_ids:
                continue
            proposal = (user_package, reduced)
            evaluation = evaluate_trade(state, proposal, policy=policy)
            if evaluation["can_execute"]:
                best = proposal, evaluation
                break
    if best is None:
        return {
            "changed": False,
            "message": (
                "The other front office could not construct a legal counter it "
                "would accept from your available assets."
            ),
            "packages": [_package_dict(item) for item in packages],
            "evaluation": current,
        }
    proposal, evaluation = best
    return {
        "changed": True,
        "message": "The other front office returned its minimum acceptable construction.",
        "packages": [_package_dict(item) for item in proposal],
        "evaluation": evaluation,
        "summary": _trade_summary(state, proposal),
    }


def _offers_for_fixed_package(
    state: "LeagueState",
    *,
    fixed: TradeTeamPackage,
    counterparty_team: str,
    policy: TradeRulePolicy,
    objective: str,
    limit: int,
) -> list[tuple[tuple[TradeTeamPackage, TradeTeamPackage], dict[str, object]]]:
    candidates = _candidate_packages(
        state,
        team=counterparty_team,
        receiving_team=fixed.team,
        exclude_players=set(),
        exclude_assets=set(),
        objective=objective,
    )
    fixed_reference = _package_value_for_team(state, fixed, team=counterparty_team)
    candidates.sort(
        key=lambda package: (
            abs(_package_value_for_team(state, package, team=fixed.team) - fixed_reference),
            len(package.player_ids) + len(package.asset_ids),
            _package_signature(package),
        )
    )
    accepted: list[tuple[tuple[TradeTeamPackage, TradeTeamPackage], dict[str, object]]] = []
    for candidate in candidates[:48]:
        proposal = (fixed, candidate)
        evaluation = evaluate_trade(state, proposal, policy=policy)
        if evaluation["can_execute"]:
            accepted.append((proposal, evaluation))
            if len(accepted) >= limit:
                break
    return accepted


def _candidate_packages(
    state: "LeagueState",
    *,
    team: str,
    receiving_team: str,
    exclude_players: set[int],
    exclude_assets: set[str],
    objective: str,
) -> list[TradeTeamPackage]:
    profile = front_office_profile(state, team)
    players = [item for item in state.roster(team) if item.player_id not in exclude_players]
    players.sort(
        key=lambda item: (
            0 if item.player_id in profile.trade_block_player_ids else 1,
            abs(player_trade_value(state, item.player_id, receiving_team=receiving_team) - 28),
            item.player_id,
        )
    )
    market_players = players[:7]
    highest_value = sorted(
        players,
        key=lambda item: (
            -player_trade_value(state, item.player_id, receiving_team=receiving_team),
            item.player_id,
        ),
    )[:5]
    players = list({
        item.player_id: item for item in (*highest_value, *market_players)
    }.values())[:10]
    assets = [
        item for item in state.draft_assets
        if item.current_team == team
        and item.asset_id not in exclude_assets
        and _draft_asset_is_available(state, item)
    ]
    assets.sort(
        key=lambda item: (
            0 if (objective == "draft_capital" and item.round == 1) else 1,
            item.draft_year,
            item.round,
            item.asset_id,
        )
    )
    assets = assets[:8]
    packages: list[TradeTeamPackage] = []
    packages.extend(TradeTeamPackage(team, (player.player_id,), ()) for player in players)
    packages.extend(TradeTeamPackage(team, (), (asset.asset_id,)) for asset in assets)
    packages.extend(
        TradeTeamPackage(team, (player.player_id,), (asset.asset_id,))
        for player in players[:7]
        for asset in assets[:5]
    )
    packages.extend(
        TradeTeamPackage(team, tuple(item.player_id for item in pair), ())
        for pair in combinations(players[:6], 2)
    )
    packages.extend(
        TradeTeamPackage(team, tuple(item.player_id for item in group), ())
        for group in combinations(players[:6], 3)
    )
    firsts = [item for item in assets if item.round == 1][:4]
    seconds = [item for item in assets if item.round == 2][:4]
    packages.extend(
        TradeTeamPackage(team, (), (first.asset_id, second.asset_id))
        for first in firsts
        for second in seconds
    )
    packages.extend(
        TradeTeamPackage(
            team,
            tuple(item.player_id for item in pair),
            (asset.asset_id,),
        )
        for pair in combinations(players[:6], 2)
        for asset in assets[:4]
    )
    packages.extend(
        TradeTeamPackage(
            team,
            (player.player_id,),
            tuple(item.asset_id for item in pair),
        )
        for player in players[:6]
        for pair in combinations(assets[:6], 2)
    )
    packages.extend(
        TradeTeamPackage(team, (), tuple(item.asset_id for item in group))
        for size in (3, 4)
        for group in combinations(assets[:8], size)
    )
    unique: dict[str, TradeTeamPackage] = {}
    for package in packages:
        unique.setdefault(_package_signature(package), package)
    return sorted(
        unique.values(),
        key=lambda package: (
            _objective_package_sort(state, package, objective),
            _package_signature(package),
        ),
    )


def _package_for_assets(
    state: "LeagueState",
    *,
    player_ids: Sequence[int],
    asset_ids: Sequence[str],
) -> TradeTeamPackage:
    player_ids = tuple(dict.fromkeys(int(item) for item in player_ids))
    asset_ids = tuple(dict.fromkeys(str(item) for item in asset_ids))
    if not player_ids and not asset_ids:
        raise ValueError("choose at least one player or draft asset")
    if len(player_ids) + len(asset_ids) > 6:
        raise ValueError("Trade Finder supports up to six assets in one package")
    players = []
    for player_id in player_ids:
        player = next(
            (item for item in state.players if item.player_id == player_id and item.roster_status == "active"),
            None,
        )
        if player is None:
            raise ValueError("trade finder player is not active")
        players.append(player)
    assets = []
    for asset_id in asset_ids:
        asset = next((item for item in state.draft_assets if item.asset_id == asset_id), None)
        if asset is None or not _draft_asset_is_available(state, asset):
            raise ValueError("trade finder draft asset is unavailable")
        assets.append(asset)
    owners = {item.team for item in players} | {item.current_team for item in assets}
    if len(owners) != 1:
        raise ValueError("every asset in a Trade Finder package must have the same owner")
    return TradeTeamPackage(next(iter(owners)), player_ids, asset_ids)


def _package_for_asset(
    state: "LeagueState",
    *,
    player_id: int | None,
    asset_id: str | None,
) -> TradeTeamPackage:
    return _package_for_assets(
        state,
        player_ids=(() if player_id is None else (player_id,)),
        asset_ids=(() if asset_id is None else (asset_id,)),
    )


def _package_value_for_team(
    state: "LeagueState",
    package: TradeTeamPackage,
    *,
    team: str,
) -> float:
    assets = {item.asset_id: item for item in state.draft_assets}
    player_values = sorted((
        player_trade_value(state, player_id, receiving_team=team)
        for player_id in package.player_ids
    ), reverse=True)
    player_weights = (1.0, 0.84, 0.68, 0.54, 0.45, 0.38)
    player_total = sum(
        value * player_weights[min(index, len(player_weights) - 1)]
        for index, value in enumerate(player_values)
    )
    pick_values = sorted((
        draft_asset_value_for_team(state, assets[asset_id], team=team)
        for asset_id in package.asset_ids if asset_id in assets
    ), reverse=True)
    pick_total = sum(
        value * max(0.76, 1.0 - index * 0.06)
        for index, value in enumerate(pick_values)
    )
    return player_total + pick_total


def _objective_package_sort(
    state: "LeagueState",
    package: TradeTeamPackage,
    objective: str,
) -> float:
    lifecycle = {item.player_id: item for item in state.player_lifecycles}
    salary = sum(player_cap_charge(state, item)[0] for item in package.player_ids)
    if objective == "win_now":
        return -sum(lifecycle[item].overall for item in package.player_ids if item in lifecycle)
    if objective == "youth":
        return sum(
            lifecycle[item].age if item in lifecycle and lifecycle[item].age is not None else 27
            for item in package.player_ids
        ) - 4 * len(package.asset_ids)
    if objective == "cap_relief":
        return salary
    if objective == "draft_capital":
        return -10 * len(package.asset_ids) - len(package.player_ids)
    return len(package.player_ids) + len(package.asset_ids)


def _trade_offer_response(
    state: "LeagueState",
    *,
    packages: tuple[TradeTeamPackage, TradeTeamPackage],
    evaluation: Mapping[str, object],
    objective: str,
    mode: str,
) -> dict[str, object]:
    team_results = evaluation["teams"]
    assert isinstance(team_results, list)
    user_result = next(item for item in team_results if item["team"] == state.user_team)
    cpu_result = next(item for item in team_results if item["team"] != state.user_team)
    partner = str(cpu_result["team"])
    user_package = next(item for item in packages if item.team == state.user_team)
    cpu_package = next(item for item in packages if item.team == partner)
    incoming = _package_value_for_team(state, cpu_package, team=state.user_team)
    outgoing = _package_value_for_team(state, user_package, team=state.user_team)
    fairness = 100 - min(45, abs(incoming - outgoing) * 1.4)
    objective_bonus = _finder_objective_bonus(state, cpu_package, objective)
    finder_score = fairness + objective_bonus + float(cpu_result["value_delta"]) * 0.08
    signature = "|".join(sorted(_package_signature(item) for item in packages))
    return {
        "offer_id": hashlib.sha256(signature.encode()).hexdigest()[:14],
        "signature": signature,
        "partner": partner,
        "mode": mode,
        "objective": objective,
        "finder_score": round(finder_score, 3),
        "fairness": round(fairness, 1),
        "headline": f"{partner} is ready to deal",
        "summary": _trade_summary(state, packages),
        "you_send": _describe_package(state, user_package),
        "you_receive": _describe_package(state, cpu_package),
        "packages": [_package_dict(item) for item in packages],
        "evaluation": evaluation,
        "why_it_works": list(cpu_result.get("decision_factors", [])),
        "partner_plan": cpu_result.get("front_office", {}),
        "user_value_delta": round(float(user_result["value_delta"]), 2),
    }


def _finder_objective_bonus(
    state: "LeagueState",
    incoming: TradeTeamPackage,
    objective: str,
) -> float:
    lifecycle = {item.player_id: item for item in state.player_lifecycles}
    if objective == "win_now":
        return sum(max(0, lifecycle[item].overall - 76) for item in incoming.player_ids if item in lifecycle) * 0.8
    if objective == "youth":
        return sum(max(0, 26 - (lifecycle[item].age or 27)) for item in incoming.player_ids if item in lifecycle) * 0.7
    if objective == "cap_relief":
        return -sum(player_cap_charge(state, item)[0] for item in incoming.player_ids) / 8_000_000
    if objective == "draft_capital":
        return 5.0 * len(incoming.asset_ids)
    return 0.0


def _describe_package(state: "LeagueState", package: TradeTeamPackage) -> list[dict[str, object]]:
    players = {item.player_id: item for item in state.players}
    assets = {item.asset_id: item for item in state.draft_assets}
    lifecycle = {item.player_id: item for item in state.player_lifecycles}
    result: list[dict[str, object]] = []
    for player_id in package.player_ids:
        player = players[player_id]
        life = lifecycle.get(player_id)
        salary, source = player_cap_charge(state, player_id)
        result.append({
            "type": "player", "id": player_id, "name": player.name,
            "position": player.position,
            "overall": round(life.overall, 1) if life else None,
            "age": round(life.age, 1) if life and life.age is not None else None,
            "salary": salary, "salary_source": source,
        })
    for asset_id in package.asset_ids:
        asset = assets[asset_id]
        result.append({
            "type": "pick", "id": asset.asset_id,
            "name": f"{asset.draft_year} round {asset.round} ({asset.original_team})",
            "protection": asset.protection or "Unprotected",
        })
    return result


def _trade_summary(
    state: "LeagueState",
    packages: tuple[TradeTeamPackage, TradeTeamPackage],
) -> str:
    parts = []
    for package in packages:
        descriptions = _describe_package(state, package)
        parts.append(f"{package.team} sends {', '.join(str(item['name']) for item in descriptions)}")
    return "; ".join(parts)


def _package_dict(package: TradeTeamPackage) -> dict[str, object]:
    return {
        "team": package.team,
        "player_ids": list(package.player_ids),
        "asset_ids": list(package.asset_ids),
        "consent_player_ids": list(package.consent_player_ids),
        "player_destinations": {
            str(player_id): team for player_id, team in package.player_destinations
        },
        "asset_destinations": {
            asset_id: team for asset_id, team in package.asset_destinations
        },
    }


def _package_signature(package: TradeTeamPackage) -> str:
    return (
        f"{package.team}:p:{','.join(map(str, sorted(package.player_ids)))}:"
        f"a:{','.join(sorted(package.asset_ids))}:"
        f"pr:{','.join(f'{player_id}>{team}' for player_id, team in package.player_destinations)}:"
        f"ar:{','.join(f'{asset_id}>{team}' for asset_id, team in package.asset_destinations)}"
    )


def deterministic_trade_id(
    *,
    league_id: str,
    revision: int,
    packages: Sequence[TradeTeamPackage],
) -> str:
    encoded = "|".join(
        (
            league_id,
            str(revision),
            *(
                _package_signature(item)
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
    used_assets: set[str] = set()
    used_teams: set[str] = set()
    shuffled = list(teams)
    rng.shuffle(shuffled)
    for seller in shuffled:
        if len(proposals) >= max_deals:
            break
        if seller in used_teams:
            continue
        seller_profile = front_office_profile(state, seller)
        candidate_buyers = [
            team for team in teams
            if team != seller
            and team not in used_teams
            and (
                team_strategy(state, team) != seller_profile.strategy
                or set(front_office_profile(state, team).needs)
                != set(seller_profile.needs)
            )
        ]
        rng.shuffle(candidate_buyers)
        movable = [
            item for item in state.roster(seller)
            if item.player_id not in used_players
            and item.player_id not in seller_profile.untouchable_player_ids
        ]
        movable.sort(
            key=lambda item: (
                0 if item.player_id in seller_profile.trade_block_player_ids else 1,
                _player_base_value(state, item.player_id),
                item.player_id,
            )
        )
        for seller_player in movable[:4]:
            fixed = TradeTeamPackage(seller, (seller_player.player_id,), ())
            for buyer in candidate_buyers[:10]:
                offers = _offers_for_fixed_package(
                    state,
                    fixed=fixed,
                    counterparty_team=buyer,
                    policy=policy,
                    objective=(
                        "draft_capital"
                        if seller_profile.strategy == "rebuilding"
                        else "win_now"
                    ),
                    limit=3,
                )
                viable = [
                    item for item in offers
                    if not (
                        set(item[0][1].player_ids) & used_players
                        or set(item[0][1].asset_ids) & used_assets
                    )
                ]
                if not viable:
                    continue
                proposal, _ = viable[0]
                chance = 0.12 + policy.ai_aggressiveness * 0.88
                if float(rng.random()) > chance:
                    continue
                proposals.append(proposal)
                used_teams.update((seller, buyer))
                for package in proposal:
                    used_players.update(package.player_ids)
                    used_assets.update(package.asset_ids)
                break
            if seller in used_teams:
                break
    return tuple(proposals)
