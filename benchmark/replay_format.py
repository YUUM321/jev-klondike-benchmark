from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from solitaire.engine import KlondikeEngine

from .runner import GameResult


REPLAY_SCHEMA_VERSION = 1


def build_replay(
    result: GameResult, decisions: list[dict[str, Any]]
) -> dict[str, Any]:
    """Convert one captured game into the stable browser replay schema."""

    engine = KlondikeEngine()
    initial_state = engine.reset(result.seed)
    initial_actions = [engine.action_label(action) for action in engine.get_legal_actions()]
    if decisions:
        initial_state = decisions[0]["visible_state_data"]
        initial_actions = decisions[0]["legal_actions"]

    frames: list[dict[str, Any]] = [
        {
            "step": 0,
            "state": initial_state,
            "action": None,
            "confidence": None,
            "probabilities": {},
            "legal_actions": initial_actions,
            "events": {"hidden_revealed": 0, "foundation_delta": 0},
            "decision_metadata": {},
        }
    ]
    for index, decision in enumerate(decisions):
        next_legal = (
            decisions[index + 1]["legal_actions"]
            if index + 1 < len(decisions)
            else []
        )
        frames.append(
            {
                "step": decision["step"],
                "state": decision["state_after_data"],
                "action": decision["selected"],
                "confidence": decision["confidence"],
                "probabilities": decision["probabilities"],
                "legal_actions": next_legal,
                "events": {
                    "hidden_revealed": decision["new_hidden_cards_revealed"],
                    "foundation_delta": decision["foundation_delta"],
                },
                "state_hash": decision["state_hash_after"],
                "decision_metadata": decision["decision_metadata"],
            }
        )

    return {
        "schema_version": REPLAY_SCHEMA_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "game": {
            "name": "Klondike Solitaire",
            "variant": "Draw-1",
            "stock_recycles": "unlimited",
            "tableau_flip": "automatic",
        },
        "run": asdict(result),
        "frames": frames,
    }
