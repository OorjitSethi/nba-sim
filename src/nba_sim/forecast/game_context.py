from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from math import asin, cos, erf, log, radians, sin, sqrt
from typing import Iterable

import numpy as np

from nba_sim.data.point_in_time import HistoricalGame, ScheduledGame
from nba_sim.validation.probabilistic import paired_bootstrap_difference


@dataclass(frozen=True)
class Venue:
    latitude: float
    longitude: float
    utc_offset_hours: int
    altitude_feet: int


TEAM_VENUES = {
    "ATL": Venue(33.757, -84.396, -5, 1050),
    "BOS": Venue(42.366, -71.062, -5, 43),
    "BKN": Venue(40.683, -73.975, -5, 30),
    "CHA": Venue(35.225, -80.839, -5, 750),
    "CHI": Venue(41.881, -87.674, -6, 594),
    "CLE": Venue(41.496, -81.688, -5, 650),
    "DAL": Venue(32.790, -96.810, -6, 430),
    "DEN": Venue(39.749, -105.008, -7, 5280),
    "DET": Venue(42.341, -83.055, -5, 600),
    "GSW": Venue(37.768, -122.388, -8, 16),
    "HOU": Venue(29.751, -95.362, -6, 50),
    "IND": Venue(39.764, -86.156, -5, 715),
    "LAC": Venue(34.043, -118.267, -8, 305),
    "LAL": Venue(34.043, -118.267, -8, 305),
    "MEM": Venue(35.138, -90.051, -6, 337),
    "MIA": Venue(25.781, -80.188, -5, 7),
    "MIL": Venue(43.045, -87.917, -6, 617),
    "MIN": Venue(44.980, -93.276, -6, 830),
    "NOP": Venue(29.949, -90.082, -6, 3),
    "NYK": Venue(40.751, -73.994, -5, 33),
    "OKC": Venue(35.463, -97.515, -6, 1200),
    "ORL": Venue(28.539, -81.384, -5, 82),
    "PHI": Venue(39.901, -75.172, -5, 39),
    "PHX": Venue(33.446, -112.071, -7, 1086),
    "POR": Venue(45.532, -122.667, -8, 50),
    "SAC": Venue(38.580, -121.500, -8, 30),
    "SAS": Venue(29.427, -98.438, -6, 650),
    "TOR": Venue(43.643, -79.379, -5, 250),
    "UTA": Venue(40.768, -111.901, -7, 4226),
    "WAS": Venue(38.898, -77.021, -5, 39),
}

SPECIAL_VENUES = {
    "Venetian Arena": Venue(22.148, 113.559, 8, 20),
    "Hinkle Fieldhouse": TEAM_VENUES["IND"],
}


@dataclass(frozen=True)
class TeamScheduleContext:
    rest_days: int
    back_to_back: bool
    games_in_last_four_days: int
    travel_miles: float
    time_zones_crossed: int

    def as_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["travel_miles"] = round(self.travel_miles, 1)
        return result


@dataclass(frozen=True)
class GameScheduleContext:
    neutral_site: bool
    venue_altitude_feet: int
    home: TeamScheduleContext
    away: TeamScheduleContext

    def feature_vector(self) -> np.ndarray:
        return np.asarray(
            (
                0.0 if self.neutral_site else 1.0,
                float(np.clip(self.home.rest_days - self.away.rest_days, -3, 3)),
                float(self.home.back_to_back) - float(self.away.back_to_back),
                float(
                    self.away.games_in_last_four_days
                    - self.home.games_in_last_four_days
                ),
                (self.away.travel_miles - self.home.travel_miles) / 1_000.0,
                float(
                    self.away.time_zones_crossed
                    - self.home.time_zones_crossed
                ),
                (
                    self.venue_altitude_feet / 1_000.0
                    if not self.neutral_site
                    else 0.0
                ),
            ),
            dtype=np.float64,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "neutral_site": self.neutral_site,
            "venue_altitude_feet": self.venue_altitude_feet,
            "home": self.home.as_dict(),
            "away": self.away.as_dict(),
        }


@dataclass(frozen=True)
class ContextValidationReport:
    training_games: int
    holdout_games: int
    evaluation_start: str
    baseline_margin_mae: float
    context_margin_mae: float
    baseline_log_loss: float
    context_log_loss: float
    margin_difference_upper_95: float
    log_loss_difference_upper_95: float
    promoted: bool
    coefficients: dict[str, float]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class ScheduleContextModel:
    """Ridge-shrunk schedule effects with a frozen chronological holdout gate."""

    feature_names = (
        "home_court",
        "rest_advantage_days",
        "home_minus_away_back_to_back",
        "away_minus_home_games_in_four",
        "away_minus_home_travel_1000_miles",
        "away_minus_home_time_zones",
        "venue_altitude_1000_feet",
    )

    def __init__(self, *, ridge: float = 500.0) -> None:
        self.ridge = float(ridge)
        self.coefficients = np.zeros(len(self.feature_names), dtype=np.float64)
        self.validation: ContextValidationReport | None = None

    def fit(
        self,
        games: Iterable[HistoricalGame],
        *,
        evaluation_start: date = date(2025, 7, 1),
        bootstrap_samples: int = 2_000,
        seed: int = 2026,
    ) -> "ScheduleContextModel":
        ordered = tuple(sorted(games, key=lambda game: (game.game_date, game.game_id)))
        if len(ordered) < 100:
            raise ValueError("context fitting requires at least 100 games")
        features, residuals, base_margins, dates = _training_rows(ordered)
        train = dates < evaluation_start
        holdout = ~train
        if int(np.sum(train)) < 100 or int(np.sum(holdout)) < 100:
            raise ValueError("context fitting requires substantial train and holdout windows")

        context_coefficients = _ridge_fit(
            features[train],
            residuals[train],
            ridge=self.ridge,
        )
        home_only = _ridge_fit(
            features[train, :1],
            residuals[train],
            ridge=self.ridge,
        )
        observed = base_margins[holdout] + residuals[holdout]
        baseline_prediction = (
            base_margins[holdout]
            + np.einsum("ni,i->n", features[holdout, :1], home_only)
        )
        context_prediction = (
            base_margins[holdout]
            + np.einsum(
                "ni,i->n",
                features[holdout],
                context_coefficients,
            )
        )
        baseline_errors = np.abs(observed - baseline_prediction)
        context_errors = np.abs(observed - context_prediction)
        outcomes = observed > 0
        baseline_log = _log_losses(baseline_prediction, outcomes)
        context_log = _log_losses(context_prediction, outcomes)
        margin_difference = paired_bootstrap_difference(
            context_errors,
            baseline_errors,
            samples=bootstrap_samples,
            seed=seed,
        )
        log_difference = paired_bootstrap_difference(
            context_log,
            baseline_log,
            samples=bootstrap_samples,
            seed=seed + 1,
        )
        promoted = (
            margin_difference.upper_95 < 0.0
            and log_difference.upper_95 < 0.0
        )
        self.validation = ContextValidationReport(
            training_games=int(np.sum(train)),
            holdout_games=int(np.sum(holdout)),
            evaluation_start=evaluation_start.isoformat(),
            baseline_margin_mae=round(float(np.mean(baseline_errors)), 4),
            context_margin_mae=round(float(np.mean(context_errors)), 4),
            baseline_log_loss=round(float(np.mean(baseline_log)), 6),
            context_log_loss=round(float(np.mean(context_log)), 6),
            margin_difference_upper_95=round(margin_difference.upper_95, 6),
            log_loss_difference_upper_95=round(log_difference.upper_95, 6),
            promoted=promoted,
            coefficients={
                name: round(float(value), 5)
                for name, value in zip(self.feature_names, context_coefficients)
            },
        )
        self.coefficients = _ridge_fit(
            features,
            residuals,
            ridge=self.ridge,
        )
        return self

    def adjustment(
        self,
        context: GameScheduleContext,
        *,
        deployed_home_court_points: float,
    ) -> dict[str, object]:
        if self.validation is None:
            raise RuntimeError("context model must be fitted before prediction")
        structural_neutral_correction = (
            -float(deployed_home_court_points) if context.neutral_site else 0.0
        )
        learned = float(np.dot(context.feature_vector(), self.coefficients))
        learned_increment = float(learned - (
            0.0 if context.neutral_site else self.coefficients[0]
        ))
        applied_increment = learned_increment if self.validation.promoted else 0.0
        return {
            "margin_points": round(
                structural_neutral_correction + applied_increment,
                4,
            ),
            "structural_neutral_correction": round(
                structural_neutral_correction,
                4,
            ),
            "learned_increment": float(round(learned_increment, 4)),
            "learned_increment_applied": self.validation.promoted,
            "promotion_passed": self.validation.promoted,
        }


def context_for_scheduled_game(
    game: ScheduledGame,
    *,
    historical_games: Iterable[HistoricalGame],
    season_schedule: Iterable[ScheduledGame],
) -> GameScheduleContext:
    if not game.teams_identified:
        raise ValueError("schedule context requires identified teams")
    current_venue = _scheduled_venue(game)
    appearances: dict[str, list[tuple[date, Venue]]] = {
        str(game.home_team): [],
        str(game.away_team): [],
    }
    for historical in historical_games:
        if historical.game_date >= game.game_date:
            continue
        venue = TEAM_VENUES.get(historical.home_team)
        if venue is None:
            continue
        for team in (historical.home_team, historical.away_team):
            if team in appearances:
                appearances[team].append((historical.game_date, venue))
    for scheduled in season_schedule:
        if (
            scheduled.game_date >= game.game_date
            or not scheduled.teams_identified
        ):
            continue
        venue = _scheduled_venue(scheduled)
        for team in (scheduled.home_team, scheduled.away_team):
            if team in appearances:
                appearances[str(team)].append((scheduled.game_date, venue))

    return GameScheduleContext(
        neutral_site=game.neutral_site,
        venue_altitude_feet=current_venue.altitude_feet,
        home=_team_context(
            appearances[str(game.home_team)],
            game_date=game.game_date,
            current_venue=current_venue,
        ),
        away=_team_context(
            appearances[str(game.away_team)],
            game_date=game.game_date,
            current_venue=current_venue,
        ),
    )


def _training_rows(
    games: tuple[HistoricalGame, ...],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    teams = sorted({game.home_team for game in games} | {game.away_team for game in games})
    ratings = {team: 1_500.0 for team in teams}
    appearances: dict[str, list[tuple[date, Venue]]] = {team: [] for team in teams}
    features: list[np.ndarray] = []
    residuals: list[float] = []
    base_margins: list[float] = []
    dates: list[date] = []
    for game in games:
        venue = TEAM_VENUES.get(game.home_team)
        if venue is None:
            continue
        context = GameScheduleContext(
            neutral_site=game.neutral_site,
            venue_altitude_feet=venue.altitude_feet,
            home=_team_context(
                appearances[game.home_team],
                game_date=game.game_date,
                current_venue=venue,
            ),
            away=_team_context(
                appearances[game.away_team],
                game_date=game.game_date,
                current_venue=venue,
            ),
        )
        base_margin = (
            ratings[game.home_team] - ratings[game.away_team]
        ) / 28.0
        features.append(context.feature_vector())
        residuals.append(float(game.margin) - base_margin)
        base_margins.append(base_margin)
        dates.append(game.game_date)
        _update_elo(ratings, game)
        appearances[game.home_team].append((game.game_date, venue))
        appearances[game.away_team].append((game.game_date, venue))
    return (
        np.asarray(features, dtype=np.float64),
        np.asarray(residuals, dtype=np.float64),
        np.asarray(base_margins, dtype=np.float64),
        np.asarray(dates, dtype=object),
    )


def _team_context(
    appearances: list[tuple[date, Venue]],
    *,
    game_date: date,
    current_venue: Venue,
) -> TeamScheduleContext:
    prior = sorted(
        (appearance for appearance in appearances if appearance[0] < game_date),
        key=lambda item: item[0],
    )
    if not prior:
        return TeamScheduleContext(7, False, 0, 0.0, 0)
    previous_date, previous_venue = prior[-1]
    rest_days = min(7, max(0, (game_date - previous_date).days - 1))
    games_in_four = sum(
        1
        for appearance_date, _ in prior
        if 0 < (game_date - appearance_date).days <= 3
    )
    return TeamScheduleContext(
        rest_days=rest_days,
        back_to_back=rest_days == 0,
        games_in_last_four_days=games_in_four,
        travel_miles=_haversine_miles(previous_venue, current_venue),
        time_zones_crossed=abs(
            previous_venue.utc_offset_hours - current_venue.utc_offset_hours
        ),
    )


def _scheduled_venue(game: ScheduledGame) -> Venue:
    if game.arena_name in SPECIAL_VENUES:
        return SPECIAL_VENUES[game.arena_name]
    if game.home_team in TEAM_VENUES:
        return TEAM_VENUES[str(game.home_team)]
    return Venue(39.5, -98.35, -6, 0)


def _haversine_miles(first: Venue, second: Venue) -> float:
    latitude = radians(second.latitude - first.latitude)
    longitude = radians(second.longitude - first.longitude)
    value = (
        sin(latitude / 2.0) ** 2
        + cos(radians(first.latitude))
        * cos(radians(second.latitude))
        * sin(longitude / 2.0) ** 2
    )
    return 2.0 * 3_958.8 * asin(sqrt(value))


def _ridge_fit(features: np.ndarray, targets: np.ndarray, *, ridge: float) -> np.ndarray:
    # RMS scaling keeps binary venue indicators well-conditioned without
    # centering away their meaningful zero (neutral-site) state.
    scale = np.sqrt(np.mean(features**2, axis=0))
    scale[scale < 1e-9] = 1.0
    standardized = features / scale
    penalty = ridge * np.eye(features.shape[1])
    gram = np.einsum("ni,nj->ij", standardized, standardized)
    target_projection = np.einsum("ni,n->i", standardized, targets)
    coefficients = np.linalg.solve(
        gram + penalty,
        target_projection,
    )
    return coefficients / scale


def _update_elo(ratings: dict[str, float], game: HistoricalGame) -> None:
    home_advantage = 0.0 if game.neutral_site else 65.0
    difference = ratings[game.home_team] + home_advantage - ratings[game.away_team]
    expected = 1.0 / (1.0 + 10.0 ** (-difference / 400.0))
    actual = 1.0 if game.margin > 0 else 0.0
    multiplier = log(max(1.0, abs(game.margin) + 1.0)) * (
        2.2 / (0.001 * abs(difference) + 2.2)
    )
    adjustment = 18.0 * multiplier * (actual - expected)
    ratings[game.home_team] += adjustment
    ratings[game.away_team] -= adjustment


def _log_losses(margins: np.ndarray, outcomes: np.ndarray) -> np.ndarray:
    probabilities = np.asarray(
        [0.5 * (1.0 + erf(float(margin) / (13.5 * sqrt(2.0)))) for margin in margins]
    )
    probabilities = np.clip(probabilities, 1e-9, 1.0 - 1e-9)
    return -(
        outcomes.astype(float) * np.log(probabilities)
        + (~outcomes).astype(float) * np.log(1.0 - probabilities)
    )
