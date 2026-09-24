from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from solitaire.engine import KlondikeEngine

from .runner import GameResult


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
    initial_actions = [engine.action_label(action) for action in engine.get_legal_actions()]
    if decisions:
        initial_state = decisions[0]["visible_state_data"]
        initial_actions = decisions[0]["legal_actions"]

    frames: list[dict[str, Any]] = [
        {
            "step": 0,
            "state_before": initial_state,
            "state_after": initial_state,
            "action": None,
            "confidence": None,
            "probabilities": {},
            "legal_actions": initial_actions,
            "events": {"hidden_revealed": 0, "foundation_delta": 0},
            "decision_metadata": {},
            "public_history": {
                "visible_state_visit_count": 1,
                "actions_tried_from_visible_state": [],
                "recent_actions": [],
            },
            "forced": False,
            "decision_latency_ms": None,
        }
    ]
    for decision in decisions:
        frames.append(
            {
                "step": decision["step"],
                "state_before": decision["visible_state_data"],
                "state_after": decision["state_after_data"],
                "action": decision["selected"],
                "confidence": decision["confidence"],
                "probabilities": decision["probabilities"],
                "legal_actions": decision["legal_actions"],
                "events": {
                    "hidden_revealed": decision["new_hidden_cards_revealed"],
                    "foundation_delta": decision["foundation_delta"],
                },
                "state_hash": decision["state_hash_after"],
                "decision_metadata": decision["decision_metadata"],
                "public_history": decision.get("public_history", {}),
                "forced": decision["forced"],
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
