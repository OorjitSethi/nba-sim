from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from typing import Mapping


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


@dataclass(frozen=True)
class LeagueCalendar:
    season: str
    cap_year_start: date
    cap_year_end: date
    regular_season_start: date
    regular_season_end: date
    current_date: date

    def __post_init__(self) -> None:
        if not (
            self.cap_year_start
            <= self.regular_season_start
            < self.regular_season_end
            <= self.cap_year_end
        ):
            raise ValueError("league calendar dates are not chronological")
        if not self.cap_year_start <= self.current_date <= self.cap_year_end:
            raise ValueError("current date must be inside the cap year")

    @property
    def phase(self) -> str:
        if self.current_date < self.regular_season_start:
            return "offseason"
        if self.current_date <= self.regular_season_end:
            return "regular_season"
        return "postseason"

    def advance_to(self, target: date) -> "LeagueCalendar":
        if target <= self.current_date:
            raise ValueError("league date must move forward")
        if target > self.cap_year_end:
            raise ValueError("league date cannot move beyond the cap year")
        return replace(self, current_date=target)

    def as_dict(self) -> dict[str, object]:
        return {
            "season": self.season,
            "cap_year_start": self.cap_year_start.isoformat(),
            "cap_year_end": self.cap_year_end.isoformat(),
            "regular_season_start": self.regular_season_start.isoformat(),
            "regular_season_end": self.regular_season_end.isoformat(),
            "current_date": self.current_date.isoformat(),
            "phase": self.phase,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "LeagueCalendar":
        return cls(
            season=str(value["season"]),
            cap_year_start=date.fromisoformat(str(value["cap_year_start"])),
            cap_year_end=date.fromisoformat(str(value["cap_year_end"])),
            regular_season_start=date.fromisoformat(
                str(value["regular_season_start"])
            ),
            regular_season_end=date.fromisoformat(
                str(value["regular_season_end"])
            ),
            current_date=date.fromisoformat(str(value["current_date"])),
        )


@dataclass(frozen=True)
class FranchiseRecord:
    team: str
    name: str
    conference: str
    division: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "team", _required(self.team, "team").upper())
        _required(self.name, "franchise name")
        _required(self.conference, "conference")
        _required(self.division, "division")

    def as_dict(self) -> dict[str, object]:
        return {
            "team": self.team,
            "name": self.name,
            "conference": self.conference,
            "division": self.division,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "FranchiseRecord":
        return cls(
            team=str(value["team"]),
            name=str(value["name"]),
            conference=str(value["conference"]),
            division=str(value["division"]),
        )


@dataclass(frozen=True)
class PlayerRecord:
    player_id: int
    name: str
    team: str
    position: str
    roster_status: str
    expected_minutes: float
    profile_source: str

    def __post_init__(self) -> None:
        if self.player_id <= 0:
            raise ValueError("player_id must be positive")
        _required(self.name, "player name")
        object.__setattr__(self, "team", _required(self.team, "team").upper())
        _required(self.roster_status, "roster status")
        _required(self.profile_source, "profile source")
        if self.expected_minutes < 0:
            raise ValueError("expected minutes cannot be negative")

    def as_dict(self) -> dict[str, object]:
        return {
            "player_id": self.player_id,
            "name": self.name,
            "team": self.team,
            "position": self.position,
            "roster_status": self.roster_status,
            "expected_minutes": round(self.expected_minutes, 3),
            "profile_source": self.profile_source,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "PlayerRecord":
        return cls(
            player_id=int(value["player_id"]),
            name=str(value["name"]),
            team=str(value["team"]),
            position=str(value.get("position", "")),
            roster_status=str(value["roster_status"]),
            expected_minutes=float(value["expected_minutes"]),
            profile_source=str(value["profile_source"]),
        )


@dataclass(frozen=True)
class PlayerLifecycleRecord:
    player_id: int
    as_of_season: str
    age: float | None
    age_source: str
    stage: str
    offense: float
    playmaking: float
    defense: float
    athleticism: float
    overall: float
    potential_mean: float
    potential_sd: float
    workload_minutes: float
    games_played: int
    confidence: str
    model_version: str

    def __post_init__(self) -> None:
        if self.player_id <= 0:
            raise ValueError("lifecycle player_id must be positive")
        _required(self.as_of_season, "lifecycle season")
        _required(self.age_source, "lifecycle age source")
        _required(self.stage, "lifecycle stage")
        _required(self.confidence, "lifecycle confidence")
        _required(self.model_version, "lifecycle model version")
        if self.age is not None and not 15 <= self.age <= 50:
            raise ValueError("lifecycle age must be between 15 and 50")
        for name in (
            "offense",
            "playmaking",
            "defense",
            "athleticism",
            "overall",
            "potential_mean",
        ):
            value = float(getattr(self, name))
            if not 0 <= value <= 100:
                raise ValueError(f"{name} must be between 0 and 100")
        if not 0 < self.potential_sd <= 25:
            raise ValueError("potential_sd must be between 0 and 25")
        if self.workload_minutes < 0 or self.games_played < 0:
            raise ValueError("lifecycle workload cannot be negative")

    def as_dict(self) -> dict[str, object]:
        return {
            "player_id": self.player_id,
            "as_of_season": self.as_of_season,
            "age": round(self.age, 2) if self.age is not None else None,
            "age_source": self.age_source,
            "stage": self.stage,
            "offense": round(self.offense, 3),
            "playmaking": round(self.playmaking, 3),
            "defense": round(self.defense, 3),
            "athleticism": round(self.athleticism, 3),
            "overall": round(self.overall, 3),
            "potential_mean": round(self.potential_mean, 3),
            "potential_sd": round(self.potential_sd, 3),
            "workload_minutes": round(self.workload_minutes, 2),
            "games_played": self.games_played,
            "confidence": self.confidence,
            "model_version": self.model_version,
        }

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, object],
    ) -> "PlayerLifecycleRecord":
        return cls(
            player_id=int(value["player_id"]),
            as_of_season=str(value["as_of_season"]),
            age=(
                float(value["age"])
                if value.get("age") is not None
                else None
            ),
            age_source=str(value["age_source"]),
            stage=str(value["stage"]),
            offense=float(value["offense"]),
            playmaking=float(value["playmaking"]),
            defense=float(value["defense"]),
            athleticism=float(value["athleticism"]),
            overall=float(value["overall"]),
            potential_mean=float(value["potential_mean"]),
            potential_sd=float(value["potential_sd"]),
            workload_minutes=float(value.get("workload_minutes", 0.0)),
            games_played=int(value.get("games_played", 0)),
            confidence=str(value["confidence"]),
            model_version=str(value["model_version"]),
        )


@dataclass(frozen=True)
class CareerDecisionRecord:
    decision_id: str
    player_id: int
    season: str
    decided_on: date
    outcome: str
    reason: str
    last_team: str
    age: float | None
    overall: float
    probability: float
    random_draw: float
    season_games: int
    season_minutes: float
    injury_burden: float
    model_version: str

    def __post_init__(self) -> None:
        _required(self.decision_id, "career decision ID")
        if self.player_id <= 0:
            raise ValueError("career decision player_id must be positive")
        _required(self.season, "career decision season")
        if self.outcome not in {
            "continued",
            "retired",
            "returned",
            "remained_retired",
        }:
            raise ValueError("invalid career decision outcome")
        _required(self.reason, "career decision reason")
        object.__setattr__(self, "last_team", _required(self.last_team, "last team").upper())
        if self.age is not None and not 15 <= self.age <= 50:
            raise ValueError("career decision age must be between 15 and 50")
        if not 0 <= self.overall <= 100:
            raise ValueError("career decision overall must be between 0 and 100")
        for name in ("probability", "random_draw", "injury_burden"):
            if not 0 <= float(getattr(self, name)) <= 1:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.season_games < 0 or self.season_minutes < 0:
            raise ValueError("career decision workload cannot be negative")
        _required(self.model_version, "career decision model version")

    def as_dict(self) -> dict[str, object]:
        return {
            "decision_id": self.decision_id,
            "player_id": self.player_id,
            "season": self.season,
            "decided_on": self.decided_on.isoformat(),
            "outcome": self.outcome,
            "reason": self.reason,
            "last_team": self.last_team,
            "age": round(self.age, 2) if self.age is not None else None,
            "overall": round(self.overall, 3),
            "probability": round(self.probability, 8),
            "random_draw": round(self.random_draw, 8),
            "season_games": self.season_games,
            "season_minutes": round(self.season_minutes, 2),
            "injury_burden": round(self.injury_burden, 6),
            "model_version": self.model_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "CareerDecisionRecord":
        return cls(
            decision_id=str(value["decision_id"]),
            player_id=int(value["player_id"]),
            season=str(value["season"]),
            decided_on=date.fromisoformat(str(value["decided_on"])),
            outcome=str(value["outcome"]),
            reason=str(value["reason"]),
            last_team=str(value["last_team"]),
            age=float(value["age"]) if value.get("age") is not None else None,
            overall=float(value["overall"]),
            probability=float(value["probability"]),
            random_draw=float(value["random_draw"]),
            season_games=int(value.get("season_games", 0)),
            season_minutes=float(value.get("season_minutes", 0.0)),
            injury_burden=float(value.get("injury_burden", 0.0)),
            model_version=str(value.get("model_version", "legacy")),
        )


@dataclass(frozen=True)
class PlayerHealthRecord:
    player_id: int
    as_of_date: date
    availability: str
    body_area: str
    detail: str
    expected_return: date | None
    minute_limit: float | None
    acute_load: float
    chronic_load: float
    fatigue: float
    readiness: float
    load_concern: float
    last_load_date: date | None
    confidence: str
    source: str
    model_version: str

    def __post_init__(self) -> None:
        if self.player_id <= 0:
            raise ValueError("health player_id must be positive")
        if self.availability not in {
            "available",
            "managed",
            "questionable",
            "doubtful",
            "out",
        }:
            raise ValueError("invalid health availability")
        if self.minute_limit is not None and not 0 <= self.minute_limit <= 48:
            raise ValueError("health minute limit must be between 0 and 48")
        for name in ("acute_load", "chronic_load"):
            if float(getattr(self, name)) < 0:
                raise ValueError(f"{name} cannot be negative")
        for name in ("fatigue", "readiness"):
            if not 0 <= float(getattr(self, name)) <= 100:
                raise ValueError(f"{name} must be between 0 and 100")
        if not 0 <= self.load_concern <= 1:
            raise ValueError("load concern must be between 0 and 1")
        _required(self.confidence, "health confidence")
        _required(self.source, "health source")
        _required(self.model_version, "health model version")

    def as_dict(self) -> dict[str, object]:
        return {
            "player_id": self.player_id,
            "as_of_date": self.as_of_date.isoformat(),
            "availability": self.availability,
            "body_area": self.body_area,
            "detail": self.detail,
            "expected_return": (
                self.expected_return.isoformat()
                if self.expected_return is not None
                else None
            ),
            "minute_limit": (
                round(self.minute_limit, 2)
                if self.minute_limit is not None
                else None
            ),
            "acute_load": round(self.acute_load, 3),
            "chronic_load": round(self.chronic_load, 3),
            "fatigue": round(self.fatigue, 3),
            "readiness": round(self.readiness, 3),
            "load_concern": round(self.load_concern, 6),
            "last_load_date": (
                self.last_load_date.isoformat()
                if self.last_load_date is not None
                else None
            ),
            "confidence": self.confidence,
            "source": self.source,
            "model_version": self.model_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "PlayerHealthRecord":
        return cls(
            player_id=int(value["player_id"]),
            as_of_date=date.fromisoformat(str(value["as_of_date"])),
            availability=str(value["availability"]),
            body_area=str(value.get("body_area", "")),
            detail=str(value.get("detail", "")),
            expected_return=(
                date.fromisoformat(str(value["expected_return"]))
                if value.get("expected_return")
                else None
            ),
            minute_limit=(
                float(value["minute_limit"])
                if value.get("minute_limit") is not None
                else None
            ),
            acute_load=float(value.get("acute_load", 0.0)),
            chronic_load=float(value.get("chronic_load", 0.0)),
            fatigue=float(value.get("fatigue", 0.0)),
            readiness=float(value.get("readiness", 100.0)),
            load_concern=float(value.get("load_concern", 0.0)),
            last_load_date=(
                date.fromisoformat(str(value["last_load_date"]))
                if value.get("last_load_date")
                else None
            ),
            confidence=str(value.get("confidence", "low")),
            source=str(value.get("source", "unknown")),
            model_version=str(value.get("model_version", "unknown")),
        )


@dataclass(frozen=True)
class TeamChemistryRecord:
    team: str
    as_of_date: date
    cohesion: float
    role_clarity: float
    trust: float
    system_familiarity: float
    morale: float
    shared_sessions: int
    confidence: str
    source: str
    model_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "team", _required(self.team, "team").upper())
        for name in (
            "cohesion",
            "role_clarity",
            "trust",
            "system_familiarity",
            "morale",
        ):
            if not 0 <= float(getattr(self, name)) <= 100:
                raise ValueError(f"{name} must be between 0 and 100")
        if self.shared_sessions < 0:
            raise ValueError("shared sessions cannot be negative")
        _required(self.confidence, "chemistry confidence")
        _required(self.source, "chemistry source")
        _required(self.model_version, "chemistry model version")

    def as_dict(self) -> dict[str, object]:
        return {
            "team": self.team,
            "as_of_date": self.as_of_date.isoformat(),
            "cohesion": round(self.cohesion, 3),
            "role_clarity": round(self.role_clarity, 3),
            "trust": round(self.trust, 3),
            "system_familiarity": round(self.system_familiarity, 3),
            "morale": round(self.morale, 3),
            "shared_sessions": self.shared_sessions,
            "confidence": self.confidence,
            "source": self.source,
            "model_version": self.model_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "TeamChemistryRecord":
        return cls(
            team=str(value["team"]),
            as_of_date=date.fromisoformat(str(value["as_of_date"])),
            cohesion=float(value["cohesion"]),
            role_clarity=float(value["role_clarity"]),
            trust=float(value["trust"]),
            system_familiarity=float(value["system_familiarity"]),
            morale=float(value["morale"]),
            shared_sessions=int(value.get("shared_sessions", 0)),
            confidence=str(value.get("confidence", "low")),
            source=str(value.get("source", "unknown")),
            model_version=str(value.get("model_version", "unknown")),
        )


@dataclass(frozen=True)
class CoachingProfileRecord:
    team: str
    as_of_date: date
    coach_name: str
    offensive_system: str
    defensive_system: str
    pace_emphasis: float
    rotation_depth: int
    development_priority: str
    adaptability: float
    confidence: str
    source: str
    model_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "team", _required(self.team, "team").upper())
        _required(self.coach_name, "coach name")
        if self.offensive_system not in {
            "balanced", "motion", "pace_space", "inside_out", "heliocentric"
        }:
            raise ValueError("invalid offensive system")
        if self.defensive_system not in {
            "balanced", "switch", "drop", "zone", "perimeter_pressure"
        }:
            raise ValueError("invalid defensive system")
        if not -1 <= self.pace_emphasis <= 1:
            raise ValueError("pace emphasis must be between -1 and 1")
        if not 8 <= self.rotation_depth <= 12:
            raise ValueError("rotation depth must be between 8 and 12")
        if self.development_priority not in {
            "balanced", "veterans", "prospects", "performance"
        }:
            raise ValueError("invalid development priority")
        if not 0 <= self.adaptability <= 100:
            raise ValueError("adaptability must be between 0 and 100")
        _required(self.confidence, "coaching confidence")
        _required(self.source, "coaching source")
        _required(self.model_version, "coaching model version")

    def as_dict(self) -> dict[str, object]:
        return {
            "team": self.team,
            "as_of_date": self.as_of_date.isoformat(),
            "coach_name": self.coach_name,
            "offensive_system": self.offensive_system,
            "defensive_system": self.defensive_system,
            "pace_emphasis": round(self.pace_emphasis, 3),
            "rotation_depth": self.rotation_depth,
            "development_priority": self.development_priority,
            "adaptability": round(self.adaptability, 3),
            "confidence": self.confidence,
            "source": self.source,
            "model_version": self.model_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "CoachingProfileRecord":
        return cls(
            team=str(value["team"]),
            as_of_date=date.fromisoformat(str(value["as_of_date"])),
            coach_name=str(value.get("coach_name", "Unassigned")),
            offensive_system=str(value.get("offensive_system", "balanced")),
            defensive_system=str(value.get("defensive_system", "balanced")),
            pace_emphasis=float(value.get("pace_emphasis", 0.0)),
            rotation_depth=int(value.get("rotation_depth", 10)),
            development_priority=str(
                value.get("development_priority", "balanced")
            ),
            adaptability=float(value.get("adaptability", 50.0)),
            confidence=str(value.get("confidence", "low")),
            source=str(value.get("source", "unknown")),
            model_version=str(value.get("model_version", "unknown")),
        )


@dataclass(frozen=True)
class ScoutingReportRecord:
    player_id: int
    as_of_date: date
    evaluations: int
    observation_hours: float
    offense_mean: float
    offense_sd: float
    playmaking_mean: float
    playmaking_sd: float
    defense_mean: float
    defense_sd: float
    athleticism_mean: float
    athleticism_sd: float
    overall_mean: float
    overall_sd: float
    potential_mean: float
    potential_sd: float
    creator_probability: float
    shooter_probability: float
    two_way_probability: float
    rim_probability: float
    connector_probability: float
    confidence: str
    source: str
    model_version: str

    def __post_init__(self) -> None:
        if self.player_id <= 0:
            raise ValueError("scouting player_id must be positive")
        if self.evaluations < 0 or self.observation_hours < 0:
            raise ValueError("scouting evidence cannot be negative")
        for name in (
            "offense_mean",
            "playmaking_mean",
            "defense_mean",
            "athleticism_mean",
            "overall_mean",
            "potential_mean",
        ):
            if not 0 <= float(getattr(self, name)) <= 100:
                raise ValueError(f"{name} must be between 0 and 100")
        for name in (
            "offense_sd",
            "playmaking_sd",
            "defense_sd",
            "athleticism_sd",
            "overall_sd",
            "potential_sd",
        ):
            if not 0 < float(getattr(self, name)) <= 25:
                raise ValueError(f"{name} must be between 0 and 25")
        probabilities = (
            self.creator_probability,
            self.shooter_probability,
            self.two_way_probability,
            self.rim_probability,
            self.connector_probability,
        )
        if any(not 0 <= value <= 1 for value in probabilities):
            raise ValueError("scouting archetype probabilities must be valid")
        if abs(sum(probabilities) - 1.0) > 0.002:
            raise ValueError("scouting archetype probabilities must sum to one")
        if self.confidence not in {"low", "moderate", "high"}:
            raise ValueError("invalid scouting confidence")
        _required(self.source, "scouting source")
        _required(self.model_version, "scouting model version")

    def as_dict(self) -> dict[str, object]:
        values: dict[str, object] = {
            "player_id": self.player_id,
            "as_of_date": self.as_of_date.isoformat(),
            "evaluations": self.evaluations,
            "observation_hours": round(float(self.observation_hours), 2),
            "confidence": self.confidence,
            "source": self.source,
            "model_version": self.model_version,
        }
        for name in (
            "offense_mean", "offense_sd", "playmaking_mean", "playmaking_sd",
            "defense_mean", "defense_sd", "athleticism_mean", "athleticism_sd",
            "overall_mean", "overall_sd", "potential_mean", "potential_sd",
            "creator_probability", "shooter_probability",
            "two_way_probability", "rim_probability",
            "connector_probability",
        ):
            values[name] = round(float(getattr(self, name)), 4)
        return values

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ScoutingReportRecord":
        return cls(
            player_id=int(value["player_id"]),
            as_of_date=date.fromisoformat(str(value["as_of_date"])),
            evaluations=int(value.get("evaluations", 0)),
            observation_hours=float(value.get("observation_hours", 0)),
            offense_mean=float(value["offense_mean"]),
            offense_sd=float(value["offense_sd"]),
            playmaking_mean=float(value["playmaking_mean"]),
            playmaking_sd=float(value["playmaking_sd"]),
            defense_mean=float(value["defense_mean"]),
            defense_sd=float(value["defense_sd"]),
            athleticism_mean=float(value["athleticism_mean"]),
            athleticism_sd=float(value["athleticism_sd"]),
            overall_mean=float(value["overall_mean"]),
            overall_sd=float(value["overall_sd"]),
            potential_mean=float(value["potential_mean"]),
            potential_sd=float(value["potential_sd"]),
            creator_probability=float(value["creator_probability"]),
            shooter_probability=float(value["shooter_probability"]),
            two_way_probability=float(value["two_way_probability"]),
            rim_probability=float(value["rim_probability"]),
            connector_probability=float(value["connector_probability"]),
            confidence=str(value["confidence"]),
            source=str(value["source"]),
            model_version=str(value["model_version"]),
        )


@dataclass(frozen=True)
class ScoutingDepartmentRecord:
    team: str
    as_of_date: date
    automation_enabled: bool
    weekly_hours: int
    evaluation_quality: float
    priority: str
    risk_tolerance: str
    cycles_completed: int
    last_cycle_date: date | None
    model_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "team", _required(self.team, "team").upper())
        if not 8 <= self.weekly_hours <= 240:
            raise ValueError("weekly scouting hours must be between 8 and 240")
        if not 0 <= self.evaluation_quality <= 100:
            raise ValueError("evaluation quality must be between 0 and 100")
        if self.priority not in {
            "balanced", "draft", "trade", "free_agency", "youth"
        }:
            raise ValueError("invalid scouting priority")
        if self.risk_tolerance not in {"cautious", "balanced", "upside"}:
            raise ValueError("invalid scouting risk tolerance")
        if self.cycles_completed < 0:
            raise ValueError("scouting cycle count cannot be negative")
        _required(self.model_version, "scouting department model version")

    def as_dict(self) -> dict[str, object]:
        return {
            "team": self.team,
            "as_of_date": self.as_of_date.isoformat(),
            "automation_enabled": self.automation_enabled,
            "weekly_hours": self.weekly_hours,
            "evaluation_quality": round(float(self.evaluation_quality), 3),
            "priority": self.priority,
            "risk_tolerance": self.risk_tolerance,
            "cycles_completed": self.cycles_completed,
            "last_cycle_date": (
                self.last_cycle_date.isoformat()
                if self.last_cycle_date is not None
                else None
            ),
            "model_version": self.model_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ScoutingDepartmentRecord":
        return cls(
            team=str(value["team"]),
            as_of_date=date.fromisoformat(str(value["as_of_date"])),
            automation_enabled=bool(value.get("automation_enabled", True)),
            weekly_hours=int(value.get("weekly_hours", 80)),
            evaluation_quality=float(value.get("evaluation_quality", 50)),
            priority=str(value.get("priority", "balanced")),
            risk_tolerance=str(value.get("risk_tolerance", "balanced")),
            cycles_completed=int(value.get("cycles_completed", 0)),
            last_cycle_date=(
                date.fromisoformat(str(value["last_cycle_date"]))
                if value.get("last_cycle_date")
                else None
            ),
            model_version=str(value.get("model_version", "unknown")),
        )


@dataclass(frozen=True)
class StaffRecord:
    staff_id: str
    name: str
    team: str
    role: str
    source: str

    def __post_init__(self) -> None:
        _required(self.staff_id, "staff_id")
        _required(self.name, "staff name")
        object.__setattr__(self, "team", _required(self.team, "team").upper())
        _required(self.role, "staff role")
        _required(self.source, "staff source")

    def as_dict(self) -> dict[str, object]:
        return {
            "staff_id": self.staff_id,
            "name": self.name,
            "team": self.team,
            "role": self.role,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "StaffRecord":
        return cls(
            staff_id=str(value["staff_id"]),
            name=str(value["name"]),
            team=str(value["team"]),
            role=str(value["role"]),
            source=str(value["source"]),
        )


@dataclass(frozen=True)
class RotationAssignmentRecord:
    player_id: int
    depth_slot: int
    role: str
    designation: str
    target_minutes: float
    starter: bool
    role_promise: str | None = None

    def __post_init__(self) -> None:
        if self.player_id <= 0:
            raise ValueError("rotation player_id must be positive")
        if not 1 <= self.depth_slot <= 30:
            raise ValueError("rotation depth_slot must be between 1 and 30")
        if self.role not in {
            "franchise", "star", "starter", "sixth", "rotation", "bench", "development"
        }:
            raise ValueError("invalid rotation role")
        if self.designation not in {"standard", "two_way", "g_league", "inactive"}:
            raise ValueError("invalid roster designation")
        if not 0 <= self.target_minutes <= 48:
            raise ValueError("rotation target minutes must be between 0 and 48")
        if self.role_promise is not None and self.role_promise not in {
            "star", "starter", "sixth", "rotation", "development"
        }:
            raise ValueError("invalid role promise")
        if self.starter and (
            self.designation in {"g_league", "inactive"} or self.target_minutes <= 0
        ):
            raise ValueError("an unavailable player cannot start")

    def as_dict(self) -> dict[str, object]:
        return {
            "player_id": self.player_id,
            "depth_slot": self.depth_slot,
            "role": self.role,
            "designation": self.designation,
            "target_minutes": round(self.target_minutes, 3),
            "starter": self.starter,
            "role_promise": self.role_promise,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "RotationAssignmentRecord":
        return cls(
            player_id=int(value["player_id"]),
            depth_slot=int(value["depth_slot"]),
            role=str(value["role"]),
            designation=str(value.get("designation", "standard")),
            target_minutes=float(value.get("target_minutes", 0)),
            starter=bool(value.get("starter", False)),
            role_promise=(str(value["role_promise"]) if value.get("role_promise") else None),
        )


@dataclass(frozen=True)
class RosterPlanRecord:
    team: str
    as_of_date: date
    delegation: str
    objective: str
    assignments: tuple[RotationAssignmentRecord, ...]
    source: str
    model_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "team", _required(self.team, "team").upper())
        if self.delegation not in {"automatic", "recommend", "manual"}:
            raise ValueError("invalid roster delegation")
        if self.objective not in {"balanced", "win_now", "development"}:
            raise ValueError("invalid roster objective")
        _required(self.source, "roster plan source")
        _required(self.model_version, "roster plan model version")
        player_ids = [item.player_id for item in self.assignments]
        if len(player_ids) != len(set(player_ids)):
            raise ValueError("roster plan contains duplicate players")
        slots = [item.depth_slot for item in self.assignments]
        if len(slots) != len(set(slots)):
            raise ValueError("roster plan contains duplicate depth slots")
        available = [
            item for item in self.assignments
            if item.designation not in {"g_league", "inactive"}
            and item.target_minutes > 0
        ]
        if len(available) >= 5 and sum(item.starter for item in available) != 5:
            raise ValueError("roster plan must identify exactly five starters")
        if available and abs(sum(item.target_minutes for item in available) - 240) > 0.2:
            raise ValueError("active rotation target minutes must total 240")
        if sum(item.designation == "two_way" for item in self.assignments) > 3:
            raise ValueError("an NBA team can carry at most three two-way players")

    def as_dict(self) -> dict[str, object]:
        return {
            "team": self.team,
            "as_of_date": self.as_of_date.isoformat(),
            "delegation": self.delegation,
            "objective": self.objective,
            "assignments": [item.as_dict() for item in self.assignments],
            "source": self.source,
            "model_version": self.model_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "RosterPlanRecord":
        return cls(
            team=str(value["team"]),
            as_of_date=date.fromisoformat(str(value["as_of_date"])),
            delegation=str(value.get("delegation", "recommend")),
            objective=str(value.get("objective", "balanced")),
            assignments=tuple(
                RotationAssignmentRecord.from_dict(item)
                for item in value.get("assignments", [])  # type: ignore[arg-type]
            ),
            source=str(value.get("source", "unknown")),
            model_version=str(value.get("model_version", "unknown")),
        )


@dataclass(frozen=True)
class GeneralManagerPlanRecord:
    team: str
    as_of_date: date
    direction: str
    strength_rank: int
    average_age: float
    target_wins: int
    evaluation_horizon: int
    automation_enabled: bool
    job_security: float
    ownership_patience: float
    budget_willingness: float
    market_size: str
    payroll_ceiling: int
    risk_tolerance: float
    win_now_weight: float
    development_weight: float
    flexibility_weight: float
    draft_weight: float
    core_player_ids: tuple[int, ...]
    trade_block_player_ids: tuple[int, ...]
    needs: tuple[str, ...]
    triggers: tuple[str, ...]
    rationale: tuple[str, ...]
    last_review_reason: str
    model_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "team", _required(self.team, "team").upper())
        if self.direction not in {"contend", "compete", "retool", "rebuild"}:
            raise ValueError("invalid general-manager direction")
        if not 1 <= self.strength_rank <= 30:
            raise ValueError("strength rank must be between 1 and 30")
        if not 15 <= self.average_age <= 45:
            raise ValueError("average age must be between 15 and 45")
        if not 0 <= self.target_wins <= 82:
            raise ValueError("target wins must be between 0 and 82")
        if not 1 <= self.evaluation_horizon <= 5:
            raise ValueError("evaluation horizon must be between 1 and 5")
        for name in (
            "job_security",
            "ownership_patience",
            "budget_willingness",
        ):
            if not 0 <= float(getattr(self, name)) <= 100:
                raise ValueError(f"{name} must be between 0 and 100")
        if self.market_size not in {"small", "medium", "large"}:
            raise ValueError("invalid market size")
        if self.payroll_ceiling <= 0:
            raise ValueError("payroll ceiling must be positive")
        if not 0 <= self.risk_tolerance <= 1:
            raise ValueError("risk tolerance must be between 0 and 1")
        priorities = (
            self.win_now_weight,
            self.development_weight,
            self.flexibility_weight,
            self.draft_weight,
        )
        if any(not 0 <= value <= 1 for value in priorities):
            raise ValueError("general-manager priorities must be between 0 and 1")
        if abs(sum(priorities) - 1.0) > 0.002:
            raise ValueError("general-manager priorities must sum to one")
        if len(self.core_player_ids) != len(set(self.core_player_ids)):
            raise ValueError("general-manager core contains duplicate players")
        if len(self.trade_block_player_ids) != len(set(self.trade_block_player_ids)):
            raise ValueError("general-manager trade block contains duplicate players")
        if set(self.core_player_ids) & set(self.trade_block_player_ids):
            raise ValueError("a player cannot be core and on the trade block")
        _required(self.last_review_reason, "general-manager review reason")
        _required(self.model_version, "general-manager model version")

    def as_dict(self) -> dict[str, object]:
        return {
            "team": self.team,
            "as_of_date": self.as_of_date.isoformat(),
            "direction": self.direction,
            "strength_rank": self.strength_rank,
            "average_age": round(self.average_age, 3),
            "target_wins": self.target_wins,
            "evaluation_horizon": self.evaluation_horizon,
            "automation_enabled": self.automation_enabled,
            "job_security": round(self.job_security, 3),
            "ownership_patience": round(self.ownership_patience, 3),
            "budget_willingness": round(self.budget_willingness, 3),
            "market_size": self.market_size,
            "payroll_ceiling": self.payroll_ceiling,
            "risk_tolerance": round(self.risk_tolerance, 5),
            "priorities": {
                "win_now": round(self.win_now_weight, 6),
                "development": round(self.development_weight, 6),
                "flexibility": round(self.flexibility_weight, 6),
                "draft_capital": round(self.draft_weight, 6),
            },
            "core_player_ids": list(self.core_player_ids),
            "trade_block_player_ids": list(self.trade_block_player_ids),
            "needs": list(self.needs),
            "triggers": list(self.triggers),
            "rationale": list(self.rationale),
            "last_review_reason": self.last_review_reason,
            "model_version": self.model_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "GeneralManagerPlanRecord":
        priorities = value.get("priorities", {})
        if not isinstance(priorities, Mapping):
            raise ValueError("general-manager priorities must be an object")
        return cls(
            team=str(value["team"]),
            as_of_date=date.fromisoformat(str(value["as_of_date"])),
            direction=str(value["direction"]),
            strength_rank=int(value["strength_rank"]),
            average_age=float(value["average_age"]),
            target_wins=int(value["target_wins"]),
            evaluation_horizon=int(value.get("evaluation_horizon", 3)),
            automation_enabled=bool(value.get("automation_enabled", True)),
            job_security=float(value["job_security"]),
            ownership_patience=float(value["ownership_patience"]),
            budget_willingness=float(value["budget_willingness"]),
            market_size=str(value["market_size"]),
            payroll_ceiling=int(value["payroll_ceiling"]),
            risk_tolerance=float(value["risk_tolerance"]),
            win_now_weight=float(priorities.get("win_now", 0.25)),
            development_weight=float(priorities.get("development", 0.25)),
            flexibility_weight=float(priorities.get("flexibility", 0.25)),
            draft_weight=float(priorities.get("draft_capital", 0.25)),
            core_player_ids=tuple(int(item) for item in value.get("core_player_ids", [])),  # type: ignore[arg-type]
            trade_block_player_ids=tuple(int(item) for item in value.get("trade_block_player_ids", [])),  # type: ignore[arg-type]
            needs=tuple(str(item) for item in value.get("needs", [])),  # type: ignore[arg-type]
            triggers=tuple(str(item) for item in value.get("triggers", [])),  # type: ignore[arg-type]
            rationale=tuple(str(item) for item in value.get("rationale", [])),  # type: ignore[arg-type]
            last_review_reason=str(value.get("last_review_reason", "league review")),
            model_version=str(value.get("model_version", "unknown")),
        )


@dataclass(frozen=True)
class FranchiseExperienceRecord:
    configured_on: date
    preset: str
    difficulty: str
    contextual_help: bool
    confirm_consequential_moves: bool
    show_advanced_by_default: bool
    onboarding_complete: bool
    model_version: str

    def __post_init__(self) -> None:
        if self.preset not in {"guided", "balanced", "full_control"}:
            raise ValueError("invalid franchise experience preset")
        if self.difficulty not in {"rookie", "pro", "expert"}:
            raise ValueError("invalid franchise difficulty")
        _required(self.model_version, "franchise experience model version")

    @property
    def negotiation_tolerance(self) -> float:
        return {"rookie": 1.18, "pro": 1.0, "expert": 0.84}[self.difficulty]

    @property
    def information_level(self) -> str:
        return {
            "rookie": "fully_explained",
            "pro": "standard",
            "expert": "front_office_fog",
        }[self.difficulty]

    def as_dict(self) -> dict[str, object]:
        return {
            "configured_on": self.configured_on.isoformat(),
            "preset": self.preset,
            "difficulty": self.difficulty,
            "contextual_help": self.contextual_help,
            "confirm_consequential_moves": self.confirm_consequential_moves,
            "show_advanced_by_default": self.show_advanced_by_default,
            "onboarding_complete": self.onboarding_complete,
            "negotiation_tolerance": self.negotiation_tolerance,
            "information_level": self.information_level,
            "ratings_modifier": 0,
            "model_version": self.model_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "FranchiseExperienceRecord":
        return cls(
            configured_on=date.fromisoformat(str(value["configured_on"])),
            preset=str(value.get("preset", "guided")),
            difficulty=str(value.get("difficulty", "pro")),
            contextual_help=bool(value.get("contextual_help", True)),
            confirm_consequential_moves=bool(
                value.get("confirm_consequential_moves", True)
            ),
            show_advanced_by_default=bool(
                value.get("show_advanced_by_default", False)
            ),
            onboarding_complete=bool(value.get("onboarding_complete", False)),
            model_version=str(value.get("model_version", "unknown")),
        )


@dataclass(frozen=True)
class ContractYear:
    season: str
    salary: int
    option: str | None = None

    def __post_init__(self) -> None:
        _required(self.season, "contract season")
        if self.salary < 0:
            raise ValueError("contract salary cannot be negative")

    def as_dict(self) -> dict[str, object]:
        return {
            "season": self.season,
            "salary": self.salary,
            "option": self.option,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ContractYear":
        return cls(
            season=str(value["season"]),
            salary=int(value["salary"]),
            option=str(value["option"]) if value.get("option") else None,
        )


@dataclass(frozen=True)
class ContractRecord:
    contract_id: str
    player_id: int
    team: str
    signed_on: date
    years: tuple[ContractYear, ...]
    status: str
    source: str
    rights: str | None = None
    contract_kind: str = "standard"

    def __post_init__(self) -> None:
        _required(self.contract_id, "contract_id")
        if self.player_id <= 0:
            raise ValueError("contract player_id must be positive")
        object.__setattr__(self, "team", _required(self.team, "team").upper())
        if not self.years:
            raise ValueError("contract must contain at least one salary year")
        _required(self.status, "contract status")
        _required(self.source, "contract source")
        _required(self.contract_kind, "contract kind")

    def as_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "contract_id": self.contract_id,
            "player_id": self.player_id,
            "team": self.team,
            "signed_on": self.signed_on.isoformat(),
            "years": [year.as_dict() for year in self.years],
            "status": self.status,
            "source": self.source,
        }
        if self.rights is not None:
            value["rights"] = self.rights
        if self.contract_kind != "standard":
            value["contract_kind"] = self.contract_kind
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ContractRecord":
        return cls(
            contract_id=str(value["contract_id"]),
            player_id=int(value["player_id"]),
            team=str(value["team"]),
            signed_on=date.fromisoformat(str(value["signed_on"])),
            years=tuple(
                ContractYear.from_dict(year)
                for year in value.get("years", [])  # type: ignore[arg-type]
            ),
            status=str(value["status"]),
            source=str(value["source"]),
            rights=str(value["rights"]) if value.get("rights") else None,
            contract_kind=str(value.get("contract_kind", "standard")),
        )


@dataclass(frozen=True)
class DraftAssetRecord:
    asset_id: str
    original_team: str
    current_team: str
    draft_year: int
    round: int
    protection: str | None
    source: str

    def __post_init__(self) -> None:
        _required(self.asset_id, "asset_id")
        object.__setattr__(
            self,
            "original_team",
            _required(self.original_team, "original team").upper(),
        )
        object.__setattr__(
            self,
            "current_team",
            _required(self.current_team, "current team").upper(),
        )
        if self.draft_year < 1947:
            raise ValueError("draft year is invalid")
        if self.round not in {1, 2}:
            raise ValueError("NBA draft assets must be round one or two")
        _required(self.source, "draft asset source")

    def as_dict(self) -> dict[str, object]:
        return {
            "asset_id": self.asset_id,
            "original_team": self.original_team,
            "current_team": self.current_team,
            "draft_year": self.draft_year,
            "round": self.round,
            "protection": self.protection,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "DraftAssetRecord":
        return cls(
            asset_id=str(value["asset_id"]),
            original_team=str(value["original_team"]),
            current_team=str(value["current_team"]),
            draft_year=int(value["draft_year"]),
            round=int(value["round"]),
            protection=(
                str(value["protection"]) if value.get("protection") else None
            ),
            source=str(value["source"]),
        )


@dataclass(frozen=True)
class CapExceptionRecord:
    exception_id: str
    team: str
    kind: str
    amount: int
    expires_on: date
    source: str

    def __post_init__(self) -> None:
        _required(self.exception_id, "exception_id")
        object.__setattr__(self, "team", _required(self.team, "team").upper())
        _required(self.kind, "exception kind")
        if self.amount < 0:
            raise ValueError("exception amount cannot be negative")
        _required(self.source, "exception source")

    def as_dict(self) -> dict[str, object]:
        return {
            "exception_id": self.exception_id,
            "team": self.team,
            "kind": self.kind,
            "amount": self.amount,
            "expires_on": self.expires_on.isoformat(),
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "CapExceptionRecord":
        return cls(
            exception_id=str(value["exception_id"]),
            team=str(value["team"]),
            kind=str(value["kind"]),
            amount=int(value["amount"]),
            expires_on=date.fromisoformat(str(value["expires_on"])),
            source=str(value["source"]),
        )


@dataclass(frozen=True)
class InjuryRecord:
    injury_id: str
    player_id: int
    team: str
    status: str
    description: str
    started_on: date
    expected_return: date | None
    source: str
    severity: str = "unknown"
    body_area: str = ""
    resolved_on: date | None = None
    games_missed: int = 0
    model_version: str = "legacy"

    def __post_init__(self) -> None:
        _required(self.injury_id, "injury_id")
        if self.player_id <= 0:
            raise ValueError("injury player_id must be positive")
        object.__setattr__(self, "team", _required(self.team, "team").upper())
        _required(self.status, "injury status")
        _required(self.source, "injury source")
        if self.status not in {
            "active", "recovering", "cleared", "unknown",
            "out", "questionable", "probable",
        }:
            raise ValueError("invalid injury status")
        if self.severity not in {
            "day_to_day", "minor", "moderate", "major", "severe", "unknown"
        }:
            raise ValueError("invalid injury severity")
        if self.games_missed < 0:
            raise ValueError("injury games missed cannot be negative")
        if self.expected_return is not None and self.expected_return < self.started_on:
            raise ValueError("expected return cannot precede injury start")
        if self.resolved_on is not None and self.resolved_on < self.started_on:
            raise ValueError("injury resolution cannot precede injury start")

    def as_dict(self) -> dict[str, object]:
        return {
            "injury_id": self.injury_id,
            "player_id": self.player_id,
            "team": self.team,
            "status": self.status,
            "description": self.description,
            "started_on": self.started_on.isoformat(),
            "expected_return": (
                self.expected_return.isoformat()
                if self.expected_return is not None
                else None
            ),
            "source": self.source,
            "severity": self.severity,
            "body_area": self.body_area,
            "resolved_on": self.resolved_on.isoformat() if self.resolved_on else None,
            "games_missed": self.games_missed,
            "model_version": self.model_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "InjuryRecord":
        return cls(
            injury_id=str(value["injury_id"]),
            player_id=int(value["player_id"]),
            team=str(value["team"]),
            status=str(value["status"]),
            description=str(value.get("description", "")),
            started_on=date.fromisoformat(str(value["started_on"])),
            expected_return=(
                date.fromisoformat(str(value["expected_return"]))
                if value.get("expected_return")
                else None
            ),
            source=str(value["source"]),
            severity=str(value.get("severity", "unknown")),
            body_area=str(value.get("body_area", "")),
            resolved_on=(
                date.fromisoformat(str(value["resolved_on"]))
                if value.get("resolved_on") else None
            ),
            games_missed=int(value.get("games_missed", 0)),
            model_version=str(value.get("model_version", "legacy")),
        )


@dataclass(frozen=True)
class TransactionRecord:
    transaction_id: str
    transaction_type: str
    occurred_on: date
    teams: tuple[str, ...]
    summary: str
    source: str
    player_ids: tuple[int, ...] = ()
    asset_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _required(self.transaction_id, "transaction_id")
        _required(self.transaction_type, "transaction type")
        if not self.teams:
            raise ValueError("transaction must involve at least one team")
        object.__setattr__(
            self,
            "teams",
            tuple(_required(team, "transaction team").upper() for team in self.teams),
        )
        _required(self.summary, "transaction summary")
        _required(self.source, "transaction source")

    def as_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "transaction_id": self.transaction_id,
            "transaction_type": self.transaction_type,
            "occurred_on": self.occurred_on.isoformat(),
            "teams": list(self.teams),
            "summary": self.summary,
            "source": self.source,
        }
        if self.player_ids:
            value["player_ids"] = list(self.player_ids)
        if self.asset_ids:
            value["asset_ids"] = list(self.asset_ids)
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "TransactionRecord":
        return cls(
            transaction_id=str(value["transaction_id"]),
            transaction_type=str(value["transaction_type"]),
            occurred_on=date.fromisoformat(str(value["occurred_on"])),
            teams=tuple(str(team) for team in value.get("teams", [])),
            summary=str(value["summary"]),
            source=str(value["source"]),
            player_ids=tuple(
                int(player_id)
                for player_id in value.get("player_ids", [])  # type: ignore[arg-type]
            ),
            asset_ids=tuple(
                str(asset_id)
                for asset_id in value.get("asset_ids", [])  # type: ignore[arg-type]
            ),
        )
