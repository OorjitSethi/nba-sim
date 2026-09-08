# Deterministic offseason state machine

The Offseason Hub connects a completed NBA Finals to the next regular season
through eight ordered, event-sourced checkpoints:

1. awards and lottery;
2. combine and scouting;
3. NBA Draft;
4. contract decisions;
5. free agency;
6. player progression;
7. training camp; and
8. next-season opening.

The server, not the browser, owns the current stage. Every request includes the
stage the user saw. If that exact stage was already completed, a retry returns
the current state without writing another event. A stale request cannot skip a
stage.

League-office work is automatic where it is deterministic. The first stage can
create the current draft class and lock the lottery; the second can run the
combine. Draft selections, contract choices, and free-agent decisions continue
to use their full control rooms. The interface links directly to the relevant
workspace and displays the unresolved gate.

Player progression commits one seeded draw from the same nonlinear lifecycle
model used by career projections. Actual saved minutes supply opportunity and
workload; saved games missed supply injury burden. The same atomic transition
records permanent career decisions, retires contracts and roster spots when
necessary, and retains retired player identities and histories. Retrying the
checkpoint does not apply a second year of development or a second retirement.
See [`PERMANENT_PLAYER_CAREERS.md`](PERMANENT_PLAYER_CAREERS.md).

Training camp reconstructs all 30 depth charts. Opening night is blocked unless
every team has a legal active-roster count and a complete saved plan. The final
transition archives the completed season, advances health to the new cap year,
creates a deterministic 1,230-game schedule, updates save metadata, and reviews
all automatic front offices.

Each save can contain at most 100 seasons: up to 99 archived seasons plus the
active year-100 season. Permanent career continuity is now attached to that
annual handoff; generated future-player populations build on the same checkpoint.
