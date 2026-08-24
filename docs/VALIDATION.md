# Validation protocol

## Promotion hierarchy

A model is not promoted because it looks realistic. It must pass, in order:

1. schema, physical-boundary, and rules invariants;
2. deterministic replay and worker-count reproducibility;
3. aggregate league-stat fidelity;
4. strictly chronological out-of-sample probabilistic backtesting;
5. ablation against simpler baselines;
6. calibration monitoring after deployment.

The current repository passes the first three layers. Layer four is now executed
against four official regular-season game-log snapshots. The candidate has a
statistically significant log-loss improvement on the unseen 2025-26 season, but
does not yet pass the stricter joint log-loss and margin-error promotion rule.

## League-stat fidelity

Command:

```bash
.venv/bin/nba-sim validate --games-per-matchup 5 --seed 2026
```

Recorded on 2026-07-25:

| Quantity | Result |
| --- | ---: |
| Source season | 2023-24 |
| Simulated games | 75 |
| Simulated team-games | 150 |
| Compared statistics | 12 |
| Mean absolute percentage error | 2.2336% |
| Maximum absolute percentage error | 5.7848% |
| Maximum-error statistic | turnovers |
| Release gate | pass |

The default gate requires at least 30 games, at most 6% mean error, and at most 12%
error for any single tracked statistic. The gap between observed performance and
the thresholds absorbs finite-sample Monte Carlo variation.

The 12 quantities are points, field goals made and attempted, threes made and
attempted, free throws made and attempted, assists, turnovers, steals, blocks, and
personal fouls. Targets are reconstructed from the bundled raw player totals and
divided by 2,460 team-games.

This is an in-domain statistical-ecology check. It does not measure whether the
simulator picks the correct winner of an unseen game.

The same fixed-seed audit using official 2026-27 roster membership overlaid with
2025-26 statistical player profiles records 3.0300% mean error and 7.1496%
maximum error across 150 team-games. That operational-profile gate passes. Its
target is still the bundled 2023-24 ecology, so it detects simulation drift but
cannot validate future 2026-27 team strength.

## Chronological 2025-26 holdout

The dynamic-model hyperparameters were selected using 2024-25 only, frozen, then
evaluated on the complete 2025-26 regular season. Each forecast is emitted at
17:00 UTC and a result is applied only after its recorded availability timestamp.
The paired bootstrap uses 5,000 resamples of the same games.

| Metric | Calibrated dynamic | Margin-aware Elo | League average |
| --- | ---: | ---: | ---: |
| Games | 1,230 | 1,230 | 1,230 |
| Log loss | 0.5955 | 0.6023 | 0.6876 |
| Brier score | 0.2040 | 0.2071 | 0.2473 |
| Margin MAE | 11.369 | 11.451 | 13.116 |
| Total MAE | 15.905 | 15.905 | 15.905 |
| Joint Gaussian NLL | 8.5238 | 8.5298 | 8.6331 |

Candidate minus Elo log loss is -0.00681 with a 95% interval of
[-0.01327, -0.00070]. Candidate minus Elo margin absolute error is -0.0823 with a
95% interval of [-0.1956, 0.0342]. The latter crosses zero; therefore
`promotion_passed` is false. This is a held-out statistical result, not a claim
of betting profitability, and no market baseline is reported until a licensed,
timestamped odds archive has been ingested.

## Probabilistic scoring

`evaluate_probabilistic_forecasts` reports:

- Brier score and log loss for win probability;
- expected calibration error;
- margin and total MAE/RMSE;
- bivariate Gaussian negative log likelihood;
- empirical CRPS from simulated samples;
- central interval coverage.

`paired_bootstrap_difference` compares candidate and baseline forecasts on the
same games, preserving paired outcomes. Production evaluation should use rolling
origin splits and store every prediction before the game starts.

## Required tracking-model evaluation

Before neural weights can replace the kinematic fallback, report:

- next-step and long-horizon coordinate NLL;
- average and final displacement error;
- event-head precision, recall, F1, and calibration;
- court-boundary and collision violation rates;
- possession-duration and terminal-event distributions;
- downstream EPV and final-score ablations;
- results by transition/half-court, lineup, event type, and horizon.

Splits must be game-grouped and chronological. Random frame-level splitting is
prohibited because adjacent optical frames are near-duplicates.
