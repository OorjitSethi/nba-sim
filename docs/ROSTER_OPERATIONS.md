# Roster Operations

Roster Operations is the third playable release of the public franchise rebuild
roadmap. Every franchise save carries a versioned plan for all 30 teams. The user
team's plan is visible and editable; the same saved data conditions Matchup Lab.

## Rotation model

The coach-medical optimizer ranks players from current normalized ability,
potential, age, expected role, readiness, workload concern, availability and the
selected organizational objective. The coaching profile controls rotation depth.
It then selects five starters and solves a bounded allocation that totals exactly
240 regulation minutes while respecting medical minute limits. Questionable and
high-load players receive conservative caps; doubtful and out players are removed.

The three delegation settings share one model and one state:

- **Staff handles it** re-optimizes after availability, workload, coaching and
  calendar changes.
- **Staff recommends** preserves the plan and reports medical or role conflicts.
- **I handle it** preserves the user's assignments and minute priorities.

The optimizer can be run on demand in every mode. It supports balanced, win-now,
and youth-development objectives.

## Persistent controls

Each assignment records depth slot, starter status, basketball role, target
minutes, roster designation and an optional role promise. Valid plans require at
least five available players, five starters and 240 team minutes. G League and
inactive assignments receive zero game-plan minutes. Role-promise conflicts are
surfaced in the staff room rather than silently ignored.

NBA roster limits are represented as 15 standard contracts plus up to three
two-way contracts. The interface also exposes the 50-game NBA active-list limit
for each two-way player. The current source roster universe may contain fewer
than the maximum; the limits are capacities, not synthetic filler players.

## Simulation integration

When **Use Franchise rotation & health** is enabled in Matchup Lab, saved target
minutes replace the base profile's expected-minute weights before the normal
availability conditioner runs. Inactive and G League players are excluded. Health
outs, medical caps and manual matchup overrides are then applied on top, so the
game always rebuilds a legal rotation rather than subtracting a fixed score value.

Roster movements invalidate stale plans and immediately rebuild the league's
depth charts from the new ownership state. Every initialization and user/staff
update is a hash-chained event and is verified during save replay.

## Data boundary

Readiness and workload concern are planning signals, not diagnoses. Automatic
decisions are deterministic from saved state and expose the staff's recommendation
instead of claiming medical certainty.

