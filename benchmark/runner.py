from __future__ import annotations

import json
import math
import statistics
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
    forced_decisions: int
    timed_decisions: int
    decision_latency_ms_total: float
    decision_latency_ms_mean: float | None
    decision_latency_ms_median: float | None
    decision_latency_ms_p95: float | None
    elapsed_seconds: float
    draw_count: int = 1
    error: str | None = None


def nearest_rank_percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    if not 0 < percentile <= 1:
        raise ValueError("percentile must be in (0, 1]")
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def run_game(
    agent: Agent,
    seed: int,
    *,
    stagnation_steps: int = 50,
    max_steps: int = 2_000,
    capture_decisions: bool = False,
    draw_count: int = 1,
) -> tuple[GameResult, list[dict[str, Any]]]:
    engine = KlondikeEngine(draw_count=draw_count)
    engine.reset(seed)
    agent.reset(seed)

    initial_hidden = engine.hidden_cards
    seen = {engine.state_hash()}
    initial_visible_hash = engine.visible_state_hash()
    visible_visit_counts = {initial_visible_hash: 1}
    actions_tried_by_visible_state: dict[str, list[str]] = {}
    recent_actions: list[str] = []
    repeated_states = 0
    cycle_stagnant = 0
    forced_decisions = 0
    decision_latencies_ms: list[float] = []
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
        before_visible_hash = engine.visible_state_hash()
        legal_labels = [engine.action_label(action) for action in actions]
        observation = Observation(
            visible_state=before_state_data,
            visible_text=before_state,
            visible_state_hash=before_visible_hash,
            step=engine.steps,
            action_labels=dict(zip(actions, legal_labels)),
            draw_count=draw_count,
            visible_state_visit_count=visible_visit_counts.get(
                before_visible_hash, 1
            ),
            actions_tried_from_visible_state=tuple(
                actions_tried_by_visible_state.get(before_visible_hash, ())
            ),
            recent_actions=tuple(recent_actions[-8:]),
        )
        forced = len(actions) == 1
        decision_started_ns = time.perf_counter_ns()
        try:
            decision = agent.choose(observation, actions)
            if decision.action not in actions:
                raise ValueError("agent returned an action outside the legal action set")
        except Exception as exc:  # Benchmark failures are data, not silent fallback.
            termination_reason = "agent_error"
            error = f"{type(exc).__name__}: {exc}"
            break
        decision_latency_ms = (time.perf_counter_ns() - decision_started_ns) / 1_000_000
        if forced:
            forced_decisions += 1
        else:
            decision_latencies_ms.append(decision_latency_ms)

        selected_label = engine.action_label(decision.action)
        tried_here = actions_tried_by_visible_state.setdefault(
            before_visible_hash, []
        )
        if selected_label not in tried_here:
            tried_here.append(selected_label)
        outcome = engine.step(decision.action)
        recent_actions.append(selected_label)
        after_visible_hash = engine.visible_state_hash()
        visible_visit_counts[after_visible_hash] = (
            visible_visit_counts.get(after_visible_hash, 0) + 1
        )
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
                    "draw_count": draw_count,
                    "step": engine.steps,
                    "visible_state": before_state,
                    "visible_state_data": before_state_data,
                    "public_history": {
                        "visible_state_visit_count": (
                            observation.visible_state_visit_count
                        ),
                        "actions_tried_from_visible_state": list(
                            observation.actions_tried_from_visible_state
                        ),
                        "recent_actions": list(observation.recent_actions),
                    },
                    "legal_actions": legal_labels,
                    "selected": selected_label,
                    "confidence": decision.confidence,
                    "probabilities": decision.probabilities,
                    "decision_metadata": decision.metadata,
                    "forced": forced,
                    "decision_latency_ms": round(decision_latency_ms, 6),
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

    latency_total = sum(decision_latencies_ms)
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
        forced_decisions=forced_decisions,
        timed_decisions=len(decision_latencies_ms),
        decision_latency_ms_total=round(latency_total, 6),
        decision_latency_ms_mean=(
            round(latency_total / len(decision_latencies_ms), 6)
            if decision_latencies_ms
            else None
        ),
        decision_latency_ms_median=(
            round(statistics.median(decision_latencies_ms), 6)
            if decision_latencies_ms
            else None
        ),
        decision_latency_ms_p95=(
            round(nearest_rank_percentile(decision_latencies_ms, 0.95), 6)
            if decision_latencies_ms
            else None
        ),
        elapsed_seconds=round(time.perf_counter() - started, 6),
        draw_count=draw_count,
        error=error,
    )
    final_result = (
        "win"
        if result.win
        else "error"
        if termination_reason == "agent_error"
        else "loss"
    )
    for record in decisions:
        record["final_result"] = final_result
        record["termination_reason"] = termination_reason
    return result, decisions


def result_json(result: GameResult) -> str:
    return json.dumps(asdict(result), ensure_ascii=False, sort_keys=True)
