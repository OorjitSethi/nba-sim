from __future__ import annotations

from dataclasses import dataclass


SECOND_MS = 1_000
MINUTE_MS = 60 * SECOND_MS


@dataclass(frozen=True)
class Ruleset:
    name: str
    regulation_periods: int = 4
    regulation_period_ms: int = 12 * MINUTE_MS
    overtime_period_ms: int = 5 * MINUTE_MS
    initial_shot_clock_ms: int = 24 * SECOND_MS
    offensive_rebound_shot_clock_ms: int = 14 * SECOND_MS
    final_period_seconds: int = 120
    regulation_fouls_before_penalty: int = 4
    overtime_fouls_before_penalty: int = 3
    last_two_minute_fouls_before_penalty: int = 1
    personal_foul_limit: int = 6

    def period_length_ms(self, period: int) -> int:
        if period <= 0:
            raise ValueError("period must be positive")
        if period <= self.regulation_periods:
            return self.regulation_period_ms
        return self.overtime_period_ms

    def shot_clock_after_offensive_rebound(self, game_clock_ms: int) -> int:
        return min(game_clock_ms, self.offensive_rebound_shot_clock_ms)

    def shot_clock_for_new_possession(self, game_clock_ms: int) -> int:
        return min(game_clock_ms, self.initial_shot_clock_ms)

    def in_team_foul_penalty(
        self,
        *,
        period: int,
        period_clock_ms: int,
        team_fouls_after_foul: int,
        last_two_minute_fouls_after_foul: int,
    ) -> bool:
        ordinary_limit = (
            self.regulation_fouls_before_penalty
            if period <= self.regulation_periods
            else self.overtime_fouls_before_penalty
        )
        if team_fouls_after_foul > ordinary_limit:
            return True
        in_final_two = period_clock_ms <= self.final_period_seconds * SECOND_MS
        return (
            in_final_two
            and last_two_minute_fouls_after_foul
            > self.last_two_minute_fouls_before_penalty
        )


NBA_2025_26 = Ruleset(name="NBA 2025-26")
