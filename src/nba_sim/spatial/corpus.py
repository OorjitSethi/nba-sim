from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable

import numpy as np

from nba_sim.spatial.training_data import (
    AxisOffsetDiscretizer,
    TrackingSequence,
    TrajectoryDiscretizer2D,
)


@dataclass(frozen=True, eq=False)
class CourtMotionExample:
    sequence_id: str
    skeletons_30hz: np.ndarray
    positions_5hz: np.ndarray
    shoulder_normals_5hz: np.ndarray
    trajectory_targets: np.ndarray
    event_targets: np.ndarray


@dataclass(frozen=True, eq=False)
class SportsNGENExample:
    sequence_id: str
    object_features: np.ndarray
    identity_indices: np.ndarray
    context_features: np.ndarray
    offset_targets: np.ndarray


class IdentityVocabulary:
    BALL_TOKEN = "__ball__"
    UNKNOWN_TOKEN = "__unknown__"

    def __init__(self, player_ids: Iterable[int]) -> None:
        ordered = sorted(set(int(player_id) for player_id in player_ids))
        self._tokens: dict[int | str, int] = {
            self.UNKNOWN_TOKEN: 0,
            self.BALL_TOKEN: 1,
        }
        for player_id in ordered:
            self._tokens[player_id] = len(self._tokens)

    def encode_players_and_ball(self, player_ids: np.ndarray) -> np.ndarray:
        encoded = [
            self._tokens.get(int(player_id), self._tokens[self.UNKNOWN_TOKEN])
            for player_id in player_ids
        ]
        encoded.append(self._tokens[self.BALL_TOKEN])
        return np.asarray(encoded, dtype=np.int64)

    def __len__(self) -> int:
        return len(self._tokens)

    def as_dict(self) -> dict[str, int]:
        return {str(token): index for token, index in self._tokens.items()}


def prepare_courtmotion_example(
    sequence: TrackingSequence,
    *,
    discretizer: TrajectoryDiscretizer2D | None = None,
) -> CourtMotionExample:
    discretizer = discretizer or TrajectoryDiscretizer2D()
    return CourtMotionExample(
        sequence_id=sequence.sequence_id,
        skeletons_30hz=sequence.skeletons_30hz.astype(np.float32),
        positions_5hz=sequence.positions_5hz.astype(np.float32),
        shoulder_normals_5hz=sequence.shoulder_normals_5hz.astype(np.float32),
        trajectory_targets=sequence.courtmotion_trajectory_targets(discretizer),
        event_targets=sequence.event_window_targets()[:-1],
    )


def prepare_sportsngen_example(
    sequence: TrackingSequence,
    *,
    vocabulary: IdentityVocabulary,
    discretizer: AxisOffsetDiscretizer,
    inject_noise: bool,
    rng: np.random.Generator | None,
) -> SportsNGENExample:
    object_features = sequence.sportsngen_object_features(
        inject_noise=inject_noise,
        rng=rng,
    )
    positions = object_features[..., :3].astype(np.float64)
    offsets = np.diff(positions, axis=0)
    return SportsNGENExample(
        sequence_id=sequence.sequence_id,
        object_features=object_features[:-1],
        identity_indices=vocabulary.encode_players_and_ball(sequence.player_ids),
        context_features=sequence.context_features.astype(np.float32),
        offset_targets=discretizer.encode(offsets),
    )


@dataclass(frozen=True)
class CorpusSplit:
    train: tuple[TrackingSequence, ...]
    validation: tuple[TrackingSequence, ...]
    test: tuple[TrackingSequence, ...]

    def __post_init__(self) -> None:
        train_ids = {sequence.sequence_id for sequence in self.train}
        validation_ids = {sequence.sequence_id for sequence in self.validation}
        test_ids = {sequence.sequence_id for sequence in self.test}
        if train_ids & validation_ids or train_ids & test_ids or validation_ids & test_ids:
            raise ValueError("corpus splits overlap")


class TrackingCorpus:
    """Tracking corpus with deterministic game-grouped leakage prevention."""

    def __init__(self, sequences: Iterable[TrackingSequence]) -> None:
        self.sequences = tuple(sequences)
        if not self.sequences:
            raise ValueError("tracking corpus cannot be empty")
        sequence_ids = [sequence.sequence_id for sequence in self.sequences]
        if len(sequence_ids) != len(set(sequence_ids)):
            raise ValueError("tracking sequence IDs must be unique")
        event_classes = {sequence.event_classes for sequence in self.sequences}
        context_dimensions = {
            sequence.context_features.shape[0] for sequence in self.sequences
        }
        if len(event_classes) != 1:
            raise ValueError("event-class dimensions differ across the corpus")
        if len(context_dimensions) != 1:
            raise ValueError("context dimensions differ across the corpus")

    @property
    def vocabulary(self) -> IdentityVocabulary:
        return IdentityVocabulary(
            player_id
            for sequence in self.sequences
            for player_id in sequence.player_ids
        )

    def split(
        self,
        *,
        validation_fraction: float = 0.15,
        test_fraction: float = 0.15,
        salt: str = "nba-sim-tracking-v1",
    ) -> CorpusSplit:
        if validation_fraction <= 0 or test_fraction <= 0:
            raise ValueError("validation and test fractions must be positive")
        if validation_fraction + test_fraction >= 1:
            raise ValueError("validation plus test fractions must be below one")

        groups: dict[str, list[TrackingSequence]] = {}
        for sequence in self.sequences:
            group = sequence.sequence_id.split(":", maxsplit=1)[0]
            groups.setdefault(group, []).append(sequence)

        train: list[TrackingSequence] = []
        validation: list[TrackingSequence] = []
        test: list[TrackingSequence] = []
        for group, sequences in sorted(groups.items()):
            digest = hashlib.blake2b(
                f"{salt}:{group}".encode("utf-8"),
                digest_size=8,
            ).digest()
            value = int.from_bytes(digest, "big") / float(2**64)
            if value < test_fraction:
                test.extend(sequences)
            elif value < test_fraction + validation_fraction:
                validation.extend(sequences)
            else:
                train.extend(sequences)
        return CorpusSplit(tuple(train), tuple(validation), tuple(test))

    def chronological_split(
        self,
        *,
        validation_fraction: float = 0.15,
        test_fraction: float = 0.15,
    ) -> CorpusSplit:
        """Split whole games by date, never individual possessions or frames."""

        if validation_fraction <= 0 or test_fraction <= 0:
            raise ValueError("validation and test fractions must be positive")
        if validation_fraction + test_fraction >= 1:
            raise ValueError("validation plus test fractions must be below one")
        groups: dict[str, list[TrackingSequence]] = {}
        group_dates = {}
        for sequence in self.sequences:
            if sequence.game_date is None:
                raise ValueError(
                    "chronological tracking splits require game_date metadata"
                )
            group = sequence.sequence_id.split(":", maxsplit=1)[0]
            groups.setdefault(group, []).append(sequence)
            previous = group_dates.setdefault(group, sequence.game_date)
            if previous != sequence.game_date:
                raise ValueError("possessions from one game have conflicting dates")
        ordered_groups = sorted(
            groups,
            key=lambda group: (group_dates[group], group),
        )
        if len(ordered_groups) < 3:
            raise ValueError(
                "chronological tracking split requires at least three games"
            )
        validation_groups = max(1, round(len(ordered_groups) * validation_fraction))
        test_groups = max(1, round(len(ordered_groups) * test_fraction))
        if validation_groups + test_groups >= len(ordered_groups):
            raise ValueError("tracking corpus is too small for the requested split")
        test_start = len(ordered_groups) - test_groups
        validation_start = test_start - validation_groups
        train = tuple(
            sequence
            for group in ordered_groups[:validation_start]
            for sequence in groups[group]
        )
        validation = tuple(
            sequence
            for group in ordered_groups[validation_start:test_start]
            for sequence in groups[group]
        )
        test = tuple(
            sequence
            for group in ordered_groups[test_start:]
            for sequence in groups[group]
        )
        return CorpusSplit(train, validation, test)
