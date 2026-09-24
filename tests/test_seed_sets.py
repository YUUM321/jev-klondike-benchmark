import json
import unittest

from benchmark.generate_seed_set import expected_files
from benchmark.seed_sets import (
    EVAL_V01_COUNT,
    SEED_SET_FILES,
    expected_eval_v01_seeds,
    read_seed_file,
    seed_file_sha256,
)
from solitaire import KlondikeEngine


class SeedSetTests(unittest.TestCase):
    def test_dev_set_is_the_known_development_range(self) -> None:
        self.assertEqual(read_seed_file(SEED_SET_FILES["dev"]), list(range(100)))

    def test_eval_set_matches_the_frozen_generator(self) -> None:
        eval_path = SEED_SET_FILES["eval-v0.1"]
        metadata_path = eval_path.with_suffix(".json")
        expected_seed_bytes, expected_metadata_bytes = expected_files()

        self.assertEqual(eval_path.read_bytes(), expected_seed_bytes)
        self.assertEqual(metadata_path.read_bytes(), expected_metadata_bytes)

        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["seed_file_sha256"], seed_file_sha256(eval_path))
        self.assertFalse(metadata["selection_uses_agent_results"])

    def test_eval_set_is_unique_and_disjoint_from_dev(self) -> None:
        development = set(read_seed_file(SEED_SET_FILES["dev"]))
        evaluation = read_seed_file(SEED_SET_FILES["eval-v0.1"])

        self.assertEqual(len(evaluation), EVAL_V01_COUNT)
        self.assertEqual(len(set(evaluation)), EVAL_V01_COUNT)
        self.assertTrue(development.isdisjoint(evaluation))
        self.assertEqual(evaluation, expected_eval_v01_seeds())

    def test_eval_set_has_no_duplicate_initial_deals(self) -> None:
        engine = KlondikeEngine()
        hashes = []
        for seed in read_seed_file(SEED_SET_FILES["eval-v0.1"]):
            engine.reset(seed)
            hashes.append(engine.state_hash())
        self.assertEqual(len(hashes), len(set(hashes)))


if __name__ == "__main__":
    unittest.main()
