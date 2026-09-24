from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from benchmark.seed_sets import (
    EVAL_V01_COUNT,
    EVAL_V01_MASTER_SEED,
    EVAL_V01_NAMESPACE,
    EVAL_V01_UPPER_BOUND,
    SEED_SET_FILES,
    expected_eval_v01_seeds,
)


def encoded_seed_file(seeds: list[int]) -> bytes:
    return ("\n".join(map(str, seeds)) + "\n").encode("utf-8")


def expected_files() -> tuple[bytes, bytes]:
    seed_bytes = encoded_seed_file(expected_eval_v01_seeds())
    metadata = {
        "schema_version": 1,
        "seed_set": "eval-v0.1",
        "role": "held-out evaluation",
        "selection_uses_agent_results": False,
        "algorithm": "sha256-counter-v1",
        "algorithm_definition": (
            "candidate = uint64_be(SHA256(namespace + NUL + master_seed + NUL + "
            "decimal_counter)[0:8]) mod upper_bound; keep first count unique values"
        ),
        "namespace": EVAL_V01_NAMESPACE,
        "master_seed": EVAL_V01_MASTER_SEED,
        "counter_start": 0,
        "upper_bound_exclusive": EVAL_V01_UPPER_BOUND,
        "count": EVAL_V01_COUNT,
        "seed_file": "eval-v0.1.txt",
        "seed_file_sha256": hashlib.sha256(seed_bytes).hexdigest(),
    }
    metadata_bytes = (
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    return seed_bytes, metadata_bytes


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reproduce or verify the frozen eval-v0.1 seed set"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify committed files instead of writing them",
    )
    args = parser.parse_args()

    seed_path = SEED_SET_FILES["eval-v0.1"]
    metadata_path = seed_path.with_suffix(".json")
    expected_seed_bytes, expected_metadata_bytes = expected_files()

    if args.check:
        mismatches = [
            str(path)
            for path, expected in (
                (seed_path, expected_seed_bytes),
                (metadata_path, expected_metadata_bytes),
            )
            if not path.exists() or path.read_bytes() != expected
        ]
        if mismatches:
            raise SystemExit("seed artifact mismatch: " + ", ".join(mismatches))
        print("eval-v0.1 seed artifacts match the frozen generation contract")
        return

    seed_path.parent.mkdir(parents=True, exist_ok=True)
    seed_path.write_bytes(expected_seed_bytes)
    metadata_path.write_bytes(expected_metadata_bytes)
    print(f"wrote {seed_path}")
    print(f"wrote {metadata_path}")


if __name__ == "__main__":
    main()
