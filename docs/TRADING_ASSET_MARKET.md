# Trading and asset market

The Trade Center is a league-wide, event-sourced player and draft-asset market.
It evaluates three separate questions:

1. does each team own every proposed asset?
2. is the construction legal under the enabled league rules?
3. does each CPU front office value the return enough to accept?

A legal trade is not automatically accepted, and an accepted trade is not
necessarily value-neutral. The dashboard exposes these decisions separately.

## Trade Finder

Trade Finder is the guided default. A user can shop one controlled asset or a
package of up to six players and picks to every other team, or target a package
owned by one external club and ask for accepted constructions. Searches can
prioritize balanced value, winning now, youth, cap relief, or draft capital.

The result list contains only proposals that clear asset ownership, every
enabled league rule, salary/apron construction, and the partner's acceptance
model. Opening a result transfers its exact packages and frozen evaluation into
the advanced manual builder. A declined but legal manual offer can request the
partner's lowest-value executable counter construction from the user's
remaining assets. Candidate construction includes players, picks, mixed
packages, and up to four-asset returns rather than only one-for-one swaps.

## Multi-team routing

The advanced trade machine supports two, three, or four participating teams.
Every selected player and pick receives an explicit destination. The evaluator
then reconstructs incoming salary, outgoing salary, roster count, consideration,
Stepien coverage, timing restrictions, and front-office value separately for
every participant. A transaction can execute only when every enabled legality
gate and every CPU decision clears.

The final event stores explicit `from_team` and `to_team` movement for every
asset. This permits circular three-team trades and split routing without relying
on display order or an implied counterparty.

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

Elite-player scarcity is nonlinear. The value increase from 92 to 96 OVR is
intentionally much larger than the increase from 72 to 76. A package is valued
as a package rather than as an unrestricted sum: its best player carries full
weight while additional players receive diminishing consolidation weight. This
prevents several low-leverage rotation players from mechanically equaling a
superstar merely because their individual scores add up.

Contract value includes the current cap charge, expected production salary,
remaining team control, player-option risk, and modeled surplus or burden.
Future first-round value uses the original team's current strength rank as a
projected slot, regresses farther-out seasons toward league average, discounts
protections, and then applies the receiving front office's timeline and risk
tolerance. The model does not treat every future first as an identical token.

Each front office also derives a strength rank, average age, positional needs
and surplus, protected core, trade block, deadline urgency, patience, and risk
tolerance. Trading a protected core player adds a real premium; acquiring a
needed position or a young player on a rebuilding timeline adds team-specific
fit value. Distant picks are discounted differently by contenders and
rebuilders.

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

The trade model version is `trade-market-front-office.v3`.
