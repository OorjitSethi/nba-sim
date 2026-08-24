# Established player ratings

Current NBA players use a visible 25–99 rating system. They do not require
scouting. The active league is normalized so that 99 is the maximum possible
current overall, stars occupy the upper tail, rotation players occupy the
middle, and fringe players occupy the lower tail.

## Overall rating

OVR is not a simple average of attributes and is no longer a single-season
percentile. Version 2 uses:

1. **Established-value prior.** The NBA's published NBA 2K26 launch ratings
   anchor known top-100 players to a recognizable scale. Other players receive
   an inferred prior from their historical role, usage, creation, efficiency,
   and defense.
2. **Current performance.** Official 2025–26 scoring volume and efficiency,
   creation, turnovers, defense, impact, and workload produce a role-balanced
   performance rank.
3. **Evidence reliability.** A full healthy season can contribute 55% of the
   estimate for a published player. Short samples receive much less weight.
4. **Age transition.** The blended 2025–26 estimate advances one season into
   2026–27. Young players receive modest development; veteran decline
   accelerates nonlinearly. Shooting and passing skill partially preserve older
   players, while athletic attributes decline faster.
5. **2K-style distribution.** Performance ranks use a tier curve based on the
   published top-100 distribution, with 99 reserved for the best possible
   active player.

The dossier exposes the established prior, current performance rating and rank,
evidence weight, and age adjustment. The result is independently updated by
this simulator; it is not an official 2K roster rating or a copy of 2K's
proprietary formula.

Scale source:
<https://www.nba.com/news/nba-2k26-top-100-player-ratings-announced>

## Detailed attributes

Every established player receives 37 visible attributes:

- Finishing: close shot, driving layup, driving dunk, standing dunk, post
  control, post hook, draw foul, and hands.
- Shooting: mid-range, three-point, free throw, post fade, shot IQ, and
  offensive consistency.
- Playmaking: pass accuracy, pass IQ, pass vision, ball handle, and speed with
  ball.
- Defense: interior defense, perimeter defense, steal, block, pass perception,
  help-defense IQ, and defensive consistency.
- Rebounding: offensive and defensive rebound.
- Physicals: speed, agility, strength, vertical, stamina, durability, and
  hustle.
- Mental and growth: intangibles and potential.

Attributes directly observed by the stored data use the corresponding
efficiency, tendency, rate, or event evidence. Traits without authoritative
measurements—such as strength, vertical, hands, and post technique—are explicitly
model-derived from position, size, role, spatial tendencies, and related
events.

## Spatial shooting and hot zones

The simulator already resolves shot attempts through six NBA spatial zones:
restricted area, non-restricted paint, mid-range, left corner three, right
corner three, and above-the-break three. The detailed view now exposes, for
each zone:

- shot frequency;
- shrunk make probability;
- 25–99 zone rating;
- hot, neutral, cold, or unused status.

Hot and cold status compares the player's shrunk zone efficiency with a
zone-specific league prior and requires a non-trivial attempt share. Match
simulation continues to use the underlying spatial probabilities directly,
which retains more information than reducing every location to one shooting
number.

## Roles

Role probabilities use distinct evidence gates. A creator requires high ball
handling, passing vision, speed with ball, and offensive responsibility.
Interior scorers, shooters, two-way players, rim anchors, and connectors compete
on their own relevant evidence. This prevents high-usage centers from becoming
creators merely because they score frequently.

## Progression

The current rating first applies the 2025–26 to 2026–27 age transition.
Attribute-specific aging protects shooting, passing, and IQ more than speed,
agility, vertical, finishing, and perimeter defense. The resulting detailed
ratings become the baseline for the nonlinear lifecycle projector, which
continues progression or regression in every subsequent season.
