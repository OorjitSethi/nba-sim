from __future__ import annotations

from enum import Enum


class GameStatus(str, Enum):
    SCHEDULED = "scheduled"
    LIVE = "live"
    FINAL = "final"


class ShotZone(str, Enum):
    RESTRICTED_AREA = "restricted_area"
    PAINT_NON_RA = "paint_non_ra"
    MID_RANGE = "mid_range"
    LEFT_CORNER_THREE = "left_corner_three"
    RIGHT_CORNER_THREE = "right_corner_three"
    ABOVE_BREAK_THREE = "above_break_three"
    BACKCOURT = "backcourt"

    @property
    def point_value(self) -> int:
        if self in {
            ShotZone.LEFT_CORNER_THREE,
            ShotZone.RIGHT_CORNER_THREE,
            ShotZone.ABOVE_BREAK_THREE,
            ShotZone.BACKCOURT,
        }:
            return 3
        return 2


class PossessionEnd(str, Enum):
    MADE_SHOT = "made_shot"
    DEFENSIVE_REBOUND = "defensive_rebound"
    TURNOVER = "turnover"
    PERIOD_END = "period_end"
