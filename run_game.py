from __future__ import annotations

import argparse

from agents import HeuristicAgent, RandomAgent
from benchmark.runner import run_game


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one local baseline game")
    parser.add_argument("--agent", choices=("random", "heuristic"), default="heuristic")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-steps", type=int, default=2_000)
    parser.add_argument("--draw-count", type=int, choices=(1, 3), default=1)
    args = parser.parse_args()

    agent = RandomAgent() if args.agent == "random" else HeuristicAgent()
    result, decisions = run_game(
        agent,
        args.seed,
        max_steps=args.max_steps,
        capture_decisions=True,
        draw_count=args.draw_count,
    )
    for record in decisions:
        print(f"\n=== step {record['step']} ===")
        print(record["visible_state"])
        print(f"selected: {record['selected']}")
    print(f"\nresult: {result}")


if __name__ == "__main__":
    main()
