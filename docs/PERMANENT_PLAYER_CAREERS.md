# Permanent player careers and retirement

Player progression now commits a complete career decision at the offseason
boundary. The decision is event sourced with the same seed and immutable league
history as the rest of the franchise save.

## Career-decision model

`nba-career-decisions.v1` uses a continuous retirement hazard rather than a
fixed-age cutoff. A known age supplies the baseline hazard; current overall,
season minutes, actual role relative to planned role, contract security, roster
market status, saved injury burden, team role clarity, cohesion, trust and morale
adjust it. Unknown ages receive no actual retirement draw because the simulator
does not invent an age.

Every eligible draw stores its probability, random draw, age, rating, games,
minutes, injury burden, reason and model version. Productive veterans can play
well beyond the typical retirement window because the result remains
probabilistic. Age 49 is the safety boundary for an active career record.

Retirement, lifecycle progression, active-roster removal, contract deactivation
and the transaction entry are committed in one `offseason_stage_advanced`
event. Retrying or reconnecting cannot apply the decision twice.

## Permanent identity and history

A retired player is marked `retired`; the player is never deleted. The original
ID, name, last team, position, lifecycle, decisions and transactions remain in
league state. Career totals and season lines are reconstructed from persisted
regular-season and playoff box scores. Saved award recipients remain attached to
the same player ID. This makes the career ledger auditable down to its games.

The career ledger appears in Player Development and reports actual retirements
separately from non-mutating career projections.

## Comebacks

For two offseasons after retirement, a sufficiently capable player age 40 or
younger can make a rare seeded comeback attempt. A successful reinstatement
places the player in free agency with no fabricated contract; the normal signing
and roster systems decide what happens next. Failed attempts are recorded but do
not change the roster.

## Limits

The model represents basketball-career behavior, not medical advice or a claim
about a named player's private intentions. Low-confidence inputs stay bounded,
and deterministic replay means identical save state and seed produce identical
decisions.
