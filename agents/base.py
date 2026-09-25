from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from solitaire.engine import Action


@dataclass(frozen=True, slots=True)
class Observation:
    """The complete information boundary exposed to every agent."""

    visible_state: dict[str, Any]
    visible_text: str
    visible_state_hash: str
    step: int
    action_labels: dict[Action, str]
    draw_count: int = 1
    visible_state_visit_count: int = 1
    actions_tried_from_visible_state: tuple[str, ...] = ()
    action_attempt_counts: dict[str, int] = field(default_factory=dict)
    action_outcome_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    steps_since_new_visible_state: int = 0
    recent_actions: tuple[str, ...] = ()
    recent_transitions: tuple[dict[str, Any], ...] = ()
    progress: dict[str, int] = field(default_factory=dict)

    def label(self, action: Action) -> str:
        return self.action_labels[action]


@dataclass(slots=True)
class Decision:
    action: Action
    confidence: float | None = None
    probabilities: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class Agent(Protocol):
    name: str

    def reset(self, seed: int) -> None: ...

    def choose(self, observation: Observation, actions: list[Action]) -> Decision: ...
