from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

from .runner import GameResult


SUMMARY_FIELDS = (
    "agent",
    "games",
    "completed_games",
    "wins",
    "win_rate",
    "mean_foundation_cards",
    "mean_hidden_cards_revealed",
    "mean_steps",
    "mean_repeated_states",
    "agent_errors",
)


def summarize(results: list[GameResult]) -> list[dict[str, str | int | float]]:
    grouped: dict[str, list[GameResult]] = defaultdict(list)
    for result in results:
        grouped[result.agent].append(result)

    rows: list[dict[str, str | int | float]] = []
    for agent in sorted(grouped):
        games = grouped[agent]
        completed = [game for game in games if game.stop_reason != "agent_error"]
        divisor = len(completed) or 1
        rows.append(
            {
                "agent": agent,
                "games": len(games),
                "completed_games": len(completed),
                "wins": sum(game.win for game in completed),
                "win_rate": round(sum(game.win for game in completed) / divisor, 6),
                "mean_foundation_cards": round(
                    sum(game.foundation_cards for game in completed) / divisor, 3
                ),
                "mean_hidden_cards_revealed": round(
                    sum(game.hidden_cards_revealed for game in completed) / divisor, 3
                ),
                "mean_steps": round(sum(game.steps for game in completed) / divisor, 3),
                "mean_repeated_states": round(
                    sum(game.repeated_states for game in completed) / divisor, 3
                ),
                "agent_errors": len(games) - len(completed),
            }
        )
    return rows


def write_runs(path: Path, results: list[GameResult]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        for result in results:
            handle.write(__import__("json").dumps(asdict(result), sort_keys=True) + "\n")


def write_summary(path: Path, rows: list[dict[str, str | int | float]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
