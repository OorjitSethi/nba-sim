# General Manager Intelligence

General Manager Intelligence is the fifth playable release of the franchise
rebuild. It gives every team a durable organizational plan instead of deriving a
temporary contender/rebuilder label only when a trade is opened.

## Persistent organizational state

Each of the 30 teams stores a versioned plan containing:

- a contend, compete, retool, or rebuild direction;
- current modeled strength rank, known average age, win target, and a one-to-five
  season evaluation horizon;
- ownership patience, budget willingness, market size, payroll ceiling, and
  general-manager job security;
- risk tolerance and normalized priorities for present wins, development, cap
  flexibility, and draft capital;
- a protected core, active trade block, positional needs, live change triggers,
  audit rationale, and the reason for the latest review.

The state is event sourced. Initialization, league reviews, and a user's manual
mandate are separate hash-chained events, so every branch replays the same plan
and decision context.

## Automatic review model

The automatic audit combines roster strength, actual record, recent ten-game
form, age curve, payroll, ownership spending tolerance, roster balance, health,
and the current competitive window. Small samples do not cause a patient
organization to reverse direction: prior plans receive hysteresis until enough
games or a sufficiently large strength change supplies contrary evidence.

Reviews occur after season checkpoints, weekly calendar advances, completed
trades, and the postseason. Manual review is also available from the interface.
A manual mandate freezes the user's direction, horizon, and priorities while
the other 29 automated teams continue to adapt.

## Trade-market integration

The Trade Center consumes the persisted plan directly. Direction maps to the
team's contender, balanced, or rebuilding valuation curve. Risk tolerance,
ownership patience, job security, win-now priority, protected core, trade block,
and roster needs influence:

- player and draft-pick value for that specific receiving team;
- the premium required to move a core player;
- willingness to move a listed player;
- negotiation tolerance and counteroffer construction;
- deadline urgency and CPU-to-CPU market behavior.

There is no hidden ratings boost or difficulty exception. The plan displayed in
Front Office AI is the same persisted input read by the transaction engine.

## User experience

The default view explains the current mandate through a compact priority chart,
ownership constraints, live triggers, protected assets, and the complete league
strategy table. Automatic mode is the recommended consumer experience.

Advanced controls let the user choose a manual direction, planning horizon, and
four priority weights. Submitted weights are normalized, so the interface cannot
create an invalid plan by entering values that do not total exactly 100.
