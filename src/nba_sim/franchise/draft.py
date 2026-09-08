from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
import hashlib
from typing import Iterable, Mapping

import numpy as np

from nba_sim.franchise.cba import CBA_2026_27, rules_for_season
from nba_sim.franchise.models import (
    ContractRecord,
    ContractYear,
    DraftAssetRecord,
    PlayerHealthRecord,
    PlayerLifecycleRecord,
    PlayerRecord,
    ScoutingReportRecord,
)
from nba_sim.franchise.health import build_health_record
from nba_sim.franchise.scouting import (
    build_initial_scouting_report,
    report_summary,
    scout_player,
)
from nba_sim.randomness import RandomStreamFactory


DRAFT_MODEL_VERSION = "draft-ecosystem-calibrated.v2"
DRAFT_CLASS_SIZE = 75
_POSITIONS = ("PG", "SG", "SF", "PF", "C")
_POSITION_PROBABILITIES = (0.18, 0.20, 0.22, 0.20, 0.20)
_AGES = (18.5, 19.0, 19.5, 20.0, 21.0, 22.0, 23.0)
_AGE_PROBABILITIES = (0.11, 0.25, 0.15, 0.18, 0.18, 0.11, 0.02)
_TALENT_TIERS = (
    "generational",
    "franchise",
    "all_star",
    "starter",
    "rotation",
    "fringe",
)
_TALENT_PROBABILITIES = (0.0022, 0.012, 0.062, 0.23, 0.42, 0.2738)
_ARCHETYPES = (
    "Primary creator",
    "Movement shooter",
    "Two-way wing",
    "Rim-running big",
    "Interior hub",
    "Defensive anchor",
    "Connector",
)
_FIRST_NAMES = (
    "Malik", "Isaiah", "Jaylen", "Andre", "Cameron", "Elijah", "Miles",
    "Darius", "Jordan", "Noah", "Micah", "Julian", "Marcus", "Trey",
    "Khalil", "Luca", "Mateo", "Niko", "Amari", "Xavier", "Devin",
    "Keon", "Caleb", "Jabari", "Terrence", "Ari", "Rayan", "Jonas",
)
_LAST_NAMES = (
    "Carter", "Williams", "Okafor", "Mitchell", "Robinson", "Daniels",
    "Bennett", "Walker", "Lewis", "Reed", "Collins", "Foster", "Hayes",
    "Brooks", "Murray", "Grant", "Ellis", "Diallo", "Petrovic", "Santos",
    "Moretti", "Kovac", "Mensah", "Nwosu", "Harris", "Young", "King",
)
_PROGRAMS = (
    "Duke", "Kentucky", "Kansas", "UConn", "Baylor", "Gonzaga", "Arkansas",
    "Michigan", "Houston", "UCLA", "Texas", "Auburn", "G League Ignite",
    "France", "Spain", "Serbia", "Australia", "Canada", "Germany", "Nigeria",
)


@dataclass(frozen=True)
class DraftProspectRecord:
    player_id: int
    name: str
    position: str
    age: float
    height_inches: float
    wingspan_inches: float
    weight_pounds: int
    origin: str
    archetype: str
    consensus_rank: int
    public_score: float
    offense: float
    playmaking: float
    defense: float
    athleticism: float
    overall: float
    potential: float
    report: ScoutingReportRecord
    latent_tier: str = "unknown"
    development_variance: float = 5.5
    durability: float = 75.0

    def as_dict(self) -> dict[str, object]:
        return {
            "player_id": self.player_id,
            "name": self.name,
            "position": self.position,
            "age": round(self.age, 2),
            "height_inches": round(self.height_inches, 2),
            "wingspan_inches": round(self.wingspan_inches, 2),
            "weight_pounds": self.weight_pounds,
            "origin": self.origin,
            "archetype": self.archetype,
            "consensus_rank": self.consensus_rank,
            "public_score": round(self.public_score, 4),
            "offense": round(self.offense, 4),
            "playmaking": round(self.playmaking, 4),
            "defense": round(self.defense, 4),
            "athleticism": round(self.athleticism, 4),
            "overall": round(self.overall, 4),
            "potential": round(self.potential, 4),
            "report": self.report.as_dict(),
            "latent_tier": self.latent_tier,
            "development_variance": round(self.development_variance, 4),
            "durability": round(self.durability, 4),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "DraftProspectRecord":
        report = value.get("report")
        if not isinstance(report, Mapping):
            raise ValueError("draft prospect requires a scouting report")
        return cls(
            player_id=int(value["player_id"]),
            name=str(value["name"]),
            position=str(value["position"]),
            age=float(value["age"]),
            height_inches=float(value["height_inches"]),
            wingspan_inches=float(value["wingspan_inches"]),
            weight_pounds=int(value["weight_pounds"]),
            origin=str(value["origin"]),
            archetype=str(value["archetype"]),
            consensus_rank=int(value["consensus_rank"]),
            public_score=float(value["public_score"]),
            offense=float(value["offense"]),
            playmaking=float(value["playmaking"]),
            defense=float(value["defense"]),
            athleticism=float(value["athleticism"]),
            overall=float(value["overall"]),
            potential=float(value["potential"]),
            report=ScoutingReportRecord.from_dict(report),
            latent_tier=str(value.get("latent_tier", "unknown")),
            development_variance=float(value.get("development_variance", 5.5)),
            durability=float(value.get("durability", 75.0)),
        )

    def lifecycle(self, season: str) -> PlayerLifecycleRecord:
        return PlayerLifecycleRecord(
            player_id=self.player_id,
            as_of_season=season,
            age=self.age,
            age_source="generated-draft-class",
            stage="prospect",
            offense=self.offense,
            playmaking=self.playmaking,
            defense=self.defense,
            athleticism=self.athleticism,
            overall=self.overall,
            potential_mean=self.potential,
            potential_sd=max(2.0, self.development_variance),
            workload_minutes=0.0,
            games_played=0,
            confidence="low",
            model_version=DRAFT_MODEL_VERSION,
        )


@dataclass(frozen=True)
class DraftSlotRecord:
    overall_pick: int
    round: int
    pick_in_round: int
    original_team: str
    current_team: str
    lottery_balls: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "overall_pick": self.overall_pick,
            "round": self.round,
            "pick_in_round": self.pick_in_round,
            "original_team": self.original_team,
            "current_team": self.current_team,
            "lottery_balls": self.lottery_balls,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "DraftSlotRecord":
        return cls(
            overall_pick=int(value["overall_pick"]),
            round=int(value["round"]),
            pick_in_round=int(value["pick_in_round"]),
            original_team=str(value["original_team"]),
            current_team=str(value["current_team"]),
            lottery_balls=int(value.get("lottery_balls", 0)),
        )


@dataclass(frozen=True)
class DraftSelectionRecord:
    overall_pick: int
    team: str
    original_team: str
    player_id: int
    player_name: str
    position: str

    def as_dict(self) -> dict[str, object]:
        return {
            "overall_pick": self.overall_pick,
            "team": self.team,
            "original_team": self.original_team,
            "player_id": self.player_id,
            "player_name": self.player_name,
            "position": self.position,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "DraftSelectionRecord":
        return cls(
            overall_pick=int(value["overall_pick"]),
            team=str(value["team"]),
            original_team=str(value["original_team"]),
            player_id=int(value["player_id"]),
            player_name=str(value["player_name"]),
            position=str(value["position"]),
        )


@dataclass(frozen=True)
class DraftEcosystemRecord:
    draft_year: int
    status: str
    class_seed: int
    lottery_seed: int | None
    combine_complete: bool
    scouting_cycles: int
    prospects: tuple[DraftProspectRecord, ...]
    order: tuple[DraftSlotRecord, ...]
    selections: tuple[DraftSelectionRecord, ...]
    user_board: tuple[int, ...]
    latent_class_strength: float = 0.0
    public_class_strength: float = 70.0
    public_class_label: str = "Average class"
    model_version: str = DRAFT_MODEL_VERSION

    def as_dict(self) -> dict[str, object]:
        return {
            "draft_year": self.draft_year,
            "status": self.status,
            "class_seed": self.class_seed,
            "lottery_seed": self.lottery_seed,
            "combine_complete": self.combine_complete,
            "scouting_cycles": self.scouting_cycles,
            "prospects": [item.as_dict() for item in self.prospects],
            "order": [item.as_dict() for item in self.order],
            "selections": [item.as_dict() for item in self.selections],
            "user_board": list(self.user_board),
            "latent_class_strength": round(self.latent_class_strength, 4),
            "public_class_strength": round(self.public_class_strength, 4),
            "public_class_label": self.public_class_label,
            "model_version": self.model_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "DraftEcosystemRecord":
        return cls(
            draft_year=int(value["draft_year"]),
            status=str(value["status"]),
            class_seed=int(value["class_seed"]),
            lottery_seed=(
                int(value["lottery_seed"])
                if value.get("lottery_seed") is not None
                else None
            ),
            combine_complete=bool(value.get("combine_complete", False)),
            scouting_cycles=int(value.get("scouting_cycles", 0)),
            prospects=tuple(
                DraftProspectRecord.from_dict(item)
                for item in value.get("prospects", [])  # type: ignore[arg-type]
            ),
            order=tuple(
                DraftSlotRecord.from_dict(item)
                for item in value.get("order", [])  # type: ignore[arg-type]
            ),
            selections=tuple(
                DraftSelectionRecord.from_dict(item)
                for item in value.get("selections", [])  # type: ignore[arg-type]
            ),
            user_board=tuple(
                int(item) for item in value.get("user_board", [])  # type: ignore[arg-type]
            ),
            latent_class_strength=float(value.get("latent_class_strength", 0.0)),
            public_class_strength=float(value.get("public_class_strength", 70.0)),
            public_class_label=str(value.get("public_class_label", "Average class")),
            model_version=str(value.get("model_version", DRAFT_MODEL_VERSION)),
        )


@dataclass(frozen=True)
class DraftIntake:
    players: tuple[PlayerRecord, ...]
    lifecycles: tuple[PlayerLifecycleRecord, ...]
    health: tuple[PlayerHealthRecord, ...]
    scouting_reports: tuple[ScoutingReportRecord, ...]
    contracts: tuple[ContractRecord, ...]


def materialize_draft_intake(
    ecosystem: DraftEcosystemRecord,
    *,
    teams: Iterable[str],
    incoming_season: str,
    occurred_on: date,
) -> DraftIntake:
    if ecosystem.status != "complete" or len(ecosystem.selections) != 60:
        raise ValueError("draft intake requires all 60 selections")
    normalized_teams = tuple(sorted(set(item.upper() for item in teams)))
    if len(normalized_teams) != 30:
        raise ValueError("draft intake requires all 30 teams")
    selected = {item.player_id: item for item in ecosystem.selections}
    players: list[PlayerRecord] = []
    lifecycles: list[PlayerLifecycleRecord] = []
    health: list[PlayerHealthRecord] = []
    reports: list[ScoutingReportRecord] = []
    contracts: list[ContractRecord] = []
    for prospect in ecosystem.prospects:
        selection = selected.get(prospect.player_id)
        if selection is not None:
            team = selection.team
            roster_status = "active"
            expected_minutes = _rookie_role_minutes(
                selection.overall_pick,
                prospect.overall,
            )
        else:
            digest = hashlib.sha256(
                f"{ecosystem.class_seed}:undrafted:{prospect.player_id}".encode()
            ).digest()
            team = normalized_teams[int.from_bytes(digest[:2], "big") % 30]
            roster_status = "free_agent"
            expected_minutes = 0.0
        player = PlayerRecord(
            player_id=prospect.player_id,
            name=prospect.name,
            team=team,
            position=prospect.position,
            roster_status=roster_status,
            expected_minutes=expected_minutes,
            profile_source=(
                f"generated-draft-{ecosystem.draft_year}:"
                f"{prospect.archetype.lower().replace(' ', '-')}"
            ),
        )
        lifecycle = prospect.lifecycle(incoming_season)
        players.append(player)
        lifecycles.append(lifecycle)
        health.append(build_health_record(player, lifecycle=lifecycle, as_of=occurred_on))
        reports.append(prospect.report)
        if selection is not None:
            contracts.append(_rookie_contract(
                player,
                pick=selection.overall_pick,
                season=incoming_season,
                signed_on=occurred_on,
                draft_year=ecosystem.draft_year,
            ))
    return DraftIntake(
        players=tuple(players),
        lifecycles=tuple(lifecycles),
        health=tuple(health),
        scouting_reports=tuple(reports),
        contracts=tuple(contracts),
    )


def generate_draft_ecosystem(
    *,
    teams: Iterable[str],
    draft_year: int,
    season: str,
    seed: int,
    as_of: date,
) -> tuple[DraftEcosystemRecord, tuple[DraftAssetRecord, ...]]:
    normalized_teams = tuple(sorted(set(team.upper() for team in teams)))
    rng = RandomStreamFactory(seed).generator(f"draft-class:{draft_year}")
    class_shift = float(rng.normal(0.0, 1.65))
    if float(rng.random()) < 0.045:
        class_shift += float(rng.normal(0.0, 2.8))
    class_shift = _clip(class_shift, -5.0, 5.0)
    raw: list[DraftProspectRecord] = []
    used_names: set[str] = set()
    for index in range(DRAFT_CLASS_SIZE):
        position = str(rng.choice(_POSITIONS, p=_POSITION_PROBABILITIES))
        archetype = str(rng.choice(_ARCHETYPES))
        name = _unique_name(rng, used_names)
        age = float(rng.choice(_AGES, p=_AGE_PROBABILITIES))
        latent_tier = str(rng.choice(_TALENT_TIERS, p=_TALENT_PROBABILITIES))
        base, ceiling = _talent_baseline(
            latent_tier,
            class_shift=class_shift,
            rng=rng,
        )
        traits = _prospect_traits(
            base=base,
            archetype=archetype,
            position=position,
            rng=rng,
        )
        overall = _weighted_overall(traits)
        age_upside = max(0.0, 21.5 - age) * 0.7
        potential = _clip(
            ceiling + age_upside + float(rng.normal(0.0, 1.8)),
            overall,
            99.0,
        )
        development_variance = _clip(
            3.2
            + (23.0 - age) * 0.48
            + float(rng.gamma(1.5, 0.8)),
            3.0,
            10.5,
        )
        durability = _clip(52.0 + 47.0 * float(rng.beta(4.7, 1.8)), 45.0, 99.0)
        public_score = (
            0.64 * overall
            + 0.36 * potential
            + float(rng.normal(0, 4.4))
        )
        player_id = 9_000_000 + draft_year * 100 + index
        player = PlayerRecord(
            player_id=player_id,
            name=name,
            team=normalized_teams[0],
            position=position,
            roster_status="prospect",
            expected_minutes=0.0,
            profile_source="draft-public-prior",
        )
        lifecycle = PlayerLifecycleRecord(
            player_id=player_id,
            as_of_season=season,
            age=age,
            age_source="generated-draft-class",
            stage="prospect",
            offense=traits["offense"],
            playmaking=traits["playmaking"],
            defense=traits["defense"],
            athleticism=traits["athleticism"],
            overall=overall,
            potential_mean=potential,
            potential_sd=development_variance,
            workload_minutes=0.0,
            games_played=0,
            confidence="low",
            model_version=DRAFT_MODEL_VERSION,
        )
        report = build_initial_scouting_report(
            player,
            lifecycle,
            as_of=as_of,
            seed=seed,
        )
        height = _height_for_position(position, rng)
        raw.append(
            DraftProspectRecord(
                player_id=player_id,
                name=name,
                position=position,
                age=age,
                height_inches=height,
                wingspan_inches=height + float(rng.normal(4.2, 2.0)),
                weight_pounds=int(round(_weight_for_position(position, rng))),
                origin=str(rng.choice(_PROGRAMS)),
                archetype=archetype,
                consensus_rank=0,
                public_score=public_score,
                offense=traits["offense"],
                playmaking=traits["playmaking"],
                defense=traits["defense"],
                athleticism=traits["athleticism"],
                overall=overall,
                potential=potential,
                report=report,
                latent_tier=latent_tier,
                development_variance=development_variance,
                durability=durability,
            )
        )
    consensus = sorted(raw, key=lambda item: (-item.public_score, item.player_id))
    ranks = {item.player_id: rank for rank, item in enumerate(consensus, 1)}
    prospects = tuple(
        replace(item, consensus_rank=ranks[item.player_id])
        for item in raw
    )
    public_top = sorted((item.public_score for item in raw), reverse=True)[:30]
    public_strength = float(np.mean(public_top)) if public_top else 70.0
    assets = tuple(
        DraftAssetRecord(
            asset_id=f"{draft_year}-r{round_number}-{team}",
            original_team=team,
            current_team=team,
            draft_year=draft_year,
            round=round_number,
            protection=None,
            source="league-draft-rights",
        )
        for round_number in (1, 2)
        for team in normalized_teams
    )
    return (
        DraftEcosystemRecord(
            draft_year=draft_year,
            status="class_ready",
            class_seed=seed,
            lottery_seed=None,
            combine_complete=False,
            scouting_cycles=0,
            prospects=prospects,
            order=(),
            selections=(),
            user_board=tuple(item.player_id for item in consensus),
            latent_class_strength=class_shift,
            public_class_strength=public_strength,
            public_class_label=_class_label(public_strength),
        ),
        assets,
    )


def run_321_lottery(
    ecosystem: DraftEcosystemRecord,
    *,
    team_strengths: Mapping[str, float],
    assets: Iterable[DraftAssetRecord],
    seed: int,
) -> DraftEcosystemRecord:
    if ecosystem.order:
        raise ValueError("draft lottery has already been completed")
    teams = tuple(
        sorted(team_strengths, key=lambda team: (team_strengths[team], team))
    )
    if len(teams) != 30:
        raise ValueError("draft lottery requires all 30 teams")
    lottery = list(teams[:16])
    balls = {
        team: 2 if index < 3 else 3 if index < 10 else 2 if index < 14 else 1
        for index, team in enumerate(lottery)
    }
    rng = RandomStreamFactory(seed).generator(
        f"draft-lottery:{ecosystem.draft_year}"
    )
    drawn: list[str] = []
    remaining = list(lottery)
    while remaining:
        weights = np.asarray([balls[team] for team in remaining], dtype=float)
        chosen_index = int(rng.choice(len(remaining), p=weights / weights.sum()))
        drawn.append(remaining.pop(chosen_index))
    # The three draft-relegated teams retain the official No. 12 pick floor.
    # Project the unconstrained weighted drawing onto the nearest legal top 12
    # while preserving the original relative draw order inside both groups.
    original_position = {team: position for position, team in enumerate(drawn)}
    top_twelve = set(drawn[:12])
    relegated = set(teams[:3])
    for missing_team in sorted(
        relegated - top_twelve,
        key=original_position.__getitem__,
    ):
        displaced = max(
            top_twelve - relegated,
            key=original_position.__getitem__,
        )
        top_twelve.remove(displaced)
        top_twelve.add(missing_team)
    drawn = sorted(top_twelve, key=original_position.__getitem__) + sorted(
        set(drawn) - top_twelve,
        key=original_position.__getitem__,
    )
    first_round = drawn + list(teams[16:])
    owner = {
        (item.round, item.original_team): item.current_team
        for item in assets
        if item.draft_year == ecosystem.draft_year
    }
    order = []
    for round_number, ordered_teams in (
        (1, first_round),
        (2, list(teams)),
    ):
        for pick_in_round, original_team in enumerate(ordered_teams, 1):
            order.append(
                DraftSlotRecord(
                    overall_pick=(round_number - 1) * 30 + pick_in_round,
                    round=round_number,
                    pick_in_round=pick_in_round,
                    original_team=original_team,
                    current_team=owner.get(
                        (round_number, original_team),
                        original_team,
                    ),
                    lottery_balls=(
                        balls.get(original_team, 0)
                        if round_number == 1
                        else 0
                    ),
                )
            )
    return replace(
        ecosystem,
        status="lottery_complete",
        lottery_seed=seed,
        order=tuple(order),
    )


def scout_prospect(
    ecosystem: DraftEcosystemRecord,
    *,
    player_id: int,
    hours: float,
    evaluation_quality: float,
    occurred_on: date,
    seed: int,
    namespace: str,
) -> DraftEcosystemRecord:
    prospect = _prospect(ecosystem, player_id)
    report = scout_player(
        prospect.report,
        prospect.lifecycle(str(ecosystem.draft_year)),
        hours=hours,
        evaluation_quality=evaluation_quality,
        occurred_on=occurred_on,
        seed=seed,
        namespace=namespace,
    )
    return replace(
        ecosystem,
        prospects=tuple(
            replace(item, report=report)
            if item.player_id == player_id
            else item
            for item in ecosystem.prospects
        ),
    )


def run_draft_combine(
    ecosystem: DraftEcosystemRecord,
    *,
    occurred_on: date,
    seed: int,
) -> DraftEcosystemRecord:
    if ecosystem.combine_complete:
        raise ValueError("draft combine is already complete")
    updated = ecosystem
    for prospect in ecosystem.prospects:
        updated = scout_prospect(
            updated,
            player_id=prospect.player_id,
            hours=4,
            evaluation_quality=72,
            occurred_on=occurred_on,
            seed=seed,
            namespace=f"combine:{ecosystem.draft_year}:{prospect.player_id}",
        )
    return replace(updated, combine_complete=True)


def set_user_board(
    ecosystem: DraftEcosystemRecord,
    player_ids: Iterable[int],
) -> DraftEcosystemRecord:
    available = {item.player_id for item in ecosystem.prospects}
    ordered = tuple(dict.fromkeys(int(item) for item in player_ids))
    if set(ordered) != available or len(ordered) != len(available):
        raise ValueError("draft board must rank every prospect exactly once")
    return replace(ecosystem, user_board=ordered)


def make_next_pick(
    ecosystem: DraftEcosystemRecord,
    *,
    user_team: str,
    player_id: int | None,
    seed: int,
    team_scouting_quality: Mapping[str, float] | None = None,
    team_position_needs: Mapping[str, Mapping[str, float]] | None = None,
    team_risk_tolerance: Mapping[str, str] | None = None,
) -> DraftEcosystemRecord:
    if not ecosystem.order:
        raise ValueError("run the draft lottery before making selections")
    if len(ecosystem.selections) >= len(ecosystem.order):
        raise ValueError("the draft is complete")
    slot = ecosystem.order[len(ecosystem.selections)]
    selected_ids = {item.player_id for item in ecosystem.selections}
    available = [
        item for item in ecosystem.prospects
        if item.player_id not in selected_ids
    ]
    if slot.current_team == user_team:
        if player_id is None:
            raise ValueError("select a prospect for your pick")
        prospect = next(
            (item for item in available if item.player_id == player_id),
            None,
        )
        if prospect is None:
            raise ValueError("selected prospect is no longer available")
    else:
        prospect = max(
            available,
            key=lambda item: _cpu_draft_score(
                item,
                team=slot.current_team,
                pick=slot.overall_pick,
                seed=seed,
                evaluation_quality=(team_scouting_quality or {}).get(
                    slot.current_team,
                    55.0,
                ),
                position_need=(team_position_needs or {}).get(
                    slot.current_team,
                    {},
                ).get(item.position, 0.0),
                risk_tolerance=(team_risk_tolerance or {}).get(
                    slot.current_team,
                    "balanced",
                ),
            ),
        )
    selection = DraftSelectionRecord(
        overall_pick=slot.overall_pick,
        team=slot.current_team,
        original_team=slot.original_team,
        player_id=prospect.player_id,
        player_name=prospect.name,
        position=prospect.position,
    )
    selections = (*ecosystem.selections, selection)
    status = "complete" if len(selections) == len(ecosystem.order) else "in_progress"
    return replace(ecosystem, selections=selections, status=status)


def draft_response(
    ecosystem: DraftEcosystemRecord,
    *,
    user_team: str,
) -> dict[str, object]:
    selected = {item.player_id: item for item in ecosystem.selections}
    board_rank = {
        player_id: rank
        for rank, player_id in enumerate(ecosystem.user_board, 1)
    }
    prospects = []
    for item in sorted(
        ecosystem.prospects,
        key=lambda prospect: board_rank.get(prospect.player_id, 999),
    ):
        report = report_summary(item.report)
        row = {
            **report,
            "name": item.name,
            "position": item.position,
            "age": item.age,
            "origin": item.origin,
            "archetype": item.archetype,
            "consensus_rank": item.consensus_rank,
            "board_rank": board_rank.get(item.player_id),
            "height_inches": (
                item.height_inches if ecosystem.combine_complete else None
            ),
            "wingspan_inches": (
                item.wingspan_inches if ecosystem.combine_complete else None
            ),
            "weight_pounds": (
                item.weight_pounds if ecosystem.combine_complete else None
            ),
            "drafted": item.player_id in selected,
            "selection": (
                selected[item.player_id].as_dict()
                if item.player_id in selected
                else None
            ),
        }
        prospects.append(row)
    next_slot = (
        ecosystem.order[len(ecosystem.selections)].as_dict()
        if ecosystem.order
        and len(ecosystem.selections) < len(ecosystem.order)
        else None
    )
    return {
        "ready": True,
        "draft_year": ecosystem.draft_year,
        "status": ecosystem.status,
        "combine_complete": ecosystem.combine_complete,
        "class_size": len(ecosystem.prospects),
        "class_outlook": {
            "label": ecosystem.public_class_label,
            "public_strength": round(ecosystem.public_class_strength, 2),
            "average_age": round(
                float(np.mean([item.age for item in ecosystem.prospects])), 2
            ),
            "positions": {
                position: sum(item.position == position for item in ecosystem.prospects)
                for position in _POSITIONS
            },
            "international_prospects": sum(
                item.origin in {
                    "France", "Spain", "Serbia", "Australia", "Canada",
                    "Germany", "Nigeria",
                }
                for item in ecosystem.prospects
            ),
            "interpretation": (
                "Public class strength is derived from noisy consensus information; "
                "it does not reveal hidden player ceilings or guarantee outcomes."
            ),
        },
        "prospects": prospects,
        "order": [item.as_dict() for item in ecosystem.order],
        "selections": [item.as_dict() for item in ecosystem.selections],
        "next_slot": next_slot,
        "user_on_clock": (
            next_slot is not None and next_slot["current_team"] == user_team
        ),
        "lottery": [
            {
                **item.as_dict(),
                "number_one_odds": round(item.lottery_balls / 37, 6),
            }
            for item in ecosystem.order[:16]
        ],
        "model_version": ecosystem.model_version,
    }


def _prospect_traits(
    *,
    base: float,
    archetype: str,
    position: str,
    rng: np.random.Generator,
) -> dict[str, float]:
    values = {
        "offense": base + float(rng.normal(0, 3.5)),
        "playmaking": base + float(rng.normal(-2, 4.5)),
        "defense": base + float(rng.normal(0, 4.0)),
        "athleticism": base + float(rng.normal(2, 4.0)),
    }
    boosts = {
        "Primary creator": {"offense": 5, "playmaking": 9, "defense": -3},
        "Movement shooter": {"offense": 8, "playmaking": 1, "defense": -2},
        "Two-way wing": {"offense": 3, "defense": 6, "athleticism": 3},
        "Rim-running big": {"offense": 2, "playmaking": -6, "defense": 4, "athleticism": 7},
        "Interior hub": {"offense": 5, "playmaking": 5, "athleticism": -2},
        "Defensive anchor": {"offense": -3, "playmaking": -5, "defense": 10, "athleticism": 3},
        "Connector": {"offense": 1, "playmaking": 6, "defense": 4},
    }[archetype]
    for name, value in boosts.items():
        values[name] += value
    if position == "C":
        values["playmaking"] -= 2
        values["defense"] += 2
    return {name: _clip(value, 48, 92) for name, value in values.items()}


def _talent_baseline(
    tier: str,
    *,
    class_shift: float,
    rng: np.random.Generator,
) -> tuple[float, float]:
    bands = {
        "generational": ((80.0, 84.0), (96.0, 99.0)),
        "franchise": ((76.0, 82.0), (91.0, 97.0)),
        "all_star": ((72.0, 79.0), (86.0, 94.0)),
        "starter": ((68.0, 75.0), (80.0, 89.0)),
        "rotation": ((63.0, 71.0), (72.0, 84.0)),
        "fringe": ((57.0, 67.0), (64.0, 78.0)),
    }
    base_band, ceiling_band = bands[tier]
    base = float(rng.uniform(*base_band)) + 0.34 * class_shift
    ceiling = float(rng.uniform(*ceiling_band)) + 0.52 * class_shift
    return base, ceiling


def _class_label(public_strength: float) -> str:
    if public_strength >= 82.5:
        return "Exceptional class"
    if public_strength >= 80.5:
        return "Strong class"
    if public_strength >= 78.5:
        return "Above-average class"
    if public_strength < 76.5:
        return "Weak class"
    return "Average class"


def _rookie_role_minutes(pick: int, overall: float) -> float:
    return round(_clip(23.5 - 0.23 * (pick - 1) + 0.34 * (overall - 72.0), 6.0, 28.0), 1)


def _rookie_contract(
    player: PlayerRecord,
    *,
    pick: int,
    season: str,
    signed_on: date,
    draft_year: int,
) -> ContractRecord:
    start = int(season.split("-", 1)[0])
    rookie_scale_growth = rules_for_season(season).salary_cap / CBA_2026_27.salary_cap
    if pick <= 30:
        first_salary = max(
            round(2_350_000 * rookie_scale_growth / 10_000) * 10_000,
            round(14_100_000 * rookie_scale_growth * (0.94 ** (pick - 1)) / 10_000) * 10_000,
        )
        years_count = 4
    else:
        first_salary = round(
            (2_100_000 + (60 - pick) * 25_000) * rookie_scale_growth / 10_000
        ) * 10_000
        years_count = 3
    years = []
    for offset in range(years_count):
        option = None
        if pick <= 30 and offset in {2, 3}:
            option = "team"
        elif pick > 30 and offset == 2:
            option = "team"
        years.append(ContractYear(
            season=f"{start + offset}-{str(start + offset + 1)[-2:]}",
            salary=round(first_salary * (1.05 ** offset) / 10_000) * 10_000,
            option=option,
        ))
    return ContractRecord(
        contract_id=f"rookie-{draft_year}-{pick}-{player.player_id}",
        player_id=player.player_id,
        team=player.team,
        signed_on=signed_on,
        years=tuple(years),
        status="active",
        source=f"modeled-{draft_year}-rookie-scale",
        rights="rookie",
        contract_kind="standard",
    )


def _weighted_overall(values: Mapping[str, float]) -> float:
    return _clip(
        0.38 * values["offense"]
        + 0.22 * values["playmaking"]
        + 0.28 * values["defense"]
        + 0.12 * values["athleticism"],
        48,
        92,
    )


def _cpu_draft_score(
    prospect: DraftProspectRecord,
    *,
    team: str,
    pick: int,
    seed: int,
    evaluation_quality: float,
    position_need: float,
    risk_tolerance: str,
) -> float:
    digest = hashlib.sha256(
        f"{seed}|{team}|{pick}|{prospect.player_id}".encode()
    ).digest()
    quality = _clip(evaluation_quality, 0.0, 100.0)
    noise_width = 11.0 - 0.075 * quality
    noise = (int.from_bytes(digest[:4], "big") / 2**32 - 0.5) * noise_width
    upside_weight = {
        "conservative": 0.11,
        "balanced": 0.16,
        "aggressive": 0.22,
    }.get(risk_tolerance, 0.16)
    return (
        prospect.public_score
        + upside_weight * prospect.potential
        - 0.10 * prospect.consensus_rank
        + 1.6 * _clip(position_need, 0.0, 3.0)
        + noise
    )


def _prospect(
    ecosystem: DraftEcosystemRecord,
    player_id: int,
) -> DraftProspectRecord:
    for item in ecosystem.prospects:
        if item.player_id == player_id:
            return item
    raise ValueError("unknown draft prospect")


def _unique_name(rng: np.random.Generator, used: set[str]) -> str:
    while True:
        name = f"{rng.choice(_FIRST_NAMES)} {rng.choice(_LAST_NAMES)}"
        if name not in used:
            used.add(name)
            return name


def _height_for_position(position: str, rng: np.random.Generator) -> float:
    mean = {"PG": 74.5, "SG": 77, "SF": 79, "PF": 81, "C": 83}[position]
    return _clip(float(rng.normal(mean, 1.4)), 71, 87)


def _weight_for_position(position: str, rng: np.random.Generator) -> float:
    mean = {"PG": 190, "SG": 205, "SF": 220, "PF": 235, "C": 250}[position]
    return _clip(float(rng.normal(mean, 12)), 165, 285)


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(float(value), high))


__all__ = [
    "DRAFT_MODEL_VERSION",
    "DraftEcosystemRecord",
    "DraftIntake",
    "DraftProspectRecord",
    "DraftSelectionRecord",
    "DraftSlotRecord",
    "draft_response",
    "generate_draft_ecosystem",
    "make_next_pick",
    "materialize_draft_intake",
    "run_321_lottery",
    "run_draft_combine",
    "scout_prospect",
    "set_user_board",
]
