from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import asdict, fields
from pathlib import Path

from .runner import GameResult


SUMMARY_FIELDS = (
    "agent",
    "games",
    "completed_games",
    "wins",
    "win_rate",
    "hard_dead_ends",
    "hard_dead_end_rate",
    "cycle_stagnations",
    "cycle_stagnation_rate",
    "turn_caps",
    "turn_cap_rate",
    "mean_foundation_cards",
    "mean_max_foundation_cards_seen",
    "mean_hidden_cards_revealed",
    "mean_steps",
    "mean_repeated_states",
    "mean_unique_states_visited",
    "mean_revisit_rate",
    "total_choice_decisions",
    "total_draw_choices",
    "draw_rate",
    "total_recycle_choices",
    "recycle_rate",
    "mean_elapsed_seconds",
    "total_timed_decisions",
    "total_decision_latency_seconds",
    "mean_decision_latency_ms",
    "mean_game_median_decision_latency_ms",
    "mean_game_p95_decision_latency_ms",
    "mean_forced_decisions",
    "mean_policy_forced_decisions",
    "agent_errors",
)


def summarize(results: list[GameResult]) -> list[dict[str, str | int | float]]:
    grouped: dict[str, list[GameResult]] = defaultdict(list)
    for result in results:
        grouped[result.agent].append(result)

    rows: list[dict[str, str | int | float]] = []
    for agent in sorted(grouped):
        games = grouped[agent]
        completed = [
            game for game in games if game.termination_reason != "agent_error"
        ]
        divisor = len(completed) or 1
        reason_counts = {
            reason: sum(game.termination_reason == reason for game in completed)
            for reason in ("win", "hard_dead_end", "cycle_stagnation", "turn_cap")
        }
        timed_decisions = sum(game.timed_decisions for game in completed)
        choice_decisions = sum(game.choice_decisions for game in completed)
        draw_choices = sum(game.draw_choices for game in completed)
        recycle_choices = sum(game.recycle_choices for game in completed)
        latency_total_ms = sum(
            game.decision_latency_ms_total for game in completed
        )
        game_medians = [
            game.decision_latency_ms_median
            for game in completed
            if game.decision_latency_ms_median is not None
        ]
        game_p95s = [
            game.decision_latency_ms_p95
            for game in completed
            if game.decision_latency_ms_p95 is not None
        ]
        rows.append(
            {
                "agent": agent,
                "games": len(games),
                "completed_games": len(completed),
                "wins": reason_counts["win"],
                "win_rate": round(reason_counts["win"] / divisor, 6),
                "hard_dead_ends": reason_counts["hard_dead_end"],
                "hard_dead_end_rate": round(
                    reason_counts["hard_dead_end"] / divisor, 6
                ),
                "cycle_stagnations": reason_counts["cycle_stagnation"],
                "cycle_stagnation_rate": round(
                    reason_counts["cycle_stagnation"] / divisor, 6
                ),
                "turn_caps": reason_counts["turn_cap"],
                "turn_cap_rate": round(reason_counts["turn_cap"] / divisor, 6),
                "mean_foundation_cards": round(
                    sum(game.foundation_cards for game in completed) / divisor, 3
                ),
                "mean_max_foundation_cards_seen": round(
                    sum(game.max_foundation_cards_seen for game in completed)
                    / divisor,
                    3,
                ),
                "mean_hidden_cards_revealed": round(
                    sum(game.hidden_cards_revealed for game in completed) / divisor, 3
                ),
                "mean_steps": round(sum(game.steps for game in completed) / divisor, 3),
                "mean_repeated_states": round(
                    sum(game.repeated_states for game in completed) / divisor, 3
                ),
                "mean_unique_states_visited": round(
                    sum(game.unique_states_visited for game in completed) / divisor, 3
                ),
                "mean_revisit_rate": round(
                    sum(game.revisit_rate for game in completed) / divisor, 6
                ),
                "total_choice_decisions": choice_decisions,
                "total_draw_choices": draw_choices,
                "draw_rate": (
                    round(draw_choices / choice_decisions, 6)
                    if choice_decisions
                    else 0.0
                ),
                "total_recycle_choices": recycle_choices,
                "recycle_rate": (
                    round(recycle_choices / choice_decisions, 6)
                    if choice_decisions
                    else 0.0
                ),
                "mean_elapsed_seconds": round(
                    sum(game.elapsed_seconds for game in completed) / divisor, 6
                ),
                "total_timed_decisions": timed_decisions,
                "total_decision_latency_seconds": round(latency_total_ms / 1000, 6),
                "mean_decision_latency_ms": (
                    round(latency_total_ms / timed_decisions, 6)
                    if timed_decisions
                    else ""
                ),
                "mean_game_median_decision_latency_ms": (
                    round(sum(game_medians) / len(game_medians), 6)
                    if game_medians
                    else ""
                ),
                "mean_game_p95_decision_latency_ms": (
                    round(sum(game_p95s) / len(game_p95s), 6)
                    if game_p95s
                    else ""
                ),
                "mean_forced_decisions": round(
                    sum(game.forced_decisions for game in completed) / divisor, 3
                ),
                "mean_policy_forced_decisions": round(
                    sum(game.policy_forced_decisions for game in completed) / divisor,
                    3,
                ),
                "agent_errors": len(games) - len(completed),
            }
        )
    return rows


def write_runs(path: Path, results: list[GameResult]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        for result in results:
            handle.write(__import__("json").dumps(asdict(result), sort_keys=True) + "\n")


def write_runs_csv(path: Path, results: list[GameResult]) -> None:
    fieldnames = [field.name for field in fields(GameResult)]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(asdict(result) for result in results)


def write_summary(path: Path, rows: list[dict[str, str | int | float]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
