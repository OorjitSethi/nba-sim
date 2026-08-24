"""Multi-agent court state and trajectory generation."""

from nba_sim.spatial.interfaces import (
    KinematicTrajectoryModel,
    TrajectoryModel,
    TrajectoryRollout,
)
from nba_sim.spatial.corpus import (
    CorpusSplit,
    IdentityVocabulary,
    TrackingCorpus,
)
from nba_sim.spatial.sampling import OffsetGrid, nucleus_sample_index
from nba_sim.spatial.state import AgentState, SpatialFrame, SpatialSummary
from nba_sim.spatial.training_data import (
    AxisOffsetDiscretizer,
    TrackingEventClass,
    TrackingSequence,
    TrajectoryDiscretizer2D,
)
from nba_sim.spatial.training import (
    TrackingEpochMetrics,
    TrackingTrainingConfig,
    TrackingTrainingReport,
    train_tracking_model,
)

__all__ = [
    "AgentState",
    "AxisOffsetDiscretizer",
    "CorpusSplit",
    "IdentityVocabulary",
    "KinematicTrajectoryModel",
    "OffsetGrid",
    "SpatialFrame",
    "SpatialSummary",
    "TrackingEventClass",
    "TrackingCorpus",
    "TrackingSequence",
    "TrackingEpochMetrics",
    "TrackingTrainingConfig",
    "TrackingTrainingReport",
    "TrajectoryModel",
    "TrajectoryRollout",
    "TrajectoryDiscretizer2D",
    "nucleus_sample_index",
    "train_tracking_model",
]
