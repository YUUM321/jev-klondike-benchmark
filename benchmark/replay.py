from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_records(path: Path, *, agent: str, seed: int) -> list[dict]:
    records = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            if record.get("agent") == agent and record.get("seed") == seed:
                records.append(record)
    return sorted(records, key=lambda record: record["step"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay one logged benchmark game")
    parser.add_argument("log", type=Path, help="path to decisions.jsonl")
    parser.add_argument("--agent", default="jev")
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--from-step", type=int, default=1)
    parser.add_argument("--to-step", type=int)
    args = parser.parse_args()

    records = load_records(args.log, agent=args.agent, seed=args.seed)
    records = [
        record
        for record in records
        if record["step"] >= args.from_step
        and (args.to_step is None or record["step"] <= args.to_step)
    ]
    if not records:
        raise SystemExit("no matching decisions")
    for record in records:
        print(f"\n=== {record['agent']} seed={record['seed']} step={record['step']} ===")
        print(record["visible_state"])
        print("\nLegal actions:")
        for index, action in enumerate(record["legal_actions"]):
            marker = "*" if action == record["selected"] else " "
            print(f"{marker} {index}: {action}")
        print(
            f"selected={record['selected']} confidence={record.get('confidence')} "
            f"final={record.get('final_result')}"
        )


if __name__ == "__main__":
    main()
