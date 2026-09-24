from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .replay_format import write_replay
from .runner import GameResult


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line.strip():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSONL at {path}:{line_number}") from exc
    return records


def export_replays(result_dir: Path, output_dir: Path | None = None) -> list[Path]:
    runs_path = result_dir / "runs.jsonl"
    decisions_path = result_dir / "decisions.jsonl"
    manifest_path = result_dir / "manifest.json"
    for required in (runs_path, decisions_path):
        if not required.exists():
            raise FileNotFoundError(f"missing benchmark artifact: {required}")

    manifest: dict[str, Any] = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    variant = str(manifest.get("rules", {}).get("variant", "Klondike Draw-1"))
    manifest_draw_count = int(manifest.get("rules", {}).get("draw_count", 3 if "Draw-3" in variant else 1))

    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for decision in read_jsonl(decisions_path):
        grouped[(str(decision["agent"]), int(decision["seed"]))].append(decision)

    destination = output_dir or result_dir / "replays"
    written: list[Path] = []
    for raw_result in read_jsonl(runs_path):
        key = (str(raw_result["agent"]), int(raw_result["seed"]))
        decisions = sorted(grouped.get(key, []), key=lambda record: record["step"])
        if not decisions:
            continue
        result_data = dict(raw_result)
        result_data.setdefault("draw_count", manifest_draw_count)
        result = GameResult(**result_data)
        path = destination / f"{result.agent}-seed-{result.seed}.json"
        write_replay(path, result, decisions, draw_count=result.draw_count)
        written.append(path)
    if not written:
        raise ValueError("no captured decisions matched runs.jsonl")
    return written


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export browser replay JSON from an existing benchmark result directory"
    )
    parser.add_argument("result_dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    for path in export_replays(args.result_dir, args.output_dir):
        print(path)


if __name__ == "__main__":
    main()
