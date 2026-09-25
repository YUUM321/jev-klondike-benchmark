from __future__ import annotations

import json
import math
import statistics
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable

from agents.base import Agent, Observation
from solitaire.engine import ActionKind, KlondikeEngine


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
    stagnation_steps: int = 50
    max_steps: int = 700
    policy_forced_decisions: int = 0
    choice_decisions: int = 0
    draw_choices: int = 0
    recycle_choices: int = 0
    draw_rate: float = 0.0
    recycle_rate: float = 0.0
    max_foundation_cards_seen: int = 0


def nearest_rank_percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    if not 0 < percentile <= 1:
        raise ValueError("percentile must be in (0, 1]")
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def progress_snapshot(
    engine: KlondikeEngine,
    *,
    initial_hidden: int,
    visible_state_visit_count: int,
    steps_since_new_visible_state: int,
    max_foundation_cards_seen: int,
    steps_since_foundation_increase: int,
    steps_since_hidden_reveal: int,
    steps_since_structural_progress: int,
    stock_passes_since_structural_progress: int,
) -> dict[str, int]:
    """Return observable facts only; no weights, rewards, or action advice."""

    return {
        "foundation_cards": engine.foundation_cards,
        "max_foundation_cards_seen": max_foundation_cards_seen,
        "tableau_hidden_remaining": engine.hidden_cards,
        "hidden_cards_revealed_total": initial_hidden - engine.hidden_cards,
        "visible_state_visit_count": visible_state_visit_count,
        "steps_since_new_visible_state": steps_since_new_visible_state,
        "steps_since_hidden_reveal": steps_since_hidden_reveal,
        "steps_since_foundation_increase": steps_since_foundation_increase,
        "steps_since_structural_progress": steps_since_structural_progress,
        "stock_passes_since_structural_progress": (
            stock_passes_since_structural_progress
        ),
    }


def run_game(
    agent: Agent,
    seed: int,
    *,
    stagnation_steps: int = 50,
    max_steps: int = 700,
    capture_decisions: bool = False,
    draw_count: int = 1,
    resume_decisions: list[dict[str, Any]] | None = None,
    elapsed_seconds_offset: float = 0.0,
    on_decision: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[GameResult, list[dict[str, Any]]]:
    engine = KlondikeEngine(draw_count=draw_count)
    engine.reset(seed)
    agent.reset(seed)

    initial_hidden = engine.hidden_cards
    seen = {engine.state_hash()}
    initial_visible_hash = engine.visible_state_hash()
    visible_visit_counts = {initial_visible_hash: 1}
    actions_tried_by_visible_state: dict[str, list[str]] = {}
    action_attempts_by_visible_state: dict[str, dict[str, int]] = {}
    action_outcomes_by_visible_state: dict[
        str, dict[str, dict[str, int]]
    ] = {}
    recent_actions: list[str] = []
    recent_transitions: list[dict[str, Any]] = []
    seen_visible_states = {initial_visible_hash}
    steps_since_new_visible_state = 0
    repeated_states = 0
    cycle_stagnant = 0
    forced_decisions = 0
    policy_forced_decisions = 0
    choice_decisions = 0
    draw_choices = 0
    recycle_choices = 0
    max_foundation_cards_seen = engine.foundation_cards
    steps_since_foundation_increase = 0
    steps_since_hidden_reveal = 0
    steps_since_structural_progress = 0
    stock_passes_since_structural_progress = 0
    decision_latencies_ms: list[float] = []
    decisions: list[dict[str, Any]] = []
    termination_reason = "turn_cap"
    error: str | None = None
    if resume_decisions and not capture_decisions:
        raise ValueError("resume_decisions requires capture_decisions=True")

    # Restore the exact engine and public-memory state from committed actions.
    # Hidden cards never need to be serialized: reset(seed) plus deterministic
    # legal actions reconstructs the same full state locally.
    for prior in sorted(resume_decisions or [], key=lambda item: item["step"]):
        if prior.get("seed") != seed or prior.get("agent") != agent.name:
            raise ValueError("resume decision belongs to a different game")
        if prior.get("draw_count", draw_count) != draw_count:
            raise ValueError("resume decision uses a different draw count")
        if prior.get("step") != engine.steps + 1:
            raise ValueError("resume decisions are not a contiguous step sequence")
        if prior.get("visible_state_data") != engine.get_visible_state():
            raise ValueError(
                f"resume state mismatch before step {prior.get('step')}"
            )

        actions = engine.get_legal_actions()
        selected = [
            action
            for action in actions
            if engine.action_label(action) == prior.get("selected")
        ]
        if len(selected) != 1:
            raise ValueError(
                f"cannot reconstruct resume action at step {prior.get('step')}"
            )
        before_visible_hash = engine.visible_state_hash()
        before_progress = progress_snapshot(
            engine,
            initial_hidden=initial_hidden,
            visible_state_visit_count=visible_visit_counts[before_visible_hash],
            steps_since_new_visible_state=steps_since_new_visible_state,
            max_foundation_cards_seen=max_foundation_cards_seen,
            steps_since_foundation_increase=steps_since_foundation_increase,
            steps_since_hidden_reveal=steps_since_hidden_reveal,
            steps_since_structural_progress=steps_since_structural_progress,
            stock_passes_since_structural_progress=(
                stock_passes_since_structural_progress
            ),
        )
        if "progress" in prior and prior["progress"] != before_progress:
            raise ValueError(
                f"resume progress mismatch before step {prior.get('step')}"
            )
        selected_label = str(prior["selected"])
        tried_here = actions_tried_by_visible_state.setdefault(
            before_visible_hash, []
        )
        if selected_label not in tried_here:
            tried_here.append(selected_label)
        attempts_here = action_attempts_by_visible_state.setdefault(
            before_visible_hash, {}
        )
        attempts_here[selected_label] = attempts_here.get(selected_label, 0) + 1

        forced = bool(prior.get("forced", len(actions) == 1))
        policy_forced = bool(prior.get("policy_forced", False))
        if forced:
            forced_decisions += 1
        elif policy_forced:
            policy_forced_decisions += 1
        else:
            decision_latencies_ms.append(float(prior["decision_latency_ms"]))
            choice_decisions += 1
            if selected[0].kind is ActionKind.DRAW:
                draw_choices += 1
            elif selected[0].kind is ActionKind.RECYCLE:
                recycle_choices += 1

        outcome = engine.step(selected[0])
        foundation_reached_new_peak = (
            engine.foundation_cards > max_foundation_cards_seen
        )
        max_foundation_cards_seen = max(
            max_foundation_cards_seen, engine.foundation_cards
        )
        steps_since_foundation_increase = (
            0
            if outcome.foundation_delta > 0
            else steps_since_foundation_increase + 1
        )
        steps_since_hidden_reveal = (
            0
            if outcome.hidden_cards_revealed > 0
            else steps_since_hidden_reveal + 1
        )
        structural_progress = (
            outcome.hidden_cards_revealed > 0 or foundation_reached_new_peak
        )
        steps_since_structural_progress = (
            0 if structural_progress else steps_since_structural_progress + 1
        )
        if structural_progress:
            stock_passes_since_structural_progress = 0
        elif selected[0].kind is ActionKind.RECYCLE:
            stock_passes_since_structural_progress += 1
        recent_actions.append(selected_label)
        after_visible_hash = engine.visible_state_hash()
        visible_visit_counts[after_visible_hash] = (
            visible_visit_counts.get(after_visible_hash, 0) + 1
        )
        reached_new_visible_state = after_visible_hash not in seen_visible_states
        if reached_new_visible_state:
            seen_visible_states.add(after_visible_hash)
            steps_since_new_visible_state = 0
        else:
            steps_since_new_visible_state += 1
        outcome_id = f"v_{after_visible_hash[:12]}"
        outcomes_here = action_outcomes_by_visible_state.setdefault(
            before_visible_hash, {}
        ).setdefault(selected_label, {})
        outcomes_here[outcome_id] = outcomes_here.get(outcome_id, 0) + 1
        recent_transitions.append(
            {
                "action": selected_label,
                "outcome_visible_state": outcome_id,
                "outcome_was_new": reached_new_visible_state,
                "outcome_visit_count": visible_visit_counts[after_visible_hash],
            }
        )
        was_seen = outcome.state_hash in seen
        if was_seen:
            repeated_states += 1
        else:
            seen.add(outcome.state_hash)
        cycle_stagnant = cycle_stagnant + 1 if was_seen else 0

        if prior.get("state_after_data") != engine.get_visible_state():
            raise ValueError(
                f"resume state mismatch after step {prior.get('step')}"
            )
        if prior.get("state_hash_after") != outcome.state_hash:
            raise ValueError(
                f"resume full-state hash mismatch after step {prior.get('step')}"
            )
        after_progress = progress_snapshot(
            engine,
            initial_hidden=initial_hidden,
            visible_state_visit_count=visible_visit_counts[after_visible_hash],
            steps_since_new_visible_state=steps_since_new_visible_state,
            max_foundation_cards_seen=max_foundation_cards_seen,
            steps_since_foundation_increase=steps_since_foundation_increase,
            steps_since_hidden_reveal=steps_since_hidden_reveal,
            steps_since_structural_progress=steps_since_structural_progress,
            stock_passes_since_structural_progress=(
                stock_passes_since_structural_progress
            ),
        )
        if "progress_after" in prior and prior["progress_after"] != after_progress:
            raise ValueError(
                f"resume progress mismatch after step {prior.get('step')}"
            )
        decisions.append(dict(prior))

    if cycle_stagnant >= stagnation_steps:
        termination_reason = "cycle_stagnation"

    # Reconstructing a saved state is recovery overhead, not agent/game runtime.
    started = time.perf_counter()
    while termination_reason == "turn_cap" and engine.steps < max_steps:
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
        before_progress = progress_snapshot(
            engine,
            initial_hidden=initial_hidden,
            visible_state_visit_count=visible_visit_counts.get(
                before_visible_hash, 1
            ),
            steps_since_new_visible_state=steps_since_new_visible_state,
            max_foundation_cards_seen=max_foundation_cards_seen,
            steps_since_foundation_increase=steps_since_foundation_increase,
            steps_since_hidden_reveal=steps_since_hidden_reveal,
            steps_since_structural_progress=steps_since_structural_progress,
            stock_passes_since_structural_progress=(
                stock_passes_since_structural_progress
            ),
        )
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
            action_attempt_counts=dict(
                action_attempts_by_visible_state.get(before_visible_hash, {})
            ),
            action_outcome_counts={
                label: dict(outcomes)
                for label, outcomes in action_outcomes_by_visible_state.get(
                    before_visible_hash, {}
                ).items()
            },
            steps_since_new_visible_state=steps_since_new_visible_state,
            recent_actions=tuple(recent_actions[-8:]),
            recent_transitions=tuple(recent_transitions[-8:]),
            progress=before_progress,
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
        policy_forced = bool(decision.metadata.get("policy_forced", False))
        if forced:
            forced_decisions += 1
        elif policy_forced:
            policy_forced_decisions += 1
        else:
            decision_latencies_ms.append(decision_latency_ms)
            choice_decisions += 1
            if decision.action.kind is ActionKind.DRAW:
                draw_choices += 1
            elif decision.action.kind is ActionKind.RECYCLE:
                recycle_choices += 1

        selected_label = engine.action_label(decision.action)
        tried_here = actions_tried_by_visible_state.setdefault(
            before_visible_hash, []
        )
        if selected_label not in tried_here:
            tried_here.append(selected_label)
        attempts_here = action_attempts_by_visible_state.setdefault(
            before_visible_hash, {}
        )
        attempts_here[selected_label] = attempts_here.get(selected_label, 0) + 1
        outcome = engine.step(decision.action)
        foundation_reached_new_peak = (
            engine.foundation_cards > max_foundation_cards_seen
        )
        max_foundation_cards_seen = max(
            max_foundation_cards_seen, engine.foundation_cards
        )
        steps_since_foundation_increase = (
            0
            if outcome.foundation_delta > 0
            else steps_since_foundation_increase + 1
        )
        steps_since_hidden_reveal = (
            0
            if outcome.hidden_cards_revealed > 0
            else steps_since_hidden_reveal + 1
        )
        structural_progress = (
            outcome.hidden_cards_revealed > 0 or foundation_reached_new_peak
        )
        steps_since_structural_progress = (
            0 if structural_progress else steps_since_structural_progress + 1
        )
        if structural_progress:
            stock_passes_since_structural_progress = 0
        elif decision.action.kind is ActionKind.RECYCLE:
            stock_passes_since_structural_progress += 1
        recent_actions.append(selected_label)
        after_visible_hash = engine.visible_state_hash()
        visible_visit_counts[after_visible_hash] = (
            visible_visit_counts.get(after_visible_hash, 0) + 1
        )
        reached_new_visible_state = after_visible_hash not in seen_visible_states
        if reached_new_visible_state:
            seen_visible_states.add(after_visible_hash)
            steps_since_new_visible_state = 0
        else:
            steps_since_new_visible_state += 1
        outcome_id = f"v_{after_visible_hash[:12]}"
        outcomes_here = action_outcomes_by_visible_state.setdefault(
            before_visible_hash, {}
        ).setdefault(selected_label, {})
        outcomes_here[outcome_id] = outcomes_here.get(outcome_id, 0) + 1
        recent_transitions.append(
            {
                "action": selected_label,
                "outcome_visible_state": outcome_id,
                "outcome_was_new": reached_new_visible_state,
                "outcome_visit_count": visible_visit_counts[after_visible_hash],
            }
        )
        after_legal_labels = [
            engine.action_label(action) for action in engine.get_legal_actions()
        ]
        after_public_history = {
            "visible_state_visit_count": visible_visit_counts[after_visible_hash],
            "actions_tried_from_visible_state": list(
                actions_tried_by_visible_state.get(after_visible_hash, ())
            ),
            "action_attempt_counts": dict(
                action_attempts_by_visible_state.get(after_visible_hash, {})
            ),
            "action_outcome_counts": {
                label: dict(outcomes)
                for label, outcomes in action_outcomes_by_visible_state.get(
                    after_visible_hash, {}
                ).items()
            },
            "steps_since_new_visible_state": steps_since_new_visible_state,
            "recent_actions": list(recent_actions[-8:]),
            "recent_transitions": list(recent_transitions[-8:]),
        }
        after_progress = progress_snapshot(
            engine,
            initial_hidden=initial_hidden,
            visible_state_visit_count=visible_visit_counts[after_visible_hash],
            steps_since_new_visible_state=steps_since_new_visible_state,
            max_foundation_cards_seen=max_foundation_cards_seen,
            steps_since_foundation_increase=steps_since_foundation_increase,
            steps_since_hidden_reveal=steps_since_hidden_reveal,
            steps_since_structural_progress=steps_since_structural_progress,
            stock_passes_since_structural_progress=(
                stock_passes_since_structural_progress
            ),
        )
        was_seen = outcome.state_hash in seen
        if was_seen:
            repeated_states += 1
        else:
            seen.add(outcome.state_hash)

        cycle_stagnant = cycle_stagnant + 1 if was_seen else 0

        if capture_decisions:
            record = {
                "seed": seed,
                "agent": agent.name,
                "draw_count": draw_count,
                "step": engine.steps,
                "visible_state": before_state,
                "visible_state_data": before_state_data,
                "public_history": {
                    "visible_state_visit_count": observation.visible_state_visit_count,
                    "actions_tried_from_visible_state": list(
                        observation.actions_tried_from_visible_state
                    ),
                    "action_attempt_counts": dict(
                        observation.action_attempt_counts
                    ),
                    "action_outcome_counts": {
                        label: dict(outcomes)
                        for label, outcomes in observation.action_outcome_counts.items()
                    },
                    "steps_since_new_visible_state": (
                        observation.steps_since_new_visible_state
                    ),
                    "recent_actions": list(observation.recent_actions),
                    "recent_transitions": list(observation.recent_transitions),
                },
                "public_history_after": after_public_history,
                "progress": before_progress,
                "progress_after": after_progress,
                "legal_actions": legal_labels,
                "legal_actions_after": after_legal_labels,
                "selected": selected_label,
                "action_kind": decision.action.kind.value,
                "confidence": decision.confidence,
                "probabilities": decision.probabilities,
                "decision_metadata": decision.metadata,
                "forced": forced,
                "policy_forced": policy_forced,
                "decision_latency_ms": round(decision_latency_ms, 6),
                "elapsed_seconds_at_commit": round(
                    elapsed_seconds_offset + time.perf_counter() - started, 6
                ),
                "state_after": engine.visible_text(),
                "state_after_data": engine.get_visible_state(),
                "state_hash_after": outcome.state_hash,
                "new_hidden_cards_revealed": outcome.hidden_cards_revealed,
                "foundation_delta": outcome.foundation_delta,
            }
            decisions.append(record)
            if on_decision is not None:
                on_decision(record)

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
        policy_forced_decisions=policy_forced_decisions,
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
        elapsed_seconds=round(
            elapsed_seconds_offset + time.perf_counter() - started, 6
        ),
        draw_count=draw_count,
        error=error,
        stagnation_steps=stagnation_steps,
        max_steps=max_steps,
        choice_decisions=choice_decisions,
        draw_choices=draw_choices,
        recycle_choices=recycle_choices,
        draw_rate=(
            round(draw_choices / choice_decisions, 6) if choice_decisions else 0.0
        ),
        recycle_rate=(
            round(recycle_choices / choice_decisions, 6)
            if choice_decisions
            else 0.0
        ),
        max_foundation_cards_seen=max_foundation_cards_seen,
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
