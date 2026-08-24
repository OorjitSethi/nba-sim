from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np

from nba_sim.data.point_in_time import PlayerSeasonStat
from nba_sim.domain.enums import ShotZone
from nba_sim.domain.profiles import PlayerProfile
from nba_sim.franchise.models import PlayerLifecycleRecord, PlayerRecord
from nba_sim.franchise.rating_anchors import published_2k26_rating


RATING_MODEL_VERSION = "established-player-ratings.v2"
RATING_MINIMUM = 25
RATING_MAXIMUM = 99

ATTRIBUTE_GROUPS: dict[str, tuple[str, ...]] = {
    "Finishing": (
        "close_shot",
        "driving_layup",
        "driving_dunk",
        "standing_dunk",
        "post_control",
        "post_hook",
        "draw_foul",
        "hands",
    ),
    "Shooting": (
        "mid_range",
        "three_point",
        "free_throw",
        "post_fade",
        "shot_iq",
        "offensive_consistency",
    ),
    "Playmaking": (
        "pass_accuracy",
        "pass_iq",
        "pass_vision",
        "ball_handle",
        "speed_with_ball",
    ),
    "Defense": (
        "interior_defense",
        "perimeter_defense",
        "steal",
        "block",
        "pass_perception",
        "help_defense_iq",
        "defensive_consistency",
    ),
    "Rebounding": (
        "offensive_rebound",
        "defensive_rebound",
    ),
    "Physicals": (
        "speed",
        "agility",
        "strength",
        "vertical",
        "stamina",
        "durability",
        "hustle",
    ),
    "Mental & growth": (
        "intangibles",
        "potential",
    ),
}

ATTRIBUTE_LABELS = {
    name: name.replace("_", " ").title()
    for names in ATTRIBUTE_GROUPS.values()
    for name in names
}
ATTRIBUTE_LABELS.update(
    {
        "mid_range": "Mid-Range Shot",
        "three_point": "Three-Point Shot",
        "speed_with_ball": "Speed With Ball",
        "shot_iq": "Shot IQ",
        "pass_iq": "Pass IQ",
        "help_defense_iq": "Help Defense IQ",
    }
)

_ZONE_PRIORS = {
    ShotZone.RESTRICTED_AREA: 0.64,
    ShotZone.PAINT_NON_RA: 0.42,
    ShotZone.MID_RANGE: 0.40,
    ShotZone.LEFT_CORNER_THREE: 0.37,
    ShotZone.RIGHT_CORNER_THREE: 0.37,
    ShotZone.ABOVE_BREAK_THREE: 0.35,
    ShotZone.BACKCOURT: 0.02,
}


@dataclass(frozen=True)
class RatingInput:
    player: PlayerRecord
    profile: PlayerProfile
    statistics: PlayerSeasonStat | None
    lifecycle: PlayerLifecycleRecord | None = None
    historical_profile: PlayerProfile | None = None


def build_league_ratings(
    inputs: Iterable[RatingInput],
) -> dict[int, dict[str, object]]:
    materialized = tuple(inputs)
    performance_scores = {
        item.player.player_id: _impact_score(item)
        for item in materialized
    }
    prior_scores = {
        item.player.player_id: _established_prior_score(item)
        for item in materialized
    }
    performance_ordered = sorted(
        performance_scores,
        key=lambda player_id: (
            performance_scores[player_id],
            player_id,
        ),
        reverse=True,
    )
    prior_ordered = sorted(
        prior_scores,
        key=lambda player_id: (prior_scores[player_id], player_id),
        reverse=True,
    )
    performance_ranks = {
        player_id: rank
        for rank, player_id in enumerate(performance_ordered, start=1)
    }
    prior_ranks = {
        player_id: rank
        for rank, player_id in enumerate(prior_ordered, start=1)
    }
    result = {}
    for item in materialized:
        player_id = item.player.player_id
        published_prior = published_2k26_rating(item.player.name)
        inferred_prior = min(
            80,
            _overall_from_rank(prior_ranks[player_id]),
        )
        established_prior = published_prior or inferred_prior
        performance_rating = _overall_from_rank(
            performance_ranks[player_id]
        )
        current_weight = _current_evidence_weight(
            item,
            has_published_prior=published_prior is not None,
        )
        pre_age_rating = (
            current_weight * performance_rating
            + (1.0 - current_weight) * established_prior
        )
        age_adjustment = _age_transition_adjustment(item)
        overall = int(
            _clip(
                round(pre_age_rating + age_adjustment),
                65,
                99,
            )
        )
        result[player_id] = _rating_profile(
            item,
            overall=overall,
            league_rank=0,
            league_size=len(materialized),
            age_adjustment=age_adjustment,
            overall_components={
                "established_prior": established_prior,
                "prior_source": (
                    "published NBA 2K26 scale anchor"
                    if published_prior is not None
                    else "historical role prior"
                ),
                "current_performance": performance_rating,
                "current_performance_rank": performance_ranks[player_id],
                "current_evidence_weight": round(current_weight, 4),
                "pre_age_rating": round(pre_age_rating, 3),
                "age_adjustment": round(age_adjustment, 3),
                "as_of_rating": overall,
            },
        )

    ordered_final = sorted(
        result,
        key=lambda player_id: (
            int(result[player_id]["overall"]),
            performance_scores[player_id],
            player_id,
        ),
        reverse=True,
    )
    for league_rank, player_id in enumerate(ordered_final, start=1):
        result[player_id]["league_rank"] = league_rank
    return result


def lifecycle_composites(
    rating: dict[str, object],
) -> dict[str, float]:
    attributes = rating["attributes"]
    assert isinstance(attributes, dict)

    def average(names: tuple[str, ...]) -> float:
        return float(np.mean([float(attributes[name]) for name in names]))

    composites = {
        "offense": average(
            (
                "close_shot", "driving_layup", "driving_dunk",
                "mid_range", "three_point", "free_throw",
                "post_control", "shot_iq",
            )
        ),
        "playmaking": average(
            (
                "pass_accuracy", "pass_iq", "pass_vision",
                "ball_handle", "speed_with_ball",
            )
        ),
        "defense": average(
            (
                "interior_defense", "perimeter_defense", "steal",
                "block", "pass_perception", "help_defense_iq",
            )
        ),
        "athleticism": average(
            ("speed", "agility", "strength", "vertical", "stamina")
        ),
    }
    weights = {
        "offense": 0.38,
        "playmaking": 0.22,
        "defense": 0.28,
        "athleticism": 0.12,
    }
    target = float(rating["overall"])
    # The lifecycle engine recomputes OVR from these four composites. Center
    # them on the calibrated OVR so year one starts continuously rather than
    # jumping back to an unrelated raw attribute average.
    for _ in range(3):
        weighted = sum(
            weights[name] * composites[name] for name in weights
        )
        gap = target - weighted
        if abs(gap) < 1e-6:
            break
        adjustable = tuple(
            name
            for name in weights
            if (
                gap > 0 and composites[name] < RATING_MAXIMUM
            ) or (
                gap < 0 and composites[name] > RATING_MINIMUM
            )
        )
        adjustable_weight = sum(weights[name] for name in adjustable)
        if adjustable_weight <= 0:
            break
        for name in adjustable:
            composites[name] = _clip(
                composites[name] + gap / adjustable_weight,
                RATING_MINIMUM,
                RATING_MAXIMUM,
            )
    return {
        **{
            name: float(value)
            for name, value in composites.items()
        },
        "overall": float(target),
    }


def _rating_profile(
    item: RatingInput,
    *,
    overall: int,
    league_rank: int,
    league_size: int,
    age_adjustment: float,
    overall_components: dict[str, object],
) -> dict[str, object]:
    profile = item.profile
    statistics = item.statistics
    zones = profile.shot_zones
    position = item.player.position.upper()
    guard = "G" in position
    center = "C" in position
    height = profile.height_inches
    usage = profile.usage_rate
    speed = profile.speed
    minutes = (
        statistics.minutes
        if statistics is not None
        else profile.expected_minutes
    )
    games = statistics.games_played if statistics is not None else 0
    assists_per36 = _per36(statistics.assists, minutes) if statistics else 0
    turnovers_per36 = _per36(statistics.turnovers, minutes) if statistics else 2.2
    rebounds_per36 = (
        _per36(
            statistics.offensive_rebounds + statistics.defensive_rebounds,
            minutes,
        )
        if statistics
        else 5.0
    )
    rim = _zone(zones, ShotZone.RESTRICTED_AREA)
    paint = _zone(zones, ShotZone.PAINT_NON_RA)
    mid = _zone(zones, ShotZone.MID_RANGE)
    three = _weighted_zone(
        zones,
        (
            ShotZone.LEFT_CORNER_THREE,
            ShotZone.RIGHT_CORNER_THREE,
            ShotZone.ABOVE_BREAK_THREE,
        ),
        prior=0.36,
    )
    ast_to = assists_per36 / max(turnovers_per36, 0.7)
    defense_signal = (
        _clip((114.0 - statistics.defensive_rating) / 15.0, -1, 1)
        if statistics
        else profile.defensive_impact / 0.10
    )
    steal_rate = (
        _per36(statistics.steals, minutes) if statistics else profile.steal_share
    )
    block_rate = (
        _per36(statistics.blocks, minutes)
        if statistics
        else profile.block_probability * 36
    )
    orebound_rate = (
        statistics.offensive_rebound_rate if statistics else 0.06
    )
    drebound_rate = (
        statistics.defensive_rebound_rate if statistics else 0.15
    )
    foul_draw = (
        statistics.free_throws_attempted
        / max(statistics.field_goals_attempted, 1)
        if statistics
        else profile.shooting_foul_probability
    )
    reliability = min(1.0, games / 45.0) if statistics else 0.25

    attributes = {
        "close_shot": _zone_rating(paint[1], ShotZone.PAINT_NON_RA),
        "driving_layup": _rating(
            55 + 38 * rim[1] + 24 * usage + 9 * speed - 6 * center
        ),
        "driving_dunk": _rating(
            34 + 46 * rim[0] + 14 * speed + 0.55 * (height - 72)
        ),
        "standing_dunk": _rating(
            24 + 58 * rim[0] + 1.5 * (height - 72) + 10 * center
        ),
        "post_control": _rating(
            32 + 28 * (paint[0] + mid[0]) + 1.3 * (height - 72)
            + 35 * usage + 8 * center
        ),
        "post_hook": _rating(
            30 + 48 * paint[1] + 1.2 * (height - 72) + 8 * center
        ),
        "draw_foul": _rating(48 + 95 * foul_draw),
        "hands": _rating(
            62 + 12 * reliability + 12 * (1 - profile.turnover_probability)
        ),
        "mid_range": _zone_rating(mid[1], ShotZone.MID_RANGE),
        "three_point": _rating(70 + 245 * (three[1] - 0.36)),
        "free_throw": _rating(25 + 74 * profile.free_throw_probability),
        "post_fade": _rating(
            32 + 48 * mid[1] + 1.0 * (height - 72) + 8 * center
        ),
        "shot_iq": _rating(
            52 + 75 * _expected_points_per_shot(profile) - 55
            + 14 * reliability
        ),
        "offensive_consistency": _rating(
            46 + 95 * usage + 18 * reliability
        ),
        "pass_accuracy": _rating(
            40 + 5.0 * ast_to + 70 * (
                statistics.assist_rate if statistics else
                max(0, (profile.assist_probability - 0.28) / 1.65)
            )
        ),
        "pass_iq": _rating(
            52 + 7.0 * ast_to
            - 85 * max(0, profile.turnover_probability - 0.10)
        ),
        "pass_vision": _rating(
            42 + 120 * (
                statistics.assist_rate if statistics else
                max(0, (profile.assist_probability - 0.28) / 1.65)
            ) + 4 * ast_to
        ),
        "ball_handle": _rating(
            32 + 100 * usage + 50 * (
                statistics.assist_rate if statistics else 0.12
            ) + 12 * guard - 22 * center
        ),
        "speed_with_ball": _rating(
            25 + 45 * speed
            + 0.35 * (
                32 + 100 * usage
                + 50 * (
                    statistics.assist_rate if statistics else 0.12
                )
                + 12 * guard - 22 * center
            )
            + 5 * guard - 18 * center
        ),
        "interior_defense": _rating(
            43 + 1.1 * (height - 72) + 6.5 * block_rate
            + 13 * defense_signal + 7 * center
        ),
        "perimeter_defense": _rating(
            49 + 31 * speed + 12 * defense_signal + 8 * guard
            - 6 * center
        ),
        "steal": _rating(43 + 18 * steal_rate + 7 * defense_signal),
        "block": _rating(40 + 14 * block_rate + 0.8 * (height - 72)),
        "pass_perception": _rating(
            48 + 16 * steal_rate + 8 * defense_signal
        ),
        "help_defense_iq": _rating(
            57 + 17 * defense_signal + 4 * block_rate + 8 * reliability
        ),
        "defensive_consistency": _rating(
            55 + 17 * defense_signal + 15 * reliability
        ),
        "offensive_rebound": _rating(
            40 + 390 * orebound_rate + 0.55 * (height - 72)
        ),
        "defensive_rebound": _rating(
            37 + 255 * drebound_rate + 0.5 * (height - 72)
        ),
        "speed": _rating(25 + 74 * speed),
        "agility": _rating(28 + 69 * speed + 6 * guard - 5 * center),
        "strength": _rating(
            36 + 1.45 * (height - 72) + 14 * center + 8 * (not guard)
        ),
        "vertical": _rating(
            37 + 32 * speed + 3.2 * block_rate + 7 * rim[0]
        ),
        "stamina": _rating(50 + 1.15 * minutes),
        "durability": _rating(60 + 26 * reliability),
        "hustle": _rating(
            54 + 1.0 * minutes + 0.7 * rebounds_per36
        ),
        "intangibles": _rating(
            58 + 80 * (
                statistics.player_impact_estimate if statistics else 0.08
            )
        ),
        "potential": _potential_rating(item, overall),
    }
    attributes = {
        name: int(
            _clip(
                round(
                    value
                    + _attribute_age_adjustment(
                        name,
                        age_adjustment,
                    )
                ),
                RATING_MINIMUM,
                RATING_MAXIMUM,
            )
        )
        for name, value in attributes.items()
    }
    attributes["potential"] = _potential_rating(item, overall)
    creator_score = (
        0.38 * attributes["ball_handle"]
        + 0.32 * attributes["pass_vision"]
        + 0.18 * attributes["speed_with_ball"]
        + 0.12 * attributes["offensive_consistency"]
    )
    role_probabilities = _role_probabilities(attributes, creator_score)
    zone_rows = []
    for zone in (
        ShotZone.RESTRICTED_AREA,
        ShotZone.PAINT_NON_RA,
        ShotZone.MID_RANGE,
        ShotZone.LEFT_CORNER_THREE,
        ShotZone.RIGHT_CORNER_THREE,
        ShotZone.ABOVE_BREAK_THREE,
    ):
        frequency, make_probability = _zone(zones, zone)
        difference = make_probability - _ZONE_PRIORS[zone]
        status = (
            "unused"
            if frequency < 0.015
            else "hot"
            if difference >= 0.035
            else "cold"
            if difference <= -0.035
            else "neutral"
        )
        zone_rows.append(
            {
                "zone": zone.value,
                "label": zone.value.replace("_", " ").title(),
                "frequency": round(frequency, 4),
                "make_probability": round(make_probability, 4),
                "league_prior": _ZONE_PRIORS[zone],
                "rating": _zone_rating(make_probability, zone),
                "status": status,
            }
        )
    primary_role, primary_probability = max(
        role_probabilities.items(), key=lambda value: value[1]
    )
    return {
        "player_id": item.player.player_id,
        "name": item.player.name,
        "team": item.player.team,
        "position": item.player.position,
        "overall": overall,
        "league_rank": league_rank,
        "league_size": league_size,
        "attributes": attributes,
        "attribute_groups": ATTRIBUTE_GROUPS,
        "attribute_labels": ATTRIBUTE_LABELS,
        "zones": zone_rows,
        "hot_zones": [
            row["zone"] for row in zone_rows if row["status"] == "hot"
        ],
        "role_probabilities": {
            name: round(value, 4)
            for name, value in role_probabilities.items()
        },
        "primary_role": primary_role,
        "primary_role_probability": round(primary_probability, 4),
        "creator_rating": int(round(creator_score)),
        "overall_components": overall_components,
        "age": _rating_age(item),
        "lifecycle_stage": (
            item.lifecycle.stage if item.lifecycle is not None else "unknown"
        ),
        "exact": True,
        "established_player": True,
        "source": (
            f"official-{statistics.season}+established-prior+age-curve"
            if statistics is not None
            else "current-roster+established-prior+age-curve"
        ),
        "model_version": RATING_MODEL_VERSION,
    }


def _impact_score(item: RatingInput) -> float:
    stats = item.statistics
    profile = item.profile
    if stats is None or stats.games_played <= 0:
        return (
            -0.45
            + 0.02 * profile.expected_minutes
            + 0.8 * profile.defensive_impact
            + 0.5 * (profile.usage_rate - 0.18)
        )
    minutes = max(stats.minutes, 1)
    points = (
        2 * stats.field_goals_made
        + stats.threes_made
        + stats.free_throws_made
    )
    points_per36 = 36 * points / minutes
    assists_per36 = _per36(stats.assists, minutes)
    rebounds_per36 = _per36(
        stats.offensive_rebounds + stats.defensive_rebounds, minutes
    )
    stocks_per36 = _per36(stats.steals + stats.blocks, minutes)
    true_shooting = points / max(
        2 * (stats.field_goals_attempted + 0.44 * stats.free_throws_attempted),
        1,
    )
    turnovers_per36 = _per36(stats.turnovers, minutes)
    measured = (
        3.5 * stats.player_impact_estimate
        + 0.030 * points_per36
        + 0.025 * assists_per36
        + 0.004 * rebounds_per36
        + 0.018 * stocks_per36
        + 0.70 * (true_shooting - 0.56)
        + 0.013 * stats.minutes
        + 0.017 * (114 - stats.defensive_rating)
        + 0.50 * profile.defensive_impact
        + 0.60 * (stats.usage_rate - 0.20)
        + 0.30 * stats.assist_rate
        - 0.015 * turnovers_per36
    )
    sample_reliability = min(
        1.0,
        stats.games_played / 30.0,
        stats.games_played * stats.minutes / 600.0,
    )
    prior = (
        -0.45
        + 0.02 * profile.expected_minutes
        + 0.8 * profile.defensive_impact
        + 0.5 * (profile.usage_rate - 0.18)
    )
    return sample_reliability * measured + (1 - sample_reliability) * prior


def _established_prior_score(item: RatingInput) -> float:
    profile = item.historical_profile or item.profile
    expected_points = _expected_points_per_shot(profile)
    return (
        0.027 * profile.expected_minutes
        + 1.10 * (profile.usage_rate - 0.18)
        + 0.34 * (profile.assist_probability - 0.43)
        - 0.65 * (profile.turnover_probability - 0.12)
        + 0.55 * (expected_points - 1.02)
        + 0.90 * profile.defensive_impact
        + 0.35 * profile.block_probability
    )


def _current_evidence_weight(
    item: RatingInput,
    *,
    has_published_prior: bool,
) -> float:
    statistics = item.statistics
    if statistics is None or statistics.games_played <= 0:
        return 0.0
    reliability = min(
        1.0,
        statistics.games_played / 65.0,
        statistics.games_played * statistics.minutes / 1_400.0,
    )
    if has_published_prior:
        return 0.10 + 0.45 * reliability
    return 0.25 + 0.45 * reliability


def _rating_age(item: RatingInput) -> float | None:
    if item.lifecycle is not None and item.lifecycle.age is not None:
        return float(item.lifecycle.age)
    if item.statistics is not None and item.statistics.age is not None:
        return float(item.statistics.age + 1.0)
    return None


def _age_transition_adjustment(item: RatingInput) -> float:
    age = _rating_age(item)
    if age is None:
        return 0.0
    if age <= 20:
        return 0.80
    if age <= 22:
        return 0.60
    if age <= 23:
        return 0.45
    if age <= 24:
        return 0.30
    if age <= 25:
        return 0.18
    if age <= 27:
        return 0.08
    if age <= 29:
        return 0.0

    decline = -0.18 * (age - 29.0) ** 1.35
    preservation = _skill_aging_preservation(item)
    return decline * (1.0 - 0.35 * preservation)


def _skill_aging_preservation(item: RatingInput) -> float:
    profile = item.profile
    three = _weighted_zone(
        profile.shot_zones,
        (
            ShotZone.LEFT_CORNER_THREE,
            ShotZone.RIGHT_CORNER_THREE,
            ShotZone.ABOVE_BREAK_THREE,
        ),
        prior=0.36,
    )
    mid = _zone(profile.shot_zones, ShotZone.MID_RANGE)
    shooting = _clip(
        0.70 * (three[1] - 0.31) / 0.11
        + 0.30 * (mid[1] - 0.34) / 0.12,
        0.0,
        1.0,
    )
    free_throw = _clip(
        (profile.free_throw_probability - 0.64) / 0.26,
        0.0,
        1.0,
    )
    passing = _clip(
        (profile.assist_probability - 0.35) / 0.49,
        0.0,
        1.0,
    )
    return 0.50 * shooting + 0.25 * free_throw + 0.25 * passing


def _attribute_age_adjustment(
    attribute: str,
    overall_adjustment: float,
) -> float:
    if attribute == "potential":
        return 0.0
    if overall_adjustment >= 0:
        multiplier = (
            1.15
            if attribute in {
                "speed", "agility", "vertical", "stamina",
                "driving_layup", "driving_dunk",
            }
            else 0.75
        )
        return overall_adjustment * multiplier
    if attribute in {
        "speed", "agility", "vertical", "stamina",
        "driving_layup", "driving_dunk", "perimeter_defense",
    }:
        return overall_adjustment * 1.35
    if attribute in {
        "three_point", "mid_range", "free_throw", "post_fade",
        "pass_iq", "pass_vision", "shot_iq", "hands",
    }:
        return overall_adjustment * 0.35
    return overall_adjustment * 0.75


def _potential_rating(item: RatingInput, overall: int) -> int:
    age = _rating_age(item)
    if age is None:
        room = 2.0
    elif age <= 20:
        room = 8.0
    elif age <= 21:
        room = 7.0
    elif age <= 22:
        room = 6.0
    elif age <= 23:
        room = 5.0
    elif age <= 24:
        room = 4.0
    elif age <= 25:
        room = 3.0
    elif age <= 26:
        room = 2.0
    elif age <= 27:
        room = 1.0
    else:
        room = 0.0
    return _rating(overall + room)


def _role_probabilities(
    attributes: dict[str, int],
    creator_score: float,
) -> dict[str, float]:
    scores = {
        "Creator": (
            2.2 * (creator_score - 82)
            + 0.35 * (attributes["ball_handle"] - 76)
        ),
        "Shooter": (
            1.25 * (attributes["three_point"] - 72)
            + 0.45 * (attributes["mid_range"] - 70)
        ),
        "Two-way": (
            0.55 * (attributes["perimeter_defense"] - 68)
            + 0.45 * (attributes["offensive_consistency"] - 68)
        ),
        "Rim anchor": (
            0.75 * (attributes["interior_defense"] - 68)
            + 0.65 * (attributes["block"] - 68)
        ),
        "Interior scorer": (
            0.55 * (attributes["close_shot"] - 70)
            + 0.45 * (attributes["post_control"] - 68)
            + 0.35 * (attributes["draw_foul"] - 68)
        ),
        "Connector": (
            0.55 * (attributes["pass_iq"] - 66)
            + 0.35 * (attributes["help_defense_iq"] - 66)
            - 0.20 * abs(attributes["offensive_consistency"] - 70)
        ),
    }
    peak = max(scores.values())
    exponentials = {
        name: float(np.exp((score - peak) / 7.0))
        for name, score in scores.items()
    }
    total = sum(exponentials.values())
    return {name: value / total for name, value in exponentials.items()}


def _overall_from_rank(rank: int) -> int:
    for maximum_rank, overall in (
        (2, 99),
        (3, 97),
        (5, 96),
        (9, 95),
        (14, 94),
        (18, 93),
        (20, 92),
        (24, 91),
        (29, 90),
        (31, 89),
        (41, 88),
        (46, 87),
        (53, 86),
        (58, 85),
        (65, 84),
        (83, 83),
        (100, 82),
        (130, 80),
        (170, 78),
        (220, 76),
        (280, 74),
        (350, 72),
        (430, 70),
        (510, 68),
    ):
        if rank <= maximum_rank:
            return overall
    return 65


def _zone_rating(make_probability: float, zone: ShotZone) -> int:
    prior = _ZONE_PRIORS[zone]
    slope = 170 if zone.point_value == 2 else 245
    return _rating(70 + slope * (make_probability - prior))


def _weighted_zone(
    zones: object,
    selected: tuple[ShotZone, ...],
    *,
    prior: float,
) -> tuple[float, float]:
    rows = [_zone(zones, zone) for zone in selected]
    frequency = sum(row[0] for row in rows)
    make_probability = (
        sum(row[0] * row[1] for row in rows) / frequency
        if frequency > 0
        else prior
    )
    return frequency, make_probability


def _zone(
    zones: object,
    zone: ShotZone,
) -> tuple[float, float]:
    profile = zones.get(zone)  # type: ignore[union-attr]
    if profile is None:
        return 0.0, _ZONE_PRIORS[zone]
    return float(profile.frequency), float(profile.make_probability)


def _expected_points_per_shot(profile: PlayerProfile) -> float:
    return sum(
        zone.frequency * zone.make_probability * shot_zone.point_value
        for shot_zone, zone in profile.shot_zones.items()
    )


def _per36(value: float, minutes: float) -> float:
    return 36 * value / max(minutes, 1)


def _rating(value: float) -> int:
    return int(round(_clip(value, RATING_MINIMUM, RATING_MAXIMUM)))


def _clip(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, float(value)))
