from __future__ import annotations

from dataclasses import replace
from typing import Iterable, Mapping

from nba_sim.domain.profiles import PlayerProfile, TeamProfile


def condition_team_profile(
    team: TeamProfile,
    *,
    inactive_player_ids: Iterable[int] = (),
    minute_limits: Mapping[int, float] | None = None,
) -> TeamProfile:
    """Create a legal game-day profile from explicit availability information.

    Minutes are reallocated proportionally to the source projection, subject to
    supplied caps, and always sum to the NBA's 240 regulation player-minutes.
    The source profile is immutable and is never modified.
    """

    inactive = frozenset(int(player_id) for player_id in inactive_player_ids)
    limits = {
        int(player_id): float(limit)
        for player_id, limit in (minute_limits or {}).items()
    }
    roster_ids = {player.player_id for player in team.roster}
    unknown = (inactive | set(limits)) - roster_ids
    if unknown:
        raise KeyError(f"unknown player IDs for {team.abbreviation}: {sorted(unknown)}")
    overlap = inactive & set(limits)
    if overlap:
        raise ValueError(
            f"inactive players cannot have minute limits: {sorted(overlap)}"
        )
    for player_id, limit in limits.items():
        if not 0.0 <= limit <= 48.0:
            raise ValueError(
                f"minute limit for player {player_id} must be between 0 and 48"
            )

    active = tuple(
        player for player in team.roster if player.player_id not in inactive
    )
    if len(active) < 5:
        raise ValueError(f"{team.abbreviation} has fewer than five active players")

    caps = {
        player.player_id: limits.get(player.player_id, 48.0)
        for player in active
    }
    if sum(caps.values()) < 240.0 - 1e-9:
        raise ValueError("minute limits leave fewer than 240 available player-minutes")
    ordered = sorted(
        active,
        key=lambda player: player.expected_minutes,
        reverse=True,
    )
    selected = list(ordered[: min(10, len(ordered))])
    selected_ids = {player.player_id for player in selected}
    for player in ordered[len(selected) :]:
        if sum(caps[player_id] for player_id in selected_ids) >= 240.0:
            break
        selected.append(player)
        selected_ids.add(player.player_id)
    if sum(caps[player_id] for player_id in selected_ids) < 240.0 - 1e-9:
        raise ValueError("minute limits leave fewer than 240 available player-minutes")
    selected_tuple = tuple(selected)
    allocations = _allocate_minutes(
        selected_tuple,
        {player_id: caps[player_id] for player_id in selected_ids},
    )
    conditioned = tuple(
        replace(
            player,
            expected_minutes=allocations.get(player.player_id, 0.0),
        )
        for player in active
    )
    return replace(team, roster=conditioned, minute_limits=limits)


def _allocate_minutes(
    players: tuple[PlayerProfile, ...],
    caps: Mapping[int, float],
) -> dict[int, float]:
    remaining = 240.0
    allocations = {player.player_id: 0.0 for player in players}
    available = {player.player_id for player in players}
    weights = {
        player.player_id: max(player.expected_minutes, 0.1)
        for player in players
    }

    while available and remaining > 1e-10:
        denominator = sum(weights[player_id] for player_id in available)
        if denominator <= 0:
            raise ValueError("active rotation has no positive minute weights")
        capped: list[int] = []
        for player_id in available:
            proposed = remaining * weights[player_id] / denominator
            if proposed >= caps[player_id] - allocations[player_id] - 1e-10:
                capped.append(player_id)
        if not capped:
            for player_id in available:
                allocations[player_id] += (
                    remaining * weights[player_id] / denominator
                )
            remaining = 0.0
            break
        for player_id in capped:
            addition = caps[player_id] - allocations[player_id]
            allocations[player_id] += addition
            remaining -= addition
            available.remove(player_id)

    if remaining > 1e-7:
        raise ValueError("could not allocate 240 legal player-minutes")
    return allocations
