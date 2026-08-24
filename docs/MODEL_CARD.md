# Model card

## Intended use

NBA Sim is intended for research, scenario analysis, software testing, and
probabilistic basketball simulation. It can generate coherent games, compare
lineup assumptions, estimate distributions through Monte Carlo, and serve as a
training/evaluation harness for future tracking models.

It is not a betting oracle, medical tool, injury diagnosis system, or source of
official NBA statistics.

## Operational components

- Event-sourced game, possession, rotation, and box-score engines
- Semi-Markov EPV fallback
- Deterministic Monte Carlo
- Season and best-of-seven simulation
- Full 30-team fast-season simulation with retrievable game box scores
- Explicit inactive-player and minute-limit conditioning
- Heuristic macro prior plus minimum-KL ensemble reconciliation
- Dynamic Bayesian team ratings and Bayesian ridge RAPM
- Availability-conditioned game-day distributions with schedule-context gates
- Append-only bitemporal warehouse and source-snapshot provenance
- Official roster, game-log, and injury-report adapters
- Rolling-origin probabilistic scoring and paired-bootstrap comparison
- Licensed NPZ tracking contract and chronological neural-training harness

## Experimental components

The PyTorch CourtMotion and SportsNGEN modules are architecture implementations,
not pretrained models. They have shape and contract tests, but no bundled learned
parameters. The kinematic fallback is used when a trained trajectory model is not
injected.

CourtMotion is basketball-specific. SportsNGEN demonstrated its method on tennis
and qualitative football generation; applying its design to basketball is an
engineering hypothesis that requires basketball tracking validation.

## Training and evaluation data

The checked-in operational profile adapter still uses a 2023-24 legacy SQLite
artifact. The local ignored warehouse can be refreshed independently. On
2026-07-25 it contained a 589-player official 2026-27 league-roster observation, four
complete regular-season game-log snapshots (2022-23 through 2025-26), and one
19-row archived official injury-report snapshot. It also contained 582 completed
2025-26 official player-stat observations; 504 current roster players matched
those observations, 5 retained older historical profiles, and 80 used explicit
replacement priors.

The game-day base distribution uses the dynamic team-strength configuration
frozen before the 2025-26 test season. Current absences modify that distribution
through scenario-specific roster-profile deltas. A separate schedule-context
challenger uses rest, back-to-back, congestion, inferred travel, time zones, and
altitude. Its learned increment is disabled because it did not clear both strict
paired-bootstrap promotion gates on the 2025-26 holdout. Neutral-site home-court
removal is treated as a structural correction.

The repository does not distribute:

- licensed NBA optical or skeletal tracking sequences;
- multi-season point-in-time odds and game-outcome snapshots;
- trained neural checkpoints.

Prior-season player statistics improve the profile layer but do not encode
offseason development, rookie performance, coaching changes, or a finalized
opening-night rotation. Injury PDFs are report-time observations, not diagnoses.
Consequently, no claim of current-game superiority or state-of-the-art tracking
accuracy is made.

## Known limitations

- Legacy shot-zone data lacks attempt-count uncertainty, so efficiency is shrunk
  toward zone priors.
- Defensive and matchup information is coarser than modern optical data.
- Coaching schemes, referee crews, and injury severity are not learned from a
  historical causal model. Schedule-load features are observational and therefore
  cannot be interpreted causally.
- Aggregate fidelity can coexist with weak game-level discrimination.
- The current macro backtest omits a market baseline until licensed timestamped
  prices are supplied.
- Macro reconciliation is only as strong as its supplied target distribution.
- Rare NBA rulings and review sequences are not yet exhaustively encoded.
- A full League Sim requires 1,230 possession-level game realizations and remains
  compute-heavy. Its progress and ETA are estimates, and closing the local server
  terminates the in-memory job.
- League Sim represents one realized seeded season. A single season is not a
  probability estimate; use Matchup Lab's Monte Carlo or Hybrid mode for matchup
  distributions.
- Player lifecycle curves are currently research-informed structural priors, not
  chronologically trained estimates from a longitudinal in-app player panel.
  Injury burden is a scenario input, and players without official season age
  deliberately receive no age-specific growth, decline, or retirement effect.
- Health workload values are external-load planning indices. They omit internal
  load, practice tracking, sleep, symptoms, biomechanics, and clinician data.
  The load-concern score is not an injury probability, and an expected-return
  date is not medical clearance.
- Chemistry and coaching values are user scenario priors. Their game effects are
  bounded and deterministic but not yet chronologically trained causal estimates
  of real NBA coaches, locker rooms, or tactical systems.
- Scouting reports are reproducible Bayesian belief states, not observed truth.
  Initial noise, observation noise, and department quality are transparent
  structural priors until licensed scouting evidence and chronological
  department-level hit rates are available for calibration.
- Established-player OVRs blend a published 2K26 scale anchor, reliability-
  weighted current performance, and a one-season nonlinear age transition.
  They are simulator estimates, not official current 2K values or direct
  measurements of true ability. Spatial shooting attributes use stored zone
  evidence; unobserved physical and technique traits are transparent
  model-derived estimates.
- Draft prospects are fictional seeded model entities, not forecasts for named
  real-world amateurs. Their latent talent, public rankings, scouting noise, and
  CPU choices are structural distributions rather than a model trained on
  licensed historical scouting grades. Before a season result is committed, the
  draft's preliminary order uses roster strength instead of fabricated standings.
- Trade values are structural front-office utilities rather than prices fitted
  to a licensed transaction market. Missing authoritative contracts use clearly
  labeled modeled cap charges, which preserve rule functionality but are less
  reliable than imported contract data. CPU trades are deterministic conditional
  on the seed and branch, and sparse execution does not prove that a real NBA
  front office would make the same deal.

## Safe interpretation

Every forecast should be represented as a distribution, not a point certainty.
Inputs, data timestamps, code version, seed, lineup assumptions, and model
checkpoint must be retained. A new model should replace an existing one only after
chronological held-out scoring and paired baseline comparison.

## Research references

- CourtMotion: <https://arxiv.org/abs/2512.01478>
- SportsNGEN: <https://arxiv.org/abs/2403.12977>
- Bayesian NBA player impact: <https://arxiv.org/abs/1604.03186>
- Team-sport talent-identification methods: <https://pmc.ncbi.nlm.nih.gov/articles/PMC9227581/>
