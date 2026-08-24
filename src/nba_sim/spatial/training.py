from __future__ import annotations

import hashlib
import json
import os
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Sequence

import numpy as np

from nba_sim.spatial.corpus import (
    CorpusSplit,
    TrackingCorpus,
    prepare_courtmotion_example,
    prepare_sportsngen_example,
)
from nba_sim.spatial.training_data import AxisOffsetDiscretizer


Architecture = Literal["courtmotion", "sportsngen"]


@dataclass(frozen=True)
class TrackingTrainingConfig:
    architecture: Architecture
    epochs: int = 20
    learning_rate: float = 3e-4
    weight_decay: float = 1e-2
    gradient_clip: float = 1.0
    trajectory_weight: float = 0.7
    validation_fraction: float = 0.15
    test_fraction: float = 0.15
    seed: int = 2026
    device: str = "auto"

    def __post_init__(self) -> None:
        if self.architecture not in {"courtmotion", "sportsngen"}:
            raise ValueError("architecture must be courtmotion or sportsngen")
        if self.epochs <= 0:
            raise ValueError("epochs must be positive")
        if self.learning_rate <= 0 or self.weight_decay < 0:
            raise ValueError("optimizer parameters are invalid")
        if self.gradient_clip <= 0:
            raise ValueError("gradient_clip must be positive")
        if not 0 <= self.trajectory_weight <= 1:
            raise ValueError("trajectory_weight must be in [0, 1]")


@dataclass(frozen=True)
class TrackingEpochMetrics:
    epoch: int
    train_loss: float
    validation_loss: float


@dataclass(frozen=True)
class TrackingTrainingReport:
    architecture: Architecture
    best_epoch: int
    best_validation_loss: float
    test_loss: float
    train_sequences: int
    validation_sequences: int
    test_sequences: int
    corpus_fingerprint: str
    checkpoint_path: str
    manifest_path: str
    history: tuple[TrackingEpochMetrics, ...]

    def as_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["history"] = [asdict(item) for item in self.history]
        return result


def train_tracking_model(
    corpus: TrackingCorpus,
    *,
    output_directory: str | Path,
    config: TrackingTrainingConfig,
    skeleton_edges: Sequence[tuple[int, int]] | None = None,
) -> TrackingTrainingReport:
    """Train with chronological, game-grouped splits and save an audit manifest."""

    from nba_sim.spatial import torch_models

    torch = torch_models.torch
    if torch is None:
        raise ImportError(
            "PyTorch is required for tracking training. "
            "Install the project with the 'tracking' extra."
        )
    split = corpus.chronological_split(
        validation_fraction=config.validation_fraction,
        test_fraction=config.test_fraction,
    )
    _seed_everything(torch, config.seed)
    device = _resolve_device(torch, config.device)
    output_root = Path(output_directory)
    output_root.mkdir(parents=True, exist_ok=True)
    fingerprint = _corpus_fingerprint(corpus)

    if config.architecture == "courtmotion":
        if not skeleton_edges:
            raise ValueError(
                "CourtMotion training requires the licensed skeleton topology"
            )
        first = corpus.sequences[0]
        model_config = torch_models.CourtMotionConfig(
            joints=first.skeletons_30hz.shape[-2],
            event_classes=first.event_classes,
        )
        model = torch_models.CourtMotionModel(
            model_config,
            skeleton_edges,
        ).to(device)
        loss_context = {
            "positive_weight": _event_positive_weight(torch, split, device),
            "skeleton_edges": tuple(tuple(edge) for edge in skeleton_edges),
        }
    else:
        first = corpus.sequences[0]
        vocabulary = corpus.vocabulary
        model_config = torch_models.SportsNGENConfig(
            object_feature_dim=first.sportsngen_object_features().shape[-1],
            context_dim=first.context_features.shape[0],
            identity_vocab_size=len(vocabulary),
        )
        model = torch_models.SportsNGENModel(model_config).to(device)
        loss_context = {
            "vocabulary": vocabulary,
            "discretizer": AxisOffsetDiscretizer(
                bins_per_axis=model_config.offset_bins_per_axis,
                max_abs_offsets=(5.0, 5.0, 3.0),
            ),
        }

    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )
    checkpoint = output_root / f"{config.architecture}-best.pt"
    history = []
    best_validation = float("inf")
    best_epoch = 0
    for epoch in range(1, config.epochs + 1):
        train_loss = _run_epoch(
            torch,
            model,
            split.train,
            config=config,
            device=device,
            optimizer=optimizer,
            loss_context=loss_context,
            epoch=epoch,
        )
        validation_loss = _run_epoch(
            torch,
            model,
            split.validation,
            config=config,
            device=device,
            optimizer=None,
            loss_context=loss_context,
            epoch=epoch,
        )
        history.append(
            TrackingEpochMetrics(
                epoch=epoch,
                train_loss=train_loss,
                validation_loss=validation_loss,
            )
        )
        if validation_loss < best_validation:
            best_validation = validation_loss
            best_epoch = epoch
            _save_checkpoint(
                torch,
                checkpoint,
                {
                    "architecture": config.architecture,
                    "model_config": asdict(model_config),
                    "training_config": asdict(config),
                    "model_state_dict": model.state_dict(),
                    "epoch": epoch,
                    "validation_loss": validation_loss,
                    "corpus_fingerprint": fingerprint,
                    "skeleton_edges": loss_context.get("skeleton_edges"),
                    "identity_vocabulary": (
                        loss_context["vocabulary"].as_dict()
                        if "vocabulary" in loss_context
                        else None
                    ),
                },
            )

    saved = torch.load(checkpoint, map_location=device, weights_only=False)
    model.load_state_dict(saved["model_state_dict"])
    test_loss = _run_epoch(
        torch,
        model,
        split.test,
        config=config,
        device=device,
        optimizer=None,
        loss_context=loss_context,
        epoch=best_epoch,
    )
    manifest = output_root / f"{config.architecture}-manifest.json"
    report = TrackingTrainingReport(
        architecture=config.architecture,
        best_epoch=best_epoch,
        best_validation_loss=best_validation,
        test_loss=test_loss,
        train_sequences=len(split.train),
        validation_sequences=len(split.validation),
        test_sequences=len(split.test),
        corpus_fingerprint=fingerprint,
        checkpoint_path=str(checkpoint),
        manifest_path=str(manifest),
        history=tuple(history),
    )
    _atomic_json(
        manifest,
        {
            **report.as_dict(),
            "training_config": asdict(config),
            "model_config": asdict(model_config),
            "split_policy": "chronological-whole-game",
            "checkpoint_sha256": _sha256(checkpoint),
        },
    )
    return report


def _run_epoch(
    torch: object,
    model: object,
    sequences: tuple,
    *,
    config: TrackingTrainingConfig,
    device: object,
    optimizer: object | None,
    loss_context: dict[str, object],
    epoch: int,
) -> float:
    training = optimizer is not None
    model.train(training)
    indices = list(range(len(sequences)))
    if training:
        random.Random(config.seed + epoch).shuffle(indices)
    losses = []
    context = torch.enable_grad() if training else torch.no_grad()
    with context:
        for index in indices:
            sequence = sequences[index]
            if config.architecture == "courtmotion":
                example = prepare_courtmotion_example(sequence)
                output = model(
                    skeletons_30hz=torch.as_tensor(
                        example.skeletons_30hz[None],
                        device=device,
                    ),
                    positions_5hz=torch.as_tensor(
                        example.positions_5hz[None],
                        device=device,
                    ),
                    shoulder_normals_5hz=torch.as_tensor(
                        example.shoulder_normals_5hz[None],
                        device=device,
                    ),
                )
                trajectory = torch.as_tensor(
                    example.trajectory_targets[None],
                    dtype=torch.long,
                    device=device,
                )
                events = torch.as_tensor(
                    example.event_targets[None],
                    dtype=torch.float32,
                    device=device,
                )
                trajectory_loss = torch.nn.functional.cross_entropy(
                    output["trajectory_logits"].flatten(0, -2),
                    trajectory.flatten(),
                    label_smoothing=0.01,
                )
                event_loss = torch.nn.functional.binary_cross_entropy_with_logits(
                    output["event_logits"],
                    events,
                    pos_weight=loss_context["positive_weight"],
                )
                loss = (
                    config.trajectory_weight * trajectory_loss
                    + (1 - config.trajectory_weight) * event_loss
                )
            else:
                vocabulary = loss_context["vocabulary"]
                discretizer = loss_context["discretizer"]
                rng = np.random.default_rng(
                    config.seed + epoch * 1_000_003 + index
                )
                example = prepare_sportsngen_example(
                    sequence,
                    vocabulary=vocabulary,
                    discretizer=discretizer,
                    inject_noise=training,
                    rng=rng if training else None,
                )
                output = model(
                    object_features=torch.as_tensor(
                        example.object_features[None],
                        device=device,
                    ),
                    identity_indices=torch.as_tensor(
                        example.identity_indices[None],
                        dtype=torch.long,
                        device=device,
                    ),
                    context_features=torch.as_tensor(
                        example.context_features[None],
                        device=device,
                    ),
                )
                targets = torch.as_tensor(
                    example.offset_targets[None],
                    dtype=torch.long,
                    device=device,
                )
                loss = torch.nn.functional.cross_entropy(
                    output["offset_logits"].flatten(0, -2),
                    targets.flatten(),
                    label_smoothing=0.01,
                )
            if training:
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(
                    model.parameters(),
                    config.gradient_clip,
                )
                optimizer.step()
            losses.append(float(loss.detach().cpu()))
    if not losses:
        raise ValueError("training split contains no sequences")
    return float(np.mean(losses))


def _event_positive_weight(torch: object, split: CorpusSplit, device: object) -> object:
    labels = np.concatenate(
        [sequence.event_window_targets()[:-1] for sequence in split.train],
        axis=(0),
    )
    positives = labels.sum(axis=(0, 1, 2))
    negatives = np.prod(labels.shape[:-1]) - positives
    weight = np.clip(negatives / np.maximum(positives, 1.0), 1.0, 100.0)
    return torch.as_tensor(weight, dtype=torch.float32, device=device)


def _resolve_device(torch: object, requested: str) -> object:
    if requested != "auto":
        return torch.device(requested)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def _seed_everything(torch: object, seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)


def _corpus_fingerprint(corpus: TrackingCorpus) -> str:
    digest = hashlib.sha256()
    for sequence in sorted(corpus.sequences, key=lambda item: item.sequence_id):
        digest.update(sequence.sequence_id.encode("utf-8"))
        digest.update(str(sequence.game_date).encode("ascii"))
        digest.update(sequence.player_ids.tobytes())
        digest.update(str(sequence.positions_5hz.shape).encode("ascii"))
    return digest.hexdigest()


def _save_checkpoint(torch: object, path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    torch.save(payload, temporary)
    os.replace(temporary, path)


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "TrackingEpochMetrics",
    "TrackingTrainingConfig",
    "TrackingTrainingReport",
    "train_tracking_model",
]
