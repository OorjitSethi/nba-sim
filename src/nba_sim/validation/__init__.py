"""Leakage-aware calibration and simulation-fidelity evaluation."""

from nba_sim.validation.backtest import (
    CalibratedDynamicTeamModel,
    ChronologicalBacktestReport,
    ChronologicalBacktester,
    EloForecastBaseline,
    LeagueAverageBaseline,
    default_backtester,
    market_distribution,
)
from nba_sim.validation.fidelity import (
    FidelityGate,
    FidelityGateResult,
    FidelityMetric,
    FidelityReport,
    LeaguePerTeamGameTargets,
    evaluate_legacy_league_fidelity,
)
from nba_sim.validation.probabilistic import (
    BootstrapDifference,
    ProbabilisticMetrics,
    evaluate_probabilistic_forecasts,
    paired_bootstrap_difference,
)

__all__ = [
    "CalibratedDynamicTeamModel",
    "ChronologicalBacktestReport",
    "ChronologicalBacktester",
    "EloForecastBaseline",
    "LeagueAverageBaseline",
    "default_backtester",
    "market_distribution",
    "FidelityGate",
    "FidelityGateResult",
    "FidelityMetric",
    "FidelityReport",
    "LeaguePerTeamGameTargets",
    "BootstrapDifference",
    "ProbabilisticMetrics",
    "evaluate_legacy_league_fidelity",
    "evaluate_probabilistic_forecasts",
    "paired_bootstrap_difference",
]
