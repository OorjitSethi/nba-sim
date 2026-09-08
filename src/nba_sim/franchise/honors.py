from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping

from nba_sim.franchise.season_cycle import (
    FranchiseSeasonRecord,
    SeasonHonorRecipientRecord,
    SeasonHonorRecord,
    aggregate_player_stats,
    standings,
)
from nba_sim.franchise.state import LeagueState


HONORS_MODEL_VERSION = "season-honors.v1"


def _rate(value: object) -> float:
    return float(value or 0.0)


def _recipient(
    row: Mapping[str, object],
    *,
    rank: int,
    score: float,
) -> SeasonHonorRecipientRecord:
    return SeasonHonorRecipientRecord(
        player_id=int(row["player_id"]) if row.get("player_id") is not None else None,
        name=str(row["name"]),
        team=str(row["team"]),
        rank=rank,
        score=score,
    )


def _honor(
    key: str,
    label: str,
    kind: str,
    rows: Iterable[Mapping[str, object]],
    scorer: Callable[[Mapping[str, object]], float],
    *,
    count: int,
    rationale: str,
) -> SeasonHonorRecord | None:
    ranked = sorted(rows, key=lambda row: (scorer(row), _rate(row.get("games"))), reverse=True)
    recipients = tuple(
        _recipient(row, rank=index + 1, score=scorer(row))
        for index, row in enumerate(ranked[:count])
    )
    if not recipients:
        return None
    return SeasonHonorRecord(
        key=key,
        label=label,
        kind=kind,
        recipients=recipients,
        rationale=rationale,
        model_version=HONORS_MODEL_VERSION,
    )


def _game_score(row: Mapping[str, object]) -> float:
    """Basketball-Reference-style Game Score from aggregated box-score totals."""
    return (
        _rate(row.get("points"))
        + 0.4 * _rate(row.get("field_goals_made"))
        - 0.7 * _rate(row.get("field_goals_attempted"))
        - 0.4 * (_rate(row.get("free_throws_attempted")) - _rate(row.get("free_throws_made")))
        + 0.7 * _rate(row.get("offensive_rebounds"))
        + 0.3 * _rate(row.get("defensive_rebounds"))
        + _rate(row.get("steals"))
        + 0.7 * _rate(row.get("assists"))
        + 0.7 * _rate(row.get("blocks"))
        - 0.4 * _rate(row.get("personal_fouls"))
        - _rate(row.get("turnovers"))
    )


def build_regular_season_honors(
    state: LeagueState,
    cycle: FranchiseSeasonRecord,
) -> tuple[SeasonHonorRecord, ...]:
    """Calculate deterministic regular-season honors without postseason leakage."""
    stats = aggregate_player_stats(cycle, stages={"regular_season"})
    if not stats:
        return ()
    table = standings(cycle)
    win_rate = {str(row["team"]): _rate(row["win_percentage"]) for row in table}
    point_diff = {str(row["team"]): _rate(row["point_differential"]) for row in table}
    lifecycle = {item.player_id: item for item in state.player_lifecycles}
    players = {item.player_id: item for item in state.players}
    starter_ids = {
        item.player_id
        for plan in state.roster_plans
        for item in plan.assignments
        if item.starter
    }
    max_games = max(int(row["games"]) for row in stats)
    qualification = min(65, max(1, int(max_games * 0.8)))
    eligible = [row for row in stats if int(row["games"]) >= qualification]
    if len(eligible) < 15:
        eligible = stats

    def impact(row: Mapping[str, object]) -> float:
        games = max(1.0, _rate(row.get("games")))
        return _game_score(row) / games

    def team_context(row: Mapping[str, object]) -> float:
        team = str(row["team"])
        return 12.0 * win_rate.get(team, 0.0) + 0.018 * point_diff.get(team, 0.0)

    def mvp_score(row: Mapping[str, object]) -> float:
        return impact(row) + team_context(row) + 0.012 * _rate(row.get("minutes"))

    def offense_score(row: Mapping[str, object]) -> float:
        games = max(1.0, _rate(row.get("games")))
        return (
            _rate(row.get("points")) / games
            + 1.35 * _rate(row.get("assists")) / games
            - 0.85 * _rate(row.get("turnovers")) / games
            + 2.0 * _rate(row.get("fg_pct"))
            + 0.8 * team_context(row)
        )

    def defense_score(row: Mapping[str, object]) -> float:
        games = max(1.0, _rate(row.get("games")))
        life = lifecycle.get(int(row["player_id"]))
        prior = life.defense if life is not None else 70.0
        return (
            3.0 * (_rate(row.get("steals")) + _rate(row.get("blocks"))) / games
            + 0.32 * _rate(row.get("defensive_rebounds")) / games
            + 0.07 * prior
            + 0.65 * team_context(row)
        )

    rookies = [
        row for row in eligible
        if (
            lifecycle.get(int(row["player_id"])) is not None
            and lifecycle[int(row["player_id"])].games_played == 0
            and (lifecycle[int(row["player_id"])].age or 99) <= 25
        )
    ]
    bench = [row for row in eligible if int(row["player_id"]) not in starter_ids]

    def improvement_score(row: Mapping[str, object]) -> float:
        life = lifecycle.get(int(row["player_id"]))
        prior_expectation = ((life.overall - 60.0) * 0.48) if life else 7.0
        age = life.age if life and life.age is not None else 27.0
        experience_guard = 1.0 if life and life.games_played >= 30 and age <= 30 else 0.65
        return experience_guard * (impact(row) - prior_expectation) + 0.25 * team_context(row)

    def clutch_proxy(row: Mapping[str, object]) -> float:
        # The engine has no quarter split yet; shrink individual impact toward close-game team success.
        team = str(row["team"])
        player_id = int(row["player_id"])
        close = [
            game for game in cycle.games
            if game.stage == "regular_season"
            and game.completed
            and team in {game.home_team, game.away_team}
            and abs(int(game.home_score) - int(game.away_score)) <= 5
        ]
        close_rate = (
            sum(game.winner == team for game in close) / len(close)
            if close else win_rate.get(team, 0.0)
        )
        close_boxes = [
            box for game in close for box in game.box_scores
            if box.player_id == player_id
        ]
        close_impact = (
            sum(
                box.points
                + 0.4 * box.field_goals_made
                - 0.7 * box.field_goals_attempted
                - 0.4 * (box.free_throws_attempted - box.free_throws_made)
                + 0.7 * box.offensive_rebounds
                + 0.3 * box.defensive_rebounds
                + box.steals
                + 0.7 * box.assists
                + 0.7 * box.blocks
                - 0.4 * box.personal_fouls
                - box.turnovers
                for box in close_boxes
            ) / len(close_boxes)
            if close_boxes else impact(row)
        )
        return 0.8 * close_impact + 8.0 * close_rate

    honors: list[SeasonHonorRecord] = []

    def add(value: SeasonHonorRecord | None) -> None:
        if value is not None:
            honors.append(value)

    award_specs = (
        ("mvp", "Most Valuable Player", eligible, mvp_score, "Impact, availability, team wins and point differential; regular season only."),
        ("dpoy", "Defensive Player of the Year", eligible, defense_score, "Defensive events, defensive rebounding, calibrated defensive rating and team success."),
        ("roy", "Rookie of the Year", rookies, mvp_score, "First-year players ranked by production, efficiency, availability and team context."),
        ("sixth_man", "Sixth Player of the Year", bench, offense_score, "Non-starters ranked by two-way box production, efficiency and team context."),
        ("mip", "Most Improved Player", eligible, improvement_score, "Current production measured against age- and experience-aware prior player quality."),
        ("clutch", "Clutch Player of the Year", eligible, clutch_proxy, "Individual impact blended with team performance in games decided by five points or fewer."),
    )
    for key, label, rows, scorer, rationale in award_specs:
        add(_honor(key, label, "award", rows, scorer, count=1, rationale=rationale))

    statistical = (
        ("scoring_title", "Scoring Champion", lambda row: _rate(row.get("ppg"))),
        ("rebounding_title", "Rebounding Champion", lambda row: _rate(row.get("rpg"))),
        ("assists_title", "Assists Champion", lambda row: _rate(row.get("apg"))),
        ("steals_title", "Steals Champion", lambda row: _rate(row.get("spg"))),
        ("blocks_title", "Blocks Champion", lambda row: _rate(row.get("bpg"))),
    )
    for key, label, scorer in statistical:
        add(_honor(
            key, label, "statistical_title", eligible, scorer, count=1,
            rationale=f"Per-game leader among players meeting the {qualification}-game qualification threshold.",
        ))

    all_nba_pool = sorted(eligible, key=mvp_score, reverse=True)
    all_defense_pool = sorted(eligible, key=defense_score, reverse=True)
    for index, ordinal in enumerate(("First", "Second", "Third")):
        rows = all_nba_pool[index * 5:(index + 1) * 5]
        add(_honor(
            f"all_nba_{index + 1}", f"All-NBA {ordinal} Team", "honors_team",
            rows, mvp_score, count=5,
            rationale="Positionless selection using regular-season impact, availability and team context.",
        ))
    for index, ordinal in enumerate(("First", "Second")):
        rows = all_defense_pool[index * 5:(index + 1) * 5]
        add(_honor(
            f"all_defense_{index + 1}", f"All-Defensive {ordinal} Team", "honors_team",
            rows, defense_score, count=5,
            rationale="Positionless selection using defensive events, calibrated defense and team context.",
        ))
    rookie_pool = sorted(rookies, key=mvp_score, reverse=True)
    for index, ordinal in enumerate(("First", "Second")):
        rows = rookie_pool[index * 5:(index + 1) * 5]
        add(_honor(
            f"all_rookie_{index + 1}", f"All-Rookie {ordinal} Team", "honors_team",
            rows, mvp_score, count=5,
            rationale="First-year player production and availability with team-context adjustment.",
        ))

    coaches = {item.team: item for item in state.coaching_profiles}
    team_quality = {
        team: sum(
            lifecycle[item.player_id].overall
            for item in state.players
            if item.team == team and item.player_id in lifecycle
        ) / max(1, sum(item.team == team and item.player_id in lifecycle for item in state.players))
        for team in win_rate
    }
    league_quality = sum(team_quality.values()) / max(1, len(team_quality))
    coach_rows = []
    for team, rate in win_rate.items():
        coach = coaches.get(team)
        coach_rows.append({
            "name": coach.coach_name if coach else f"{team} Head Coach",
            "team": team,
            "score": 100.0 * rate + 1.6 * (league_quality - team_quality.get(team, league_quality)),
        })
    add(_honor(
        "coach_of_year", "Coach of the Year", "award", coach_rows,
        lambda row: _rate(row.get("score")), count=1,
        rationale="Team record adjusted for preseason roster quality and coaching adaptability.",
    ))
    executive_rows = [
        {
            "name": f"{team} Basketball Operations",
            "team": team,
            "score": 100.0 * rate + 1.15 * (league_quality - team_quality.get(team, league_quality)),
        }
        for team, rate in win_rate.items()
    ]
    add(_honor(
        "executive_of_year", "Executive of the Year", "award", executive_rows,
        lambda row: _rate(row.get("score")), count=1,
        rationale="Team performance adjusted for inherited roster quality; organization-level where staff identity is unavailable.",
    ))
    return tuple(honors)


def postseason_performance(cycle: FranchiseSeasonRecord) -> dict[str, object]:
    regular = {int(row["player_id"]): row for row in aggregate_player_stats(cycle, stages={"regular_season"})}
    playoffs = aggregate_player_stats(cycle, stages={"playoffs"})
    comparisons: list[dict[str, object]] = []
    for row in playoffs:
        player_id = int(row["player_id"])
        baseline = regular.get(player_id)
        if baseline is None:
            continue
        playoff_games = int(row["games"])
        regular_games = max(1, int(baseline["games"]))
        playoff_score = _game_score(row) / max(1, playoff_games)
        regular_score = _game_score(baseline) / regular_games
        reliability = playoff_games / (playoff_games + 12.0)
        delta = reliability * (playoff_score - regular_score)
        label = "riser" if delta >= 1.0 else "faller" if delta <= -1.0 else "steady"
        comparisons.append({
            "player_id": player_id,
            "name": row["name"],
            "team": row["team"],
            "playoff_games": playoff_games,
            "regular_game_score": round(regular_score, 2),
            "playoff_game_score": round(playoff_score, 2),
            "adjusted_delta": round(delta, 2),
            "classification": label,
        })
    comparisons.sort(key=lambda row: float(row["adjusted_delta"]), reverse=True)
    return {
        "method": "Per-game box impact delta with n/(n+12) sample-size shrinkage",
        "risers": comparisons[:10],
        "fallers": list(reversed(comparisons[-10:])),
        "all": comparisons,
    }


def postseason_round_mvp(
    cycle: FranchiseSeasonRecord,
    round_name: str,
    *,
    teams: set[str] | None = None,
) -> Mapping[str, object] | None:
    rows = aggregate_player_stats(cycle, stages={"playoffs"}, round_name=round_name)
    if teams is not None:
        rows = [row for row in rows if str(row["team"]) in teams]
    if not rows:
        return None
    return max(rows, key=lambda row: _game_score(row) / max(1, int(row["games"])))
