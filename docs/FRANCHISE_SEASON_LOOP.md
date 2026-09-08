# Franchise season loop

The Season Hub is the fourth playable release of the franchise rebuild. It owns
a durable 2026–27 basketball calendar inside each save instead of treating a
season simulation as a disposable report.

## Regular season

The generated calendar has 1,230 games. Every team plays 82 games, with 41 at
home and 41 away. Division opponents meet four times; conference and
cross-conference frequencies follow the encoded NBA structure. A team cannot be
scheduled twice on one date.

Users may continue through the next league day, their next team game, seven days,
or thirty days, or press **Sim entire regular season** to finish every remaining
game in one cancellable job. Each matchup runs one complete possession-level game. Before
tipoff the simulator applies the saved roster plan, inactive/G League assignments,
medical availability and minute limits, plus the saved chemistry and coaching
environment. There is no ensemble selection that pulls the realized score back
toward an average.

Every completed game stores its deterministic seed, score, possessions and native
player box score. Standings, point differential and player per-game leaders are
derived from those records rather than separately generated summaries. Opening a
completed team game returns the same persisted box score after save replay.

Workload is recorded from actual simulated minutes. After every final, the seeded
injury engine evaluates each appearance from minutes, known age, load, fatigue,
prior history, and managed-return status. Occurrences affect future availability,
persist their severity and expected return, count missed games, and recover through
a minute-limited ramp. Recovery advances with the calendar, and a roster plan in
automatic delegation mode is re-optimized after a simulation batch.

## Exact-game execution and progress

Long regular-season advances and postseason rounds run as resumable background
jobs. The interface polls lightweight job state and advances the batch bar after every completed game, including the
latest final, elapsed time, measured throughput and estimated time remaining. A
browser refresh reconnects to the same in-memory job. Safe cancellation discards
the uncommitted regular-season batch or in-progress playoff round. Fully completed
postseason rounds remain saved, so a save never contains half a series.

Games on the same date are independent because the schedule forbids a team from
playing twice that day. Those games are therefore distributed across CPU workers;
dates remain sequential so recovery, workload and future availability retain
their original chronological semantics. Per-game seeds are derived from the save
seed and stable game ID, results are sorted before workload is applied, and the
same seed produces byte-for-byte identical events and box scores regardless of
worker completion order.

Within a game, immutable lineup shot mix and defensive-pressure aggregates are
memoized. This removes millions of repeated reductions without changing the EPV
integration step, hazard equations, random draws, player models, rotations or
possession engine. The optimization therefore changes execution cost, not model
fidelity.

## Postseason

After the 1,230th game, each conference is seeded by win percentage and point
differential. Seeds 7–10 enter the NBA play-in structure. The resulting eight
teams play seeded best-of-seven rounds with the 2–2–1–1–1 home pattern. Play-in,
playoff and Finals games use the same event-level engine and save the same box
score detail as the regular season.

The Playoff Hub advances one round at a time or through every remaining round.
Each series stores a stable identity, seed, result, game number and clickable box
score. Conference champions, Eastern and Western Conference Finals MVPs, Finals
MVP and the NBA champion are written into the event ledger.

Regular-season honors are frozen when the Play-In begins and never consume
postseason statistics. The ballot model produces MVP, Defensive Player of the
Year, Rookie of the Year, Sixth Player, Most Improved, Clutch Player, Coach and
Executive awards; scoring, rebounding, assists, steals and blocks titles; three
All-NBA teams; two All-Defensive teams; and two All-Rookie teams. Its displayed
rationale identifies the production, availability, prior-quality and team-context
signals used by each selection. These are transparent simulation rules, not a
claim about the NBA's real voter ballots.

The playoff-performance view compares regular-season and postseason per-game box
impact, then shrinks the difference by `n / (n + 12)`. That exposes meaningful
risers and fallers without treating a one-game spike or slump as a stable trait.

## Offseason handoff

The completed postseason moves the branch into an eight-stage, server-owned
offseason checklist. Automatic league-office stages can prepare the lottery and
combine; manual Draft, contract, and free-agency decisions remain in their full
control rooms. Progression commits one deterministic year from saved workload and
injury history, and training camp rebuilds all 30 rotations.

Each request carries its expected stage, so a retry cannot duplicate work or skip
ahead. Opening night is gated by league-wide roster and plan integrity. The final
transition archives the completed season, updates the cap-year calendar and save
metadata, advances health, reviews front offices, and creates the next balanced
1,230-game schedule. See
[`OFFSEASON_STATE_MACHINE.md`](OFFSEASON_STATE_MACHINE.md).

## Persistence

The full schedule lives in the genesis state for new saves. Simulation events
store only newly completed regular-season games and health updates. Postseason
round events store the authoritative season snapshot because bracket state,
honors and series metadata advance together atomically. Replaying the hash chain
reconstructs identical standings, box scores, honors, bracket and champion.
