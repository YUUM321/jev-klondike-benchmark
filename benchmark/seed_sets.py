from __future__ import annotations

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SEED_DIR = ROOT / "benchmark" / "seeds"
SEED_SET_FILES = {
    "dev": SEED_DIR / "dev.txt",
    "eval-v0.1": SEED_DIR / "eval-v0.1.txt",
}

EVAL_V01_MASTER_SEED = "20260924"
EVAL_V01_NAMESPACE = "jev-klondike/eval-v0.1"
EVAL_V01_COUNT = 100
EVAL_V01_UPPER_BOUND = 2**31


def read_seed_file(path: Path) -> list[int]:
    seeds: list[int] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.partition("#")[0].strip()
        if line:
            seeds.append(int(line))
    if len(seeds) != len(set(seeds)):
        raise ValueError(f"seed file contains duplicates: {path}")
    return seeds


def stable_seed_sample(
    *,
    master_seed: str,
    namespace: str,
    count: int,
    upper_bound: int = EVAL_V01_UPPER_BOUND,
) -> list[int]:
    """Return a version-independent deterministic sample without replacement.

    SHA-256 counter blocks are converted to integers. The v0.1 bound is a
    power of two, so reduction introduces no modulo bias.
    """

    if count < 1:
        raise ValueError("count must be positive")
    if upper_bound < count or upper_bound < 1:
        raise ValueError("upper_bound must be at least count")

    seeds: list[int] = []
    seen: set[int] = set()
    counter = 0
    while len(seeds) < count:
        payload = f"{namespace}\0{master_seed}\0{counter}".encode("utf-8")
        digest = hashlib.sha256(payload).digest()
        candidate = int.from_bytes(digest[:8], "big") % upper_bound
        counter += 1
        if candidate not in seen:
            seen.add(candidate)
            seeds.append(candidate)
    return seeds


def expected_eval_v01_seeds() -> list[int]:
    return stable_seed_sample(
        master_seed=EVAL_V01_MASTER_SEED,
        namespace=EVAL_V01_NAMESPACE,
        count=EVAL_V01_COUNT,
    )


def seed_file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
