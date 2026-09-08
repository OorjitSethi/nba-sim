# Normal and Advanced interfaces

The top-bar preference is stored per browser under
`nba-sim-interface-mode-v1`. Normal is the default. It does not change the
simulation engine, accuracy settings, house rules, existing staff delegation or
saved roster. Advanced restores the specialist navigation and original controls.

Normal offers Play a game and Franchise. Matchups default to a single game and
put optional lineup controls in a disclosure. Franchise has Home, Calendar,
Stats, My team, Trade Finder, Free agency and Draft room. A responsive sidebar becomes
a compact menu on small screens. Home shows the team record, next game or
offseason step, availability updates, core players and upcoming schedule.
Its primary action uses the existing season simulation flow, and the
offseason action appears before historical season results. Standings, awards,
playoff brackets and leaders remain available in expandable sections.

My team presents player cards before optional manual rotation controls. Trade
Finder uses searchable checkboxes in Normal, synchronized with the existing
asset selector; selected assets stay visible in a summary even when filtered.
Advanced restores the original selector and full rotation table. No simulation,
valuation, rule or saved delegation settings are changed by switching modes.

Opening a feature on an older save prepares its missing system through the
existing initialization endpoint. Setup is serialized and results from a save
that is no longer selected are ignored. Draft lottery and combine preparation
remain in the existing Season offseason flow. Normal never waives players just
to manufacture a free-agent pool.

Normal free agency proposes a two-year deal at the player's current asking
price with a rotation role. The existing evaluation endpoint checks it before
the user confirms; signing still uses the existing signing endpoint. Rejected
offers show the reason and direct users to Advanced for custom negotiation.

The five-step Normal tutorial shares the existing first-visit memory and replay
button. Advanced retains the original ten-step tutorial. Keyboard navigation
skips hidden tabs.

## Manual verification

1. Select Normal, reload, and confirm only Play a game and Franchise appear.
2. Simulate one matchup and open its box score.
3. Load a franchise and inspect Home and all seven menu destinations. Open My team,
   expand manual adjustments, then switch to Advanced to verify the full table.
4. In Free agency, choose an available player and Make an offer. Check the cost
   and acceptance before confirming; cancelling must not sign anyone.
5. Select Advanced. Confirm all specialist screens and lineup controls return.
6. Replay Tutorial in each mode and check that it describes the visible screens.
7. In Trade Finder, clear the selection, search a player and check their box.
   Clear the search and select a pick. Confirm both appear in the selected summary
   and remain selected when switching to Advanced. Do not execute a trade merely
   to verify the interface.

## Stats central

Open Franchise → Stats in either mode. My team shows appearances for the selected
franchise, including players who subsequently left. Player stats combines each
player's season across teams; a team filter shows only that stint. Team stats
includes all 30 teams, with records, scoring, opponent scoring, rebounding,
playmaking, defensive stats and shooting. Switch between per-game and totals,
search, sort any numeric column, and click a player for game logs. The season
selector also includes archived seasons. Regular season, playoffs and play-in
are separate. Players who did not play do not count toward games played;
shooting percentages are calculated from total makes/attempts, not averaged
percentages. Zero attempts display a dash. No games are resimulated for stats.

Verification: 45 focused tests passed, including a saved-day simulation,
statistics aggregation, traded-player stints, stage separation, historical
selection and error handling. Browser checks verified the current save's stats,
player search and game logs, team totals and sorting, empty playoff results,
Advanced access and manual panels remaining open after interacting inside them.
The missing favicon now returns HTTP 200. The Normal/Advanced handlers target
only toggle buttons, preventing page-wide clicks from resetting the interface.

Browser verification covered Normal game completion, Advanced navigation,
preference persistence and loading an existing franchise. Existing dashboard and
public-experience tests passed (24 tests). No Python simulation or rules files
were changed for this interface release.
