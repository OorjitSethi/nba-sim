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
League-date advancement applies that recovery deterministically. Medical status
does not auto-clear when an expected-return date passes; that date is an
estimate, not clearance.

The load-concern index responds to rapid load increases, very low recent
preparation relative to chronic load, current fatigue, and availability status.
It is deliberately not called an injury probability. Available research finds
associations and substantial player-to-player variation, while the basketball
systematic review describes limited conclusive evidence for precise individual
risk prediction.

## Simulation integration

Matchup Lab accepts a Franchise save:

- out and doubtful players are inactive;
- managed players use their saved minute cap;
- explicit Matchup Lab restrictions can make a cap stricter, never looser.

The dashboard's **Use Franchise health** control sends the active save into the
same rotation-conditioning code used by ordinary manual absences.

## API

- `POST /api/franchise/initialize-health`
- `POST /api/franchise/update-health`
- `POST /api/franchise/record-workload`

## Accuracy boundary

The local data currently observes game minutes but not practice load, internal
load, sleep, soreness, biomechanics, medical imaging, or clinician assessment.
Those inputs must be user-entered or supplied through an appropriately licensed
source. The initial acute/chronic baseline is therefore an estimate based on the
prior-season role and is labeled with its confidence.

Research informing the structure and its caution:

- NBA game load, fatigue, and injury associations:
  <https://pmc.ncbi.nlm.nih.gov/articles/PMC6107769/>
- Basketball training-load systematic review:
  <https://pmc.ncbi.nlm.nih.gov/articles/PMC11431307/>
- IOC consensus on load and health monitoring:
  <https://bjsm.bmj.com/content/50/17/1043>
- 2026 NBA rest/load-management observational study:
  <https://pubmed.ncbi.nlm.nih.gov/42218310/>
