import unittest

from agents import HeuristicAgent, RandomAgent
from benchmark.runner import run_game
from solitaire import KlondikeEngine


class DeterminismTests(unittest.TestCase):
    def test_same_seed_same_deal(self) -> None:
        first = KlondikeEngine()
        second = KlondikeEngine()
        self.assertEqual(first.reset(37), second.reset(37))
        self.assertEqual(first.state_hash(), second.state_hash())

    def test_different_seed_different_deal(self) -> None:
        first = KlondikeEngine()
        second = KlondikeEngine()
        first.reset(1)
        second.reset(2)
        self.assertNotEqual(first.state_hash(), second.state_hash())

    def test_random_agent_is_reproducible(self) -> None:
        first, _ = run_game(RandomAgent(), 9, max_steps=150)
        second, _ = run_game(RandomAgent(), 9, max_steps=150)
        comparable = (
            "win",
            "foundation_cards",
            "hidden_cards_revealed",
            "steps",
            "repeated_states",
            "unique_states",
            "stop_reason",
        )
        self.assertEqual(
            tuple(getattr(first, key) for key in comparable),
            tuple(getattr(second, key) for key in comparable),
        )

    def test_heuristic_agent_is_reproducible(self) -> None:
        first, _ = run_game(HeuristicAgent(), 11, max_steps=150)
        second, _ = run_game(HeuristicAgent(), 11, max_steps=150)
        self.assertEqual(first.foundation_cards, second.foundation_cards)
        self.assertEqual(first.hidden_cards_revealed, second.hidden_cards_revealed)
        self.assertEqual(first.steps, second.steps)


if __name__ == "__main__":
    unittest.main()
