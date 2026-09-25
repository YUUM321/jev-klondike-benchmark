import json
import unittest
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from agents import HeuristicAgent
from benchmark.replay_format import build_replay
from benchmark.export_replays import export_replays
from benchmark.runner import run_game
from solitaire import KlondikeEngine


class ReplayTests(unittest.TestCase):
    def test_public_example_matches_current_replay_contract(self) -> None:
        root = Path(__file__).resolve().parents[1]
        schema = json.loads(
            (root / "web" / "replay.schema.json").read_text(encoding="utf-8")
        )
        replay = json.loads(
            (root / "web" / "replay.example.json").read_text(encoding="utf-8")
        )

        self.assertEqual(
            replay["schema_version"],
            schema["properties"]["schema_version"]["const"],
        )
        self.assertIn("draw_rate", replay["run"])
        self.assertIn("recycle_rate", replay["run"])
        self.assertIn("max_foundation_cards_seen", replay["run"])
        for frame in replay["frames"]:
            self.assertIn("action_kind", frame)
            self.assertIn("progress_before", frame)
            self.assertIn("progress_after", frame)

    def test_replay_has_initial_frame_and_one_frame_per_action(self) -> None:
        result, decisions = run_game(
            HeuristicAgent(), 2, max_steps=5, capture_decisions=True
        )
        replay = build_replay(result, decisions)
        self.assertEqual(replay["schema_version"], 2)
        self.assertEqual(len(replay["frames"]), result.steps + 1)
        self.assertEqual(replay["frames"][0]["step"], 0)
        self.assertIsNone(replay["frames"][0]["action"])
        self.assertEqual(replay["frames"][-1]["step"], result.steps)
        self.assertIsNone(replay["frames"][0]["decision_latency_ms"])
        self.assertGreaterEqual(replay["frames"][1]["decision_latency_ms"], 0)

    def test_initial_replay_frame_does_not_leak_hidden_cards(self) -> None:
        result, decisions = run_game(
            HeuristicAgent(), 37, max_steps=1, capture_decisions=True
        )
        replay = build_replay(result, decisions)
        initial_json = json.dumps(replay["frames"][0]["state_before"])
        engine = KlondikeEngine()
        engine.reset(37)
        for pile in engine.tableau:
            for card in pile:
                if not card.face_up:
                    self.assertNotIn(card.code, initial_json)

    def test_draw_three_replay_declares_variant_and_visible_packet(self) -> None:
        result, decisions = run_game(
            HeuristicAgent(), 2, max_steps=20, capture_decisions=True, draw_count=3
        )
        replay = build_replay(result, decisions)
        self.assertEqual(replay["game"]["variant"], "Draw-3")
        self.assertEqual(replay["game"]["draw_count"], 3)
        draw_frames = [
            frame for frame in replay["frames"] if frame["action"] == "draw up to 3 cards from stock"
        ]
        self.assertTrue(draw_frames)
        self.assertGreaterEqual(len(draw_frames[0]["state_after"]["waste_visible"]), 1)

    def test_decision_frame_keeps_pre_and_post_state_aligned(self) -> None:
        result, decisions = run_game(
            HeuristicAgent(), 2, max_steps=2, capture_decisions=True
        )
        replay = build_replay(result, decisions)
        frame = replay["frames"][1]
        decision = decisions[0]
        self.assertEqual(frame["state_before"], decision["visible_state_data"])
        self.assertEqual(frame["state_after"], decision["state_after_data"])
        self.assertEqual(frame["legal_actions"], decision["legal_actions"])
        self.assertEqual(frame["legal_actions_before"], decision["legal_actions"])
        self.assertEqual(
            frame["legal_actions_after"], decision["legal_actions_after"]
        )
        self.assertEqual(
            frame["public_history_after"], decision["public_history_after"]
        )
        self.assertEqual(frame["action"], decision["selected"])
        self.assertEqual(frame["action_kind"], decision["action_kind"])
        self.assertEqual(frame["progress_before"], decision["progress"])
        self.assertEqual(frame["progress_after"], decision["progress_after"])
        self.assertEqual(frame["policy_forced"], decision["policy_forced"])

    def test_old_decision_logs_reconstruct_after_phase_context(self) -> None:
        result, decisions = run_game(
            HeuristicAgent(), 2, max_steps=3, capture_decisions=True, draw_count=3
        )
        for decision in decisions:
            decision.pop("legal_actions_after")
            decision.pop("public_history_after")
        replay = build_replay(result, decisions)
        self.assertIn("legal_actions_after", replay["frames"][-1])
        self.assertIn("public_history_after", replay["frames"][-1])
        self.assertGreaterEqual(
            replay["frames"][-1]["public_history_after"]["visible_state_visit_count"],
            1,
        )

    def test_existing_benchmark_logs_export_without_rerunning_agent(self) -> None:
        result, decisions = run_game(
            HeuristicAgent(), 2, max_steps=4, capture_decisions=True
        )
        with TemporaryDirectory() as temporary:
            result_dir = Path(temporary)
            (result_dir / "manifest.json").write_text(
                json.dumps({"rules": {"variant": "Klondike Draw-1", "draw_count": 1}}),
                encoding="utf-8",
            )
            (result_dir / "runs.jsonl").write_text(
                json.dumps(asdict(result)) + "\n", encoding="utf-8"
            )
            (result_dir / "decisions.jsonl").write_text(
                "".join(json.dumps(record) + "\n" for record in decisions),
                encoding="utf-8",
            )
            [path] = export_replays(result_dir)
            replay = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(replay["run"]["seed"], 2)
            self.assertEqual(replay["schema_version"], 2)
            self.assertEqual(len(replay["frames"]), result.steps + 1)


if __name__ == "__main__":
    unittest.main()
