# Contributing

Thanks for your interest in NBA Sim. The project favors reproducible behavior,
explicit modeling assumptions, and tests that preserve basketball invariants.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
nba-sim-demo
python -m unittest discover -s tests -v
```

Optional tracking work requires `python -m pip install -e '.[tracking,dev]'`.

## Pull requests

- Keep simulation changes deterministic under a fixed seed.
- Add or update tests for rules, event replay, box-score reconciliation, or
  probabilistic behavior affected by the change.
- State any data assumptions and keep downloaded or licensed data out of Git.
- Do not describe an untrained architecture as a validated forecast model.
- Update the model card or validation documentation when changing calibration or
  promotion criteria.
