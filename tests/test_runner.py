import unittest
import ssl
from io import BytesIO
from tempfile import TemporaryDirectory
from pathlib import Path
import csv
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from agents import (
    JevAgent,
    JevGuardAgent,
    JevHistoryAgent,
    JevMemoryAgent,
    JevProgressAgent,
    JevRawAgent,
    Observation,
)
from benchmark.metrics import summarize, write_runs_csv
from benchmark.runner import nearest_rank_percentile, run_game
from run_benchmark import (
    is_high_confidence_loss,
    portable_path,
    read_jsonl,
    sanitized_argv,
)
from solitaire import ActionKind, KlondikeEngine


class FirstActionAgent:
    name = "first"

    def reset(self, seed: int) -> None:
        pass

    def choose(self, observation, actions):
        from agents.base import Decision

        return Decision(actions[0])


class RunnerTests(unittest.TestCase):
    def test_manifest_paths_are_publishable(self) -> None:
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "repository"
            internal_seed = root / "benchmark" / "seeds" / "dev.txt"
            external_seed = base / "private" / "custom.txt"
            output_dir = base / "private" / "results"

            self.assertEqual(
                portable_path(internal_seed, root), "benchmark/seeds/dev.txt"
            )
            self.assertEqual(
                portable_path(external_seed, root), "<external>/custom.txt"
            )
            self.assertEqual(
                sanitized_argv(
                    [
                        "run_benchmark.py",
                        "--seeds",
                        str(external_seed),
                        "--output-dir",
                        str(output_dir),
                    ],
                    root,
                ),
                [
                    "run_benchmark.py",
                    "--seeds",
                    "<external>/custom.txt",
                    "--output-dir",
                    "<output-dir>",
                ],
            )
            self.assertEqual(
                sanitized_argv(
                    [
                        "run_benchmark.py",
                        f"--seeds={external_seed}",
                        f"--output-dir={output_dir}",
                    ],
                    root,
                ),
                [
                    "run_benchmark.py",
                    "--seeds=<external>/custom.txt",
                    "--output-dir=<output-dir>",
                ],
            )

    def test_runner_records_required_metrics(self) -> None:
        result, decisions = run_game(
            FirstActionAgent(), 3, max_steps=20, capture_decisions=True
        )
        self.assertEqual(result.seed, 3)
        self.assertLessEqual(result.steps, 20)
        self.assertEqual(len(decisions), result.steps)
        self.assertIn("final_result", decisions[0])
        self.assertIn("termination_reason", decisions[0])
        self.assertIn("state_after", decisions[0])
        self.assertIn("public_history", decisions[0])
        self.assertIn("decision_latency_ms", decisions[0])
        self.assertIn("elapsed_seconds_at_commit", decisions[0])
        self.assertGreaterEqual(decisions[0]["decision_latency_ms"], 0)
        self.assertEqual(
            result.forced_decisions
            + result.policy_forced_decisions
            + result.timed_decisions,
            result.steps,
        )
        self.assertGreaterEqual(result.decision_latency_ms_total, 0)
        self.assertEqual(
            result.repeated_states + result.unique_states_visited - 1,
            result.steps,
        )

    def test_jev_missing_key_fails_instead_of_falling_back(self) -> None:
        engine = KlondikeEngine()
        # Find a deterministic opening with more than one legal choice.
        for seed in range(100):
            engine.reset(seed)
            actions = engine.get_legal_actions()
            if len(actions) > 1:
                break
        agent = JevAgent(api_key_env="DEFINITELY_NOT_A_REAL_ENV_VAR")
        agent.reset(seed)
        labels = {action: engine.action_label(action) for action in actions}
        observation = Observation(
            visible_state=engine.get_visible_state(),
            visible_text=engine.visible_text(),
            visible_state_hash=engine.visible_state_hash(),
            step=engine.steps,
            action_labels=labels,
        )
        with self.assertRaisesRegex(RuntimeError, "no fallback"):
            agent.choose(observation, actions)

    def test_jev_http_error_preserves_response_body(self) -> None:
        engine = KlondikeEngine()
        engine.reset(0)
        actions = engine.get_legal_actions()
        observation = Observation(
            visible_state=engine.get_visible_state(),
            visible_text=engine.visible_text(),
            visible_state_hash=engine.visible_state_hash(),
            step=engine.steps,
            action_labels={action: engine.action_label(action) for action in actions},
        )
        agent = JevAgent(api_key="test-key", retries=2)
        agent._opener = Mock()
        agent._opener.open.side_effect = HTTPError(
            "https://api.typesafe.ai/v1/systemone",
            403,
            "Forbidden",
            {"x-typesafe-request-id": "req_test"},
            BytesIO(b'{"detail":"quota exceeded"}'),
        )

        with self.assertRaisesRegex(
            RuntimeError, r'Jev HTTP 403 Forbidden.*req_test.*quota exceeded'
        ):
            agent.choose(observation, actions)

    def test_jev_pins_tls_1_2_for_direct_connections(self) -> None:
        context = Mock()
        with patch("agents.jev_agent.ssl.create_default_context", return_value=context):
            JevAgent(api_key="test-key", proxy_url=None)

        self.assertEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)
        self.assertEqual(context.maximum_version, ssl.TLSVersion.TLSv1_2)

    def test_agent_receives_observation_not_engine(self) -> None:
        class BoundaryAgent:
            name = "boundary"

            def reset(self, seed: int) -> None:
                pass

            def choose(self, observation, actions):
                from agents.base import Decision

                self.observation = observation
                return Decision(actions[0])

        agent = BoundaryAgent()
        run_game(agent, 4, max_steps=1)
        self.assertIsInstance(agent.observation, Observation)
        self.assertFalse(hasattr(agent.observation, "stock"))
        self.assertFalse(hasattr(agent.observation, "tableau"))

    def test_forced_jev_decision_has_no_model_confidence(self) -> None:
        engine = KlondikeEngine()
        engine.reset(0)
        action = engine.get_legal_actions()[0]
        observation = Observation(
            visible_state=engine.get_visible_state(),
            visible_text=engine.visible_text(),
            visible_state_hash=engine.visible_state_hash(),
            step=0,
            action_labels={action: engine.action_label(action)},
        )
        decision = JevAgent(api_key_env="DEFINITELY_NOT_A_REAL_ENV_VAR").choose(
            observation, [action]
        )
        self.assertIsNone(decision.confidence)
        self.assertTrue(decision.metadata["forced"])
        self.assertFalse(
            is_high_confidence_loss(
                {
                    "final_result": "loss",
                    "confidence": 1.0,
                    "decision_metadata": {"forced": True},
                }
            )
        )
        self.assertTrue(
            is_high_confidence_loss(
                {
                    "final_result": "loss",
                    "confidence": 0.95,
                    "decision_metadata": {"forced": False},
                }
            )
        )
        self.assertFalse(
            is_high_confidence_loss(
                {
                    "final_result": "loss",
                    "confidence": 0.99,
                    "decision_metadata": {
                        "forced": False,
                        "policy_forced": True,
                    },
                }
            )
        )

    def test_agent_error_is_not_a_loss_or_high_confidence_failure(self) -> None:
        class ErrorAfterOneAgent:
            name = "error-after-one"

            def reset(self, seed: int) -> None:
                self.calls = 0

            def choose(self, observation, actions):
                from agents.base import Decision

                self.calls += 1
                if self.calls > 1:
                    raise RuntimeError("simulated failure")
                return Decision(actions[0], confidence=0.99)

        result, decisions = run_game(
            ErrorAfterOneAgent(), 0, max_steps=3, capture_decisions=True
        )
        self.assertEqual(result.termination_reason, "agent_error")
        self.assertEqual(decisions[0]["final_result"], "error")
        self.assertFalse(is_high_confidence_loss(decisions[0]))

    def test_interrupted_game_resumes_from_last_committed_action(self) -> None:
        class InterruptingFirstActionAgent(FirstActionAgent):
            def reset(self, seed: int) -> None:
                self.calls = 0

            def choose(self, observation, actions):
                self.calls += 1
                if self.calls > 4:
                    raise ConnectionError("simulated TLS disconnect")
                return super().choose(observation, actions)

        interrupted, partial = run_game(
            InterruptingFirstActionAgent(),
            7,
            max_steps=12,
            capture_decisions=True,
        )
        self.assertEqual(interrupted.termination_reason, "agent_error")
        self.assertEqual(len(partial), 4)

        newly_committed = []
        resumed, resumed_decisions = run_game(
            FirstActionAgent(),
            7,
            max_steps=12,
            capture_decisions=True,
            resume_decisions=partial,
            elapsed_seconds_offset=interrupted.elapsed_seconds,
            on_decision=newly_committed.append,
        )
        uninterrupted, uninterrupted_decisions = run_game(
            FirstActionAgent(), 7, max_steps=12, capture_decisions=True
        )

        self.assertEqual(
            [record["selected"] for record in resumed_decisions],
            [record["selected"] for record in uninterrupted_decisions],
        )
        self.assertEqual(len(newly_committed), resumed.steps - len(partial))
        for field in (
            "win",
            "foundation_cards",
            "hidden_cards_revealed",
            "steps",
            "repeated_states",
            "unique_states_visited",
            "termination_reason",
        ):
            self.assertEqual(getattr(resumed, field), getattr(uninterrupted, field))
        self.assertGreaterEqual(resumed.elapsed_seconds, interrupted.elapsed_seconds)

    def test_resume_rejects_tampered_state(self) -> None:
        _, partial = run_game(
            FirstActionAgent(), 2, max_steps=2, capture_decisions=True
        )
        partial[0]["state_hash_after"] = "tampered"
        with self.assertRaisesRegex(ValueError, "full-state hash mismatch"):
            run_game(
                FirstActionAgent(),
                2,
                max_steps=4,
                capture_decisions=True,
                resume_decisions=partial,
            )

    def test_checkpoint_reader_discards_only_a_truncated_final_line(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "checkpoint.jsonl"
            path.write_text('{"step": 1}\n{"step":', encoding="utf-8")
            self.assertEqual(
                read_jsonl(path, tolerate_truncated_final=True), [{"step": 1}]
            )
            with self.assertRaisesRegex(ValueError, "invalid JSON"):
                read_jsonl(path)

    def test_public_history_is_shared_through_observation(self) -> None:
        class HistoryCaptureAgent:
            name = "history-capture"

            def reset(self, seed: int) -> None:
                self.observations = []

            def choose(self, observation, actions):
                from agents.base import Decision

                self.observations.append(observation)
                selected = next(
                    action
                    for action in actions
                    if action.kind in {ActionKind.DRAW, ActionKind.RECYCLE}
                )
                return Decision(selected)

        agent = HistoryCaptureAgent()
        run_game(agent, 0, max_steps=30)
        repeated = next(
            observation
            for observation in agent.observations
            if observation.visible_state_visit_count > 1
        )
        self.assertTrue(repeated.actions_tried_from_visible_state)
        self.assertTrue(repeated.action_attempt_counts)
        self.assertTrue(repeated.action_outcome_counts)
        self.assertTrue(repeated.recent_transitions)
        self.assertLessEqual(len(repeated.recent_actions), 8)

    def test_memory_agent_forces_the_only_untried_legal_action(self) -> None:
        engine = KlondikeEngine(draw_count=3)
        for seed in range(100):
            engine.reset(seed)
            actions = engine.get_legal_actions()
            if len(actions) > 1:
                break
        labels = {action: engine.action_label(action) for action in actions}
        untried = actions[-1]
        attempted = {labels[action]: 2 for action in actions[:-1]}
        observation = Observation(
            visible_state=engine.get_visible_state(),
            visible_text=engine.visible_text(),
            visible_state_hash=engine.visible_state_hash(),
            step=12,
            action_labels=labels,
            draw_count=3,
            visible_state_visit_count=3,
            actions_tried_from_visible_state=tuple(attempted),
            action_attempt_counts=attempted,
            steps_since_new_visible_state=7,
        )

        decision = JevMemoryAgent(
            api_key_env="DEFINITELY_NOT_A_REAL_ENV_VAR"
        ).choose(observation, actions)

        self.assertEqual(decision.action, untried)
        self.assertTrue(decision.metadata["memory_guard_applied"])
        self.assertTrue(decision.metadata["policy_forced"])
        self.assertEqual(
            len(decision.metadata["excluded_previously_tried_actions"]),
            len(actions) - 1,
        )

    def test_memory_agent_excludes_repeated_action_when_alternatives_exist(self) -> None:
        engine = KlondikeEngine(draw_count=3)
        for seed in range(100):
            engine.reset(seed)
            actions = engine.get_legal_actions()
            if len(actions) >= 3:
                break
        labels = {action: engine.action_label(action) for action in actions}
        repeated = actions[0]
        observation = Observation(
            visible_state=engine.get_visible_state(),
            visible_text=engine.visible_text(),
            visible_state_hash=engine.visible_state_hash(),
            step=20,
            action_labels=labels,
            draw_count=3,
            action_attempt_counts={labels[repeated]: 8},
        )

        candidates, guarded = JevMemoryAgent._memory_candidates(
            observation, actions
        )

        self.assertTrue(guarded)
        self.assertNotIn(repeated, candidates)
        self.assertEqual(candidates, actions[1:])

    def test_jev_rule_contract_is_explicit(self) -> None:
        rules = JevAgent._rules_text(3)
        self.assertIn("without reshuffling", rules)
        self.assertIn("Only Kings", rules)
        self.assertIn("flip automatically", rules)
        self.assertIn("may move back to tableau", rules)

    def test_jev_conditions_have_isolated_context_payloads(self) -> None:
        engine = KlondikeEngine(draw_count=3)
        engine.reset(5)
        actions = engine.get_legal_actions()
        observation = Observation(
            visible_state=engine.get_visible_state(),
            visible_text=engine.visible_text(),
            visible_state_hash=engine.visible_state_hash(),
            step=12,
            action_labels={action: engine.action_label(action) for action in actions},
            draw_count=3,
            visible_state_visit_count=4,
            action_attempt_counts={engine.action_label(actions[0]): 3},
            progress={
                "foundation_cards": 2,
                "max_foundation_cards_seen": 4,
                "tableau_hidden_remaining": 17,
                "hidden_cards_revealed_total": 4,
                "visible_state_visit_count": 4,
                "steps_since_new_visible_state": 9,
                "steps_since_hidden_reveal": 11,
                "steps_since_foundation_increase": 7,
                "steps_since_structural_progress": 11,
                "stock_passes_since_structural_progress": 1,
            },
        )

        raw_state = JevRawAgent()._state_payload(observation)
        history_state = JevHistoryAgent()._state_payload(observation)
        progress_state = JevProgressAgent()._state_payload(observation)
        guard_state = JevGuardAgent()._state_payload(observation)

        self.assertNotIn("public_history", raw_state)
        self.assertNotIn("progress", raw_state)
        self.assertEqual(
            JevRawAgent()._criterion_text(observation, actions[0]),
            observation.label(actions[0]),
        )
        self.assertIn("public_history", history_state)
        self.assertNotIn("progress", history_state)
        self.assertIn("public_history", progress_state)
        self.assertEqual(
            progress_state["progress"]["version"], "observable-progress-v1"
        )
        self.assertEqual(progress_state["progress"]["foundation_cards"], 2)
        self.assertIn("public_history", guard_state)
        self.assertNotIn("progress", guard_state)

    def test_progress_log_contains_only_observable_consistent_facts(self) -> None:
        result, decisions = run_game(
            FirstActionAgent(), 9, max_steps=20, capture_decisions=True, draw_count=3
        )
        required = {
            "foundation_cards",
            "max_foundation_cards_seen",
            "tableau_hidden_remaining",
            "hidden_cards_revealed_total",
            "visible_state_visit_count",
            "steps_since_new_visible_state",
            "steps_since_hidden_reveal",
            "steps_since_foundation_increase",
            "steps_since_structural_progress",
            "stock_passes_since_structural_progress",
        }
        for index, decision in enumerate(decisions):
            progress = decision["progress"]
            after = decision["progress_after"]
            self.assertEqual(set(progress), required)
            self.assertEqual(
                progress["tableau_hidden_remaining"],
                sum(
                    card == "XX"
                    for pile in decision["visible_state_data"]["tableau"]
                    for card in pile
                ),
            )
            self.assertEqual(
                progress["hidden_cards_revealed_total"]
                + progress["tableau_hidden_remaining"],
                21,
            )
            self.assertGreaterEqual(
                after["max_foundation_cards_seen"],
                progress["max_foundation_cards_seen"],
            )
            self.assertIn(
                decision["action_kind"], {kind.value for kind in ActionKind}
            )
            if index + 1 < len(decisions):
                self.assertEqual(after, decisions[index + 1]["progress"])
        self.assertEqual(
            result.max_foundation_cards_seen,
            decisions[-1]["progress_after"]["max_foundation_cards_seen"],
        )

    def test_draw_and_recycle_rates_exclude_forced_choices(self) -> None:
        class StockCycleAgent:
            name = "stock-rate"

            def reset(self, seed: int) -> None:
                pass

            def choose(self, observation, actions):
                from agents.base import Decision

                selected = next(
                    action
                    for action in actions
                    if action.kind in {ActionKind.DRAW, ActionKind.RECYCLE}
                )
                return Decision(selected)

        result, decisions = run_game(
            StockCycleAgent(), 0, max_steps=35, capture_decisions=True, draw_count=3
        )
        eligible = [
            record
            for record in decisions
            if not record["forced"] and not record["policy_forced"]
        ]
        draws = sum(record["action_kind"] == "draw" for record in eligible)
        recycles = sum(record["action_kind"] == "recycle" for record in eligible)
        self.assertEqual(result.choice_decisions, len(eligible))
        self.assertEqual(result.draw_choices, draws)
        self.assertEqual(result.recycle_choices, recycles)
        self.assertAlmostEqual(
            result.draw_rate, draws / len(eligible) if eligible else 0.0, places=6
        )
        self.assertAlmostEqual(
            result.recycle_rate,
            recycles / len(eligible) if eligible else 0.0,
            places=6,
        )

    def test_jev_option_order_does_not_depend_on_hidden_state_or_game_seed(self) -> None:
        engine = KlondikeEngine()
        for seed in range(100):
            engine.reset(seed)
            actions = engine.get_legal_actions()
            if len(actions) > 2:
                break
        hidden_variant = engine.clone()
        hidden_variant.stock[0], hidden_variant.stock[1] = (
            hidden_variant.stock[1],
            hidden_variant.stock[0],
        )

        def observation_for(game):
            return Observation(
                visible_state=game.get_visible_state(),
                visible_text=game.visible_text(),
                visible_state_hash=game.visible_state_hash(),
                step=game.steps,
                action_labels={
                    action: game.action_label(action) for action in actions
                },
            )

        first_agent = JevAgent(option_order_seed=17)
        second_agent = JevAgent(option_order_seed=17)
        first_agent.reset(1)
        second_agent.reset(999)
        first_order = first_agent._ordered(observation_for(engine), actions)
        second_order = second_agent._ordered(observation_for(hidden_variant), actions)
        self.assertEqual(first_order, second_order)

    def test_cycle_stagnation_counts_only_transitions_to_seen_states(self) -> None:
        class StockCycleAgent:
            name = "stock-cycle"

            def reset(self, seed: int) -> None:
                pass

            def choose(self, observation, actions):
                from agents.base import Decision

                action = next(
                    action
                    for action in actions
                    if action.kind in {ActionKind.DRAW, ActionKind.RECYCLE}
                )
                return Decision(action)

        result, _ = run_game(StockCycleAgent(), 0, stagnation_steps=5)
        self.assertEqual(result.termination_reason, "cycle_stagnation")
        self.assertEqual(result.repeated_states, 5)
        self.assertEqual(result.unique_states_visited, 25)
        self.assertEqual(result.steps, 29)
        self.assertEqual(result.stagnation_steps, 5)
        self.assertAlmostEqual(result.revisit_rate, 5 / 29, places=6)

    def test_csv_keeps_termination_and_revisit_metrics(self) -> None:
        result, _ = run_game(FirstActionAgent(), 0, max_steps=3)
        summary = summarize([result])[0]
        self.assertIn("turn_caps", summary)
        self.assertIn("mean_unique_states_visited", summary)
        self.assertIn("mean_revisit_rate", summary)
        self.assertIn("mean_decision_latency_ms", summary)
        self.assertIn("mean_game_p95_decision_latency_ms", summary)
        self.assertIn("draw_rate", summary)
        self.assertIn("recycle_rate", summary)
        self.assertIn("mean_max_foundation_cards_seen", summary)
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "runs.csv"
            write_runs_csv(path, [result])
            with path.open(encoding="utf-8", newline="") as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["termination_reason"], "turn_cap")
            self.assertIn("unique_states_visited", row)
            self.assertIn("revisit_rate", row)
            self.assertIn("decision_latency_ms_median", row)
            self.assertIn("decision_latency_ms_p95", row)
            self.assertIn("draw_rate", row)
            self.assertIn("recycle_rate", row)

    def test_latency_percentile_uses_nearest_rank(self) -> None:
        self.assertIsNone(nearest_rank_percentile([], 0.95))
        self.assertEqual(nearest_rank_percentile([4, 1, 3, 2], 0.50), 2)
        self.assertEqual(nearest_rank_percentile([4, 1, 3, 2], 0.95), 4)


if __name__ == "__main__":
    unittest.main()
