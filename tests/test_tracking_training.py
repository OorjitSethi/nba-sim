from __future__ import annotations

import unittest
from unittest.mock import patch

from nba_sim.spatial.corpus import TrackingCorpus
from nba_sim.spatial.training import (
    TrackingTrainingConfig,
    train_tracking_model,
)
from tests.test_tracking_data import make_sequence


class TrackingTrainingTests(unittest.TestCase):
    def test_invalid_training_configuration_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "architecture"):
            TrackingTrainingConfig(architecture="unknown")  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "epochs"):
            TrackingTrainingConfig(architecture="courtmotion", epochs=0)

    def test_missing_torch_fails_before_any_training_side_effect(self) -> None:
        corpus = TrackingCorpus((make_sequence(),))
        with patch("nba_sim.spatial.torch_models.torch", None):
            with self.assertRaisesRegex(ImportError, "tracking.*extra"):
                train_tracking_model(
                    corpus,
                    output_directory="unused",
                    config=TrackingTrainingConfig(
                        architecture="sportsngen",
                        epochs=1,
                    ),
                )


if __name__ == "__main__":
    unittest.main()
