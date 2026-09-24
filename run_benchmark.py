from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from agents import HeuristicAgent, JevAgent, RandomAgent
from benchmark.metrics import summarize, write_runs_csv, write_summary
from benchmark.runner import run_game
from benchmark.replay_format import write_replay
from benchmark.seed_sets import SEED_SET_FILES, read_seed_file, seed_file_sha256


ROOT = Path(__file__).resolve().parent


def is_high_confidence_loss(decision: dict) -> bool:
    return (
        decision.get("final_result") == "loss"
        and decision.get("termination_reason") != "agent_error"
        and (decision.get("confidence") or 0) > 0.9
        and not decision.get("decision_metadata", {}).get("forced", False)
    )


def git_provenance(root: Path) -> dict[str, str | bool | None]:
    """Capture the exact source version without making Git a runtime requirement."""

    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=normal"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        return {"git_commit": commit, "git_dirty": dirty}
    except (FileNotFoundError, subprocess.CalledProcessError):
        return {"git_commit": None, "git_dirty": None}


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
    seed_group = parser.add_mutually_exclusive_group()
    seed_group.add_argument(
        "--seed-set",
        choices=tuple(SEED_SET_FILES),
        help="named frozen set; default is dev to avoid accidental eval-set tuning",
    )
    seed_group.add_argument("--seeds", type=Path, help="custom seed file")
    parser.add_argument("--limit", type=int, help="run only the first N seeds")
    parser.add_argument("--stagnation-steps", type=int, default=50)
    parser.add_argument("--max-steps", type=int, default=2_000)
    parser.add_argument("--draw-count", type=int, choices=(1, 3), default=1)
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

    seed_set = args.seed_set or ("custom" if args.seeds else "dev")
    seed_path = args.seeds or SEED_SET_FILES[seed_set]
    seeds = read_seed_file(seed_path)
    if args.limit is not None:
        seeds = seeds[: args.limit]
    if not seeds:
        raise SystemExit("no seeds selected")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir or ROOT / "results" / run_id
    output_dir.mkdir(parents=True, exist_ok=False)

    if seed_set == "eval-v0.1":
        seed_contract = json.loads(
            seed_path.with_suffix(".json").read_text(encoding="utf-8")
        )
    elif seed_set == "dev":
        seed_contract = {
            "seed_set": "dev",
            "role": "development",
            "held_out": False,
            "note": "These deals influenced tests and heuristic development.",
        }
    else:
        seed_contract = None

    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        **git_provenance(ROOT),
        "agents": list(args.agents),
        "seeds": seeds,
        "seed_set": seed_set,
        "seed_file": str(seed_path.resolve()),
        "seed_file_sha256": seed_file_sha256(seed_path),
        "seed_set_contract": seed_contract,
        "rules": {
            "variant": f"Klondike Draw-{args.draw_count}",
            "draw_count": args.draw_count,
            "stock_recycles": "unlimited",
            "tableau_flip": "automatic when exposed",
            "agent_observation": "visible information only",
            "public_history": {
                "version": "public-history-v1",
                "identity": "visible_state_hash only",
                "visible_state_visit_count": True,
                "actions_tried_from_visible_state": True,
                "recent_actions": 8,
            },
        },
        "termination": {
            "stagnation_steps": args.stagnation_steps,
            "max_steps": args.max_steps,
        },
        "timing": {
            "clock": "time.perf_counter_ns",
            "scope": "wall time inside agent.choose",
            "forced_decisions_excluded": True,
            "jev_includes_network_and_retries": True,
            "percentile_method": "nearest-rank",
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
                    draw_count=args.draw_count,
                )
                results.append(result)
                runs_handle.write(json.dumps(asdict(result), sort_keys=True) + "\n")
                runs_handle.flush()
                for decision in decisions:
                    decisions_handle.write(json.dumps(decision, sort_keys=True) + "\n")
                    if is_high_confidence_loss(decision):
                        high_confidence_losses.append(decision)
                decisions_handle.flush()
                if decisions:
                    write_replay(
                        output_dir / "replays" / f"{agent_name}-seed-{seed}.json",
                        result,
                        decisions,
                    )
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
