# Trading and asset market

The Trade Center is a league-wide, event-sourced player and draft-asset market.
It evaluates three separate questions:

1. does each team own every proposed asset?
2. is the construction legal under the enabled league rules?
3. does each CPU front office value the return enough to accept?

A legal trade is not automatically accepted, and an accepted trade is not
necessarily value-neutral. The dashboard exposes these decisions separately.

## Configurable rule policy

Every encoded gate is stored as its own branch-specific toggle:

- salary matching;
- first-apron incoming-salary restrictions;
- second-apron salary aggregation;
- Stepien Rule;
- seven-draft-year pick horizon;
- recently signed player waiting periods;
- recently acquired player aggregation;
- extension-and-trade waiting periods;
- no-trade and one-year Bird consent;
- former-team reacquisition;
- asset consideration on both sides;
- roster limits;
- trade deadline;
- optional injured-player house rule;
- CPU acceptance; and
- CPU-to-CPU trading.

Disabling a rule does not remove it from the evaluation. The proposal returns an
explicit house-rule warning, and the setting is preserved by the franchise event
ledger and inherited by branches.

The injured-player rule defaults off. The NBA does not impose a general
prohibition on trading an injured player, so enabling it is deliberately labeled
as a house rule rather than a CBA restriction.

## Salary matching and aprons

The evaluator uses the official 2026–27 system levels:

- salary cap: $164.961 million;
- tax: $200.428 million;
- first apron: $209.015 million; and
- second apron: $221.686 million.

Below the cap, available cap room is included. Above the cap but below the first
apron, the expanded simultaneous traded-player formula is used. Above the first
apron, a team cannot take back more salary than it sends. A team above the
second apron also cannot aggregate multiple outgoing player salaries.

Authoritative `ContractRecord` values are used whenever loaded. The current
roster snapshot does not contain complete licensed contracts, so missing values
receive an explicitly labeled **modeled cap charge** based on current 25–99
ability and role. The UI never labels these modeled values as real contracts.

Official references:

- [2023 NBA–NBPA Collective Bargaining Agreement](https://nbpa.com/cba/)
- [NBA trade rules and waiting periods](https://www.nba.com/news/nba-trade-deadline-explained)
- [Official 2026–27 cap and apron levels](https://www.nba.com/news/nba-salary-cap-2026-27-season)

## Draft assets and Stepien

Initialization creates each team's own first- and second-round selection from
2027 through 2033. Existing ownership from the draft ecosystem is retained.
Every asset stores original and current ownership separately.

The Stepien evaluator applies the proposed outgoing picks to the complete
post-trade ledger and checks whether the team would lack a first-round
selection in consecutive future drafts. Acquired first-round selections count
as coverage. The seven-year horizon is enforced independently.

## Front-office valuation

Player trade value combines:

- normalized present ability;
- potential and age curve;
- rotation responsibility;
- receiving-team timeline;
- health availability;
- cap burden; and
- the receiving team's contender, balanced, or rebuilding posture.

Contenders put more weight on current impact and less on distant upside.
Rebuilding teams place more weight on youth, potential, and uncertain future
first-round picks. Draft-asset value reflects round, distance, protection, and
the uncertainty option value of future firsts.

These values govern decisions; they are not exposed as hidden player truth.
CPU acceptance allows a small negotiation band to avoid requiring meaningless
decimal equality.

## CPU-to-CPU market

The user's team is excluded from autonomous transactions. Other teams can trade
through either:

- a manual league trade cycle with a user-selected maximum; or
- an automatic, at-most-one-deal market check when the franchise calendar
  advances by at least seven days.

Candidate pairings prefer teams on different competitive timelines. Packages
can include players and future first-round compensation. Every proposal passes
through the same ownership, CBA, rule-toggle, and bilateral-acceptance engine as
a user proposal. Randomness is namespaced by league seed, date, and revision, so
the market is reproducible from the same branch.

## Atomic execution

`trade_completed` is one atomic event containing:

- a human-readable transaction record;
- every player movement;
- every draft-asset movement; and
- the frozen legality/valuation evaluation.

Replay updates player team assignment, active contract team, injury team,
pick ownership, and transaction history together. A stale proposal fails if
ownership changed before execution.

The trade model version is `trade-market-cba-2026-27.v1`.
