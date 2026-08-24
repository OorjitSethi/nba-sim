from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def _softmax(logits: np.ndarray, temperature: float) -> np.ndarray:
    if temperature <= 0:
        raise ValueError("temperature must be positive")
    scaled = np.asarray(logits, dtype=np.float64) / temperature
    if scaled.ndim != 1 or scaled.size == 0:
        raise ValueError("logits must be a non-empty one-dimensional vector")
    scaled -= np.max(scaled)
    probabilities = np.exp(scaled)
    denominator = probabilities.sum()
    if not np.isfinite(denominator) or denominator <= 0:
        raise ValueError("logits produced an invalid probability distribution")
    return probabilities / denominator


def nucleus_sample_index(
    logits: np.ndarray,
    rng: np.random.Generator,
    *,
    top_p: float = 0.9,
    temperature: float = 1.0,
) -> int:
    """Sample from the smallest descending-probability set with mass >= top_p."""

    if not 0.0 < top_p <= 1.0:
        raise ValueError("top_p must be in (0, 1]")
    probabilities = _softmax(logits, temperature)
    order = np.argsort(probabilities)[::-1]
    cumulative = np.cumsum(probabilities[order])
    cutoff = int(np.searchsorted(cumulative, top_p, side="left")) + 1
    retained = order[:cutoff]
    retained_probabilities = probabilities[retained]
    retained_probabilities /= retained_probabilities.sum()
    return int(rng.choice(retained, p=retained_probabilities))


@dataclass(frozen=True)
class OffsetGrid:
    dimensions: int
    bins_per_axis: int
    max_abs_offset: tuple[float, ...]

    def __post_init__(self) -> None:
        if self.dimensions not in {2, 3}:
            raise ValueError("offset grids support two or three dimensions")
        if self.bins_per_axis < 3 or self.bins_per_axis % 2 == 0:
            raise ValueError("bins_per_axis must be an odd integer >= 3")
        if len(self.max_abs_offset) != self.dimensions:
            raise ValueError("max_abs_offset does not match dimensions")
        if any(limit <= 0 for limit in self.max_abs_offset):
            raise ValueError("offset limits must be positive")

    @property
    def size(self) -> int:
        return self.bins_per_axis**self.dimensions

    def centers(self) -> tuple[np.ndarray, ...]:
        return tuple(
            np.linspace(-limit, limit, self.bins_per_axis)
            for limit in self.max_abs_offset
        )

    def unravel(self, index: int) -> tuple[int, ...]:
        if not 0 <= index < self.size:
            raise IndexError(index)
        result = np.unravel_index(index, (self.bins_per_axis,) * self.dimensions)
        return tuple(int(value) for value in result)

    def sample(
        self,
        logits: np.ndarray,
        rng: np.random.Generator,
        *,
        top_p: float = 0.9,
        temperature: float = 1.0,
        continuous: bool = True,
    ) -> np.ndarray:
        logits = np.asarray(logits)
        if logits.shape != (self.size,):
            raise ValueError(f"expected {self.size} logits, got {logits.shape}")
        flat_index = nucleus_sample_index(
            logits,
            rng,
            top_p=top_p,
            temperature=temperature,
        )
        indices = self.unravel(flat_index)
        centers = self.centers()
        result = np.asarray(
            [axis_centers[index] for axis_centers, index in zip(centers, indices)],
            dtype=np.float64,
        )
        if continuous:
            widths = np.asarray(
                [2.0 * limit / (self.bins_per_axis - 1) for limit in self.max_abs_offset]
            )
            result += rng.uniform(-0.5, 0.5, size=self.dimensions) * widths
            result = np.clip(
                result,
                -np.asarray(self.max_abs_offset),
                np.asarray(self.max_abs_offset),
            )
        return result
