from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path
from typing import Sequence

from nba_sim.competition.season import (
    PlayoffSeriesSimulator,
    SeasonSimulator,
    round_robin_schedule,
)
from nba_sim.data.legacy import LegacySQLiteRepository
from nba_sim.domain.scenarios import condition_team_profile
from nba_sim.forecast.macro import HeuristicMacroModel
from nba_sim.forecast.reconcile import MomentReconciler
from nba_sim.simulation.game import GameSimulator
from nba_sim.simulation.monte_carlo import run_monte_carlo, simulate_ensemble
from nba_sim.validation.fidelity import FidelityGate, evaluate_legacy_league_fidelity


def _default_database() -> Path:
    configured = os.environ.get("NBA_SIM_DB")
    if configured:
        return Path(configured)
    return Path.cwd() / "ETL" / "nba_universe.db"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nba-sim",
        description="Calibrated event-sourced NBA simulation.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=_default_database(),
        help="path to the legacy SQLite database",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_teams = subparsers.add_parser("list-teams")
    list_teams.set_defaults(handler=_list_teams)

    simulate = subparsers.add_parser("simulate")
    _add_matchup_arguments(simulate)
    simulate.add_argument("--seed", type=int, default=0)
    simulate.add_argument("--events", action="store_true")
    simulate.set_defaults(handler=_simulate)

    monte_carlo = subparsers.add_parser("monte-carlo")
    _add_matchup_arguments(monte_carlo)
    monte_carlo.add_argument("--trials", type=int, default=1_000)
    monte_carlo.add_argument("--seed", type=int, default=0)
    monte_carlo.add_argument(
        "--workers",
        type=int,
        default=0,
        help="worker processes; 0 selects up to eight automatically",
    )
    monte_carlo.set_defaults(handler=_monte_carlo)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--games-per-matchup", type=int, default=2)
    validate.add_argument("--seed", type=int, default=0)
    validate.add_argument(
        "--raw-player-totals",
        type=Path,
        default=None,
        help="league_roster_raw.json used to construct per-team-game targets",
    )
    validate.set_defaults(handler=_validate)

    hybrid = subparsers.add_parser("hybrid")
    _add_matchup_arguments(hybrid)
    hybrid.add_argument("--trials", type=int, default=500)
    hybrid.add_argument("--seed", type=int, default=0)
    hybrid.add_argument("--workers", type=int, default=0)
    hybrid.set_defaults(handler=_hybrid)

    season = subparsers.add_parser("season")
    season.add_argument(
        "--teams",
        default=None,
        help="comma-separated abbreviations; defaults to every available team",
    )
    season.add_argument("--repeats", type=int, default=2)
    season.add_argument("--start-date", type=date.fromisoformat, default=date(2026, 10, 20))
    season.add_argument("--seed", type=int, default=0)
    season.add_argument("--include-games", action="store_true")
    season.set_defaults(handler=_season)

    series = subparsers.add_parser("series")
    series.add_argument("--higher-seed", required=True)
    series.add_argument("--lower-seed", required=True)
    series.add_argument("--best-of", type=int, default=7)
    series.add_argument("--seed", type=int, default=0)
    series.set_defaults(handler=_series)
    return parser


def _add_matchup_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--home", required=True)
    parser.add_argument("--away", required=True)
    parser.add_argument(
        "--home-out",
        default="",
        help="comma-separated inactive player IDs",
    )
    parser.add_argument(
        "--away-out",
        default="",
        help="comma-separated inactive player IDs",
    )
    parser.add_argument(
        "--home-minute-limits",
        default="",
        help="comma-separated PLAYER_ID:MINUTES caps",
    )
    parser.add_argument(
        "--away-minute-limits",
        default="",
        help="comma-separated PLAYER_ID:MINUTES caps",
    )


def _simulator(args: argparse.Namespace) -> GameSimulator:
    repository = LegacySQLiteRepository(args.db)
    home = condition_team_profile(
        repository.load_team(args.home),
        inactive_player_ids=_parse_ids(args.home_out),
        minute_limits=_parse_minute_limits(args.home_minute_limits),
    )
    away = condition_team_profile(
        repository.load_team(args.away),
        inactive_player_ids=_parse_ids(args.away_out),
        minute_limits=_parse_minute_limits(args.away_minute_limits),
    )
    return GameSimulator(
        home_team=home,
        away_team=away,
    )


def _parse_ids(value: str) -> tuple[int, ...]:
    if not value.strip():
        return ()
    try:
        return tuple(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as error:
        raise ValueError("inactive player IDs must be integers") from error


def _parse_minute_limits(value: str) -> dict[int, float]:
    if not value.strip():
        return {}
    result: dict[int, float] = {}
    try:
        for item in value.split(","):
            player_id, minutes = item.strip().split(":", maxsplit=1)
            parsed_id = int(player_id)
            if parsed_id in result:
                raise ValueError(f"duplicate minute limit for player {parsed_id}")
            result[parsed_id] = float(minutes)
    except ValueError as error:
        raise ValueError(
            "minute limits must use comma-separated PLAYER_ID:MINUTES pairs"
        ) from error
    return result


def _list_teams(args: argparse.Namespace) -> dict[str, object]:
    repository = LegacySQLiteRepository(args.db)
    return {"teams": repository.available_teams()}


def _simulate(args: argparse.Namespace) -> dict[str, object]:
    result = _simulator(args).simulate(seed=args.seed)
    return result.as_dict(include_events=args.events)


def _monte_carlo(args: argparse.Namespace) -> dict[str, object]:
    summary = run_monte_carlo(
        _simulator(args),
        trials=args.trials,
        seed=args.seed,
        workers=args.workers,
    )
    return summary.as_dict()


def _validate(args: argparse.Namespace) -> dict[str, object]:
    repository = LegacySQLiteRepository(args.db)
    raw_totals = args.raw_player_totals
    if raw_totals is None:
        raw_totals = args.db.parent / "raw_data" / "league_roster_raw.json"
    report = evaluate_legacy_league_fidelity(
        repository,
        raw_player_totals_path=raw_totals,
        games_per_matchup=args.games_per_matchup,
        seed=args.seed,
    )
    payload = report.as_dict()
    payload["gate"] = FidelityGate().evaluate(report).as_dict()
    return payload


def _hybrid(args: argparse.Namespace) -> dict[str, object]:
    simulator = _simulator(args)
    target = HeuristicMacroModel().predict(
        home_team=simulator.home_team,
        away_team=simulator.away_team,
    )
    results = simulate_ensemble(
        simulator,
        trials=args.trials,
        seed=args.seed,
        workers=args.workers,
    )
    reconciled = MomentReconciler().reconcile(results, target)
    return reconciled.as_dict()


def _season(args: argparse.Namespace) -> dict[str, object]:
    repository = LegacySQLiteRepository(args.db)
    if args.teams is None:
        abbreviations = repository.available_teams()
    else:
        abbreviations = tuple(
            abbreviation.strip().upper()
            for abbreviation in args.teams.split(",")
            if abbreviation.strip()
        )
    if len(abbreviations) != len(set(abbreviations)):
        raise ValueError("teams must be unique")
    teams = {
        abbreviation: repository.load_team(abbreviation)
        for abbreviation in abbreviations
    }
    schedule = round_robin_schedule(
        abbreviations,
        start_date=args.start_date,
        repeats=args.repeats,
    )
    return SeasonSimulator(teams=teams, schedule=schedule).simulate(
        seed=args.seed
    ).as_dict(include_games=args.include_games)


def _series(args: argparse.Namespace) -> dict[str, object]:
    repository = LegacySQLiteRepository(args.db)
    simulator = PlayoffSeriesSimulator(
        higher_seed=repository.load_team(args.higher_seed),
        lower_seed=repository.load_team(args.lower_seed),
        best_of=args.best_of,
    )
    return simulator.simulate(seed=args.seed).as_dict()


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        payload = args.handler(args)
    except (FileNotFoundError, KeyError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
