from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from solitaire.engine import Action, KlondikeEngine


@dataclass(slots=True)
class Decision:
    action: Action
    confidence: float | None = None
    probabilities: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class Agent(Protocol):
    name: str

    def reset(self, seed: int) -> None: ...

    def choose(self, engine: KlondikeEngine, actions: list[Action]) -> Decision: ...
