from __future__ import annotations

import hashlib
import json
import os
import random
import ssl
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
    TLS_VERSION = "TLSv1.2"
    CONTEXT_MODE = "history"
    RAW_INSTRUCTIONS = (
        "Goal: maximize the probability of eventually winning this Klondike game. "
        "Choose exactly one of the supplied legal actions. Consider future "
        "flexibility, hidden-card revelation, and dead-end risk."
    )
    HISTORY_INSTRUCTIONS = (
        f"{RAW_INSTRUCTIONS} Use the supplied public history as memory across "
        "decisions."
    )
    PROGRESS_INSTRUCTIONS = (
        f"{HISTORY_INSTRUCTIONS} Progress indicators are observable facts, not a "
        "reward score. Use them to distinguish structural progress from repeated "
        "or merely novel rearrangements."
    )
    INSTRUCTIONS = HISTORY_INSTRUCTIONS

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
        proxy_url: str | None = None,
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
        self.proxy_url = proxy_url or os.getenv("HTTPS_PROXY") or os.getenv(
            "https_proxy"
        )
        self._opener = self._build_opener()

    def _build_opener(self) -> urllib.request.OpenerDirector:
        """Build a proxy-aware opener with a reproducible TLS 1.2 transport."""

        proxy_map = (
            {"http": self.proxy_url, "https": self.proxy_url}
            if self.proxy_url
            else urllib.request.getproxies()
        )
        context = ssl.create_default_context()
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.maximum_version = ssl.TLSVersion.TLSv1_2
        return urllib.request.build_opener(
            urllib.request.ProxyHandler(proxy_map),
            urllib.request.HTTPSHandler(context=context),
        )

    def reset(self, seed: int) -> None:
        pass

    @staticmethod
    def _rules_text(draw_count: int) -> str:
        draw_rule = (
            "Draw one card from stock at a time."
            if draw_count == 1
            else "Draw up to three cards from stock; only the top waste card is playable."
        )
        return (
            f"{draw_rule} Unlimited stock recycling without reshuffling. "
            "Tableau builds downward in alternating colors. Only Kings or "
            "King-led sequences may enter empty tableau columns. Exposed "
            "tableau cards flip automatically. Foundations build by suit from "
            "Ace to King, and foundation top cards may move back to tableau."
        )

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

    def _criterion_text(self, observation: Observation, action: Action) -> str:
        label = observation.label(action)
        if self.CONTEXT_MODE == "raw":
            return label
        attempts = observation.action_attempt_counts.get(label, 0)
        if attempts == 0:
            return f"{label} | memory: untried from this visible state"
        outcomes = observation.action_outcome_counts.get(label, {})
        outcome_text = ", ".join(
            f"{state} x{count}" for state, count in sorted(outcomes.items())
        )
        return (
            f"{label} | memory: tried {attempts} time(s) from this visible state; "
            f"observed outcomes: {outcome_text or 'none recorded'}"
        )

    @staticmethod
    def _public_history(observation: Observation) -> dict[str, Any]:
        return {
            "version": "public-history-v2",
            "visible_state_visit_count": observation.visible_state_visit_count,
            "actions_tried_from_visible_state": list(
                observation.actions_tried_from_visible_state
            ),
            "action_attempt_counts": dict(observation.action_attempt_counts),
            "action_outcome_counts": {
                label: dict(outcomes)
                for label, outcomes in observation.action_outcome_counts.items()
            },
            "steps_since_new_visible_state": (
                observation.steps_since_new_visible_state
            ),
            "recent_actions": list(observation.recent_actions),
            "recent_transitions": list(observation.recent_transitions),
        }

    def _state_payload(self, observation: Observation) -> dict[str, Any]:
        state: dict[str, Any] = {
            "game": "Klondike Solitaire",
            "rules": self._rules_text(observation.draw_count),
            "visible_state": observation.visible_state,
        }
        if self.CONTEXT_MODE in {"history", "progress", "guard"}:
            state["public_history"] = self._public_history(observation)
        if self.CONTEXT_MODE == "progress":
            state["progress"] = {
                "version": "observable-progress-v1",
                **observation.progress,
            }
        return state

    def choose(self, observation: Observation, actions: list[Action]) -> Decision:
        if not actions:
            raise ValueError("cannot choose without a legal action")
        if len(actions) == 1:
            return Decision(
                action=actions[0],
                confidence=None,
                probabilities={},
                metadata={
                    "forced": True,
                    "candidate_count": 1,
                    "context_mode": self.CONTEXT_MODE,
                },
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
            option_id: self._criterion_text(observation, action)
            for option_id, action in option_map.items()
        }
        payload = {
            "model": self.model,
            "state": self._state_payload(observation),
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
                with self._opener.open(request, timeout=self.timeout) as response:
                    response_data = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                try:
                    body = exc.read().decode("utf-8", errors="replace").strip()
                finally:
                    exc.close()
                request_id = exc.headers.get("x-typesafe-request-id")
                details = f" body={body[:2_000]}" if body else ""
                request_details = (
                    f" request_id={request_id}" if request_id else ""
                )
                raise JevAPIError(
                    f"Jev HTTP {exc.code} {exc.reason}{request_details}{details}"
                ) from exc
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
            observation.label(option_map[option_id]): float(probability)
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
                "context_mode": self.CONTEXT_MODE,
                "option_order": self.option_order,
                "request_sha256": request_hash,
                "latency_ms": latency_ms,
                "attempts": attempt + 1,
                "model": response_data.get("model", self.model),
                "usage": response_data.get("usage"),
                "request_id": response_data.get("request_id"),
            },
        )


class JevRawAgent(JevAgent):
    """Jev with only the current visible state, rules, and legal actions."""

    name = "jev_raw"
    CONTEXT_MODE = "raw"
    INSTRUCTIONS = JevAgent.RAW_INSTRUCTIONS


class JevHistoryAgent(JevAgent):
    """Canonical explicit name for the public-history-v2 condition."""

    name = "jev_history"
    CONTEXT_MODE = "history"
    INSTRUCTIONS = JevAgent.HISTORY_INSTRUCTIONS


class JevProgressAgent(JevHistoryAgent):
    """History condition plus unweighted, observable progress indicators."""

    name = "jev_progress"
    CONTEXT_MODE = "progress"
    INSTRUCTIONS = JevAgent.PROGRESS_INSTRUCTIONS


class JevGuardAgent(JevHistoryAgent):
    """Jev with an explicit public-memory guard against unproductive repeats.

    If an exact visible state has legal actions that have never been tried from
    that state, previously tried actions are withheld for that decision. This
    uses only public history and is reported as a separate benchmark agent.
    """

    name = "jev_guard"
    CONTEXT_MODE = "guard"
    MEMORY_POLICY = "untried-actions-first-v1"

    @staticmethod
    def _memory_candidates(
        observation: Observation, actions: list[Action]
    ) -> tuple[list[Action], bool]:
        untried = [
            action
            for action in actions
            if observation.action_attempt_counts.get(observation.label(action), 0)
            == 0
        ]
        guarded = bool(untried) and len(untried) < len(actions)
        return (untried if guarded else actions), guarded

    def choose(self, observation: Observation, actions: list[Action]) -> Decision:
        candidates, guarded = self._memory_candidates(observation, actions)
        decision = super().choose(observation, candidates)
        excluded = [
            observation.label(action) for action in actions if action not in candidates
        ]
        policy_forced = len(actions) > 1 and len(candidates) == 1
        decision.metadata.update(
            {
                "forced": len(actions) == 1,
                "policy_forced": policy_forced,
                "memory_policy": self.MEMORY_POLICY,
                "memory_guard_applied": guarded,
                "full_legal_count": len(actions),
                "excluded_previously_tried_actions": excluded,
            }
        )
        return decision


class JevMemoryAgent(JevGuardAgent):
    """Backward-compatible name for the jev_guard experimental condition."""

    name = "jev_memory"
