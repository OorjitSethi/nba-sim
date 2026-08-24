"""Calibrated, event-sourced NBA simulation."""

from nba_sim.domain.profiles import PlayerProfile, TeamProfile, ZoneProfile
from nba_sim.domain.rules import NBA_2025_26, Ruleset
from nba_sim.simulation.game import GameResult, GameSimulator

__all__ = [
    "GameResult",
    "GameSimulator",
    "NBA_2025_26",
    "PlayerProfile",
    "Ruleset",
    "TeamProfile",
    "ZoneProfile",
]

__version__ = "0.1.0"
