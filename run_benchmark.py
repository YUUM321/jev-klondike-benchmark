from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from agents import HeuristicAgent, JevAgent, RandomAgent
from benchmark.metrics import summarize, write_runs_csv, write_summary
from benchmark.runner import run_game


ROOT = Path(__file__).resolve().parent


def is_high_confidence_loss(decision: dict) -> bool:
    return (
        decision.get("final_result") == "loss"
        and (decision.get("confidence") or 0) > 0.9
        and not decision.get("decision_metadata", {}).get("forced", False)
    )


def read_seeds(path: Path) -> list[int]:
    seeds = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.partition("#")[0].strip()
        if line:
            seeds.append(int(line))
    if len(seeds) != len(set(seeds)):
        raise ValueError("seed file contains duplicates")
    return seeds


def build_agent(name: str, args: argparse.Namespace):
    if name == "random":
        return RandomAgent()
    if name == "heuristic":
        return HeuristicAgent()
    if name == "jev":
        return JevAgent(
            api_key_env=args.jev_api_key_env,
            base_url=args.jev_base_url,
            model=args.jev_model,
            timeout=args.jev_timeout,
            retries=args.jev_retries,
            option_order=args.jev_option_order,
            option_order_seed=args.jev_option_order_seed,
        )
    raise ValueError(f"unknown agent: {name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Jev x Klondike benchmark")
    parser.add_argument(
        "--agents",
        nargs="+",
        choices=("random", "heuristic", "jev"),
        default=("random", "heuristic"),
        help="Jev is opt-in because it makes paid network calls",
    )
    parser.add_argument("--seeds", type=Path, default=ROOT / "benchmark" / "seeds.txt")
    parser.add_argument("--limit", type=int, help="run only the first N seeds")
    parser.add_argument("--stagnation-steps", type=int, default=50)
    parser.add_argument("--max-steps", type=int, default=2_000)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--log-decisions", choices=("jev", "all", "none"), default="jev"
    )
    parser.add_argument("--jev-api-key-env", default="TYPESAFE_API_KEY")
    parser.add_argument("--jev-base-url", default="https://api.typesafe.ai")
    parser.add_argument("--jev-model", default="jev-latest")
    parser.add_argument("--jev-timeout", type=float, default=30.0)
    parser.add_argument("--jev-retries", type=int, default=2)
    parser.add_argument(
        "--jev-option-order", choices=("seeded", "canonical"), default="seeded"
    )
    parser.add_argument("--jev-option-order-seed", type=int, default=0)
    args = parser.parse_args()

    if "jev" in args.agents and not os.getenv(args.jev_api_key_env):
        raise SystemExit(
            f"{args.jev_api_key_env} is not set. Refusing to label a fallback as Jev."
        )

    seeds = read_seeds(args.seeds)
    if args.limit is not None:
        seeds = seeds[: args.limit]
    if not seeds:
        raise SystemExit("no seeds selected")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir or ROOT / "results" / run_id
    output_dir.mkdir(parents=True, exist_ok=False)

    seed_bytes = args.seeds.read_bytes()
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "agents": list(args.agents),
        "seeds": seeds,
        "seed_file": str(args.seeds.resolve()),
        "seed_file_sha256": hashlib.sha256(seed_bytes).hexdigest(),
        "rules": {
            "variant": "Klondike Draw-1",
            "stock_recycles": "unlimited",
            "tableau_flip": "automatic when exposed",
            "agent_observation": "visible information only",
        },
        "termination": {
            "stagnation_steps": args.stagnation_steps,
            "max_steps": args.max_steps,
        },
        "jev": {
            "base_url": args.jev_base_url,
            "model_requested": args.jev_model,
            "api_key_env": args.jev_api_key_env,
            "option_order": args.jev_option_order,
            "option_order_seed": args.jev_option_order_seed,
            "fallback": "none",
        },
        "argv": sys.argv,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    results = []
    high_confidence_losses = []
    with (output_dir / "runs.jsonl").open("w", encoding="utf-8") as runs_handle, (
        output_dir / "decisions.jsonl"
    ).open("w", encoding="utf-8") as decisions_handle:
        for agent_name in args.agents:
            agent = build_agent(agent_name, args)
            for index, seed in enumerate(seeds, start=1):
                capture = args.log_decisions == "all" or (
                    args.log_decisions == "jev" and agent_name == "jev"
                )
                result, decisions = run_game(
                    agent,
                    seed,
                    stagnation_steps=args.stagnation_steps,
                    max_steps=args.max_steps,
                    capture_decisions=capture,
                )
                results.append(result)
                runs_handle.write(json.dumps(asdict(result), sort_keys=True) + "\n")
                runs_handle.flush()
                for decision in decisions:
                    decisions_handle.write(json.dumps(decision, sort_keys=True) + "\n")
                    if is_high_confidence_loss(decision):
                        high_confidence_losses.append(decision)
                decisions_handle.flush()
                print(
                    f"[{agent_name} {index}/{len(seeds)}] seed={seed} "
                    f"win={result.win} foundation={result.foundation_cards} "
                    f"hidden={result.hidden_cards_revealed} "
                    f"stop={result.termination_reason}"
                )

    rows = summarize(results)
    write_runs_csv(output_dir / "runs.csv", results)
    write_summary(output_dir / "summary.csv", rows)
    with (output_dir / "high_confidence_losses.jsonl").open(
        "w", encoding="utf-8"
    ) as handle:
        for record in high_confidence_losses:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    print(f"\nResults: {output_dir}")
    for row in rows:
        print(row)


if __name__ == "__main__":
    main()
