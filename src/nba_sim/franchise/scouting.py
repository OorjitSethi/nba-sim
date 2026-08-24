from __future__ import annotations

from dataclasses import replace
from datetime import date
import math

from nba_sim.franchise.models import (
    PlayerLifecycleRecord,
    PlayerRecord,
    ScoutingDepartmentRecord,
    ScoutingReportRecord,
)
from nba_sim.randomness import RandomStreamFactory


SCOUTING_MODEL_VERSION = "scouting-beliefs-v1"
MINIMUM_SCOUTING_SD = 1.5
_ATTRIBUTES = ("offense", "playmaking", "defense", "athleticism", "overall")


def default_scouting_department(
    team: str,
    *,
    as_of: date,
) -> ScoutingDepartmentRecord:
    return ScoutingDepartmentRecord(
        team=team,
        as_of_date=as_of,
        automation_enabled=True,
        weekly_hours=80,
        evaluation_quality=55,
        priority="balanced",
        risk_tolerance="balanced",
        cycles_completed=0,
        last_cycle_date=None,
        model_version=SCOUTING_MODEL_VERSION,
    )


def build_initial_scouting_report(
    player: PlayerRecord,
    lifecycle: PlayerLifecycleRecord,
    *,
    as_of: date,
    seed: int,
) -> ScoutingReportRecord:
    source_sd = {
        "official": 6.0,
        "stat": 6.5,
        "prior": 10.5,
    }
    label = player.profile_source.lower()
    sd = next(
        (value for key, value in source_sd.items() if key in label),
        8.5,
    )
    rng = RandomStreamFactory(seed).generator(
        f"scouting-prior:{player.player_id}"
    )

    def belief(value: float, scale: float = 1.0) -> float:
        return _clip(value + float(rng.normal(0, sd * 0.42 * scale)))

    means = {
        attribute: belief(float(getattr(lifecycle, attribute)))
        for attribute in _ATTRIBUTES
    }
    potential_sd = min(14.0, max(sd, lifecycle.potential_sd + 2.5))
    potential = belief(lifecycle.potential_mean, 1.1)
    probabilities = _archetype_probabilities(means)
    return ScoutingReportRecord(
        player_id=player.player_id,
        as_of_date=as_of,
        evaluations=0,
        observation_hours=0,
        offense_mean=means["offense"],
        offense_sd=sd,
        playmaking_mean=means["playmaking"],
        playmaking_sd=sd,
        defense_mean=means["defense"],
        defense_sd=sd * 1.1,
        athleticism_mean=means["athleticism"],
        athleticism_sd=sd,
        overall_mean=means["overall"],
        overall_sd=sd,
        potential_mean=potential,
        potential_sd=potential_sd,
        **probabilities,
        confidence=_confidence(sd),
        source="public-data-prior",
        model_version=SCOUTING_MODEL_VERSION,
    )


def scout_player(
    report: ScoutingReportRecord,
    lifecycle: PlayerLifecycleRecord,
    *,
    hours: float,
    evaluation_quality: float,
    occurred_on: date,
    seed: int,
    namespace: str,
) -> ScoutingReportRecord:
    if not 1 <= hours <= 120:
        raise ValueError("scouting hours must be between 1 and 120")
    quality = max(0.0, min(100.0, evaluation_quality))
    rng = RandomStreamFactory(seed).generator(namespace)
    observation_sd = max(
        MINIMUM_SCOUTING_SD,
        11.5 / math.sqrt(max(hours, 1) / 4) * (1.2 - quality * 0.006),
    )

    changes: dict[str, float | int | str | date] = {
        "as_of_date": occurred_on,
        "evaluations": report.evaluations + 1,
        "observation_hours": report.observation_hours + hours,
        "source": "department-observation",
    }
    means: dict[str, float] = {}
    for attribute in _ATTRIBUTES:
        prior_mean = float(getattr(report, f"{attribute}_mean"))
        prior_sd = float(getattr(report, f"{attribute}_sd"))
        truth = float(getattr(lifecycle, attribute))
        mean, sd = _bayesian_update(
            prior_mean,
            prior_sd,
            truth + float(rng.normal(0, observation_sd)),
            observation_sd,
        )
        changes[f"{attribute}_mean"] = mean
        changes[f"{attribute}_sd"] = sd
        means[attribute] = mean
    potential_mean, potential_sd = _bayesian_update(
        report.potential_mean,
        report.potential_sd,
        lifecycle.potential_mean
        + float(rng.normal(0, observation_sd * 1.2)),
        observation_sd * 1.2,
    )
    changes["potential_mean"] = potential_mean
    changes["potential_sd"] = potential_sd
    changes["confidence"] = _confidence(float(changes["overall_sd"]))
    changes.update(_archetype_probabilities(means))
    return replace(report, **changes)


def run_automatic_scouting_cycle(
    department: ScoutingDepartmentRecord,
    reports: tuple[ScoutingReportRecord, ...],
    players: tuple[PlayerRecord, ...],
    lifecycles: tuple[PlayerLifecycleRecord, ...],
    *,
    occurred_on: date,
    seed: int,
) -> tuple[ScoutingDepartmentRecord, tuple[ScoutingReportRecord, ...]]:
    if not department.automation_enabled:
        raise ValueError("automatic scouting is disabled")
    player_by_id = {player.player_id: player for player in players}
    lifecycle_by_id = {record.player_id: record for record in lifecycles}
    candidates = [
        report
        for report in reports
        if report.player_id in player_by_id
        and player_by_id[report.player_id].roster_status == "prospect"
    ]

    def target_score(report: ScoutingReportRecord) -> tuple[float, int]:
        player = player_by_id[report.player_id]
        youth_bonus = 8 if (
            department.priority in {"draft", "youth"}
            and lifecycle_by_id[report.player_id].stage in {"prospect", "developing"}
        ) else 0
        own_team_penalty = -8 if player.team == department.team else 0
        upside = (
            report.potential_mean + report.potential_sd
            if department.risk_tolerance == "upside"
            else report.potential_mean
        )
        score = report.overall_sd * 2 + upside * 0.22 + youth_bonus + own_team_penalty
        return (-score, report.player_id)

    selected = sorted(candidates, key=target_score)[:10]
    if not selected:
        return department, ()
    hours_each = max(1.0, department.weekly_hours / len(selected))
    updated = tuple(
        scout_player(
            report,
            lifecycle_by_id[report.player_id],
            hours=hours_each,
            evaluation_quality=department.evaluation_quality,
            occurred_on=occurred_on,
            seed=seed,
            namespace=(
                f"scouting-cycle:{department.team}:"
                f"{department.cycles_completed + 1}:{report.player_id}"
            ),
        )
        for report in selected
    )
    return (
        replace(
            department,
            as_of_date=occurred_on,
            cycles_completed=department.cycles_completed + 1,
            last_cycle_date=occurred_on,
        ),
        updated,
    )


def report_summary(report: ScoutingReportRecord) -> dict[str, object]:
    probabilities = {
        "Creator": report.creator_probability,
        "Shooter": report.shooter_probability,
        "Two-way": report.two_way_probability,
        "Rim anchor": report.rim_probability,
        "Connector": report.connector_probability,
    }
    archetype, probability = max(
        probabilities.items(),
        key=lambda item: item[1],
    )
    return {
        **report.as_dict(),
        "overall_low": round(max(0, report.overall_mean - 1.28 * report.overall_sd), 1),
        "overall_high": round(min(100, report.overall_mean + 1.28 * report.overall_sd), 1),
        "potential_low": round(max(0, report.potential_mean - 1.28 * report.potential_sd), 1),
        "potential_high": round(min(100, report.potential_mean + 1.28 * report.potential_sd), 1),
        "primary_archetype": archetype,
        "archetype_confidence": round(probability, 4),
    }


def _bayesian_update(
    prior_mean: float,
    prior_sd: float,
    observation: float,
    observation_sd: float,
) -> tuple[float, float]:
    prior_precision = 1 / max(prior_sd, MINIMUM_SCOUTING_SD) ** 2
    observation_precision = 1 / max(observation_sd, MINIMUM_SCOUTING_SD) ** 2
    variance = 1 / (prior_precision + observation_precision)
    mean = variance * (
        prior_mean * prior_precision + observation * observation_precision
    )
    return _clip(mean), max(MINIMUM_SCOUTING_SD, math.sqrt(variance))


def _archetype_probabilities(means: dict[str, float]) -> dict[str, float]:
    scores = {
        "creator_probability": (
            1.55 * (means["playmaking"] - 74)
            + 0.30 * (means["offense"] - 70)
        ),
        "shooter_probability": (
            1.05 * (means["offense"] - 70)
            - 0.08 * (means["playmaking"] - 70)
        ),
        "two_way_probability": (
            0.62 * (means["offense"] - 68)
            + 0.78 * (means["defense"] - 68)
        ),
        "rim_probability": (
            1.05 * (means["defense"] - 70)
            + 0.38 * (means["athleticism"] - 68)
        ),
        "connector_probability": (
            0.55 * (means["playmaking"] - 65)
            + 0.45 * (means["defense"] - 65)
            - 0.18 * abs(means["offense"] - 70)
        ),
    }
    peak = max(scores.values())
    exp_scores = {
        name: math.exp((value - peak) / 6.5)
        for name, value in scores.items()
    }
    total = sum(exp_scores.values())
    return {name: value / total for name, value in exp_scores.items()}


def _confidence(sd: float) -> str:
    if sd <= 3.25:
        return "high"
    if sd <= 6.5:
        return "moderate"
    return "low"


def _clip(value: float) -> float:
    return max(0.0, min(100.0, float(value)))
