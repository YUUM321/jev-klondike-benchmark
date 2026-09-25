# Jev × Klondike Benchmark

**English** | [简体中文](README.zh-CN.md)

[![Tests](https://github.com/YUUM321/jev-klondike-benchmark/actions/workflows/tests.yml/badge.svg)](https://github.com/YUUM321/jev-klondike-benchmark/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> Reproducible infrastructure for studying fast model decisions, limited public
> memory, and long-horizon failure modes in Klondike Solitaire.

This repository provides a deterministic Klondike engine, local baselines, four
Jev ablation conditions, frozen deal sets, detailed metrics, resumable runs, and
a browser-based replay viewer. It is designed to answer a narrower and more
useful question than “can a model play Solitaire?”:

> How much external structure does a fast System-One decision model need before
> its local choices become useful in a partially observable, long-horizon task?

## Project status and scope

| Component | Status |
| --- | --- |
| Klondike Draw-1 and Draw-3 engine | Complete |
| Random and heuristic baselines | Complete |
| Raw / History / Progress / Guard Jev conditions | Complete |
| Hidden-information boundary and rule tests | Complete |
| Frozen 100-deal evaluation set | Complete |
| Checkpoint, resume, provenance, and metrics | Complete |
| Browser replay and CSV viewer | Complete |
| Large-scale remote Jev results | Not included in v0.1; optional future work |

The v0.1 deliverable is the benchmark protocol and reproducible evaluation
infrastructure, not an official remote score. Large-scale Jev results are
intentionally not published because reliable evaluation requires a stable
external API environment. The repository never substitutes partial runs or
fallback policies for missing Jev results.

Included in v0.1:

- deterministic game rules and legal-action generation;
- strict visible-information observations;
- local baselines and four isolated Jev conditions;
- frozen development and held-out evaluation deals;
- per-decision logging, progress metrics, latency metrics, and provenance;
- crash-safe checkpoints, exact resume, replay export, and CI tests.

Not included in v0.1:

- an official Jev win-rate claim;
- a published large-scale remote API run;
- a complete-information solver for proving whether a deal is solvable.

## Why Klondike?

Most individual Klondike moves are easy to validate. Their long-term
consequences are not. A move that looks harmless can block a critical card many
turns later, while unlimited stock recycling allows a policy to cycle through
legal states without making progress. Draw-3 adds another dependency: removing
one waste card changes how later stock passes are grouped.

This makes Klondike useful for studying:

- whether local intuition produces durable progress;
- whether an agent creates opportunities to reveal hidden tableau cards;
- whether it repeatedly reverses earlier decisions;
- how a lightweight hand-written policy compares with a fast model;
- how confidence and latency relate to eventual outcomes.

## Benchmark protocol

### Game rules

- Klondike Draw-1 or Draw-3; Draw-1 is the default and each draw count is a
  separate experimental condition.
- Unlimited stock recycling with no reshuffle.
- Tableau builds downward by rank with alternating colors.
- Empty tableau columns accept only a King or a King-led sequence.
- Foundations build by suit from Ace to King.
- A foundation top card may move back to the tableau.
- A newly exposed tableau card flips automatically in the same transition.
- Only the top waste card is playable.
- The game is won when all 52 cards reach the foundations.

### Information boundary

The engine owns the complete deal, but an agent receives only a player-visible
`Observation`:

- hidden cards are represented as `XX`;
- stock order is never exposed;
- the deal seed and full internal state hash are never exposed;
- the engine generates every legal action, and the agent must choose one of
  those actions.

The runner also derives public history exclusively from visible information:

- visits to the current visible state;
- per-action attempt counts from that state;
- visible outcome counts for each attempted action;
- steps since a new visible state was reached;
- the last eight public actions and visible transitions.

Public history uses `visible_state_hash`. It never uses the internal
`state_hash`, which includes hidden cards and the full stock and waste order.
Random ignores public history, Heuristic uses it to reduce obvious repetition,
and each Jev condition receives only the context defined below.

### Agents and ablations

| Agent | Context and policy |
| --- | --- |
| `RandomAgent` | Uniform random choice over legal actions; reproducible policy RNG |
| `HeuristicAgent` | Small deterministic baseline favoring hidden-card reveals, safe foundation moves, and less repetition |
| `JevRawAgent` / `jev_raw` | Current visible state, explicit rules, and legal actions only |
| `JevHistoryAgent` / `jev_history` | Raw plus `public-history-v2`; no legal action is filtered |
| `JevProgressAgent` / `jev_progress` | History plus unweighted observable progress facts; no action rewards or hand-written score |
| `JevGuardAgent` / `jev_guard` | History plus `untried-actions-first-v1`, which temporarily filters previously tried actions when alternatives remain |

All four Jev conditions share the same core instruction:

```text
Goal: maximize the probability of eventually winning this Klondike game.
Choose exactly one of the supplied legal actions.
Consider future flexibility, hidden-card revelation, and dead-end risk.
```

History asks the model to use public history. Progress adds observable facts
such as the foundation peak, remaining hidden tableau cards, steps since the
last reveal or foundation increase, and stock passes without structural
progress. These are facts, not a reward function. Guard is reported as an
explicit intervention rather than being labeled “pure Jev.”

`jev` and `jev_memory` remain compatibility aliases for `jev_history` and
`jev_guard`. New experiments should use the full condition names.

### Stable option ordering

Seeded option ordering uses `stable-visible-action-v2`. Each action receives a
stable priority derived from:

```text
option-order protocol version
+ explicit option-order seed
+ visible state hash
+ action identity
```

It does not depend on the game seed, hidden cards, full state, step number, or
the engine's input enumeration order. Revisiting the same visible state keeps
the same option order, and Guard subsets preserve the relative order of the
remaining actions. The protocol version and seed are stored in `manifest.json`.

## Metrics and termination

| Category | Fields |
| --- | --- |
| Outcome | `win`, `termination_reason` |
| Progress | `foundation_cards`, `max_foundation_cards_seen`, `hidden_cards_revealed` |
| Behavior | `steps`, `repeated_states`, `unique_states_visited`, `revisit_rate`, `draw_rate`, `recycle_rate` |
| Timing | elapsed time and non-forced decision latency total / mean / median / P95 |
| Jev diagnostics | confidence, full probability distribution, model, usage, retries, request hash |

A rule-mandated single action is marked `forced`. If Guard leaves exactly one
candidate from a larger legal set, it is marked `policy_forced`. Neither is
included in model latency or confidence analysis.

Termination reasons remain distinct:

| Reason | Definition |
| --- | --- |
| `win` | All 52 cards are in the foundations |
| `hard_dead_end` | The engine has no legal action |
| `cycle_stagnation` | 50 consecutive transitions reach no previously unseen full state |
| `turn_cap` | The run reaches the default 700-decision safety cap |
| `agent_error` | The agent, remote API, or response validation fails |

`cycle_stagnation` means the current policy is cycling; it does not prove that
the deal is unsolvable. `agent_error` is an incomplete run, is excluded from the
win-rate denominator, and never enters `high_confidence_losses.jsonl`.

## Quick start

Python 3.10 or newer is required. The engine, local baselines, and test suite use
only the Python standard library.

```powershell
git clone https://github.com/YUUM321/jev-klondike-benchmark.git
cd jev-klondike-benchmark
python -m unittest discover -s tests -v
python run_benchmark.py --agents random heuristic
```

The default command uses development seeds and cannot accidentally consume the
held-out evaluation set.

Run one local game:

```powershell
python run_game.py --agent heuristic --seed 37
python run_game.py --agent heuristic --seed 37 --draw-count 3
```

### Run Jev

Provide the TypeSafe API key at runtime. It is never written to manifests,
replays, or result files.

PowerShell:

```powershell
$env:TYPESAFE_API_KEY = "your-key"
```

POSIX shells:

```bash
export TYPESAFE_API_KEY="your-key"
```

Run a one-deal development smoke test before any larger experiment:

```powershell
python run_benchmark.py --agents jev_raw --limit 1
python run_benchmark.py --agents jev_history jev_progress jev_guard --limit 1
```

The four conditions are separate treatments and must not be merged into a
single “Jev” row. Remote calls may incur API charges, and failures never fall
back to a local policy.

To inspect option-position sensitivity on development deals:

```powershell
foreach ($orderSeed in 0, 1, 2) {
  python run_benchmark.py --agents jev_raw --limit 10 `
    --jev-option-order-seed $orderSeed `
    --output-dir "results/order-smoke-$orderSeed"
}
```

### Optional held-out evaluation

The frozen set is available for independent remote runs:

```powershell
python run_benchmark.py --seed-set eval-v0.1 --draw-count 1 `
  --agents random heuristic jev_raw jev_history jev_progress jev_guard
```

Draw-3 is a separate experiment and must not be mixed into the same summary:

```powershell
python run_benchmark.py --seed-set eval-v0.1 --draw-count 3 `
  --agents random heuristic jev_raw jev_history jev_progress jev_guard
```

### Resume an interrupted run

Each successful Jev decision is flushed and synced to a per-game checkpoint.
After resolving the interruption, resume the original result directory:

```powershell
python run_benchmark.py --resume results/<run-directory>
```

Resume reconstructs the game from committed actions, verifies visible and full
state hashes, restores public history and progress counters, and refuses to run
if benchmark source semantics have changed.

## Frozen deals and provenance

Two seed sets are versioned:

- [`benchmark/seeds/dev.txt`](benchmark/seeds/dev.txt): seeds 0–99 for
  development, testing, and tuning;
- [`benchmark/seeds/eval-v0.1.txt`](benchmark/seeds/eval-v0.1.txt): 100 held-out
  seeds selected independently of agent results.

The evaluation set is generated from a public master seed with a
version-independent SHA-256 counter algorithm. Its contract and artifact hashes
are stored in
[`benchmark/seeds/eval-v0.1.json`](benchmark/seeds/eval-v0.1.json).

Verify the frozen artifacts:

```powershell
python -m benchmark.generate_seed_set --check
```

Every run writes a `manifest.json` containing:

- the exact seed list and seed-file SHA-256;
- Python and operating-system versions plus a path-sanitized command line;
- Git commit and dirty-worktree state;
- game rules and termination settings;
- Jev model, option-order protocol, and request configuration;
- timing scope and percentile method;
- a source fingerprint used to protect resume semantics.

## Output files

Each run creates `results/<UTC timestamp>/`:

```text
manifest.json                 Configuration and provenance
runs.jsonl                    One raw record per game
runs.csv                      Per-game metrics
summary.csv                   Metrics aggregated by agent
decisions.jsonl               Per-decision observations, candidates, and choices
high_confidence_losses.jsonl  Candidate steps for manual failure review
replays/<agent>-seed-<n>.json Browser-ready game replays
```

CSV is intended for analysis and tables. JSONL preserves stream-friendly raw
records. Only `replays/*.json` contains the frame-oriented format consumed by
the board viewer.

A high-confidence decision in a losing game is only a review candidate. It does
not, by itself, prove that the selected action caused the loss.

## Replay and CSV viewer

The repository includes a zero-build HTML/CSS/JavaScript viewer:

```powershell
python -m http.server 8000 -d web
```

Open [http://localhost:8000](http://localhost:8000) to load the reviewed example
or drag in a local replay. The viewer supports:

- play, pause, single-step navigation, timeline seeking, and 0.5×–4× speed;
- Stock, Waste, Foundation, and seven Tableau columns;
- Draw-3 waste packets with only the top card marked playable;
- pre-action and post-action boards, legal actions, history, and progress;
- selected-action probabilities, confidence, and decision latency;
- explicit explanations for `cycle_stagnation`, `turn_cap`, and other endings;
- local rendering of either `summary.csv` or `runs.csv` without uploading data.

Record a single Jev replay:

```powershell
$env:TYPESAFE_API_KEY = "your-key"
python record_game.py --agent jev_progress --seed 37 --output web/replay.json
python -m http.server 8000 -d web
```

Then open:

```text
http://localhost:8000/?replay=replay.json
```

`web/replay.json` is ignored by Git. The repository ships the reviewed
`web/replay.example.json`. Replay schema v2 stores aligned pre/post states,
legal actions, public history, progress, probabilities, and the chosen action.
It contains no hidden-card identities.

Existing v2 decision logs can be exported without calling Jev again:

```powershell
python -m benchmark.export_replays results/<run-directory>
```

The main page and [`web/summary.html`](web/summary.html) both accept
`summary.csv` and `runs.csv` locally.

## Repository layout

```text
agents/                        Random, Heuristic, and Jev agents
benchmark/                     Runner, metrics, replay format, and seed contract
benchmark/seeds/               Development and held-out seed sets
solitaire/                     Klondike state, rules, and legal actions
tests/                         Rule, visibility, determinism, runner, and web tests
web/                           Replay and CSV viewer
record_game.py                 Record one browser-ready replay
run_benchmark.py               Benchmark entry point
run_game.py                    Local single-game debugging entry point
```

## Correctness and CI

The test suite covers the central invariants:

- identical seeds produce identical deals;
- all 52 cards remain unique and no card is lost;
- every generated action is legal and preserves state invariants;
- hidden identities and stock order never enter agent observations;
- public history and progress contain only visible facts;
- Draw-1 and Draw-3 recycle without reshuffling and preserve draw order;
- the full state hash includes complete tableau, foundation, stock, and waste
  order;
- exposed hidden cards flip in the same transition;
- Random and Heuristic are reproducible;
- Jev conditions have isolated input payloads;
- option ordering is stable across revisits, steps, input order, and Guard
  subsets;
- missing keys and API errors never trigger a silent fallback;
- interrupted runs resume only from verified state;
- replay frames align state, candidates, choice, and outcome;
- the held-out seed set is reproducible, unique, and disjoint from development.

Run all checks:

```powershell
python -m unittest discover -s tests -v
python -m benchmark.generate_seed_set --check
node tests/test_web_summary.js
```

GitHub Actions also checks JavaScript syntax, JSON artifacts, and whitespace.

## Interpretation boundaries

- One hundred deals support exploratory v0.1 analysis, not broad capability
  claims.
- Every condition must run on the same seeds for paired comparison.
- Fixed deals do not make remote Jev responses deterministic; repeated runs are
  needed to estimate policy variance.
- Jev latency includes encoding, network transit, parsing, retries, and backoff.
- Local baseline runtime must not be interpreted as directly comparable model
  latency.
- Reported confidence is model output, not calibrated action correctness.
- Without a complete-information solver, a policy failure cannot establish that
  the underlying deal was solvable.

## Optional future work

These are extensions, not v0.1 completion requirements:

- publish an independently executed `eval-v0.1` run and annotated failure
  replays;
- add paired bootstrap confidence intervals and repeated Jev trials per seed;
- compare Jev with heuristic features and bounded lookahead;
- add a complete-information solver to separate policy failure from deal
  unsolvability.

## References

- [TypeSafe SDK](https://github.com/typesafe-ai/typesafe-sdk-js)
- [Jev API Reference](https://jev-agent.com/api-reference)
- [Jev Game Benchmark](https://jev-agent.com/game-benchmark)

## License

[MIT](LICENSE)
