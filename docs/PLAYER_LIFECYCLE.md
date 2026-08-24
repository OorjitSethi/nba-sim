# Player lifecycle

Phase three introduces a durable player-development foundation. Every new
Franchise save contains one `PlayerLifecycleRecord` per rostered player. Older
saves can add the same records through a single hash-chained
`player_lifecycles_initialized` event.

## Baseline state

Each record stores:

- season age and its provenance;
- offense, playmaking, defense, athleticism, and weighted overall;
- a potential mean and uncertainty scale;
- observed prior-season games and workload minutes;
- lifecycle stage, confidence, and model version.

Season age is taken from the stored official 2025-26 player-stat snapshot and
advanced one season for the 2026-27 save. The model does not infer an exact
birthday. Players without a measured age remain explicitly unknown.

Initial attributes are derived from the same player profile used by the game
simulator: shot mix and efficiency, usage, assists, turnovers, defensive impact,
blocks, speed, role, and expected minutes. These are simulation attributes, not
licensed NBA or NBA 2K ratings.

## Projection model

`nba-lifecycle-nonlinear.v1` samples a joint career path each season. It applies:

- nonlinear, attribute-specific aging curves;
- correlated and attribute-specific uncertainty shocks;
- opportunity and excessive-workload effects;
- balanced or specialized development focus;
- scenario-based injury burden;
- uncertainty contraction as a career is observed;
- age-, ability-, and injury-conditioned retirement risk.

Athleticism peaks earlier than playmaking in the prior. Growth is constrained by
the player's uncertain potential belief, while post-prime decline is nonlinear.
Unknown ages receive no age-specific growth, decline, or retirement effect.

The Player Development workspace runs 400 independent paths by default and
reports P10, median, and P90 outcomes. The projection is exploratory and does not
mutate the save. A fresh seed is generated for every run and returned with the
result.

## API

- `POST /api/franchise/initialize-lifecycle` upgrades an older save.
- `POST /api/franchise/project-lifecycle` projects one active player on the
  user-controlled team.

Projection inputs are `save_id`, `player_id`, `focus`, `planned_minutes`,
`injury_burden`, `seasons`, `paths`, and optional `seed`.

## Accuracy boundary

This first lifecycle phase is a research-informed structural prior. It is not yet
trained against the application's own longitudinal, point-in-time player panel.
The next accuracy step is chronological training and validation by archetype,
age, role, and playing-time history, followed by committed offseason progression
events. Medical injury burden is currently a user scenario, not a diagnosis.

Research informing the structure:

- Berry et al., Bayesian NBA aging curves:
  <https://pmc.ncbi.nlm.nih.gov/articles/PMC6690864/>
- Wakim and Jin, functional aging patterns:
  <https://arxiv.org/abs/1403.7548>
- de Moraes et al., nonlinear age effects in NBA performance:
  <https://doi.org/10.3389/fspor.2025.1693433>
