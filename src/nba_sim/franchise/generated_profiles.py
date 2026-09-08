from __future__ import annotations

from nba_sim.domain.enums import ShotZone
from nba_sim.domain.profiles import PlayerProfile, ZoneProfile
from nba_sim.franchise.draft import DraftProspectRecord
from nba_sim.franchise.models import PlayerLifecycleRecord, PlayerRecord


def generated_player_profile(
    player: PlayerRecord,
    lifecycle: PlayerLifecycleRecord,
    prospect: DraftProspectRecord | None = None,
) -> PlayerProfile:
    """Translate persisted latent attributes into a possession-engine profile."""
    archetype = prospect.archetype if prospect is not None else _source_archetype(player)
    height = prospect.height_inches if prospect is not None else _position_height(player.position)
    offense, playmaking = lifecycle.offense, lifecycle.playmaking
    defense, athleticism = lifecycle.defense, lifecycle.athleticism
    shooter = 1.0 if archetype == "Movement shooter" else 0.0
    creator = 1.0 if archetype == "Primary creator" else 0.0
    interior = 1.0 if archetype in {"Rim-running big", "Interior hub"} else 0.0
    anchor = 1.0 if archetype == "Defensive anchor" else 0.0
    frequencies = {
        ShotZone.RESTRICTED_AREA: 0.27 + 0.16 * interior - 0.08 * shooter,
        ShotZone.PAINT_NON_RA: 0.16 + 0.08 * interior,
        ShotZone.MID_RANGE: 0.13 + 0.03 * creator,
        ShotZone.LEFT_CORNER_THREE: 0.08 + 0.02 * shooter,
        ShotZone.RIGHT_CORNER_THREE: 0.08 + 0.02 * shooter,
        ShotZone.ABOVE_BREAK_THREE: 0.28 + 0.15 * shooter - 0.10 * interior,
    }
    total = sum(frequencies.values())
    frequencies = {zone: max(0.01, value / total) for zone, value in frequencies.items()}
    shot_zones = {
        ShotZone.RESTRICTED_AREA: ZoneProfile(frequencies[ShotZone.RESTRICTED_AREA], _clip(0.49 + 0.0040 * (offense - 55) + 0.0022 * (athleticism - 55) + 0.025 * interior)),
        ShotZone.PAINT_NON_RA: ZoneProfile(frequencies[ShotZone.PAINT_NON_RA], _clip(0.35 + 0.0032 * (offense - 55) + 0.012 * interior)),
        ShotZone.MID_RANGE: ZoneProfile(frequencies[ShotZone.MID_RANGE], _clip(0.32 + 0.0031 * (offense - 55) + 0.018 * creator)),
        ShotZone.LEFT_CORNER_THREE: ZoneProfile(frequencies[ShotZone.LEFT_CORNER_THREE], _clip(0.29 + 0.0028 * (offense - 55) + 0.025 * shooter)),
        ShotZone.RIGHT_CORNER_THREE: ZoneProfile(frequencies[ShotZone.RIGHT_CORNER_THREE], _clip(0.29 + 0.0028 * (offense - 55) + 0.025 * shooter)),
        ShotZone.ABOVE_BREAK_THREE: ZoneProfile(frequencies[ShotZone.ABOVE_BREAK_THREE], _clip(0.27 + 0.0027 * (offense - 55) + 0.032 * shooter + 0.008 * creator)),
    }
    guard = player.position in {"PG", "SG"}
    big = player.position in {"PF", "C"}
    return PlayerProfile(
        player_id=player.player_id,
        name=player.name,
        team_abbreviation=player.team,
        position=player.position,
        expected_minutes=player.expected_minutes,
        usage_rate=_clip(0.13 + 0.0040 * (offense - 55) + 0.025 * creator, 0.11, 0.36),
        free_throw_probability=_clip(0.64 + 0.0035 * (offense - 55) + 0.035 * shooter, 0.55, 0.92),
        turnover_probability=_clip(0.17 - 0.0013 * (playmaking - 55) + 0.012 * creator, 0.07, 0.22),
        assist_probability=_clip(0.27 + 0.0062 * (playmaking - 55) + 0.07 * creator, 0.18, 0.78),
        shooting_foul_probability=_clip(0.08 + 0.0018 * (offense - 55) + 0.025 * interior, 0.05, 0.22),
        steal_share=_clip(0.45 + 0.018 * (defense - 55) + 0.10 * guard, 0.15, 1.9),
        block_probability=_clip(0.018 + 0.0015 * (defense - 55) + 0.018 * big + 0.025 * anchor, 0.005, 0.14),
        offensive_rebound_weight=_clip(0.55 + 0.025 * (athleticism - 55) + 0.5 * big, 0.2, 2.3),
        defensive_rebound_weight=_clip(0.8 + 0.026 * (defense - 55) + 0.55 * big, 0.3, 2.6),
        defensive_impact=_clip((defense - 67.0) / 190.0 + 0.025 * anchor, -0.08, 0.16),
        speed=_clip(0.48 + 0.0062 * (athleticism - 55) + 0.035 * guard - 0.035 * big, 0.38, 0.93),
        height_inches=height,
        shot_zones=shot_zones,
    )


def _source_archetype(player: PlayerRecord) -> str:
    marker = player.profile_source.split(":", 1)
    return marker[1].replace("-", " ").title() if len(marker) == 2 else "Connector"


def _position_height(position: str) -> float:
    return {"PG": 74.5, "SG": 77.0, "SF": 79.0, "PF": 81.0, "C": 83.0}.get(position, 78.0)


def _clip(value: float, low: float = 0.01, high: float = 0.99) -> float:
    return max(low, min(high, float(value)))
