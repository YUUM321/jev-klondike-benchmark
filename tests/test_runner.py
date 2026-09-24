import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
import csv

from agents import JevAgent, Observation
from benchmark.metrics import summarize, write_runs_csv
from benchmark.runner import run_game
from run_benchmark import is_high_confidence_loss
from solitaire import ActionKind, KlondikeEngine


class FirstActionAgent:
    name = "first"

    def reset(self, seed: int) -> None:
        pass

    def choose(self, observation, actions):
        from agents.base import Decision

        return Decision(actions[0])


class RunnerTests(unittest.TestCase):
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
        self.assertAlmostEqual(result.revisit_rate, 5 / 29, places=6)

    def test_csv_keeps_termination_and_revisit_metrics(self) -> None:
        result, _ = run_game(FirstActionAgent(), 0, max_steps=3)
        summary = summarize([result])[0]
        self.assertIn("turn_caps", summary)
        self.assertIn("mean_unique_states_visited", summary)
        self.assertIn("mean_revisit_rate", summary)
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "runs.csv"
            write_runs_csv(path, [result])
            with path.open(encoding="utf-8", newline="") as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["termination_reason"], "turn_cap")
            self.assertIn("unique_states_visited", row)
            self.assertIn("revisit_rate", row)


if __name__ == "__main__":
    unittest.main()
