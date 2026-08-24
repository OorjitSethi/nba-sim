# Draft ecosystem

The draft ecosystem is a persistent, event-sourced 2027 draft class and
two-round selection engine. It deliberately separates three quantities that
franchise games often collapse into one rating:

1. **latent outcome** — the simulator's hidden player state;
2. **public consensus** — a noisy market prior that drives the initial order;
3. **team belief** — the user's Bayesian scouting report and private big board.

The browser receives only the third quantity. Latent offense, playmaking,
defense, athleticism, overall, potential, and the noisy public-score input are
stored in the local save but omitted from every draft API response.

## Reproducible class generation

A class seed deterministically generates 75 fictional prospects. Correlated
offense, playmaking, defense, and athleticism are conditioned by position and
archetype. Age affects the latent development ceiling, while public consensus
blends present ability, upside, and ranking noise. The same seed yields the same
class, reports, names, measurements, and initial board.

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

## 2027 3-2-1 lottery

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
public information plus stable team/pick decision noise. They cannot read the
user's private report or latent truth.

The user's team can select only when it owns the current slot. “Sim to my next
pick” advances CPU selections until the next owned slot, and every selection is
appended to the franchise hash chain. Replaying or branching the save restores
the exact class, reports, board, lottery, and selections.

Draft selections represent rights in the draft ledger. They are not silently
inserted into the current NBA rotation or assigned fabricated contracts.

## Event types

- `draft_ecosystem_initialized`
- `draft_lottery_completed`
- `draft_combine_completed`
- `draft_prospect_scouted`
- `draft_board_updated`
- `draft_pick_made`

The draft model version is `draft-ecosystem-321.v1`.
