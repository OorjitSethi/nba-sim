from __future__ import annotations

from dataclasses import dataclass

from nba_sim.domain.profiles import PlayerProfile, TeamProfile


@dataclass(frozen=True)
class Substitution:
    outgoing: int
    incoming: int


class RotationManager:
    """Minute-target rotation fallback with bounded dead-ball substitutions."""

    def __init__(
        self,
        team: TeamProfile,
        *,
        substitution_interval_seconds: float = 240.0,
    ) -> None:
        self.team = team
        self.current_ids = tuple(player.player_id for player in team.starting_lineup)
        self.seconds_played = {
            player.player_id: 0.0 for player in team.rotation
        }
        self.seconds_since_substitution = 0.0
        self.substitution_interval_seconds = substitution_interval_seconds

    @property
    def lineup(self) -> tuple[PlayerProfile, ...]:
        return tuple(self.team.player(player_id) for player_id in self.current_ids)

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("rotation time cannot move backwards")
        for player_id in self.current_ids:
            self.seconds_played[player_id] += seconds
        self.seconds_since_substitution += seconds

    def update(
        self,
        *,
        regulation_elapsed_seconds: float,
        fouled_out: set[int],
        overtime: bool,
    ) -> tuple[Substitution, ...]:
        minute_capped = {
            player_id
            for player_id, limit in self.team.minute_limits.items()
            if self.seconds_played.get(player_id, 0.0) >= limit * 60.0
        }
        unavailable = fouled_out | minute_capped
        invalid = [
            player_id
            for player_id in self.current_ids
            if player_id in unavailable
        ]
        if (
            not invalid
            and self.seconds_since_substitution < self.substitution_interval_seconds
        ):
            return ()

        available = [
            player
            for player in self.team.rotation
            if player.player_id not in unavailable
        ]
        if len(available) < 5:
            # Rare fallback: the legacy source has more roster players than the
            # primary rotation. Expand only when foul attrition requires it.
            available = [
                player
                for player in self.team.roster
                if player.player_id not in unavailable
            ]
        if len(available) < 5:
            raise RuntimeError(f"{self.team.abbreviation} has fewer than five players")

        if overtime:
            desired = sorted(
                available,
                key=lambda player: (
                    player.expected_minutes,
                    player.usage_rate,
                ),
                reverse=True,
            )[:5]
        else:
            progress = min(1.0, regulation_elapsed_seconds / (48.0 * 60.0))

            def deficit(player: PlayerProfile) -> float:
                target_to_date = player.expected_minutes * 60.0 * progress
                continuity = (
                    45.0 if player.player_id in self.current_ids else 0.0
                )
                return (
                    target_to_date
                    - self.seconds_played.get(player.player_id, 0.0)
                    + continuity
                )

            ranked = sorted(available, key=deficit, reverse=True)
            desired_ids = set(self.current_ids)
            for player_id in invalid:
                desired_ids.discard(player_id)

            # At ordinary windows, change at most two players to avoid wholesale
            # five-man substitutions caused by minute-target deficits.
            maximum_changes = 5 if invalid else 2
            incoming = [
                player.player_id
                for player in ranked
                if player.player_id not in desired_ids
            ][:maximum_changes]
            outgoing = sorted(
                desired_ids,
                key=lambda player_id: deficit(self.team.player(player_id)),
            )[: len(incoming)]
            for player_id in outgoing:
                desired_ids.remove(player_id)
            desired_ids.update(incoming)
            if len(desired_ids) < 5:
                for player in ranked:
                    desired_ids.add(player.player_id)
                    if len(desired_ids) == 5:
                        break
            desired = sorted(
                (self.team.player(player_id) for player_id in desired_ids),
                key=lambda player: deficit(player),
                reverse=True,
            )[:5]

        new_ids = tuple(player.player_id for player in desired)
        old_only = [player_id for player_id in self.current_ids if player_id not in new_ids]
        new_only = [player_id for player_id in new_ids if player_id not in self.current_ids]
        substitutions = tuple(
            Substitution(outgoing, incoming)
            for outgoing, incoming in zip(old_only, new_only)
        )
        self.current_ids = new_ids
        if substitutions:
            self.seconds_since_substitution = 0.0
        return substitutions
