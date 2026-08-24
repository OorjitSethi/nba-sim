from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
import hashlib
from typing import Iterable, Mapping

import numpy as np

from nba_sim.franchise.models import (
    DraftAssetRecord,
    PlayerLifecycleRecord,
    PlayerRecord,
    ScoutingReportRecord,
)
from nba_sim.franchise.scouting import (
    build_initial_scouting_report,
    report_summary,
    scout_player,
)
from nba_sim.randomness import RandomStreamFactory


DRAFT_MODEL_VERSION = "draft-ecosystem-321.v1"
DRAFT_CLASS_SIZE = 75
_POSITIONS = ("PG", "SG", "SF", "PF", "C")
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
            potential_sd=max(2.0, self.report.potential_sd),
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
            model_version=str(value.get("model_version", DRAFT_MODEL_VERSION)),
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
    raw: list[DraftProspectRecord] = []
    used_names: set[str] = set()
    for index in range(DRAFT_CLASS_SIZE):
        position = str(rng.choice(_POSITIONS))
        archetype = str(rng.choice(_ARCHETYPES))
        name = _unique_name(rng, used_names)
        age = float(rng.choice((18.5, 19.0, 19.5, 20.0, 21.0, 22.0)))
        base = 64.0 + 19.0 * float(rng.beta(2.0, 4.7))
        if index == 0:
            base = max(base, 81.5 + float(rng.normal(0, 1.0)))
        traits = _prospect_traits(
            base=base,
            archetype=archetype,
            position=position,
            rng=rng,
        )
        overall = _weighted_overall(traits)
        upside = max(1.0, (23.5 - age) * 1.7 + float(rng.normal(2.5, 2.7)))
        potential = _clip(overall + upside, overall, 97.0)
        public_score = (
            0.68 * overall
            + 0.32 * potential
            + float(rng.normal(0, 3.6))
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
            potential_sd=5.5,
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
            )
        )
    consensus = sorted(raw, key=lambda item: (-item.public_score, item.player_id))
    ranks = {item.player_id: rank for rank, item in enumerate(consensus, 1)}
    prospects = tuple(
        replace(item, consensus_rank=ranks[item.player_id])
        for item in raw
    )
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
) -> float:
    digest = hashlib.sha256(
        f"{seed}|{team}|{pick}|{prospect.player_id}".encode()
    ).digest()
    noise = (int.from_bytes(digest[:4], "big") / 2**32 - 0.5) * 7.0
    return (
        prospect.public_score
        + 0.16 * prospect.potential
        - 0.10 * prospect.consensus_rank
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
    "DraftProspectRecord",
    "DraftSelectionRecord",
    "DraftSlotRecord",
    "draft_response",
    "generate_draft_ecosystem",
    "make_next_pick",
    "run_321_lottery",
    "run_draft_combine",
    "scout_prospect",
    "set_user_board",
]
