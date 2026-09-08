# Franchise rebuild roadmap

The rebuilding game is organized as six playable releases. The default
experience automates specialist work and explains consequential decisions;
advanced controls remain available in the same save.

The Normal/Advanced interface release adds a remembered browser preference,
two primary destinations, five simple franchise tabs, a next-step home card,
automatic preparation of missing feature data, a checked free-agent offer flow
and a shorter Normal tutorial. It is an interface release; the simulation and
league rules are unchanged. See [`NORMAL_INTERFACE.md`](NORMAL_INTERFACE.md).

## Next priority order — century-scale league continuity

The next release sequence turns the completed single-season game into a living
league that can be played or simulated for as many as 100 seasons. **Go to year
100** means chronologically simulating every intervening game and offseason; it
never teleports the league forward or fabricates a year-100 snapshot.

### Priority 1 — Deterministic offseason and season rollover

The playable foundation is implemented as an eight-stage, event-sourced
Offseason Hub with stale-request protection, automatic lottery/combine
preparation, workload-conditioned progression, league-wide training camp,
season archival, roster gates and deterministic next-season scheduling. See
[`OFFSEASON_STATE_MACHINE.md`](OFFSEASON_STATE_MACHINE.md).

- Connect the existing awards, lottery, draft, contract decisions, free agency,
  progression, training camp, final cuts and schedule generation into one guided
  offseason state machine.
- Make every stage resumable, replayable and safe to retry without duplicating a
  signing, selection, retirement or season.
- Preserve user delegation: Guided mode can run routine stages automatically,
  while Full Control can stop at every consequential team decision.
- Create the next season only after league rosters, contracts, draft rights and
  cap sheets pass integrity checks.

### Priority 2 — Permanent player careers and retirement

This priority is playable. Offseason progression now applies deterministic
career decisions, atomic retirement and contract transitions, two-year rare
comeback eligibility, and a permanent game-derived career ledger. See
[`PERMANENT_PLAYER_CAREERS.md`](PERMANENT_PLAYER_CAREERS.md).

- Apply the existing attribute-specific development, prime and age-decline model
  at each season boundary, with injury history, workload, role, coaching and
  performance informing the distribution.
- Make retirement a seeded player decision driven by age, ability, health,
  demand, role satisfaction and career context—not a fixed age cutoff.
- Allow late-career decline, comeback attempts, unsigned retirement, medically
  driven retirement and rare productive longevity without erasing the player.
- Retired players leave active rosters but retain immutable identities, complete
  season/career statistics, awards, teams, transactions and draft provenance.

### Priority 3 — Calibrated generated draft classes

This priority is playable. Every future offseason creates a deterministic but
distinct 75-player population with calibrated outcome rarity, class-level
variance, team-specific evaluation noise, permanent draft provenance, modeled
rookie-scale contracts and an undrafted free-agent pool. See
[`DRAFT_ECOSYSTEM.md`](DRAFT_ECOSYSTEM.md).

- Generate a fresh class for every future draft with realistic class-to-class
  strength, positional supply, ages, physical measurements, archetypes and
  correlated skill profiles.
- Calibrate star, starter, rotation-player, replacement-level and non-NBA
  outcome frequencies; genuinely generational prospects remain rare rather than
  appearing every season.
- Preserve hidden latent talent, bust/sleeper variance, development uncertainty,
  team-specific scouting beliefs and imperfect CPU knowledge from the existing
  Draft and Scouting systems.
- Balance long-run incoming talent against retirement and roster demand without
  forcing every class toward the same average.
- Issue rookie-scale contracts and future pick ownership automatically, then
  carry every drafted and undrafted prospect through the normal career model.

### Priority 4 — Multi-season league economy and autonomous front offices

The economic foundation is playable. The complete CBA threshold set, modeled
market salaries, rookie scale, trade matching, cap bands, ownership budgets and
league-wide front-office reviews now advance with the active season. Future
figures are explicitly projected. See
[`MULTI_SEASON_LEAGUE_ECONOMY.md`](MULTI_SEASON_LEAGUE_ECONOMY.md).

- Roll cap levels, tax/apron thresholds, minimum salaries, exceptions, contract
  years and tradeable future-pick horizons forward every season.
- Let all 30 front offices change direction across contention, retooling and
  rebuilding cycles using ownership pressure, roster age, payroll, draft capital
  and recent results.
- Run realistic coaching changes, role competition, rotation rebuilding,
  extensions, free agency, waivers and CPU-to-CPU transactions each year through
  the same public rules used by the player's team.
- Prevent century-scale drift such as empty rosters, salary inflation detached
  from the cap, hoarded draft picks, permanent contenders or permanently inert
  CPU teams.

### Priority 4A — Optional local coach and general-manager minds

- Keep simulation outcomes, ratings, player value, CBA legality, roster limits,
  health and every acceptance threshold deterministic and fully testable.
- Add one optional local micro-model runtime serving 60 persistent identities:
  one coach and one general manager per team, each with separate philosophy,
  organizational memory, relationships, risk tolerance and competitive goals.
- Give those identities only structured, validator-approved choices. They may
  rank legal proposals, form plans, negotiate and explain decisions, but may
  never invent players, contracts, ratings, exceptions or transaction outcomes.
- Invoke models only at meaningful decision windows such as the draft, free
  agency, trade season, rotation reviews and coaching changes. Cache identical
  contexts and retain a deterministic fallback so long simulations never depend
  on model availability.
- Make the entire layer local-only and optional. Turning it off preserves the
  same underlying basketball and economic accuracy while using deterministic
  front-office policies for every choice.

### Priority 5 — One-to-100-season simulation runner

- Add **Sim to next season**, **Sim 5 seasons**, **Sim 10 seasons** and **Sim to
  year 100** actions, with 100 seasons as the hard career-universe limit for a
  save.
- Continue using the same possession-level game engine for every matchup; faster
  execution may remove repeated computation but may not switch to a lower-fidelity
  season model.
- Show an aesthetic nested progress view for current season, league date, game,
  offseason stage, overall century progress, elapsed time and estimated time
  remaining.
- Support cancel, resume and browser reconnection at safe checkpoints. Commit
  completed seasons atomically so interruption cannot create a half-finished
  offseason or corrupt the timeline.
- Permit opening any completed season, game, box score, draft, transaction or
  award while retaining a clear return path to the current league year.

### Priority 6 — League history, records and legacy

- Maintain single-game, single-season, career, franchise and playoff record
  books from persisted results rather than summary estimates.
- Add year-by-year champions, standings, brackets, award voting, All-NBA teams,
  draft histories, transactions, statistical leaders and franchise timelines.
- Track career totals, peaks, longevity, playoff performance and era context for
  Hall-of-Fame and jersey-retirement decisions without allowing legacy systems to
  alter on-court ratings.
- Make every historical page traceable to the original games and event ledger.

### Priority 7 — Long-horizon accuracy, performance and corruption testing

- Backtest generated career arcs, retirement ages, draft outcomes, league talent
  distribution, scoring environment, parity, payrolls and transaction rates
  against chronological NBA reference distributions.
- Run deterministic 1-, 10-, 50- and 100-season soak tests, including save,
  reload, branch, cancel and resume at every annual stage.
- Profile and parallelize only chronologically independent work, cache immutable
  calculations, and compact derived history without dropping box scores or
  changing random draws.
- Gate release on identical replay hashes, valid ownership, 30 legal rosters,
  balanced schedules, reconciled statistics and bounded economic/talent drift in
  year 100.

## Phase 1 — Front Office and Trade Finder

The trading game becomes a league market rather than a two-column calculator.

- Shop one player or pick across all 29 other front offices.
- Target a specific external player or pick and receive accepted constructions.
- Rank offers for balanced value, present contention, youth, cap relief, or
  draft capital.
- Derive each team's competitive window, strength rank, positional needs,
  surplus, protected core, trade block, urgency, patience, and risk tolerance.
- Apply core-player premiums and team-specific player/pick values.
- Explain roster fit, timeline fit, draft-capital preference, and protected-core
  resistance.
- Request a minimum executable counteroffer after a legal proposal is declined.
- Shop multi-asset packages, construct up to four-asset returns, and route players
  and picks through two-, three-, or four-team transactions.
- Apply nonlinear star scarcity, consolidation discounts, contract control,
  projected pick quality, protection, and front-office fit before acceptance.
- Run user and CPU-to-CPU trades through the same ownership, CBA, and bilateral
  acceptance engine.

## Phase 2 — Contracts and Free Agency

The playable Phase 2 foundation is implemented: complete modeled multi-year
ledgers, five-year cap projections, team/player option decisions, extensions,
waivers with dead money, an exception-aware free-agent negotiator, seeded player
preferences, and autonomous CPU roster reviews. See
[`CONTRACTS_FREE_AGENCY.md`](CONTRACTS_FREE_AGENCY.md).

The broader contract-rule horizon remains documented below as the target depth
for the full season/offseason loop:

- Multi-year guaranteed and non-guaranteed salary schedules.
- Team/player options, early termination options, incentives, trade bonuses,
  dead money, and stretch provision.
- Cap holds, Bird/Early Bird/Non-Bird rights, rookie rights, incomplete-roster
  charges, exceptions, tax, and both aprons.
- Extensions, restricted free agency, qualifying offers, offer sheets,
  moratorium, sign-and-trades, waivers, claims, and buyouts.
- Player preference models for money, role, market, contender status, loyalty,
  stability, coaching fit, and teammate fit.
- CPU cap planning across multiple seasons instead of one-transaction legality.

## Phase 3 — Roster Operations

The playable Phase 3 foundation is implemented: persistent league-wide depth
charts, five starters, bounded 240-minute rotations, NBA/two-way/G League/inactive
assignments, role promises, live staff recommendations, and automatic,
recommendation, or manual delegation. The coach-medical optimizer responds to
current ability, upside, age, coaching depth, readiness, workload, health and the
team's balanced, win-now, or development direction. Saved plans directly drive
Matchup Lab and rebuild safely after roster movement. See
[`ROSTER_OPERATIONS.md`](ROSTER_OPERATIONS.md).

## Phase 4 — Season and Offseason Loop

The playable season foundation is implemented: a persistent 1,230-game schedule,
one full event-level result per matchup, standings, point differential, saved box
scores, player leaders, workload feedback, the 7–10 play-in, seeded best-of-seven
playoffs, an interactive round-by-round bracket, per-game progress, full season
honors, conference and Finals MVPs, sample-adjusted playoff performance, and an
offseason handoff. See
[`FRANCHISE_SEASON_LOOP.md`](FRANCHISE_SEASON_LOOP.md).

The same checklist then connects the already-persistent Draft, contracts, free
agency, lifecycle and roster-operation systems into annual progression,
retirement, rookie-scale contracts, training camp, final cuts and the next season.

## Phase 5 — General Manager Intelligence

The playable Phase 5 foundation is implemented: all 30 teams have persistent
multi-year plans, ownership patience, budget willingness, market size, payroll
ceilings, job security, risk tolerance, normalized priorities, protected cores,
trade blocks, roster needs, change triggers, and audit explanations. Plans review
actual record, recent form, roster strength, age, payroll, health, depth and draft
capital with small-sample hysteresis. The exact saved plan drives team-specific
trade valuation, negotiation patience, core premiums, deadline urgency and CPU
market behavior. Automatic mode is the default; an advanced manual mandate is
available for the user's team. See
[`GENERAL_MANAGER_INTELLIGENCE.md`](GENERAL_MANAGER_INTELLIGENCE.md).

## Phase 6 — Public experience and validation

The playable Phase 6 release is implemented: Guided, Balanced, and Full Control
presets map directly to the existing GM, rotation, and scouting delegation
systems; contextual help and advanced settings remain optional; major moves can
require confirmation; and any revision can become an independent safety branch.
Rookie, Pro, and Expert difficulty change only information and CPU trade
negotiation tolerance, with an explicit zero ratings modifier. Keyboard-operable
dashboard tabs, visible focus, recovery guidance, and responsive public settings
complete the entry path.

The read-only release gate replays ledger integrity and audits 30-team ownership,
ratings, health, GM plans, rotations, the full schedule, box-score reconciliation,
contract coverage, CBA transaction fixtures, trade readiness, and save-specific
league plausibility. Its copyable tester report retains the exact branch,
revision, and seed. See
[`PUBLIC_PLAYTEST_RELEASE.md`](PUBLIC_PLAYTEST_RELEASE.md).

## Product rule

Automation never uses hidden exceptions. When the game makes a decision for the
user, it records the inputs and explains the result. Advanced mode exposes the
same underlying state and rules rather than switching to a different simulator.
