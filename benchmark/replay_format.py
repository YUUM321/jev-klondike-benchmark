from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from solitaire.engine import ActionKind, KlondikeEngine

from .runner import GameResult, progress_snapshot


REPLAY_SCHEMA_VERSION = 2


def build_replay(
    result: GameResult,
    decisions: list[dict[str, Any]],
    *,
    draw_count: int | None = None,
) -> dict[str, Any]:
    """Convert one captured game into the stable browser replay schema."""

    draw_count = draw_count or result.draw_count
    engine = KlondikeEngine(draw_count=draw_count)
    initial_state = engine.reset(result.seed)
    initial_hidden = engine.hidden_cards
    initial_actions = [engine.action_label(action) for action in engine.get_legal_actions()]
    if decisions:
        initial_state = decisions[0]["visible_state_data"]
        initial_actions = decisions[0]["legal_actions"]

    initial_progress = progress_snapshot(
        engine,
        initial_hidden=initial_hidden,
        visible_state_visit_count=1,
        steps_since_new_visible_state=0,
        max_foundation_cards_seen=engine.foundation_cards,
        steps_since_foundation_increase=0,
        steps_since_hidden_reveal=0,
        steps_since_structural_progress=0,
        stock_passes_since_structural_progress=0,
    )
    frames: list[dict[str, Any]] = [
        {
            "step": 0,
            "state_before": initial_state,
            "state_after": initial_state,
            "action": None,
            "action_kind": None,
            "confidence": None,
            "probabilities": {},
            "legal_actions": initial_actions,
            "legal_actions_before": initial_actions,
            "legal_actions_after": initial_actions,
            "events": {"hidden_revealed": 0, "foundation_delta": 0},
            "decision_metadata": {},
            "public_history": {
                "visible_state_visit_count": 1,
                "actions_tried_from_visible_state": [],
                "action_attempt_counts": {},
                "action_outcome_counts": {},
                "steps_since_new_visible_state": 0,
                "recent_actions": [],
                "recent_transitions": [],
            },
            "public_history_before": {
                "visible_state_visit_count": 1,
                "actions_tried_from_visible_state": [],
                "action_attempt_counts": {},
                "action_outcome_counts": {},
                "steps_since_new_visible_state": 0,
                "recent_actions": [],
                "recent_transitions": [],
            },
            "public_history_after": {
                "visible_state_visit_count": 1,
                "actions_tried_from_visible_state": [],
                "action_attempt_counts": {},
                "action_outcome_counts": {},
                "steps_since_new_visible_state": 0,
                "recent_actions": [],
                "recent_transitions": [],
            },
            "progress": initial_progress,
            "progress_before": initial_progress,
            "progress_after": initial_progress,
            "forced": False,
            "policy_forced": False,
            "decision_latency_ms": None,
        }
    ]
    # Reconstruct phase-specific context so older decisions.jsonl artifacts can
    # be re-exported without another paid agent run.
    visible_visit_counts = {engine.visible_state_hash(): 1}
    actions_tried_by_visible_state: dict[str, list[str]] = {}
    action_attempts_by_visible_state: dict[str, dict[str, int]] = {}
    action_outcomes_by_visible_state: dict[
        str, dict[str, dict[str, int]]
    ] = {}
    recent_actions: list[str] = []
    recent_transitions: list[dict[str, Any]] = []
    seen_visible_states = {engine.visible_state_hash()}
    steps_since_new_visible_state = 0
    max_foundation_cards_seen = engine.foundation_cards
    steps_since_foundation_increase = 0
    steps_since_hidden_reveal = 0
    steps_since_structural_progress = 0
    stock_passes_since_structural_progress = 0
    for decision in decisions:
        before_hash = engine.visible_state_hash()
        reconstructed_history_before = {
            "visible_state_visit_count": visible_visit_counts[before_hash],
            "actions_tried_from_visible_state": list(
                actions_tried_by_visible_state.get(before_hash, ())
            ),
            "action_attempt_counts": dict(
                action_attempts_by_visible_state.get(before_hash, {})
            ),
            "action_outcome_counts": {
                label: dict(outcomes)
                for label, outcomes in action_outcomes_by_visible_state.get(
                    before_hash, {}
                ).items()
            },
            "steps_since_new_visible_state": steps_since_new_visible_state,
            "recent_actions": list(recent_actions[-8:]),
            "recent_transitions": list(recent_transitions[-8:]),
        }
        reconstructed_progress_before = progress_snapshot(
            engine,
            initial_hidden=initial_hidden,
            visible_state_visit_count=visible_visit_counts[before_hash],
            steps_since_new_visible_state=steps_since_new_visible_state,
            max_foundation_cards_seen=max_foundation_cards_seen,
            steps_since_foundation_increase=steps_since_foundation_increase,
            steps_since_hidden_reveal=steps_since_hidden_reveal,
            steps_since_structural_progress=steps_since_structural_progress,
            stock_passes_since_structural_progress=(
                stock_passes_since_structural_progress
            ),
        )
        available = engine.get_legal_actions()
        selected = [
            action
            for action in available
            if engine.action_label(action) == decision["selected"]
        ]
        if len(selected) != 1:
            raise ValueError(
                f"cannot reconstruct replay action at step {decision['step']}: "
                f"{decision['selected']!r}"
            )
        tried_here = actions_tried_by_visible_state.setdefault(before_hash, [])
        if decision["selected"] not in tried_here:
            tried_here.append(decision["selected"])
        attempts_here = action_attempts_by_visible_state.setdefault(before_hash, {})
        attempts_here[decision["selected"]] = (
            attempts_here.get(decision["selected"], 0) + 1
        )
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
        recent_actions.append(decision["selected"])
        after_hash = engine.visible_state_hash()
        visible_visit_counts[after_hash] = visible_visit_counts.get(after_hash, 0) + 1
        reached_new_visible_state = after_hash not in seen_visible_states
        if reached_new_visible_state:
            seen_visible_states.add(after_hash)
            steps_since_new_visible_state = 0
        else:
            steps_since_new_visible_state += 1
        outcome_id = f"v_{after_hash[:12]}"
        outcomes_here = action_outcomes_by_visible_state.setdefault(
            before_hash, {}
        ).setdefault(decision["selected"], {})
        outcomes_here[outcome_id] = outcomes_here.get(outcome_id, 0) + 1
        recent_transitions.append(
            {
                "action": decision["selected"],
                "action_kind": decision.get(
                    "action_kind", selected[0].kind.value
                ),
                "outcome_visible_state": outcome_id,
                "outcome_was_new": reached_new_visible_state,
                "outcome_visit_count": visible_visit_counts[after_hash],
            }
        )
        reconstructed_legal_after = [
            engine.action_label(action) for action in engine.get_legal_actions()
        ]
        reconstructed_history_after = {
            "visible_state_visit_count": visible_visit_counts[after_hash],
            "actions_tried_from_visible_state": list(
                actions_tried_by_visible_state.get(after_hash, ())
            ),
            "action_attempt_counts": dict(
                action_attempts_by_visible_state.get(after_hash, {})
            ),
            "action_outcome_counts": {
                label: dict(outcomes)
                for label, outcomes in action_outcomes_by_visible_state.get(
                    after_hash, {}
                ).items()
            },
            "steps_since_new_visible_state": steps_since_new_visible_state,
            "recent_actions": list(recent_actions[-8:]),
            "recent_transitions": list(recent_transitions[-8:]),
        }
        reconstructed_progress_after = progress_snapshot(
            engine,
            initial_hidden=initial_hidden,
            visible_state_visit_count=visible_visit_counts[after_hash],
            steps_since_new_visible_state=steps_since_new_visible_state,
            max_foundation_cards_seen=max_foundation_cards_seen,
            steps_since_foundation_increase=steps_since_foundation_increase,
            steps_since_hidden_reveal=steps_since_hidden_reveal,
            steps_since_structural_progress=steps_since_structural_progress,
            stock_passes_since_structural_progress=(
                stock_passes_since_structural_progress
            ),
        )
        if engine.get_visible_state() != decision["state_after_data"]:
            raise ValueError(
                f"reconstructed state disagrees with log at step {decision['step']}"
            )
        history_before = {
            **reconstructed_history_before,
            **decision.get("public_history", {}),
        }
        history_after = {
            **reconstructed_history_after,
            **decision.get("public_history_after", {}),
        }
        progress_before = {
            **reconstructed_progress_before,
            **decision.get("progress", {}),
        }
        progress_after = {
            **reconstructed_progress_after,
            **decision.get("progress_after", {}),
        }
        legal_before = decision["legal_actions"]
        legal_after = decision.get("legal_actions_after", reconstructed_legal_after)
        frames.append(
            {
                "step": decision["step"],
                "state_before": decision["visible_state_data"],
                "state_after": decision["state_after_data"],
                "action": decision["selected"],
                "action_kind": decision.get(
                    "action_kind", selected[0].kind.value
                ),
                "confidence": decision["confidence"],
                "probabilities": decision["probabilities"],
                # Compatibility aliases retain the original pre-action meaning.
                "legal_actions": legal_before,
                "legal_actions_before": legal_before,
                "legal_actions_after": legal_after,
                "events": {
                    "hidden_revealed": decision["new_hidden_cards_revealed"],
                    "foundation_delta": decision["foundation_delta"],
                },
                "state_hash": decision["state_hash_after"],
                "decision_metadata": decision["decision_metadata"],
                "public_history": history_before,
                "public_history_before": history_before,
                "public_history_after": history_after,
                "progress": progress_before,
                "progress_before": progress_before,
                "progress_after": progress_after,
                "forced": decision["forced"],
                "policy_forced": decision.get("policy_forced", False),
                "decision_latency_ms": decision["decision_latency_ms"],
            }
        )

    return {
        "schema_version": REPLAY_SCHEMA_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "game": {
            "name": "Klondike Solitaire",
            "variant": f"Draw-{draw_count}",
            "draw_count": draw_count,
            "stock_recycles": "unlimited",
            "tableau_flip": "automatic",
        },
        "run": asdict(result),
        "frames": frames,
    }


def write_replay(
    path: Path,
    result: GameResult,
    decisions: list[dict[str, Any]],
    *,
    draw_count: int | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            build_replay(result, decisions, draw_count=draw_count),
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
