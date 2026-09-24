import unittest

from agents import JevAgent
from benchmark.runner import run_game
from solitaire import Action, KlondikeEngine


class FirstActionAgent:
    name = "first"

    def reset(self, seed: int) -> None:
        pass

    def choose(self, engine, actions):
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
        self.assertIn("state_after", decisions[0])

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
        with self.assertRaisesRegex(RuntimeError, "no fallback"):
            agent.choose(engine, actions)


if __name__ == "__main__":
    unittest.main()
