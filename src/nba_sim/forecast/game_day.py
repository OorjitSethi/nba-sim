from __future__ import annotations

import re
import unicodedata
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
import os
from typing import Iterable

import numpy as np

from nba_sim.data.point_in_time import InjuryObservation, ScheduledGame
from nba_sim.domain.profiles import TeamProfile
from nba_sim.domain.scenarios import condition_team_profile
from nba_sim.forecast.distributions import GameDistribution
from nba_sim.forecast.macro import HeuristicMacroModel
from nba_sim.randomness import RandomStreamFactory
from nba_sim.simulation.game import GameSimulator
from nba_sim.simulation.monte_carlo import (
    MonteCarloSummary,
    summarize_simulations,
)


STATUS_AVAILABILITY_PROBABILITY = {
    "available": 1.0,
    "probable": 0.85,
    "questionable": 0.50,
    "doubtful": 0.25,
    "out": 0.0,
}


@dataclass(frozen=True)
class ResolvedAvailability:
    team: str
    player_name: str
    status: str
    reason: str
    availability_probability: float
    report_timestamp: str
    player_id: int | None
    matched: bool

    @property
    def automatically_inactive(self) -> bool:
        return self.matched and self.availability_probability == 0.0

    def as_dict(self) -> dict[str, object]:
        return {
            "team": self.team,
            "player_name": self.player_name,
            "player_id": self.player_id,
            "status": self.status,
            "reason": self.reason,
            "availability_probability": self.availability_probability,
            "automatically_inactive": self.automatically_inactive,
            "matched": self.matched,
            "report_timestamp": self.report_timestamp,
        }


@dataclass(frozen=True)
class AvailabilityForecast:
    summary: MonteCarloSummary
    availability: tuple[ResolvedAvailability, ...]
    distinct_scenarios: int

    def as_dict(self) -> dict[str, object]:
        result = self.summary.as_dict()
        result.update(
            {
                "kind": "game_day",
                "availability": [row.as_dict() for row in self.availability],
                "distinct_availability_scenarios": self.distinct_scenarios,
                "availability_method": (
                    "Official statuses; Out is inactive. Probable, Questionable, "
                    "and Doubtful use transparent 85%, 50%, and 25% scenario priors."
                ),
            }
        )
        return result


@dataclass(frozen=True)
class CalibratedAvailabilityForecast:
    summary: MonteCarloSummary
    availability: tuple[ResolvedAvailability, ...]
    distinct_scenarios: int
    base_distribution: GameDistribution
    mean_roster_margin_delta: float
    mean_roster_total_delta: float

    def as_dict(self) -> dict[str, object]:
        result = self.summary.as_dict()
        result.update(
            {
                "kind": "game_day",
                "availability": [row.as_dict() for row in self.availability],
                "distinct_availability_scenarios": self.distinct_scenarios,
                "availability_method": (
                    "Official statuses; Out is inactive. Probable, Questionable, "
                    "and Doubtful use transparent 85%, 50%, and 25% scenario priors."
                ),
                "forecast_method": (
                    "Chronologically fitted dynamic team-strength distribution "
                    "plus current-roster availability deltas."
                ),
                "base_distribution": self.base_distribution.as_dict(),
                "mean_roster_margin_delta": round(
                    self.mean_roster_margin_delta,
                    4,
                ),
                "mean_roster_total_delta": round(
                    self.mean_roster_total_delta,
                    4,
                ),
            }
        )
        return result


def resolve_game_availability(
    *,
    game: ScheduledGame,
    home_team: TeamProfile,
    away_team: TeamProfile,
    observations: Iterable[InjuryObservation],
) -> tuple[ResolvedAvailability, ...]:
    if not game.teams_identified:
        return ()
    matchup = _normalize_matchup(f"{game.away_team}@{game.home_team}")
    profiles = {
        home_team.abbreviation: home_team,
        away_team.abbreviation: away_team,
    }
    result: list[ResolvedAvailability] = []
    for observation in observations:
        observation_matchup = _normalize_matchup(observation.matchup)
        if observation_matchup and observation_matchup != matchup:
            continue
        team = _resolve_team(observation, profiles)
        if team is None:
            continue
        player_id = observation.player_id
        if player_id is None:
            player_id = _resolve_player_id(
                observation.player_name,
                profiles[team],
            )
        status = observation.status.strip().lower()
        probability = STATUS_AVAILABILITY_PROBABILITY.get(status, 0.5)
        result.append(
            ResolvedAvailability(
                team=team,
                player_name=observation.player_name,
                player_id=player_id,
                status=observation.status,
                reason=observation.reason,
                availability_probability=probability,
                matched=player_id is not None,
                report_timestamp=observation.report_timestamp.isoformat(),
            )
        )
    return tuple(
        sorted(
            result,
            key=lambda row: (
                row.team,
                row.availability_probability,
                _normalize(row.player_name),
            ),
        )
    )


def simulate_with_availability(
    *,
    home_team: TeamProfile,
    away_team: TeamProfile,
    availability: Iterable[ResolvedAvailability],
    trials: int,
    seed: int,
    workers: int = 1,
) -> AvailabilityForecast:
    if trials <= 0:
        raise ValueError("trials must be positive")
    if workers < 0:
        raise ValueError("workers cannot be negative")
    availability_rows = tuple(availability)
    rows = tuple(row for row in availability_rows if row.matched)
    streams = RandomStreamFactory(seed)
    home_scores = np.empty(trials, dtype=np.int32)
    away_scores = np.empty(trials, dtype=np.int32)
    periods = np.empty(trials, dtype=np.int16)
    scenarios: set[tuple[tuple[int, ...], tuple[int, ...]]] = set()
    tasks: list[tuple[GameSimulator, int]] = []

    for trial in range(trials):
        rng = streams.generator(f"availability:{trial}")
        inactive: dict[str, set[int]] = {
            home_team.abbreviation: set(),
            away_team.abbreviation: set(),
        }
        for row in rows:
            if (
                row.player_id is not None
                and rng.random() >= row.availability_probability
            ):
                inactive[row.team].add(row.player_id)
        scenario = (
            tuple(sorted(inactive[home_team.abbreviation])),
            tuple(sorted(inactive[away_team.abbreviation])),
        )
        scenarios.add(scenario)
        tasks.append(
            (
                GameSimulator(
                    home_team=condition_team_profile(
                        home_team,
                        inactive_player_ids=scenario[0],
                    ),
                    away_team=condition_team_profile(
                        away_team,
                        inactive_player_ids=scenario[1],
                    ),
                ),
                streams.seed_for(f"game:{trial}"),
            )
        )

    resolved_workers = (
        max(1, min(os.cpu_count() or 1, 8)) if workers == 0 else workers
    )
    if resolved_workers == 1:
        outputs = map(_simulate_scenario, tasks)
        for trial, output in enumerate(outputs):
            home_scores[trial], away_scores[trial], periods[trial] = output
    else:
        chunksize = max(1, trials // (resolved_workers * 8))
        try:
            with ProcessPoolExecutor(max_workers=resolved_workers) as executor:
                outputs = executor.map(
                    _simulate_scenario,
                    tasks,
                    chunksize=chunksize,
                )
                for trial, output in enumerate(outputs):
                    home_scores[trial], away_scores[trial], periods[trial] = output
        except PermissionError:
            for trial, task in enumerate(tasks):
                output = _simulate_scenario(task)
                home_scores[trial], away_scores[trial], periods[trial] = output

    summary = summarize_simulations(
        home_team=home_team.abbreviation,
        away_team=away_team.abbreviation,
        seed=seed,
        home_scores=home_scores,
        away_scores=away_scores,
        periods=periods,
    )
    return AvailabilityForecast(
        summary=summary,
        availability=availability_rows,
        distinct_scenarios=len(scenarios),
    )


def simulate_calibrated_availability(
    *,
    home_team: TeamProfile,
    away_team: TeamProfile,
    availability: Iterable[ResolvedAvailability],
    base_distribution: GameDistribution,
    trials: int,
    seed: int,
) -> CalibratedAvailabilityForecast:
    """Sample availability around a chronologically calibrated macro forecast."""

    if trials <= 0:
        raise ValueError("trials must be positive")
    if (
        base_distribution.home_team != home_team.abbreviation
        or base_distribution.away_team != away_team.abbreviation
    ):
        raise ValueError("base distribution does not match the teams")
    availability_rows = tuple(availability)
    matched = tuple(row for row in availability_rows if row.matched)
    streams = RandomStreamFactory(seed)
    profile_prior = HeuristicMacroModel()
    full_prior = profile_prior.predict(
        home_team=home_team,
        away_team=away_team,
    )
    home_scores = np.empty(trials, dtype=np.int32)
    away_scores = np.empty(trials, dtype=np.int32)
    periods = np.full(trials, 4, dtype=np.int16)
    margin_deltas = np.empty(trials, dtype=np.float64)
    total_deltas = np.empty(trials, dtype=np.float64)
    scenarios: set[tuple[tuple[int, ...], tuple[int, ...]]] = set()

    for trial in range(trials):
        availability_rng = streams.generator(f"calibrated-availability:{trial}")
        outcome_rng = streams.generator(f"calibrated-outcome:{trial}")
        inactive: dict[str, set[int]] = {
            home_team.abbreviation: set(),
            away_team.abbreviation: set(),
        }
        for row in matched:
            if (
                row.player_id is not None
                and availability_rng.random() >= row.availability_probability
            ):
                inactive[row.team].add(row.player_id)
        scenario = (
            tuple(sorted(inactive[home_team.abbreviation])),
            tuple(sorted(inactive[away_team.abbreviation])),
        )
        scenarios.add(scenario)
        scenario_prior = profile_prior.predict(
            home_team=condition_team_profile(
                home_team,
                inactive_player_ids=scenario[0],
            ),
            away_team=condition_team_profile(
                away_team,
                inactive_player_ids=scenario[1],
            ),
        )
        margin_delta = float(
            np.clip(
                scenario_prior.mean_margin - full_prior.mean_margin,
                -15.0,
                15.0,
            )
        )
        total_delta = float(
            np.clip(
                scenario_prior.mean_total - full_prior.mean_total,
                -20.0,
                20.0,
            )
        )
        margin_deltas[trial] = margin_delta
        total_deltas[trial] = total_delta
        margin, total = outcome_rng.multivariate_normal(
            (
                base_distribution.mean_margin + margin_delta,
                base_distribution.mean_total + total_delta,
            ),
            base_distribution.covariance,
        )
        total = max(120.0, float(total))
        margin = float(np.clip(margin, -total + 2.0, total - 2.0))
        home_score = max(1, int(round((total + margin) / 2.0)))
        away_score = max(1, int(round((total - margin) / 2.0)))
        if home_score == away_score:
            if margin >= 0:
                home_score += 1
            else:
                away_score += 1
        home_scores[trial] = home_score
        away_scores[trial] = away_score

    return CalibratedAvailabilityForecast(
        summary=summarize_simulations(
            home_team=home_team.abbreviation,
            away_team=away_team.abbreviation,
            seed=seed,
            home_scores=home_scores,
            away_scores=away_scores,
            periods=periods,
        ),
        availability=availability_rows,
        distinct_scenarios=len(scenarios),
        base_distribution=base_distribution,
        mean_roster_margin_delta=float(np.mean(margin_deltas)),
        mean_roster_total_delta=float(np.mean(total_deltas)),
    )


def _resolve_team(
    observation: InjuryObservation,
    profiles: dict[str, TeamProfile],
) -> str | None:
    normalized = _normalize(observation.team)
    for abbreviation, profile in profiles.items():
        if normalized in {_normalize(abbreviation), _normalize(profile.name)}:
            return abbreviation
    player_matches = [
        abbreviation
        for abbreviation, profile in profiles.items()
        if _resolve_player_id(observation.player_name, profile) is not None
    ]
    return player_matches[0] if len(player_matches) == 1 else None


def _resolve_player_id(name: str, profile: TeamProfile) -> int | None:
    normalized = _normalize(name)
    matches = [
        player.player_id
        for player in profile.roster
        if _normalize(player.name) == normalized
    ]
    return matches[0] if len(matches) == 1 else None


def _normalize(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode(
        "ascii",
        "ignore",
    ).decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", ascii_value.lower()).strip()


def _normalize_matchup(value: str) -> str:
    return re.sub(r"[^A-Z0-9@]+", "", value.upper().replace("VS.", "@"))


def _simulate_scenario(arguments: tuple[GameSimulator, int]) -> tuple[int, int, int]:
    simulator, seed = arguments
    result = simulator.simulate(seed=seed)
    return result.home_score, result.away_score, result.periods
