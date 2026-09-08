# Contracts and free agency

The Contracts & Free Agency workspace is the second playable release of the
rebuilding roadmap. It turns salary planning into persistent league state rather
than a one-off cap calculator.

## Data boundary

The 2026–27 salary cap ($164.961M), tax ($200.428M), first apron ($209.015M),
second apron ($221.686M), minimum payroll, and mid-level exceptions are official
NBA figures. The repository does not contain a licensed current contract feed.
Existing player salaries, remaining years, and options are therefore initialized
from a deterministic current-value and age model and are labeled **modeled** in
every response and screen. They are never presented as real NBA contracts.

The ledger is replaceable: authoritative `ContractRecord` values remain the
canonical input whenever a licensed feed is connected.

## Multi-year cap planning

Every rostered player receives a salary schedule, status, rights category,
contract kind, signing date, and optional team/player option. The user workspace
shows five seasons of:

- active commitments;
- waived guaranteed salary (dead money);
- committed-player count;
- salary-cap room or overage; and
- projected cap, tax, and apron context.

Future cap lines use an explicit 8% planning assumption. Only the first season's
system levels are official.

## Negotiation model

Extensions and free-agent decisions are deterministic for the same save revision
and inputs. Interest combines:

- salary relative to modeled market value;
- contract security;
- promised role;
- current team quality;
- player age and upside; and
- a seeded preference threshold.

A legal offer can still be rejected. Free-agent offers separately check cap
room, non-taxpayer MLE, taxpayer MLE, minimum exception, apron hard-cap room, and
the phase-specific roster limit. The response exposes the selected signing path,
before/after cap position, player interest, and every blocker.

## Durable decisions

The following actions append hash-chained franchise events and replay exactly:

- extension signed;
- team or player option resolved;
- player waived with guaranteed salary retained;
- free agent signed and moved to the new active roster; and
- CPU roster review waivers.

The CPU market never controls the user's roster. A manually triggered review lets
other front offices release low-minute roster-bubble players into the same free
agent pool used by the user negotiation engine.

## Official references

- [NBA 2026–27 salary cap and apron levels](https://www.nba.com/news/nba-salary-cap-2026-27-season)
- [NBA free agency, options, RFA, and Bird-rights explainer](https://www.nba.com/news/free-agency-explained)
- [2023 NBA–NBPA Collective Bargaining Agreement](https://nbpa.com/cba/)
