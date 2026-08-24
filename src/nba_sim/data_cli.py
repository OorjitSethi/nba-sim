from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path
from typing import Sequence

from nba_sim.data.legacy import LegacySQLiteRepository
from nba_sim.data.licensed import (
    LicensedTrackingArchiveIngestor,
    MarketCsvIngestor,
)
from nba_sim.data.official_nba import (
    OfficialNBAInjuryIngestor,
    OfficialNBAStatsIngestor,
    _normalize_player_stats,
)
from nba_sim.data.point_in_time import PointInTimeWarehouse
from nba_sim.data.provenance import RawSnapshotStore
from nba_sim.spatial.training import (
    TrackingTrainingConfig,
    train_tracking_model,
)
from nba_sim.validation.backtest import default_backtester


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nba-sim-data",
        description="Point-in-time NBA data ingestion and backtesting.",
    )
    parser.add_argument(
        "--warehouse",
        type=Path,
        default=Path.cwd() / "data" / "nba_sim.sqlite",
    )
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=Path.cwd() / "data" / "raw",
    )
    parser.add_argument(
        "--legacy-db",
        type=Path,
        default=Path.cwd() / "ETL" / "nba_universe.db",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    rosters = subparsers.add_parser("sync-rosters")
    rosters.add_argument("--season", default="2026-27")
    rosters.set_defaults(handler=_sync_rosters)

    games = subparsers.add_parser("sync-games")
    games.add_argument("--season", action="append", required=True)
    games.set_defaults(handler=_sync_games)

    schedule = subparsers.add_parser("sync-schedule")
    schedule.add_argument("--season", default="2026-27")
    schedule.set_defaults(handler=_sync_schedule)

    player_stats = subparsers.add_parser("sync-player-stats")
    player_stats.add_argument("--season", default="2025-26")
    player_stats.set_defaults(handler=_sync_player_stats)

    reindex_player_stats = subparsers.add_parser("reindex-player-stats")
    reindex_player_stats.add_argument("--season", default="2025-26")
    reindex_player_stats.set_defaults(handler=_reindex_player_stats)

    injury = subparsers.add_parser("sync-injury")
    injury.add_argument("--season", required=True)
    injury.add_argument("--url", required=True)
    injury.set_defaults(handler=_sync_injury)

    market = subparsers.add_parser("ingest-market")
    market.add_argument("--csv", type=Path, required=True)
    market.set_defaults(handler=_ingest_market)

    tracking = subparsers.add_parser("ingest-tracking")
    tracking.add_argument("--directory", type=Path, required=True)
    tracking.add_argument("--vendor", required=True)
    tracking.add_argument("--season", required=True)
    tracking.add_argument(
        "--available-at",
        type=datetime.fromisoformat,
        required=True,
        help="timezone-aware ISO timestamp supplied by the license delivery",
    )
    tracking.set_defaults(handler=_ingest_tracking)

    train = subparsers.add_parser("train-tracking")
    train.add_argument("--directory", type=Path, required=True)
    train.add_argument(
        "--architecture",
        choices=("courtmotion", "sportsngen"),
        required=True,
    )
    train.add_argument("--output", type=Path, required=True)
    train.add_argument("--epochs", type=int, default=20)
    train.add_argument("--learning-rate", type=float, default=3e-4)
    train.add_argument("--seed", type=int, default=2026)
    train.add_argument("--device", default="auto")
    train.add_argument(
        "--skeleton-edges",
        type=Path,
        help="JSON array of [parent_joint, child_joint] pairs for CourtMotion",
    )
    train.set_defaults(handler=_train_tracking)

    inventory = subparsers.add_parser("inventory")
    inventory.set_defaults(handler=_inventory)

    backtest = subparsers.add_parser("backtest")
    backtest.add_argument(
        "--evaluation-start",
        type=date.fromisoformat,
        required=True,
    )
    backtest.add_argument("--evaluation-end", type=date.fromisoformat)
    backtest.add_argument("--bootstrap-samples", type=int, default=2_000)
    backtest.add_argument("--seed", type=int, default=0)
    backtest.add_argument("--include-records", action="store_true")
    backtest.set_defaults(handler=_backtest)
    return parser


def _components(
    args: argparse.Namespace,
) -> tuple[RawSnapshotStore, PointInTimeWarehouse]:
    return RawSnapshotStore(args.raw_root), PointInTimeWarehouse(args.warehouse)


def _sync_rosters(args: argparse.Namespace) -> dict[str, object]:
    snapshots, warehouse = _components(args)
    result = OfficialNBAStatsIngestor(
        snapshots=snapshots,
        warehouse=warehouse,
    ).sync_current_rosters(season=args.season)
    return result.__dict__


def _sync_games(args: argparse.Namespace) -> dict[str, object]:
    snapshots, warehouse = _components(args)
    ingestor = OfficialNBAStatsIngestor(
        snapshots=snapshots,
        warehouse=warehouse,
    )
    return {
        "results": [
            ingestor.sync_game_log(season=season).__dict__
            for season in args.season
        ]
    }


def _sync_schedule(args: argparse.Namespace) -> dict[str, object]:
    snapshots, warehouse = _components(args)
    result = OfficialNBAStatsIngestor(
        snapshots=snapshots,
        warehouse=warehouse,
    ).sync_schedule(season=args.season)
    return result.__dict__


def _sync_player_stats(args: argparse.Namespace) -> dict[str, object]:
    snapshots, warehouse = _components(args)
    result = OfficialNBAStatsIngestor(
        snapshots=snapshots,
        warehouse=warehouse,
    ).sync_player_stats(season=args.season)
    return result.__dict__


def _reindex_player_stats(args: argparse.Namespace) -> dict[str, object]:
    """Re-normalize verified local snapshots without making a network request."""
    snapshots, warehouse = _components(args)
    paths = sorted(
        path
        for path in (snapshots.root / args.season / "player-stats").glob(
            "*.json"
        )
        if not path.name.endswith(".manifest.json")
    )
    if not paths:
        raise FileNotFoundError(
            f"no local player-stat snapshot found for {args.season}"
        )
    records = 0
    for path in paths:
        snapshot = snapshots.load(path.relative_to(snapshots.root))
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = tuple(
            _normalize_player_stats(
                payload.get("base_per_game", []),
                payload.get("advanced_per_game", []),
                payload.get("bio_per_game", []),
                season=args.season,
            )
        )
        records += warehouse.ingest_player_stats(snapshot, rows)
    return {
        "dataset": "player-stats",
        "season": args.season,
        "snapshots": len(paths),
        "records": records,
        "network_requested": False,
    }


def _sync_injury(args: argparse.Namespace) -> dict[str, object]:
    snapshots, warehouse = _components(args)
    result = OfficialNBAInjuryIngestor(
        snapshots=snapshots,
        warehouse=warehouse,
    ).sync_pdf_url(args.url, season=args.season)
    return result.__dict__


def _ingest_market(args: argparse.Namespace) -> dict[str, object]:
    _, warehouse = _components(args)
    records = MarketCsvIngestor().ingest(args.csv, warehouse=warehouse)
    return {"dataset": "market-quotes", "records": records}


def _ingest_tracking(args: argparse.Namespace) -> dict[str, object]:
    snapshots, _ = _components(args)
    result = LicensedTrackingArchiveIngestor().ingest_directory(
        args.directory,
        vendor=args.vendor,
        season=args.season,
        available_at=args.available_at,
        snapshots=snapshots,
    )
    split = result.corpus.split()
    return {
        "dataset": "tracking",
        "vendor": result.vendor,
        "season": result.season,
        "sequences": result.sequences,
        "train_sequences": len(split.train),
        "validation_sequences": len(split.validation),
        "test_sequences": len(split.test),
        "snapshot_paths": [
            str(snapshot.data_path) for snapshot in result.snapshots
        ],
    }


def _train_tracking(args: argparse.Namespace) -> dict[str, object]:
    corpus = LicensedTrackingArchiveIngestor().load_directory(args.directory)
    skeleton_edges = None
    if args.skeleton_edges is not None:
        raw_edges = json.loads(args.skeleton_edges.read_text(encoding="utf-8"))
        if not isinstance(raw_edges, list):
            raise ValueError("skeleton edge file must contain a JSON array")
        try:
            skeleton_edges = tuple(
                (int(edge[0]), int(edge[1])) for edge in raw_edges
            )
        except (IndexError, TypeError, ValueError) as error:
            raise ValueError(
                "skeleton edges must be [parent_joint, child_joint] pairs"
            ) from error
    report = train_tracking_model(
        corpus,
        output_directory=args.output,
        config=TrackingTrainingConfig(
            architecture=args.architecture,
            epochs=args.epochs,
            learning_rate=args.learning_rate,
            seed=args.seed,
            device=args.device,
        ),
        skeleton_edges=skeleton_edges,
    )
    return report.as_dict()


def _inventory(args: argparse.Namespace) -> dict[str, object]:
    _, warehouse = _components(args)
    return {"snapshots": warehouse.snapshot_inventory()}


def _backtest(args: argparse.Namespace) -> dict[str, object]:
    _, warehouse = _components(args)
    repository = LegacySQLiteRepository(args.legacy_db)
    profiles = {
        abbreviation: repository.load_team(abbreviation)
        for abbreviation in repository.available_teams()
    }
    games = warehouse.games(
        end_date=args.evaluation_end,
    )
    report = default_backtester(
        profiles,
        bootstrap_samples=args.bootstrap_samples,
        bootstrap_seed=args.seed,
    ).run(
        games,
        evaluation_start=args.evaluation_start,
        evaluation_end=args.evaluation_end,
    )
    return report.as_dict(include_records=args.include_records)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        payload = args.handler(args)
    except (FileNotFoundError, ImportError, KeyError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
