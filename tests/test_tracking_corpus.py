from __future__ import annotations

import dataclasses
import unittest
from datetime import date, timedelta

import numpy as np

from nba_sim.spatial.corpus import (
    IdentityVocabulary,
    TrackingCorpus,
    prepare_courtmotion_example,
    prepare_sportsngen_example,
)
from nba_sim.spatial.training_data import AxisOffsetDiscretizer
from tests.test_tracking_data import make_sequence


def sequence_with_id(sequence_id: str, id_offset: int = 0):
    sequence = make_sequence()
    return dataclasses.replace(
        sequence,
        sequence_id=sequence_id,
        player_ids=sequence.player_ids + id_offset,
    )


class TrackingCorpusTests(unittest.TestCase):
    def test_examples_align_inputs_and_next_step_targets(self) -> None:
        sequence = make_sequence()
        courtmotion = prepare_courtmotion_example(sequence)
        self.assertEqual(courtmotion.trajectory_targets.shape, (5, 10))
        self.assertEqual(courtmotion.event_targets.shape, (5, 10, 3, 9))

        vocabulary = IdentityVocabulary(sequence.player_ids)
        sportsngen = prepare_sportsngen_example(
            sequence,
            vocabulary=vocabulary,
            discretizer=AxisOffsetDiscretizer(31, (4.0, 4.0, 8.0)),
            inject_noise=False,
            rng=None,
        )
        self.assertEqual(sportsngen.object_features.shape, (5, 11, 13))
        self.assertEqual(sportsngen.offset_targets.shape, (5, 11, 3))
        self.assertEqual(sportsngen.identity_indices.shape, (11,))

    def test_game_grouped_split_prevents_possession_leakage(self) -> None:
        sequences = []
        for game in range(30):
            for possession in range(2):
                sequences.append(
                    sequence_with_id(
                        f"game-{game}:possession-{possession}",
                        id_offset=game * 20,
                    )
                )
        corpus = TrackingCorpus(sequences)
        split = corpus.split()
        locations = {}
        for label, values in (
            ("train", split.train),
            ("validation", split.validation),
            ("test", split.test),
        ):
            for sequence in values:
                group = sequence.sequence_id.split(":")[0]
                locations.setdefault(group, set()).add(label)
        self.assertTrue(all(len(labels) == 1 for labels in locations.values()))
        self.assertTrue(split.train)
        self.assertTrue(split.validation)
        self.assertTrue(split.test)

    def test_noise_preparation_is_reproducible(self) -> None:
        sequence = make_sequence()
        vocabulary = IdentityVocabulary(sequence.player_ids)
        discretizer = AxisOffsetDiscretizer(31, (4.0, 4.0, 8.0))
        first = prepare_sportsngen_example(
            sequence,
            vocabulary=vocabulary,
            discretizer=discretizer,
            inject_noise=True,
            rng=np.random.default_rng(22),
        )
        second = prepare_sportsngen_example(
            sequence,
            vocabulary=vocabulary,
            discretizer=discretizer,
            inject_noise=True,
            rng=np.random.default_rng(22),
        )
        np.testing.assert_array_equal(first.object_features, second.object_features)

    def test_chronological_split_holds_out_complete_latest_games(self) -> None:
        start = date(2025, 1, 1)
        sequences = []
        for game in range(10):
            for possession in range(2):
                sequences.append(
                    dataclasses.replace(
                        sequence_with_id(
                            f"game-{game}:possession-{possession}",
                            id_offset=game * 20,
                        ),
                        game_date=start + timedelta(days=game),
                    )
                )
        split = TrackingCorpus(sequences).chronological_split(
            validation_fraction=0.2,
            test_fraction=0.2,
        )
        self.assertEqual(len(split.train), 12)
        self.assertEqual(len(split.validation), 4)
        self.assertEqual(len(split.test), 4)
        self.assertLess(
            max(sequence.game_date for sequence in split.train),
            min(sequence.game_date for sequence in split.validation),
        )
        self.assertLess(
            max(sequence.game_date for sequence in split.validation),
            min(sequence.game_date for sequence in split.test),
        )

    def test_chronological_split_requires_game_dates(self) -> None:
        corpus = TrackingCorpus(
            sequence_with_id(f"game-{game}:possession-0", game * 20)
            for game in range(3)
        )
        with self.assertRaisesRegex(ValueError, "game_date"):
            corpus.chronological_split()


if __name__ == "__main__":
    unittest.main()
