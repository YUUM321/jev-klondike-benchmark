from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from agents import HeuristicAgent, JevAgent, RandomAgent
from benchmark.replay_format import build_replay
from benchmark.runner import run_game


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run one game and save a browser-compatible replay.json"
    )
    parser.add_argument("--agent", choices=("random", "heuristic", "jev"), default="jev")
    parser.add_argument("--seed", type=int, default=37)
    parser.add_argument("--output", type=Path, default=Path("web/replay.json"))
    parser.add_argument("--stagnation-steps", type=int, default=50)
    parser.add_argument("--max-steps", type=int, default=2_000)
    parser.add_argument("--jev-api-key-env", default="TYPESAFE_API_KEY")
    parser.add_argument("--jev-base-url", default="https://api.typesafe.ai")
    parser.add_argument("--jev-model", default="jev-latest")
    parser.add_argument(
        "--jev-option-order", choices=("seeded", "canonical"), default="seeded"
    )
    parser.add_argument("--jev-option-order-seed", type=int, default=0)
    args = parser.parse_args()

    if args.agent == "random":
        agent = RandomAgent()
    elif args.agent == "heuristic":
        agent = HeuristicAgent()
    else:
        if not os.getenv(args.jev_api_key_env):
            raise SystemExit(
                f"{args.jev_api_key_env} is not set; refusing to create a fake Jev replay"
            )
        agent = JevAgent(
            api_key_env=args.jev_api_key_env,
            base_url=args.jev_base_url,
            model=args.jev_model,
            option_order=args.jev_option_order,
            option_order_seed=args.jev_option_order_seed,
        )

    result, decisions = run_game(
        agent,
        args.seed,
        stagnation_steps=args.stagnation_steps,
        max_steps=args.max_steps,
        capture_decisions=True,
    )
    replay = build_replay(result, decisions)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(replay, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(
        f"saved {len(replay['frames'])} frames to {args.output} "
        f"(result={result.termination_reason}, win={result.win})"
    )
    if result.error:
        raise SystemExit(result.error)


if __name__ == "__main__":
    main()
