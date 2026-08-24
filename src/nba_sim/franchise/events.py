from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from typing import Mapping


class LeagueEventType(str, Enum):
    LEAGUE_CREATED = "league_created"
    BRANCH_CREATED = "branch_created"
    DATE_ADVANCED = "date_advanced"
    STAFF_REGISTERED = "staff_registered"
    CONTRACT_REGISTERED = "contract_registered"
    DRAFT_ASSET_REGISTERED = "draft_asset_registered"
    CAP_EXCEPTION_REGISTERED = "cap_exception_registered"
    INJURY_RECORDED = "injury_recorded"
    TRANSACTION_RECORDED = "transaction_recorded"
    PLAYER_LIFECYCLES_INITIALIZED = "player_lifecycles_initialized"
    PLAYER_HEALTH_INITIALIZED = "player_health_initialized"
    PLAYER_HEALTH_UPDATED = "player_health_updated"
    PLAYER_WORKLOAD_RECORDED = "player_workload_recorded"
    TEAM_ENVIRONMENT_INITIALIZED = "team_environment_initialized"
    TEAM_CHEMISTRY_UPDATED = "team_chemistry_updated"
    COACHING_PROFILE_UPDATED = "coaching_profile_updated"
    CHEMISTRY_SESSION_RECORDED = "chemistry_session_recorded"
    SCOUTING_INITIALIZED = "scouting_initialized"
    SCOUTING_REPORT_UPDATED = "scouting_report_updated"
    SCOUTING_DEPARTMENT_UPDATED = "scouting_department_updated"
    SCOUTING_CYCLE_COMPLETED = "scouting_cycle_completed"
    DRAFT_ECOSYSTEM_INITIALIZED = "draft_ecosystem_initialized"
    DRAFT_LOTTERY_COMPLETED = "draft_lottery_completed"
    DRAFT_COMBINE_COMPLETED = "draft_combine_completed"
    DRAFT_PROSPECT_SCOUTED = "draft_prospect_scouted"
    DRAFT_BOARD_UPDATED = "draft_board_updated"
    DRAFT_PICK_MADE = "draft_pick_made"
    TRADE_CENTER_INITIALIZED = "trade_center_initialized"
    TRADE_RULE_POLICY_UPDATED = "trade_rule_policy_updated"
    TRADE_COMPLETED = "trade_completed"


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


@dataclass(frozen=True)
class LeagueEvent:
    event_id: str
    sequence: int
    event_type: LeagueEventType
    occurred_on: date
    recorded_at: datetime
    actor: str
    payload: Mapping[str, object]
    previous_hash: str
    event_hash: str

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("event_id cannot be empty")
        if self.sequence <= 0:
            raise ValueError("event sequence must be positive")
        if self.recorded_at.tzinfo is None:
            raise ValueError("recorded_at must be timezone-aware")
        if not self.actor:
            raise ValueError("event actor cannot be empty")
        if not self.previous_hash:
            raise ValueError("previous_hash cannot be empty")
        if self.event_hash != self.calculate_hash():
            raise ValueError("league event hash is invalid")

    def hash_material(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "sequence": self.sequence,
            "event_type": self.event_type.value,
            "occurred_on": self.occurred_on.isoformat(),
            "recorded_at": self.recorded_at.astimezone(timezone.utc).isoformat(),
            "actor": self.actor,
            "payload": dict(self.payload),
            "previous_hash": self.previous_hash,
        }

    def calculate_hash(self) -> str:
        return hashlib.sha256(
            _canonical(self.hash_material()).encode("utf-8")
        ).hexdigest()

    def as_dict(self) -> dict[str, object]:
        value = self.hash_material()
        value["event_hash"] = self.event_hash
        return value

    @classmethod
    def create(
        cls,
        *,
        namespace: str,
        sequence: int,
        event_type: LeagueEventType,
        occurred_on: date,
        actor: str,
        payload: Mapping[str, object],
        previous_hash: str,
        recorded_at: datetime | None = None,
    ) -> "LeagueEvent":
        timestamp = (recorded_at or datetime.now(timezone.utc)).astimezone(
            timezone.utc
        )
        identity = {
            "namespace": namespace,
            "sequence": sequence,
            "event_type": event_type.value,
            "occurred_on": occurred_on.isoformat(),
            "actor": actor,
            "payload": dict(payload),
            "previous_hash": previous_hash,
        }
        event_id = hashlib.sha256(
            _canonical(identity).encode("utf-8")
        ).hexdigest()[:24]
        provisional = cls.__new__(cls)
        object.__setattr__(provisional, "event_id", event_id)
        object.__setattr__(provisional, "sequence", sequence)
        object.__setattr__(provisional, "event_type", event_type)
        object.__setattr__(provisional, "occurred_on", occurred_on)
        object.__setattr__(provisional, "recorded_at", timestamp)
        object.__setattr__(provisional, "actor", actor)
        object.__setattr__(provisional, "payload", dict(payload))
        object.__setattr__(provisional, "previous_hash", previous_hash)
        event_hash = provisional.calculate_hash()
        return cls(
            event_id=event_id,
            sequence=sequence,
            event_type=event_type,
            occurred_on=occurred_on,
            recorded_at=timestamp,
            actor=actor,
            payload=dict(payload),
            previous_hash=previous_hash,
            event_hash=event_hash,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "LeagueEvent":
        payload = value.get("payload", {})
        if not isinstance(payload, Mapping):
            raise ValueError("league event payload must be an object")
        return cls(
            event_id=str(value["event_id"]),
            sequence=int(value["sequence"]),
            event_type=LeagueEventType(str(value["event_type"])),
            occurred_on=date.fromisoformat(str(value["occurred_on"])),
            recorded_at=datetime.fromisoformat(str(value["recorded_at"])),
            actor=str(value["actor"]),
            payload=dict(payload),
            previous_hash=str(value["previous_hash"]),
            event_hash=str(value["event_hash"]),
        )
