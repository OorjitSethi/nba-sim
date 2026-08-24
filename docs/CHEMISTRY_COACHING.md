# Chemistry and coaching

Phase five adds complete team-level environment state to Franchise saves.

`TeamChemistryRecord` separates cohesion, role clarity, trust, system
familiarity, and morale. `CoachingProfileRecord` stores the user-defined
offensive system, defensive system, pace emphasis, rotation depth, development
priority, and adaptability. New saves begin from neutral, low-confidence priors;
the application does not invent real coach identities or measured chemistry.

Team sessions gradually improve one selected dimension with diminishing returns.
Assessments, coaching plans, and sessions are separate hash-chained events.

When enabled in Matchup Lab, the saved environment applies bounded changes to
pace, ball movement, turnovers, shooting execution, and defensive impact. These
are transparent strategy priors rather than trained causal effects. Manual
Matchup Lab availability and Franchise health are applied independently.

Current evidence supports treating cohesion as multidimensional and associated
with team success, but not as proof of a universal NBA point adjustment:

- Team cohesion and team success in sport:
  <https://pubmed.ncbi.nlm.nih.gov/11811568/>
- Basketball shared understanding over a season:
  <https://pubmed.ncbi.nlm.nih.gov/27599187/>
- NBA possession-context player embeddings:
  <https://arxiv.org/abs/2302.13386>

The next accuracy layer requires chronological lineup continuity, play-type
execution, coach tenure and identity, substitution behavior, possession
networks, and held-out validation.
