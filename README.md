# NBA Sim

[![tests](https://github.com/OorjitSethi/nba-sim/actions/workflows/tests.yml/badge.svg)](https://github.com/OorjitSethi/nba-sim/actions/workflows/tests.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB.svg)](https://www.python.org/)

NBA Sim is a reproducible basketball simulation and forecasting engine built
around possessions, players, and events—not a box-score allocator. A single
seeded event stream drives the clock, score, play-by-play, and every player box
score, making a game replayable and its outputs internally consistent.

The project combines a rules-aware game engine, Monte Carlo and season
simulation, point-in-time forecasting, franchise state, and an experimental
multi-agent spatial layer. It also includes a localhost dashboard for exploring
matchups, availability scenarios, seasons, playoff series, and franchise
decisions.

> This is an independent research project and is not affiliated with or endorsed
> by the NBA or its teams. The repository does not include downloaded NBA data,
> licensed tracking data, or trained spatial-model weights.

## Why it is different

- **Possession-level coherence.** Scores, events, fouls, substitutions, and box
  scores are produced together instead of being sampled independently.
- **Spatial state is a first-class interface.** The experimental layer represents
  all ten players and the ball, constructs leakage-safe next-step datasets, and
  supports bounded multi-agent rollouts and optional neural architectures.
- **Research reproducibility.** Named random streams, event replay, immutable raw
  snapshots, checksums, and point-in-time queries make assumptions inspectable.
- **Honest model boundaries.** Aggregate simulation fidelity is kept separate
  from predictive forecasting skill, and untrained spatial architectures are not
  presented as validated models.
- **Long-horizon state.** Franchise saves use hash-chained events and deterministic
  replay for branching timelines, player development, health, scouting, drafts,
  trades, chemistry, and CBA checks.

NBA Sim is therefore aimed at model inspection and counterfactual research. It
does not try to replace the graphics or real-time controls of games such as NBA
2K; its advantage is that the simulation state, uncertainty, and assumptions are
available to inspect and test.

## Implemented system

| Layer | Capabilities |
| --- | --- |
| Game engine | Regulation and overtime, 24/14-second clocks, turnovers, fouls, bonus free throws, rebounds, substitutions, foul-outs, play-by-play, and reconciled box scores |
| EPV | Semi-Markov possession model with competing terminal hazards and clock-bounded holding times |
| Simulation | Deterministic single games, Monte Carlo distributions, schedules, seasons, and best-of series |
| Forecasting | Dynamic Bayesian team strength, regularized adjusted plus-minus, macro margin/total priors, and minimum-KL reconciliation |
| Scenarios | Injuries, inactive players, minute limits, neutral sites, rest, travel, congestion, altitude, and availability ensembles |
| Spatial research | Joint player/ball state, kinematic rollouts, discretized offset sampling, grouped chronological datasets, CourtMotion-style and SportsNGEN-style PyTorch modules |
| Validation | League-fidelity gates, rolling-origin backtests, log loss, Brier score, calibration error, bootstrap intervals, and baseline comparisons |
| Data | Append-only raw snapshots, bitemporal availability, provenance checksums, official-data adapters, and contracts for licensed market/tracking imports |
| Franchise | Event-sourced saves, CBA rules, lifecycle projections, health/workload, chemistry, scouting, draft, and trade simulation |
| Interface | CLI plus a dependency-light localhost dashboard and JSON API |

## Quick start

```bash
git clone https://github.com/OorjitSethi/nba-sim.git
cd nba-sim
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Generate the deterministic demonstration database:

```bash
nba-sim-demo
```

This creates fictional, non-authoritative profiles under `ETL/` so the engine
and dashboard can be tried without downloading or redistributing a sports
dataset.

```bash
nba-sim list-teams
nba-sim simulate --home UTA --away MEM --seed 7
nba-sim monte-carlo --home UTA --away MEM --trials 1000 --seed 7
nba-sim hybrid --home UTA --away MEM --trials 1000 --seed 7
```

Every fixed-seed command is reproducible. Matchup commands also accept
`--home-out`, `--away-out`, and `PLAYER_ID:MINUTES` minute-limit lists.

## Dashboard

```bash
nba-sim-web
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). The local interface includes:

- possession-level matchup results, distributions, box scores, and event logs;
- player-out and minute-limit counterfactuals;
- round-robin seasons, playoff series, and a full 1,230-game NBA schedule shape;
- rolling-origin backtest and league-fidelity views;
- availability-aware game-day forecasts when official snapshots are present;
- branching franchise saves with development, health, chemistry, scouting,
  draft, cap, and trade workspaces.

Full-league simulation is intentionally compute-heavy. The dashboard runs it as
a cancellable background job and reports progress, active matchup, elapsed time,
ETA, and the reproducibility seed.

The server binds to localhost and has no production authentication layer. Do not
expose it directly to the internet.

## Spatial research layer

The checked-in spatial subsystem is an experimental interface rather than a
trained NBA forecast model. It implements:

- joint frames for ten players and the ball;
- court-bounded state validation and deterministic kinematic rollouts;
- player/ball object tokens and next-step offset targets;
- game-grouped and chronological splits that prevent possession leakage;
- seeded noise preparation and nucleus sampling;
- optional PyTorch models inspired by
  [CourtMotion](https://arxiv.org/abs/2512.01478) and
  [SportsNGEN](https://arxiv.org/abs/2403.12977).

CourtMotion motivates skeletal graph and trajectory/event heads. SportsNGEN
motivates causal multi-agent object modeling and autoregressive bounded offsets.
Neither the architecture definitions nor the samplers become validated forecast
models until trained on appropriately licensed tracking data and promoted on a
held-out evaluation.

```bash
python -m pip install -e '.[tracking]'
```

## Data pipeline

The public repository intentionally excludes local SQLite warehouses, raw API
responses, market files, tracking archives, and model checkpoints. To use the
official-data adapters:

```bash
python -m pip install -e '.[data]'
nba-sim-data sync-rosters --season 2026-27
nba-sim-data sync-schedule --season 2026-27
nba-sim-data sync-player-stats --season 2025-26
nba-sim-data inventory
```

Historical and licensed sources are handled through explicit contracts. Raw
payloads retain retrieval time, source availability time, schema version, rights
tier, and checksum. See [the data pipeline](docs/DATA_PIPELINE.md) before
importing or sharing data.

Use `NBA_SIM_DB=/path/to/nba_universe.db` or `nba-sim --db ...` to select a
different compatible profile database.

## Validation boundaries

The test suite contains 130 deterministic tests covering event replay, clock and
box-score invariants, reproducibility, schedules, probabilistic scoring,
point-in-time data, spatial datasets, franchise replay, and dashboard services.

Recorded local experiments using non-bundled historical data include:

- a fixed-seed 2023-24 aggregate ecology audit over 75 games / 150 team-games
  with 2.23% mean absolute percentage error and 5.78% maximum error across 12
  per-team-game statistics;
- a frozen 2025-26 rolling-origin holdout of 1,230 games where the dynamic
  candidate improved log loss over a margin-aware Elo baseline (0.5955 vs.
  0.6023; paired-bootstrap interval for the difference
  `[-0.0133, -0.0007]`);
- a schedule-context challenger whose holdout intervals did not clear zero, so
  its learned schedule effects remain withheld.

The first result measures aggregate simulation fidelity, not game-level
prediction. The strict forecast promotion gate also considers margin accuracy,
so one improved metric does not automatically promote a candidate. Full protocol
and caveats are in [VALIDATION.md](docs/VALIDATION.md) and
[MODEL_CARD.md](docs/MODEL_CARD.md).

## Tests

```bash
python -m pip install -e '.[dev]'
nba-sim-demo
python -m unittest discover -s tests -v
```

The optional PyTorch architecture has dependency-aware contract tests. Neural
training and GPU integration are not part of the default CI job.

## Architecture

```text
CLI / local dashboard / JSON API
                |
     scenario and data adapters
                |
  point-in-time forecast + reconciliation
                |
      possession/game simulator
                |
   event log -> score -> player box scores
                |
  validation, seasons, and franchise replay

Optional tracking corpus -> spatial model interface -> bounded rollout
```

## Project layout

```text
src/nba_sim/
  competition/  schedules, seasons, and playoff series
  data/         provenance, official adapters, and point-in-time storage
  domain/       rules, profiles, scenarios, events, and game state
  epv/          semi-Markov possession hazards and expected value
  forecast/     distributions, ratings, priors, and reconciliation
  franchise/    durable league state, CBA, lifecycle, scouting, draft, trades
  simulation/   possessions, rotations, games, box scores, and Monte Carlo
  spatial/      multi-agent state, datasets, samplers, and neural interfaces
  validation/   fidelity gates and probabilistic backtesting
  web_assets/   localhost dashboard
docs/           architecture, data, validation, and model documentation
tests/          deterministic unit and integration tests
```

## Status

NBA Sim is a working research prototype, not a production betting system or a
medical decision tool. Forecast quality depends on the provenance and timing of
the supplied data, while the spatial architectures require licensed training
data and held-out validation.
