# Public playtest release

The public-experience layer makes one franchise league approachable without
forking the simulation into an easier or harder basketball model. A save stores
its experience configuration in the same hash-chained event ledger as roster,
contract, trade, health, draft, and season decisions.

## Start the dashboard

From the project folder:

```bash
.venv/bin/nba-sim-web
```

Open <http://127.0.0.1:8765>, choose **Franchise**, then create or load a league.
Open **Playtest & Settings** for onboarding, safety, and validation controls.

On the first visit in a browser, **Front Office School** opens automatically. Its
ten short steps use the Phoenix Suns to explain navigation, league creation, the
daily Season Hub loop, staff automation, trades and contracts, scouting and the
draft, simulation randomness, difficulty, and safety branches. The browser stores
a versioned first-run marker in local storage with a same-site cookie fallback, so
ordinary reloads do not reopen it. **Tutorial** in the top-right corner replays it
at any time. The final action selects PHX and prepares a new Suns franchise form;
it does not create or overwrite a save without the user's click.

## Experience presets

- **Guided GM** delegates the user team's organizational plan, roster plan, and
  draft scouting allocation to staff. Explanations and consequential-action
  confirmations are on by default.
- **Balanced** keeps automatic scouting and GM intelligence but changes the
  roster staff to recommendation mode.
- **Full control** makes the user team's GM mandate, rotation, and scouting
  allocation manual. The other 29 organizations remain autonomous.

The preset only changes delegation and presentation. It does not select a
different simulator.

## Transparent difficulty

- **Rookie** exposes maximum information and gives CPU trade negotiators a
  wider acceptance tolerance.
- **Pro** exposes complete values and uses the calibrated baseline negotiation
  tolerance.
- **Expert** presents qualitative front-office information and uses a tighter
  CPU negotiation tolerance.

Difficulty never changes established-player ratings, possession probabilities,
injuries, schedule context, generated seeds, or game outcomes for a given saved
state and seed. The serialized configuration explicitly reports a zero ratings
modifier.

## Safe experimentation

**Create safety branch** copies the active save at its exact revision. The new
timeline receives its own save identity and future ledger; the original branch
is never overwritten. The header save selector can move between branches.

Invalid actions return recovery guidance. A rejected request does not append an
event. Consequential trade execution can require confirmation, but legality and
CPU acceptance still run through the normal CBA and front-office engines.

## Readiness audit

The in-app audit is read-only. It checks:

1. the 30-team league shape and canonical player ownership;
2. deterministic hash-chain replay;
3. established ratings, player health, and 30-team GM coverage;
4. five-starter, 240-minute rotation invariants;
5. the 1,230-game, 82-per-team, 41-home schedule invariants;
6. completed game scores against native player box-score points;
7. contract coverage and known CBA transaction fixtures;
8. optional Trade Center readiness; and
9. save-specific scoring and possession plausibility after 30 completed games.

**Copy tester report** produces a compact report with the league name, branch,
team, revision, seed, readiness result, and every check. A useful bug report adds
the action attempted, expected behavior, visible error, and a screenshot.

## Recommended 20-minute external test

1. Create a Guided + Pro league for any team.
2. Open Season Hub and simulate through the next team game.
3. Inspect that game's player box score and current standings.
4. Create a safety branch named `Trade experiment`.
5. Initialize Trade Center, use Trade Finder, and open one accepted offer.
6. Change to Expert and verify the negotiation becomes qualitative while player
   ratings remain identical.
7. Return to Pro, complete or reject the experiment, and switch back to the
   original branch.
8. Run the readiness audit and copy its tester report.

## Repository verification

Run all dependency-light checks from the project folder:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

The public-experience tests additionally cover old-save compatibility, preset
persistence, staff delegation mapping, rating invariance across difficulties,
replay integrity, audit reporting, and the dashboard controls.
