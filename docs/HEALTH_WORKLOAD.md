# Health and workload

Phase four adds a durable health state for every Franchise player. It is a
planning and simulation system, not a medical diagnosis tool.

## Canonical state

`PlayerHealthRecord` stores:

- availability: available, managed, questionable, doubtful, or out;
- body area, scenario context, expected return, and minute restriction;
- seven-day acute and 28-day chronic external-load estimates;
- fatigue, readiness, and relative load-concern indices;
- last recorded workload date, provenance, confidence, and model version.

New saves initialize complete league coverage. Older saves upgrade through one
hash-chained `player_health_initialized` event. Availability changes and workload
sessions are separate events, so the league can replay exactly why a player was
restricted.

## Load and recovery

A recorded session contributes:

`external load = session minutes × intensity multiplier`

Acute load, chronic load, and fatigue use different exponential recovery rates.
League-date advancement applies that recovery deterministically. User-entered
medical status does not auto-clear when an expected-return date passes; that date
is an estimate, not clearance. A simulated injury is different: it advances from
out to a five-day, 24-minute return-to-play ramp and then to available. That
automatic path is explicitly identified by its simulation provenance.

The load-concern index responds to rapid load increases, very low recent
preparation relative to chronic load, current fatigue, and availability status.
It is deliberately not presented as a standalone injury probability. Available research finds
associations and substantial player-to-player variation, while the basketball
systematic review describes limited conclusive evidence for precise individual
risk prediction.

## Seeded injury occurrence

After each detailed regular-season or playoff game, every player who appeared
receives one deterministic injury-occurrence draw. The hazard is bounded and uses:

- actual minutes in that game;
- known season age when available;
- current load concern and fatigue;
- a modest prior-injury multiplier;
- additional exposure during a managed return.

The draw uses a stream derived from the save seed, stable game ID, and player ID.
It cannot consume or reorder the possession engine's random numbers. Repeating the
same saved timeline therefore produces the same game and injury outcomes even
when same-day games run in parallel.

An occurrence records severity, body area, description, estimated return,
recovery state, and games missed. Day-to-day, minor, moderate, major, and severe
durations use explicit bounded priors; they are simulation categories rather
than diagnoses. Injuries are applied after the final, so they affect subsequent
games rather than retroactively changing the completed game's minutes.

## Simulation integration

Matchup Lab accepts a Franchise save:

- out and doubtful players are inactive;
- managed players use their saved minute cap;
- explicit Matchup Lab restrictions can make a cap stricter, never looser.

The dashboard's **Use Franchise health** control sends the active save into the
same rotation-conditioning code used by ordinary manual absences.

The Season Hub displays the user team's current and historical injury report.
The Health & Workload workspace provides the selected player's full saved injury
history, estimated return, recovery state, and games missed. Automatic roster
delegation re-optimizes after a completed simulation batch, so newly unavailable
players are removed from future plans.

## API

- `POST /api/franchise/initialize-health`
- `POST /api/franchise/update-health`
- `POST /api/franchise/record-workload`

## Accuracy boundary

The local data currently observes game minutes but not practice load, internal
load, sleep, soreness, biomechanics, medical imaging, or clinician assessment.
The simulator therefore does not fabricate unseen practice injuries. Those
inputs must be user-entered or supplied through an appropriately licensed source.
The initial acute/chronic baseline and injury-duration categories are modeled
priors and are labeled with their provenance; neither is a medical forecast.

Research informing the structure and its caution:

- NBA game load, fatigue, and injury associations:
  <https://pmc.ncbi.nlm.nih.gov/articles/PMC6107769/>
- Basketball training-load systematic review:
  <https://pmc.ncbi.nlm.nih.gov/articles/PMC11431307/>
- IOC consensus on load and health monitoring:
  <https://bjsm.bmj.com/content/50/17/1043>
- 2026 NBA rest/load-management observational study:
  <https://pubmed.ncbi.nlm.nih.gov/42218310/>
