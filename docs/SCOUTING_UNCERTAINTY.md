# Scouting and uncertainty

Phase six separates established-player knowledge from prospect uncertainty.
Current NBA players receive exact visible game ratings and never require
scouting. Draft prospects carry uncertain front-office beliefs.

## Belief state

Every draft prospect has a persistent scouting report containing posterior means and
standard deviations for offense, playmaking, defense, athleticism, overall, and
potential. The UI converts each normal approximation to a central 80% band. It
also stores observation hours, evaluation count, report date, source,
confidence, and a five-way archetype probability distribution.

Prospect reports are deterministic noisy priors anchored to available public
profiles. `scout_player` treats a new evaluation as a noisy observation and
performs a precision-weighted Bayesian update:

`posterior precision = prior precision + observation precision`

Additional evidence normally narrows the band, but the standard deviation has a
1.5-point floor. This prevents a department from manufacturing certainty from
repeated observations of an inherently uncertain player and career.

## Automatic department

Every franchise receives an automatic department with a weekly prospect-observation
budget, evaluation quality, priority, and risk profile. A cycle ranks unresolved
targets by uncertainty, current value, potential, age-stage fit, and department
settings, then updates ten reports with independent deterministic random
streams. The default is automatic and balanced; advanced users can pause or
retarget it.

Current endpoints:

- `POST /api/franchise/initialize-scouting`
- `POST /api/franchise/scouting-board`
- `POST /api/franchise/scout-player`
- `POST /api/franchise/run-scouting-cycle`
- `POST /api/franchise/update-scouting-department`

Initialization, prospect reports, department settings, and weekly cycles are immutable
ledger events and survive reloads and branches.

## Accuracy boundary

Established ratings are documented in
[`ESTABLISHED_PLAYER_RATINGS.md`](ESTABLISHED_PLAYER_RATINGS.md). The prospect
uncertainty mechanism is structurally Bayesian and reproducible, but the
present observation noise and department quality are transparent priors rather
than chronologically calibrated NBA scouting-performance estimates. Public
profiles do not substitute for licensed video, optical tracking, medical
records, workouts, interviews, or scout-level hit-rate histories.

Research supports the design boundary: Bayesian NBA player evaluation naturally
produces posterior uncertainty, while talent-identification research repeatedly
finds that prediction requires longitudinal, multidimensional, ecologically
valid evidence and careful validation. Therefore this phase exposes uncertainty
instead of claiming that a single scout grade reveals a player's true future.

Future draft and prospect-acquisition systems should use these reports;
established-player trades and free agency use exact current ratings. Scout
hiring, regional coverage, individual scout bias, workout
measurement, interview evidence, information leakage, and chronological
calibration remain future work.
