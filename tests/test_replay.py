import json
import unittest

from agents import HeuristicAgent
from benchmark.replay_format import build_replay
from benchmark.runner import run_game
from solitaire import KlondikeEngine


class ReplayTests(unittest.TestCase):
    def test_replay_has_initial_frame_and_one_frame_per_action(self) -> None:
        result, decisions = run_game(
            HeuristicAgent(), 2, max_steps=5, capture_decisions=True
        )
        replay = build_replay(result, decisions)
        self.assertEqual(replay["schema_version"], 1)
        self.assertEqual(len(replay["frames"]), result.steps + 1)
        self.assertEqual(replay["frames"][0]["step"], 0)
        self.assertIsNone(replay["frames"][0]["action"])
        self.assertEqual(replay["frames"][-1]["step"], result.steps)

    def test_initial_replay_frame_does_not_leak_hidden_cards(self) -> None:
        result, decisions = run_game(
            HeuristicAgent(), 37, max_steps=1, capture_decisions=True
        )
        replay = build_replay(result, decisions)
        initial_json = json.dumps(replay["frames"][0]["state"])
        engine = KlondikeEngine()
        engine.reset(37)
        for pile in engine.tableau:
            for card in pile:
                if not card.face_up:
                    self.assertNotIn(card.code, initial_json)


if __name__ == "__main__":
    unittest.main()
