from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from agents import (
    HeuristicAgent,
    JevAgent,
    JevGuardAgent,
    JevHistoryAgent,
    JevMemoryAgent,
    JevProgressAgent,
    JevRawAgent,
    RandomAgent,
)
from benchmark.metrics import summarize, write_runs_csv, write_summary
from benchmark.runner import GameResult, run_game
from benchmark.replay_format import write_replay
from benchmark.seed_sets import SEED_SET_FILES, read_seed_file, seed_file_sha256


ROOT = Path(__file__).resolve().parent
SOURCE_FINGERPRINT_PATHS = ("agents", "benchmark", "solitaire", "run_benchmark.py")
JEV_AGENT_NAMES = (
    "jev_raw",
    "jev_history",
    "jev_progress",
    "jev_guard",
    # Backward-compatible names for result directories created before the
    # explicit condition names were introduced.
    "jev",
    "jev_memory",
)


def portable_path(path: Path, root: Path = ROOT) -> str:
    """Return a publishable path without exposing the host's directory layout."""

    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        return f"<external>/{resolved.name}"


def sanitized_argv(argv: list[str], root: Path = ROOT) -> list[str]:
    """Keep a reproducible command record while redacting machine-local paths."""

    placeholders = {
        "--output-dir": "<output-dir>",
        "--resume": "<result-dir>",
    }
    sanitized: list[str] = []
    previous = ""
    for value in argv:
        option, separator, inline_value = value.partition("=")
        if separator and option in placeholders:
            sanitized.append(f"{option}={placeholders[option]}")
        elif separator and option == "--seeds":
            sanitized.append(
                f"{option}={portable_path(Path(inline_value), root)}"
            )
        elif previous in placeholders:
            sanitized.append(placeholders[previous])
        elif previous == "--seeds":
            sanitized.append(portable_path(Path(value), root))
        elif Path(value).is_absolute():
            sanitized.append(portable_path(Path(value), root))
        else:
            sanitized.append(value)
        previous = value if not separator else option
    return sanitized


def is_high_confidence_loss(decision: dict) -> bool:
    return (
        decision.get("final_result") == "loss"
        and decision.get("termination_reason") != "agent_error"
        and (decision.get("confidence") or 0) > 0.9
        and not decision.get("decision_metadata", {}).get("forced", False)
        and not decision.get("decision_metadata", {}).get("policy_forced", False)
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
    agent_classes = {
        "jev": JevAgent,
        "jev_raw": JevRawAgent,
        "jev_history": JevHistoryAgent,
        "jev_progress": JevProgressAgent,
        "jev_guard": JevGuardAgent,
        "jev_memory": JevMemoryAgent,
    }
    if name in agent_classes:
        agent_class = agent_classes[name]
        return agent_class(
            api_key_env=args.jev_api_key_env,
            base_url=args.jev_base_url,
            model=args.jev_model,
            timeout=args.jev_timeout,
            retries=args.jev_retries,
            option_order=args.jev_option_order,
            option_order_seed=args.jev_option_order_seed,
        )
    raise ValueError(f"unknown agent: {name}")


def source_fingerprint(root: Path) -> str:
    """Hash benchmark source so a resumed run cannot silently change semantics."""

    digest = hashlib.sha256()
    files: list[Path] = []
    for relative in SOURCE_FINGERPRINT_PATHS:
        path = root / relative
        if path.is_dir():
            files.extend(path.rglob("*.py"))
        elif path.is_file():
            files.append(path)
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def read_jsonl(path: Path, *, tolerate_truncated_final: bool = False) -> list[dict]:
    if not path.exists():
        return []
    records: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                if tolerate_truncated_final and not handle.read().strip():
                    break
                raise ValueError(f"invalid JSON in {path} at line {line_number}") from exc
    return records


def write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    os.replace(temporary, path)


def write_jsonl_atomic(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def decision_key(record: dict) -> tuple[str, int]:
    return str(record["agent"]), int(record["seed"])


def checkpoint_path(output_dir: Path, agent: str, seed: int) -> Path:
    return output_dir / "checkpoints" / f"{agent}-seed-{seed}.jsonl"


def compatible_decision_prefix(shorter: list[dict], longer: list[dict]) -> bool:
    if len(shorter) > len(longer):
        return False
    fields = ("step", "selected", "state_hash_after")
    return all(
        all(left.get(field) == right.get(field) for field in fields)
        for left, right in zip(shorter, longer)
    )


def choose_resume_decisions(main_records: list[dict], checkpoint: list[dict]) -> list[dict]:
    if not checkpoint:
        return main_records
    if not compatible_decision_prefix(main_records, checkpoint):
        raise ValueError("checkpoint does not extend decisions.jsonl for this game")
    return checkpoint


def ordered_results(
    result_map: dict[tuple[str, int], GameResult], agents: list[str], seeds: list[int]
) -> list[GameResult]:
    return [
        result_map[(agent, seed)]
        for agent in agents
        for seed in seeds
        if (agent, seed) in result_map
    ]


def persist_outputs(
    output_dir: Path,
    result_map: dict[tuple[str, int], GameResult],
    decision_map: dict[tuple[str, int], list[dict]],
    agents: list[str],
    seeds: list[int],
) -> None:
    results = ordered_results(result_map, agents, seeds)
    decisions = [
        record
        for agent in agents
        for seed in seeds
        for record in decision_map.get((agent, seed), [])
    ]
    write_jsonl_atomic(output_dir / "runs.jsonl", [asdict(result) for result in results])
    write_jsonl_atomic(output_dir / "decisions.jsonl", decisions)
    write_jsonl_atomic(
        output_dir / "high_confidence_losses.jsonl",
        [record for record in decisions if is_high_confidence_loss(record)],
    )

    # CSV files are derived views; write temporary files before replacing them.
    runs_csv = output_dir / "runs.csv"
    summary_csv = output_dir / "summary.csv"
    runs_temporary = runs_csv.with_name(f"{runs_csv.name}.tmp")
    summary_temporary = summary_csv.with_name(f"{summary_csv.name}.tmp")
    rows = summarize(results)
    write_runs_csv(runs_temporary, results)
    write_summary(summary_temporary, rows)
    os.replace(runs_temporary, runs_csv)
    os.replace(summary_temporary, summary_csv)

    for key, records in decision_map.items():
        result = result_map.get(key)
        if result is not None and records:
            write_replay(
                output_dir / "replays" / f"{key[0]}-seed-{key[1]}.json",
                result,
                records,
            )


def load_existing_results(
    output_dir: Path,
) -> tuple[dict[tuple[str, int], GameResult], dict[tuple[str, int], list[dict]]]:
    result_map: dict[tuple[str, int], GameResult] = {}
    for record in read_jsonl(output_dir / "runs.jsonl"):
        result = GameResult(**record)
        result_map[(result.agent, result.seed)] = result

    decision_map: dict[tuple[str, int], list[dict]] = {}
    for record in read_jsonl(output_dir / "decisions.jsonl"):
        decision_map.setdefault(decision_key(record), []).append(record)
    for records in decision_map.values():
        records.sort(key=lambda item: item["step"])
    return result_map, decision_map


def apply_manifest_configuration(
    args: argparse.Namespace, manifest: dict
) -> tuple[list[int], str]:
    history_version = (
        manifest.get("rules", {}).get("public_history", {}).get("version")
    )
    if history_version != "public-history-v2":
        raise SystemExit(
            "this run cannot be resumed: it was not created with public-history-v2"
        )
    args.agents = tuple(manifest["agents"])
    args.draw_count = int(manifest["rules"]["draw_count"])
    args.stagnation_steps = int(manifest["termination"]["stagnation_steps"])
    args.max_steps = int(manifest["termination"]["max_steps"])
    args.log_decisions = manifest.get("logging", {}).get("decisions", "jev")
    jev = manifest["jev"]
    args.jev_api_key_env = jev["api_key_env"]
    args.jev_base_url = jev["base_url"]
    args.jev_model = jev["model_requested"]
    args.jev_timeout = float(jev["timeout_seconds_per_attempt"])
    args.jev_retries = int(jev["max_retries"])
    args.jev_option_order = jev["option_order"]
    args.jev_option_order_seed = int(jev["option_order_seed"])
    return [int(seed) for seed in manifest["seeds"]], str(manifest["seed_set"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Jev x Klondike benchmark")
    parser.add_argument(
        "--agents",
        nargs="+",
        choices=("random", "heuristic", *JEV_AGENT_NAMES),
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
    parser.add_argument("--max-steps", type=int, default=700)
    parser.add_argument("--draw-count", type=int, choices=(1, 3), default=1)
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument("--output-dir", type=Path)
    output_group.add_argument(
        "--resume",
        type=Path,
        metavar="RESULT_DIR",
        help="resume an interrupted run using its manifest and checkpoints",
    )
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
    resuming = args.resume is not None
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if resuming:
        output_dir = args.resume.resolve()
        manifest_path = output_dir / "manifest.json"
        if not manifest_path.is_file():
            raise SystemExit(f"resume manifest not found: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        seeds, seed_set = apply_manifest_configuration(args, manifest)
        expected_fingerprint = manifest.get("source_fingerprint_sha256")
        current_fingerprint = source_fingerprint(ROOT)
        if expected_fingerprint and expected_fingerprint != current_fingerprint:
            raise SystemExit(
                "benchmark source changed since this run started; refusing unsafe resume"
            )
    else:
        seed_set = args.seed_set or ("custom" if args.seeds else "dev")
        seed_path = args.seeds or SEED_SET_FILES[seed_set]
        seeds = read_seed_file(seed_path)
        if args.limit is not None:
            seeds = seeds[: args.limit]
        if not seeds:
            raise SystemExit("no seeds selected")
        output_dir = (args.output_dir or ROOT / "results" / run_id).resolve()
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
            "seed_file": portable_path(seed_path),
            "seed_file_sha256": seed_file_sha256(seed_path),
            "seed_set_contract": seed_contract,
            "source_fingerprint_sha256": source_fingerprint(ROOT),
            "rules": {
                "variant": f"Klondike Draw-{args.draw_count}",
                "draw_count": args.draw_count,
                "stock_recycles": "unlimited",
                "tableau_flip": "automatic when exposed",
                "agent_observation": "visible information only",
                "public_history": {
                    "version": "public-history-v2",
                    "identity": "visible_state_hash only",
                    "visible_state_visit_count": True,
                    "actions_tried_from_visible_state": True,
                    "action_attempt_counts": True,
                    "action_outcome_counts": "visible-state identifiers only",
                    "steps_since_new_visible_state": True,
                    "recent_actions": 8,
                    "recent_transitions": 8,
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
                "policy_forced_decisions_excluded": True,
                "jev_includes_network_and_retries": True,
                "percentile_method": "nearest-rank",
            },
            "jev": {
                "base_url": args.jev_base_url,
                "model_requested": args.jev_model,
                "api_key_env": args.jev_api_key_env,
                "option_order": args.jev_option_order,
                "option_order_seed": args.jev_option_order_seed,
                "timeout_seconds_per_attempt": args.jev_timeout,
                "max_retries": args.jev_retries,
                "tls_version": JevAgent.TLS_VERSION,
                "agent_memory_policies": {
                    "jev_raw": "none",
                    "jev_history": "observe-public-history-v2",
                    "jev_progress": "observe-public-history-v2+observable-progress-v1",
                    "jev_guard": JevGuardAgent.MEMORY_POLICY,
                    "jev": "observe-public-history-v2",
                    "jev_memory": JevMemoryAgent.MEMORY_POLICY,
                },
                "experimental_conditions": {
                    "jev_raw": {
                        "history": False,
                        "progress": False,
                        "action_filter": False,
                    },
                    "jev_history": {
                        "history": "public-history-v2",
                        "progress": False,
                        "action_filter": False,
                    },
                    "jev_progress": {
                        "history": "public-history-v2",
                        "progress": "observable-progress-v1",
                        "action_filter": False,
                    },
                    "jev_guard": {
                        "history": "public-history-v2",
                        "progress": False,
                        "action_filter": JevGuardAgent.MEMORY_POLICY,
                    },
                },
                "compatibility_aliases": {
                    "jev": "jev_history",
                    "jev_memory": "jev_guard",
                },
                "fallback": "none",
            },
            "progress_signal": {
                "version": "observable-progress-v1",
                "weighted_score": False,
                "action_rewards": False,
                "identity": "visible-state identifiers only",
                "fields": [
                    "foundation_cards",
                    "max_foundation_cards_seen",
                    "tableau_hidden_remaining",
                    "hidden_cards_revealed_total",
                    "visible_state_visit_count",
                    "steps_since_new_visible_state",
                    "steps_since_hidden_reveal",
                    "steps_since_foundation_increase",
                    "steps_since_structural_progress",
                    "stock_passes_since_structural_progress",
                ],
                "structural_progress": (
                    "new tableau reveal or new maximum foundation count"
                ),
            },
            "choice_rate_metrics": {
                "denominator": "non-forced and non-policy-forced decisions",
                "fields": ["draw_rate", "recycle_rate"],
            },
            "logging": {"decisions": args.log_decisions},
            "checkpointing": {
                "mode": "per-successful-decision",
                "directory": "checkpoints",
                "flush": True,
                "fsync": True,
            },
            "argv": sanitized_argv(sys.argv),
        }
        write_json_atomic(output_dir / "manifest.json", manifest)

    if not seeds:
        raise SystemExit("manifest contains no seeds")
    result_map, decision_map = load_existing_results(output_dir)
    pending_jev = any(
        agent.startswith("jev")
        and (
            (agent, seed) not in result_map
            or result_map[(agent, seed)].termination_reason == "agent_error"
        )
        for agent in args.agents
        for seed in seeds
    )
    if pending_jev and not os.getenv(args.jev_api_key_env):
        raise SystemExit(
            f"{args.jev_api_key_env} is not set. Refusing to label a fallback as Jev."
        )
    if resuming:
        current_fingerprint = source_fingerprint(ROOT)
        manifest.setdefault("source_fingerprint_sha256", current_fingerprint)
        manifest.setdefault("resume_history", []).append(
            {
                "resumed_at_utc": datetime.now(timezone.utc).isoformat(),
                "argv": sanitized_argv(sys.argv),
                **git_provenance(ROOT),
                "source_fingerprint_sha256": current_fingerprint,
            }
        )
        write_json_atomic(output_dir / "manifest.json", manifest)

    interrupted = False
    for agent_name in args.agents:
        agent = build_agent(agent_name, args)
        for index, seed in enumerate(seeds, start=1):
            key = (agent_name, seed)
            previous_result = result_map.get(key)
            if previous_result and previous_result.termination_reason != "agent_error":
                checkpoint_path(output_dir, agent_name, seed).unlink(missing_ok=True)
                print(
                    f"[{agent_name} {index}/{len(seeds)}] seed={seed} "
                    "already complete; skipped"
                )
                continue

            publish_decisions = args.log_decisions == "all" or (
                args.log_decisions == "jev" and agent_name.startswith("jev")
            )
            # Jev always receives an internal checkpoint even when public decision
            # logging is disabled. Baselines are deterministic and cheap to restart.
            checkpoint_enabled = agent_name.startswith("jev") or publish_decisions
            checkpoint = checkpoint_path(output_dir, agent_name, seed)
            checkpoint_records = (
                read_jsonl(checkpoint, tolerate_truncated_final=True)
                if checkpoint.exists()
                else []
            )
            resume_records = choose_resume_decisions(
                decision_map.get(key, []), checkpoint_records
            )
            if not checkpoint_enabled:
                resume_records = []
            elapsed_offset = previous_result.elapsed_seconds if previous_result else 0.0
            if resume_records:
                elapsed_offset = max(
                    elapsed_offset,
                    float(resume_records[-1].get("elapsed_seconds_at_commit", 0.0)),
                )

            checkpoint_handle = None
            try:
                if checkpoint_enabled:
                    write_jsonl_atomic(checkpoint, resume_records)
                    checkpoint_handle = checkpoint.open("a", encoding="utf-8")

                def commit_decision(record: dict) -> None:
                    if checkpoint_handle is None:
                        return
                    checkpoint_handle.write(json.dumps(record, sort_keys=True) + "\n")
                    checkpoint_handle.flush()
                    os.fsync(checkpoint_handle.fileno())

                result, decisions = run_game(
                    agent,
                    seed,
                    stagnation_steps=args.stagnation_steps,
                    max_steps=args.max_steps,
                    capture_decisions=checkpoint_enabled,
                    draw_count=args.draw_count,
                    resume_decisions=resume_records,
                    elapsed_seconds_offset=elapsed_offset,
                    on_decision=commit_decision,
                )
            finally:
                if checkpoint_handle is not None:
                    checkpoint_handle.close()

            result_map[key] = result
            if publish_decisions:
                decision_map[key] = decisions
            else:
                decision_map.pop(key, None)
            persist_outputs(output_dir, result_map, decision_map, list(args.agents), seeds)

            print(
                f"[{agent_name} {index}/{len(seeds)}] seed={seed} "
                f"win={result.win} foundation={result.foundation_cards} "
                f"hidden={result.hidden_cards_revealed} "
                f"stop={result.termination_reason}"
            )
            if result.termination_reason == "agent_error":
                interrupted = True
                print(
                    f"Checkpoint kept at {checkpoint}. Fix connectivity, then run:\n"
                    f"  python run_benchmark.py --resume \"{output_dir}\""
                )
                break
            checkpoint.unlink(missing_ok=True)
        if interrupted:
            break

    results = ordered_results(result_map, list(args.agents), seeds)
    persist_outputs(output_dir, result_map, decision_map, list(args.agents), seeds)
    rows = summarize(results)
    print(f"\nResults: {output_dir}")
    for row in rows:
        print(row)
    if interrupted:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
