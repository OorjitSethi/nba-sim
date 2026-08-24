from __future__ import annotations

import hashlib

import numpy as np


class RandomStreamFactory:
    """Creates order-independent deterministic random streams.

    A namespace is hashed with the master seed, so adding a new consumer does not
    perturb existing simulations. This is essential for reproducible backtests.
    """

    def __init__(self, seed: int) -> None:
        if seed < 0:
            raise ValueError("seed must be non-negative")
        self.seed = int(seed)

    def seed_for(self, namespace: str) -> int:
        if not namespace:
            raise ValueError("random-stream namespace cannot be empty")
        payload = f"{self.seed}:{namespace}".encode("utf-8")
        digest = hashlib.blake2b(payload, digest_size=8).digest()
        return int.from_bytes(digest, byteorder="big", signed=False)

    def generator(self, namespace: str) -> np.random.Generator:
        return np.random.default_rng(self.seed_for(namespace))
