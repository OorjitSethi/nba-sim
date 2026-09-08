# Draft ecosystem

The draft ecosystem is a persistent, event-sourced annual draft population and
two-round selection engine. It deliberately separates three quantities that
franchise games often collapse into one rating:

1. **latent player state** — ability, ceiling, durability, and development variance;
2. **public consensus** — a noisy market prior that drives the initial order;
3. **team belief** — the user's Bayesian scouting report and private big board.

The browser receives only the third quantity. Latent offense, playmaking,
defense, athleticism, overall, potential, and the noisy public-score input are
stored in the local save but omitted from every draft API response.

## Reproducible class generation

A class seed deterministically generates 75 fictional prospects. There is no
forced star. A calibrated mixture makes generational prospects rare, then
supplies franchise, All-Star, starter, rotation and fringe latent bands at much
more common rates. A class-level shock creates genuinely weak, average, strong,
and exceptional cohorts without forcing every year toward one mean.

Position and age use weighted populations. Correlated offense, playmaking,
defense, and athleticism are conditioned by position and archetype; potential,
durability and development variance remain distinct. Public consensus blends
present ability, upside, and larger observation noise. The same seed yields the
same population, reports, names, measurements, class outlook and initial board.
The UI's class-strength label is public consensus, not a leak of latent talent.

All 60 own-team draft assets are created with the class. Existing assets with the
same year, round, and original team are preserved, so imported traded-pick
ownership can supersede the generated default.

## Scouting

Initial reports are uncertain Bayesian priors. A manual workout combines the
prior with a noisy observation whose variance depends on hours and department
quality. The posterior can move in either direction while normally narrowing.

The automatic weekly department selects up to ten undrafted targets using:

- current uncertainty;
- estimated upside;
- youth/draft priority;
- the department's risk setting; and
- the weekly-hours budget.

The combine adds a standardized four-hour evaluation to every prospect and
reveals verified height, wingspan, and weight. Physical measurements are hidden
before that event.

## 3-2-1 lottery

The engine implements the NBA format approved for the 2027 through 2029 drafts:

- 16 lottery teams and all 16 positions drawn;
- three draft-relegated teams receive two balls each;
- the next seven non-play-in teams receive three balls each;
- four 9/10 play-in seeds receive two balls each;
- two 7/8 play-in losers receive one ball each; and
- the three draft-relegated teams cannot fall below pick 12.

The 37-ball weighted draw samples without replacement. A constrained projection
enforces the pick-12 floor while retaining the original relative draw order as
closely as possible. The user interface displays the resulting order and ball
counts.

Until a franchise season result is committed to the save, current roster
strength supplies the preliminary weakest-to-strongest ordering. This is labeled
as a projection in the interface rather than presented as standings.

The NBA's consecutive high-pick restrictions require prior lottery history. The
current class does not invent that history; the drawing is therefore governed by
the ball allocation and pick-floor rules above.

Primary rule references:

- [NBA Board of Governors approval, July 15, 2026](https://pr.nba.com/nba-board-of-governors-approves-new-draft-lottery-system-to-address-tanking/)
- [NBA 3-2-1 lottery explainer](https://www.nba.com/news/what-nba-had-in-mind-with-draft-lottery-reform)

## Draft room

The order contains 60 `DraftSlotRecord` values, preserving original and current
ownership separately. CPU teams select from remaining players using imperfect
public information, their department's evaluation quality and risk tolerance,
their positional strength, and stable team/pick decision noise. They cannot read
the user's private report or latent truth.

The user's team can select only when it owns the current slot. “Sim to my next
pick” advances CPU selections until the next owned slot, and every selection is
appended to the franchise hash chain. Replaying or branching the save restores
the exact class, reports, board, lottery, and selections.

The final selection atomically materializes the entire class. Sixty drafted
players receive permanent player, lifecycle, health and scouting identities,
team ownership, projected rookie roles, and modeled rookie-scale contracts.
Fifteen undrafted prospects enter free agency without fabricated contracts.
Generated spatial shot profiles, playmaking, defense, athleticism and archetype
traits feed the same possession engine used by established players.

At season rollover, the completed class is archived in `draft_history` before
the active draft slot is cleared. The following offseason derives the next draft
year from the active season and generates a fresh class. Archived measurements,
prospects, selections and ownership provide permanent draft provenance.

## Event types

- `draft_ecosystem_initialized`
- `draft_lottery_completed`
- `draft_combine_completed`
- `draft_prospect_scouted`
- `draft_board_updated`
- `draft_pick_made`

The draft model version is `draft-ecosystem-calibrated.v2`.
