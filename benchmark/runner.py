from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import Any

from agents.base import Agent
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
    unique_states: int
    stop_reason: str
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
    max_foundation = engine.foundation_cards
    seen = {engine.state_hash()}
    repeated_states = 0
    cycle_stagnant = 0
    decisions: list[dict[str, Any]] = []
    stop_reason = "turn_cap"
    error: str | None = None
    started = time.perf_counter()

    while engine.steps < max_steps:
        if engine.is_win():
            stop_reason = "win"
            break
        actions = engine.get_legal_actions()
        if not actions:
            stop_reason = "hard_dead_end"
            break

        before_state = engine.visible_text()
        before_state_data = engine.get_visible_state()
        legal_labels = [engine.action_label(action) for action in actions]
        try:
            decision = agent.choose(engine, actions)
            if decision.action not in actions:
                raise ValueError("agent returned an action outside the legal action set")
        except Exception as exc:  # Benchmark failures are data, not silent fallback.
            stop_reason = "agent_error"
            error = f"{type(exc).__name__}: {exc}"
            break

        selected_label = engine.action_label(decision.action)
        outcome = engine.step(decision.action)
        was_seen = outcome.state_hash in seen
        if was_seen:
            repeated_states += 1
        else:
            seen.add(outcome.state_hash)

        foundation_high = engine.foundation_cards > max_foundation
        max_foundation = max(max_foundation, engine.foundation_cards)
        structural_progress = outcome.hidden_cards_revealed > 0 or foundation_high
        novel_progress = structural_progress or not was_seen
        cycle_stagnant = 0 if novel_progress else cycle_stagnant + 1

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
            stop_reason = "cycle_stagnation"
            break

    if engine.is_win():
        stop_reason = "win"

    result = GameResult(
        seed=seed,
        agent=agent.name,
        win=engine.is_win(),
        foundation_cards=engine.foundation_cards,
        hidden_cards_revealed=initial_hidden - engine.hidden_cards,
        steps=engine.steps,
        repeated_states=repeated_states,
        unique_states=len(seen),
        stop_reason=stop_reason,
        elapsed_seconds=round(time.perf_counter() - started, 6),
        error=error,
    )
    final_result = "win" if result.win else "loss"
    for record in decisions:
        record["final_result"] = final_result
        record["stop_reason"] = stop_reason
    return result, decisions


def result_json(result: GameResult) -> str:
    return json.dumps(asdict(result), ensure_ascii=False, sort_keys=True)
