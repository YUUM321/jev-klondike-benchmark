from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import Any

from agents.base import Agent, Observation
from solitaire.engine import KlondikeEngine


@dataclass(slots=True)
class GameResult:
    seed: int
    agent: str
    win: bool
    foundation_cards: int
    hidden_cards_revealed: int
    steps: int
    repeated_states: int
    unique_states_visited: int
    revisit_rate: float
    termination_reason: str
    elapsed_seconds: float
    error: str | None = None


def run_game(
    agent: Agent,
    seed: int,
    *,
    stagnation_steps: int = 50,
    max_steps: int = 2_000,
    capture_decisions: bool = False,
) -> tuple[GameResult, list[dict[str, Any]]]:
    engine = KlondikeEngine()
    engine.reset(seed)
    agent.reset(seed)

    initial_hidden = engine.hidden_cards
    seen = {engine.state_hash()}
    repeated_states = 0
    cycle_stagnant = 0
    decisions: list[dict[str, Any]] = []
    termination_reason = "turn_cap"
    error: str | None = None
    started = time.perf_counter()

    while engine.steps < max_steps:
        if engine.is_win():
            termination_reason = "win"
            break
        actions = engine.get_legal_actions()
        if not actions:
            termination_reason = "hard_dead_end"
            break

        before_state = engine.visible_text()
        before_state_data = engine.get_visible_state()
        legal_labels = [engine.action_label(action) for action in actions]
        observation = Observation(
            visible_state=before_state_data,
            visible_text=before_state,
            visible_state_hash=engine.visible_state_hash(),
            step=engine.steps,
            action_labels=dict(zip(actions, legal_labels)),
        )
        try:
            decision = agent.choose(observation, actions)
            if decision.action not in actions:
                raise ValueError("agent returned an action outside the legal action set")
        except Exception as exc:  # Benchmark failures are data, not silent fallback.
            termination_reason = "agent_error"
            error = f"{type(exc).__name__}: {exc}"
            break

        selected_label = engine.action_label(decision.action)
        outcome = engine.step(decision.action)
        was_seen = outcome.state_hash in seen
        if was_seen:
            repeated_states += 1
        else:
            seen.add(outcome.state_hash)

        cycle_stagnant = cycle_stagnant + 1 if was_seen else 0

        if capture_decisions:
            decisions.append(
                {
                    "seed": seed,
                    "agent": agent.name,
                    "step": engine.steps,
                    "visible_state": before_state,
                    "visible_state_data": before_state_data,
                    "legal_actions": legal_labels,
                    "selected": selected_label,
                    "confidence": decision.confidence,
                    "probabilities": decision.probabilities,
                    "decision_metadata": decision.metadata,
                    "state_after": engine.visible_text(),
                    "state_after_data": engine.get_visible_state(),
                    "state_hash_after": outcome.state_hash,
                    "new_hidden_cards_revealed": outcome.hidden_cards_revealed,
                    "foundation_delta": outcome.foundation_delta,
                }
            )

        if cycle_stagnant >= stagnation_steps:
            termination_reason = "cycle_stagnation"
            break

    if engine.is_win():
        termination_reason = "win"

    result = GameResult(
        seed=seed,
        agent=agent.name,
        win=engine.is_win(),
        foundation_cards=engine.foundation_cards,
        hidden_cards_revealed=initial_hidden - engine.hidden_cards,
        steps=engine.steps,
        repeated_states=repeated_states,
        unique_states_visited=len(seen),
        revisit_rate=round(repeated_states / engine.steps, 6) if engine.steps else 0.0,
        termination_reason=termination_reason,
        elapsed_seconds=round(time.perf_counter() - started, 6),
        error=error,
    )
    final_result = "win" if result.win else "loss"
    for record in decisions:
        record["final_result"] = final_result
        record["termination_reason"] = termination_reason
    return result, decisions


def result_json(result: GameResult) -> str:
    return json.dumps(asdict(result), ensure_ascii=False, sort_keys=True)
