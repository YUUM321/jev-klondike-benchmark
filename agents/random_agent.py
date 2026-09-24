from __future__ import annotations

import random

from solitaire.engine import Action, KlondikeEngine

from .base import Decision


class RandomAgent:
    name = "random"

    def __init__(self) -> None:
        self._rng = random.Random()

    def reset(self, seed: int) -> None:
        # Separate policy randomness from deck generation while remaining reproducible.
        self._rng.seed(f"random-agent:{seed}")

    def choose(self, engine: KlondikeEngine, actions: list[Action]) -> Decision:
        if not actions:
            raise ValueError("cannot choose without a legal action")
        return Decision(action=self._rng.choice(actions))
