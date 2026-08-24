# Point-in-time data pipeline

## Time model

The warehouse separates two clocks:

- event time: when a game occurred, an injury report was issued, or a quote was
  observed;
- system availability time: when that source snapshot became eligible for a
  forecast.

Historical queries can require both clocks to precede a cutoff. Raw source
payloads are immutable and SHA-256 checked; normalized rows retain the snapshot
identity that produced them.

## Official NBA adapters

`sync-rosters` reads the official current player index and stores team membership
as an observation, rather than overwriting a canonical roster. `sync-games`
normalizes the official two-row-per-game league log into one game with a
conservative result-availability timestamp. Neutral-site rows are identified
without fabricating home court. `sync-injury` parses the NBA's continually
updated injury-report PDF by column coordinates and uses the timestamp embedded
in its filename.

`sync-schedule` snapshots the official season-wide schedule, including local
game date, UTC tip, venue, status, neutral-site flag, and team-TBD placeholders.
Schedule payloads are treated as complete-state observations: a point-in-time
query selects one whole latest snapshot so a removed or postponed entry cannot
survive by leaking in from an older edition. The release-state summary separately
counts preseason, regular-season, identified, and placeholder rows.

`sync-player-stats` snapshots the official Base, Advanced, and Bio tables
together. Current roster profiles use prior-season minutes, usage, assist and
rebound rates, pace, defensive rating, physical measurements, and counting
statistics. Observed shooting percentages are sample-size shrunk, then used to
recalibrate the existing spatial two/three-point zone profile. Players with no
prior-season observation retain an explicit replacement prior.

The injury adapter intentionally accepts an explicit URL. This preserves the
exact report edition used for a forecast and avoids silently substituting a newer
PDF.

For a scheduled-game forecast, injury rows are filtered to the official matchup
and resolved against the current roster by team and normalized player name.
`Out` is always inactive. `Probable`, `Questionable`, and `Doubtful` are sampled
with visible 85%, 50%, and 25% availability priors, respectively. These are
transparent scenario priors, not learned medical probabilities; every forecast
returns the matched rows, probabilities, distinct sampled scenario count, and
reproducible seed.

## Licensed market contract

`ingest-market` accepts CSV with:

```text
game_id,source,quote_timestamp,home_spread,total,home_moneyline_probability
```

The first five columns are required. Timestamps must be timezone-aware. A negative
home spread means the home team is favored. Queries select the latest quote no
later than the forecast cutoff.

## Licensed tracking contract

Each `.npz` contains one possession and is opened with `allow_pickle=False`.
Required arrays are:

```text
player_ids
team_indices
possession_team_index
positions_5hz
ball_positions_5hz
skeletons_30hz
shoulder_normals_5hz
event_labels_5hz
context_features
```

`sequence_id` should use `game_id:possession_id`. Neural training additionally
requires a scalar ISO `game_date` in every archive so whole games can be ordered
chronologically. Optional `model_hz` and `skeleton_hz` default to 5 and 30.

Ingest before training:

```bash
.venv/bin/nba-sim-data ingest-tracking \
  --directory /path/to/licensed-npz \
  --vendor provider-name \
  --season 2025-26 \
  --available-at 2026-04-13T00:00:00+00:00
```

Train SportsNGEN:

```bash
.venv/bin/nba-sim-data train-tracking \
  --directory /path/to/licensed-npz \
  --architecture sportsngen \
  --output checkpoints/sportsngen \
  --epochs 20 --seed 2026
```

CourtMotion also requires the licensed provider's joint topology:

```bash
.venv/bin/nba-sim-data train-tracking \
  --directory /path/to/licensed-npz \
  --architecture courtmotion \
  --skeleton-edges /path/to/skeleton-edges.json \
  --output checkpoints/courtmotion
```

No licensed source is bundled, and no checkpoint is considered eligible for
simulation until its untouched test metrics and downstream EPV ablation pass the
promotion protocol.
