from __future__ import annotations

import hashlib
import json
import os
import random
import time
import urllib.error
import urllib.request
from typing import Any

from solitaire.engine import Action

from .base import Decision, Observation


class JevAPIError(RuntimeError):
    pass


class JevAgent:
    """Strict adapter for TypeSafe's System One Choice API.

    API errors and invalid choices stop the game. There is deliberately no
    hidden first-action or heuristic fallback that could inflate Jev's score.
    """

    name = "jev"
    INSTRUCTIONS = (
        "Goal: maximize the probability of eventually winning this Klondike game. "
        "Choose exactly one of the supplied legal actions. Consider future "
        "flexibility, hidden-card revelation, and dead-end risk."
    )

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_key_env: str = "TYPESAFE_API_KEY",
        base_url: str = "https://api.typesafe.ai",
        model: str = "jev-latest",
        timeout: float = 30.0,
        retries: int = 2,
        option_order: str = "seeded",
        option_order_seed: int = 0,
    ) -> None:
        self.api_key = api_key or os.getenv(api_key_env)
        self.api_key_env = api_key_env
        self.endpoint = f"{base_url.rstrip('/')}/v1/systemone"
        self.model = model
        self.timeout = timeout
        self.retries = retries
        if option_order not in {"seeded", "canonical"}:
            raise ValueError("option_order must be 'seeded' or 'canonical'")
        self.option_order = option_order
        self.option_order_seed = option_order_seed

    def reset(self, seed: int) -> None:
        pass

    def _ordered(self, observation: Observation, actions: list[Action]) -> list[Action]:
        ordered = list(actions)
        if self.option_order == "seeded":
            # Ordering may depend only on public observation data. The game seed
            # and full state hash both encode hidden cards and are forbidden here.
            material = (
                f"option-order-v1:{self.option_order_seed}:"
                f"{observation.step}:{observation.visible_state_hash}"
            ).encode("utf-8")
            order_seed = int.from_bytes(hashlib.sha256(material).digest()[:8], "big")
            random.Random(order_seed).shuffle(ordered)
        return ordered

    def choose(self, observation: Observation, actions: list[Action]) -> Decision:
        if not actions:
            raise ValueError("cannot choose without a legal action")
        if len(actions) == 1:
            return Decision(
                action=actions[0],
                confidence=None,
                probabilities={},
                metadata={"forced": True, "candidate_count": 1},
            )
        if not self.api_key:
            raise JevAPIError(
                f"missing API key in {self.api_key_env}; no fallback was used"
            )
        if len(actions) > 255:
            raise JevAPIError(
                f"{len(actions)} legal actions exceed the documented 255 Choice limit"
            )

        ordered = self._ordered(observation, actions)
        option_map = {f"a{index:03d}": action for index, action in enumerate(ordered)}
        criteria = {
            option_id: observation.label(action)
            for option_id, action in option_map.items()
        }
        payload = {
            "model": self.model,
            "state": {
                "game": "Klondike Solitaire",
                "rules": "Draw-1; unlimited stock recycling; standard Klondike rules",
                "visible_state": observation.visible_state,
            },
            "questions": {
                "action": {
                    "type": "choice",
                    "instructions": self.INSTRUCTIONS,
                    "criteria": criteria,
                }
            },
        }
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request_hash = hashlib.sha256(encoded).hexdigest()
        request = urllib.request.Request(
            self.endpoint,
            data=encoded,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "jev-klondike-benchmark/0.1",
            },
            method="POST",
        )

        started = time.perf_counter()
        response_data: dict[str, Any] | None = None
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    response_data = json.loads(response.read().decode("utf-8"))
                break
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(0.5 * (2**attempt))
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        if response_data is None:
            raise JevAPIError(f"Jev request failed after retries: {last_error}")

        answers = response_data.get("answers")
        if answers is None and isinstance(response_data.get("result"), dict):
            answers = response_data["result"].get("answers")
        answer = answers.get("action") if isinstance(answers, dict) else None
        if not isinstance(answer, dict):
            raise JevAPIError("Jev response has no answers.action object")
        selected_id = answer.get("choice")
        if selected_id not in option_map:
            raise JevAPIError(f"Jev returned an unknown option: {selected_id!r}")

        raw_probabilities = answer.get("probabilities", {})
        probabilities = {
            criteria[option_id]: float(probability)
            for option_id, probability in raw_probabilities.items()
            if option_id in criteria
        }
        return Decision(
            action=option_map[selected_id],
            confidence=float(answer.get("confidence", 0.0)),
            probabilities=probabilities,
            metadata={
                "forced": False,
                "candidate_count": len(actions),
                "option_order": self.option_order,
                "request_sha256": request_hash,
                "latency_ms": latency_ms,
                "model": response_data.get("model", self.model),
                "usage": response_data.get("usage"),
                "request_id": response_data.get("request_id"),
            },
        )
