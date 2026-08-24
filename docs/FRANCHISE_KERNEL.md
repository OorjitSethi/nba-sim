# Franchise kernel

Phase one establishes the authoritative state layer for long-horizon franchise
simulation. It intentionally does not invent missing contract, staff, exception,
injury, or draft-asset data.

## Canonical state

`LeagueState` contains:

- the cap-year and regular-season calendar;
- all 30 franchises and the user-controlled team;
- current player identities and team assignments;
- typed collections for staff, contracts, draft assets, cap exceptions,
  injuries, and transactions;
- a deterministic league seed;
- a revision number and hash-chain head.

Every typed record validates its team and player references when the state is
constructed or replayed. Phase-specific models can extend the records through
new schema versions without changing the event-store contract.

## Event sourcing

The genesis state is immutable. State changes are represented by ordered
`LeagueEvent` records. Each event contains:

- a deterministic ID;
- its sequence and effective league date;
- a UTC recording time and actor;
- a typed JSON payload;
- the previous event hash and its own SHA-256 hash.

Loading a save reconstructs the state by applying every event to the genesis
snapshot. The load fails if an event was changed, removed, reordered, or no
longer matches the persisted head revision.

Phase one supports league creation, branching, calendar advancement, and typed
registration events for staff, contracts, draft assets, cap exceptions,
injuries, and transactions.

Phase three adds `player_lifecycles_initialized`, which upgrades older saves with
validated player-linked lifecycle state without rewriting their genesis.

## Saves and branches

Saves live in `data/franchise_saves.sqlite`. A save stores a genesis snapshot,
its lineage, and an append-only event stream. Calendar changes are committed
immediately.

Branching takes the fully replayed state at an exact parent revision and uses it
as the child branch's genesis. Subsequent child events cannot modify the parent.
This supports counterfactual roster-building decisions without duplicating or
mutating the original timeline.

## Dashboard API

- `POST /api/franchise/saves`
- `POST /api/franchise/create`
- `POST /api/franchise/load`
- `POST /api/franchise/advance-date`
- `POST /api/franchise/branch`

Every loaded response includes roster data, the latest ledger entries, state
coverage, replay counts, revision, and verified ledger-head hash.

## Phase two: CBA and cap accounting

The franchise response now includes the official 2026-27 system levels and a
team cap-sheet coverage report. The versioned rules engine supports:

- salary-cap, minimum-payroll, tax, first-apron, and second-apron bands;
- current 2026-27 non-taxpayer, taxpayer, and room mid-level exceptions;
- standard, expanded, and aggregated traded-player matching paths;
- first- and second-apron hard-cap actions from the 2023 CBA transaction table;
- plain-language blockers, explanations, and explicit scenario assumptions.

`POST /api/franchise/cap-scenario` evaluates one team's proposed mechanism
without mutating the save. Contract coverage is honest by construction: when
current salaries have not been imported, known salary is never presented as
total payroll or available cap room.

## Phase three: player lifecycle

New saves include modeled lifecycle records for every player. The Player
Development workspace exposes current attributes, age provenance, potential
uncertainty, and multi-season scenario bands.

- `POST /api/franchise/initialize-lifecycle` upgrades an older save.
- `POST /api/franchise/project-lifecycle` runs a non-mutating seeded career
  scenario for one player.

The structural prior is nonlinear and attribute-specific. Opportunity, training
focus, workload, injury burden, correlated uncertainty, and retirement risk are
modeled explicitly. Unknown ages remain unknown and suppress age-specific
effects. See [`PLAYER_LIFECYCLE.md`](PLAYER_LIFECYCLE.md).

## Phase four: health and workload

Every player can now carry persistent availability, minute restriction, acute
and chronic external load, fatigue, readiness, and load-concern state.
`player_health_initialized`, `player_health_updated`, and
`player_workload_recorded` preserve the complete timeline. Calendar events apply
deterministic recovery, while expected return never acts as automatic medical
clearance.

Matchup Lab can apply the active Franchise health policy before allocating its
240 player-minutes. See [`HEALTH_WORKLOAD.md`](HEALTH_WORKLOAD.md).

## Phase five: chemistry and coaching

All teams now carry chemistry and coaching-strategy records. Environment
initialization, assessments, coaching plans, and shared sessions are replayable
events. Matchup Lab can independently enable their bounded tactical effects.
See [`CHEMISTRY_COACHING.md`](CHEMISTRY_COACHING.md).

## Phase six: scouting and uncertainty

Established NBA players now receive exact normalized 25–99 current ratings,
37 detailed attributes, and six spatial hot-zone evaluations. Draft prospects
carry front-office beliefs distinct from latent lifecycle state. Prospect
reports store attribute and potential distributions, evidence volume, freshness,
confidence, and archetype probabilities. A default automatic department
allocates weekly hours to high-value unresolved prospects, while advanced users
can set priorities or commission a manual report. See
[`ESTABLISHED_PLAYER_RATINGS.md`](ESTABLISHED_PLAYER_RATINGS.md) and
[`SCOUTING_UNCERTAINTY.md`](SCOUTING_UNCERTAINTY.md).

## Phase seven: draft ecosystem

A seeded 75-player class now persists hidden latent talent separately from
public consensus and the user's Bayesian scouting beliefs. Weekly department
cycles, manual observation, verified combine measurements, a private big board,
all 60 draft assets, the 2027 16-team 3-2-1 lottery, and every selection are
replayable events. CPU teams consume imperfect public information rather than
the user's report or latent truth. See
[`DRAFT_ECOSYSTEM.md`](DRAFT_ECOSYSTEM.md).

## Phase eight: trading and asset market

The league now supports executable player-and-pick trades. A branch-specific
policy can independently toggle every encoded CBA, roster, deadline, consent,
and simulation gate. CPU teams evaluate timeline-aware value and can trade
among themselves during manual market cycles or weekly calendar advances.
Accepted deals atomically move players, active contracts, injury ownership, and
draft rights before adding a replayable transaction record. See
[`TRADING_ASSET_MARKET.md`](TRADING_ASSET_MARKET.md).

## Remaining phase boundary

Contracts, staff, cap exceptions, injuries, and transactions have
validated canonical schemas and event reducers, but the initial 2026-27 save
does not populate records without authoritative inputs. Contract ingestion,
multi-team transaction routing, prior exception/hard-cap history,
chronologically trained lifecycle calibration, committed annual progression,
scout hiring and calibration, rookie signing, and free agency belong to later
phases.
