# Jev × Klondike Benchmark

[English](README.md) | **简体中文**

[![Tests](https://github.com/YUUM321/jev-klondike-benchmark/actions/workflows/tests.yml/badge.svg)](https://github.com/YUUM321/jev-klondike-benchmark/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> 用于研究快速模型决策、有限公开记忆与 Klondike 长期失败模式的可复现实验基础设施。

本仓库提供确定性的 Klondike 引擎、本地基线、四种 Jev 消融条件、冻结牌局集、
完整指标、断点续跑和网页 Replay。它关注的并不只是“模型会不会玩接龙”，而是一个
更具体的问题：

> 在一个部分可观察、长决策链的任务中，快速的 System-One 决策模型需要多少外部
> 结构，才能让局部选择转化为有效的长期行为？

## 项目状态与范围

| 模块 | 状态 |
| --- | --- |
| Klondike Draw-1 / Draw-3 引擎 | 完成 |
| Random / Heuristic 本地基线 | 完成 |
| Raw / History / Progress / Guard 四种 Jev 条件 | 完成 |
| 隐藏信息边界与规则测试 | 完成 |
| 100 局冻结评测集 | 完成 |
| Checkpoint、Resume、Provenance 与指标 | 完成 |
| 网页 Replay 与 CSV 查看器 | 完成 |
| 大规模远程 Jev 结果 | v0.1 不包含；属于可选后续研究 |

v0.1 的交付目标是完整的 benchmark protocol 和可复现实验基础设施，而不是一组
官方远程分数。可靠的大规模评测需要稳定的外部 API 环境，因此本仓库不会发布
不完整的 Jev 结果，也不会用替代策略填补调用失败。

v0.1 已包含：

- 确定性的游戏规则与合法动作生成；
- 严格的玩家可见信息边界；
- 本地基线和四种彼此隔离的 Jev 条件；
- 冻结的开发集与留出评测集；
- 逐步日志、进展指标、延迟指标和实验 provenance；
- 安全 checkpoint、精确续跑、Replay 导出和 CI 测试。

v0.1 不包含：

- 官方 Jev 胜率结论；
- 已发布的大规模远程 API 运行数据；
- 用于证明牌局是否可解的完整信息 solver。

## 为什么选择 Klondike？

Klondike 的单步动作通常不难验证，真正困难的是长期后果。一个眼前合理的动作
可能在许多步后堵住关键牌；无限次 Stock 回收又允许策略在合法状态之间循环而
没有实际进展。Draw-3 还多了一层依赖：从 Waste 移走一张牌会改变下一轮 Stock
的三张分组。

因此它适合研究：

- 局部直觉能否转化为持续进展；
- Agent 是否会主动创造翻开 Tableau 暗牌的机会；
- Agent 是否反复撤销之前的决定；
- 轻量手写策略和快速模型之间有多大差距；
- confidence、延迟与最终结果之间有什么关系。

## Benchmark 协议

### 游戏规则

- 支持 Klondike Draw-1 和 Draw-3；默认 Draw-1，不同 draw count 是独立实验条件。
- Stock 可以无限次回收，回收时不洗牌。
- Tableau 按点数递减、红黑交替排列。
- 空 Tableau 列只接受 K 或以 K 开头的序列。
- Foundation 按同花色从 A 排到 K。
- Foundation 顶牌可以移回 Tableau。
- Tableau 暗牌暴露后在同一次状态转移中自动翻开。
- 只有 Waste 顶牌可以移动。
- 52 张牌全部进入 Foundation 即获胜。

### 信息边界

引擎持有完整牌局，但 Agent 只能收到玩家可见的 `Observation`：

- 暗牌统一表示为 `XX`；
- 不暴露 Stock 内部顺序；
- 不暴露牌局 seed 或完整内部状态哈希；
- 所有合法动作由引擎生成，Agent 必须从中选择。

运行器还会完全根据可见信息计算公开历史：

- 当前可见局面的访问次数；
- 从该局面选择各动作的次数；
- 每个动作曾产生的可见结果及次数；
- 距离上次到达新可见局面的步数；
- 最近 8 个公开动作和可见状态转移。

公开历史使用 `visible_state_hash`，不会使用包含暗牌和完整 Stock / Waste 顺序的
内部 `state_hash`。Random 忽略公开历史，Heuristic 用它减少明显重复，四种 Jev
条件则只接收各自实验定义允许的上下文。

### Agent 与消融条件

| Agent | 上下文与策略 |
| --- | --- |
| `RandomAgent` | 在合法动作中均匀随机选择；策略随机数可复现 |
| `HeuristicAgent` | 优先翻暗牌、安全进入 Foundation，并减少明显重复的轻量确定性基线 |
| `JevRawAgent` / `jev_raw` | 只接收当前可见状态、明确规则和合法动作 |
| `JevHistoryAgent` / `jev_history` | 在 Raw 基础上接收 `public-history-v2`，但不屏蔽合法动作 |
| `JevProgressAgent` / `jev_progress` | 在 History 基础上接收未加权的客观进展事实，不提供动作奖励或手写分数 |
| `JevGuardAgent` / `jev_guard` | 在 History 基础上使用 `untried-actions-first-v1`；有替代项时暂时过滤当前局面已经尝试过的动作 |

四种 Jev 条件共享同一条核心指令：

```text
Goal: maximize the probability of eventually winning this Klondike game.
Choose exactly one of the supplied legal actions.
Consider future flexibility, hidden-card revelation, and dead-end risk.
```

History 要求模型利用公开历史。Progress 增加 Foundation 历史峰值、剩余 Tableau
暗牌、距离上次翻牌或 Foundation 增长的步数，以及无结构进展时完成的 Stock
轮数。这些都是事实，不是 reward。Guard 是明确标注的工程干预，不会被包装成
“Pure Jev”。

`jev` 和 `jev_memory` 是 `jev_history` 与 `jev_guard` 的兼容别名。新实验应使用
完整条件名。

### 稳定候选顺序

Seeded 候选顺序使用 `stable-visible-action-v2`。每个动作的稳定优先级来自：

```text
option-order 协议版本
+ 显式 option-order seed
+ visible state hash
+ action identity
```

它不依赖游戏 seed、暗牌、完整状态、step 或引擎原始枚举顺序。同一可见局面再次
出现时，动作顺序保持一致；Guard 过滤部分动作后，剩余动作的相对顺序也不变。
协议版本和 seed 都会写入 `manifest.json`。

## 指标与终止条件

| 类别 | 字段 |
| --- | --- |
| 结果 | `win`、`termination_reason` |
| 进展 | `foundation_cards`、`max_foundation_cards_seen`、`hidden_cards_revealed` |
| 行为 | `steps`、`repeated_states`、`unique_states_visited`、`revisit_rate`、`draw_rate`、`recycle_rate` |
| 速度 | 总耗时和非强制决策 latency total / mean / median / P95 |
| Jev 诊断 | confidence、完整概率分布、模型、usage、重试次数、请求哈希 |

规则层面只有一个合法动作时记为 `forced`。Guard 从多个合法动作中过滤到只剩一个
候选时记为 `policy_forced`。两者都不进入模型延迟和 confidence 分析。

终止原因分别保留：

| 原因 | 定义 |
| --- | --- |
| `win` | 52 张牌全部进入 Foundation |
| `hard_dead_end` | 引擎没有任何合法动作 |
| `cycle_stagnation` | 连续 50 次状态转移都没有到达此前未见的完整状态 |
| `turn_cap` | 达到默认 700 次决策的保护上限 |
| `agent_error` | Agent、远程 API 或响应校验失败 |

`cycle_stagnation` 表示当前策略陷入循环，不代表牌局一定无解。`agent_error` 是未
完成运行，不计入胜率分母，也不会进入 `high_confidence_losses.jsonl`。

## 快速开始

需要 Python 3.10 或更高版本。引擎、本地基线和测试只使用 Python 标准库。

```powershell
git clone https://github.com/YUUM321/jev-klondike-benchmark.git
cd jev-klondike-benchmark
python -m unittest discover -s tests -v
python run_benchmark.py --agents random heuristic
```

默认命令只使用开发 seed，不会意外消耗留出评测集。

运行一局本地游戏：

```powershell
python run_game.py --agent heuristic --seed 37
python run_game.py --agent heuristic --seed 37 --draw-count 3
```

### 运行 Jev

在运行环境中设置 TypeSafe API key。它不会写入 manifest、Replay 或结果文件。

PowerShell：

```powershell
$env:TYPESAFE_API_KEY = "your-key"
```

POSIX shell：

```bash
export TYPESAFE_API_KEY="your-key"
```

先在开发集做单局 smoke test：

```powershell
python run_benchmark.py --agents jev_raw --limit 1
python run_benchmark.py --agents jev_history jev_progress jev_guard --limit 1
```

四种条件是不同实验处理，不能合并成一个 “Jev” 结果。远程调用可能产生 API
费用；请求失败时不会回退到本地策略。

在开发牌局上检查候选位置敏感性：

```powershell
foreach ($orderSeed in 0, 1, 2) {
  python run_benchmark.py --agents jev_raw --limit 10 `
    --jev-option-order-seed $orderSeed `
    --output-dir "results/order-smoke-$orderSeed"
}
```

### 可选的留出集评测

使用者可以在自己的远程 API 环境中运行冻结评测集：

```powershell
python run_benchmark.py --seed-set eval-v0.1 --draw-count 1 `
  --agents random heuristic jev_raw jev_history jev_progress jev_guard
```

Draw-3 是独立实验，不能与 Draw-1 混入同一个 summary：

```powershell
python run_benchmark.py --seed-set eval-v0.1 --draw-count 3 `
  --agents random heuristic jev_raw jev_history jev_progress jev_guard
```

### 从中断处继续

每次成功的 Jev 决策都会写入并同步到逐局 checkpoint。解决中断原因后，传入原
结果目录即可继续：

```powershell
python run_benchmark.py --resume results/<run-directory>
```

Resume 会从已经提交的动作重建牌局，验证可见状态和完整状态哈希，恢复公开历史
与进展计数；如果 benchmark 源码语义已经改变，则拒绝继续旧运行。

## 冻结牌局与实验 Provenance

仓库版本化维护两套 seed：

- [`benchmark/seeds/dev.txt`](benchmark/seeds/dev.txt)：0–99，用于开发、测试和调参；
- [`benchmark/seeds/eval-v0.1.txt`](benchmark/seeds/eval-v0.1.txt)：100 个留出 seed，不根据任何 Agent 结果筛选。

评测集由公开 master seed 和版本无关的 SHA-256 counter 算法生成。合同和文件哈希
保存在 [`benchmark/seeds/eval-v0.1.json`](benchmark/seeds/eval-v0.1.json)。

验证冻结文件：

```powershell
python -m benchmark.generate_seed_set --check
```

每次运行的 `manifest.json` 会保存：

- 实际 seed 列表和 seed 文件 SHA-256；
- Python、操作系统版本和清理过本机绝对路径的命令行；
- Git commit 和工作区是否存在未提交修改；
- 游戏规则与终止参数；
- Jev 模型、候选顺序协议和请求配置；
- 计时范围和 percentile 算法；
- 用于保护续跑语义的源码指纹。

## 输出文件

每次运行创建 `results/<UTC timestamp>/`：

```text
manifest.json                 实验配置与 provenance
runs.jsonl                    每局一条原始记录
runs.csv                      逐局指标
summary.csv                   按 Agent 汇总的指标
decisions.jsonl               逐步观察、候选动作与选择
high_confidence_losses.jsonl  供人工审查的高置信失败候选步骤
replays/<agent>-seed-<n>.json 网页可读的逐局 Replay
```

CSV 用于分析和表格展示；JSONL 保存适合流式处理的原始记录；只有
`replays/*.json` 是牌桌播放器读取的逐帧格式。

失败牌局中的一次高置信选择只能说明该步骤值得复查，不能单独证明它导致了失败。

## Replay 与 CSV 查看器

仓库包含一个不需要构建的 HTML/CSS/JavaScript 查看器：

```powershell
python -m http.server 8000 -d web
```

打开 [http://localhost:8000](http://localhost:8000) 即可读取经过审查的内置示例，
也可以拖入本地 Replay。查看器支持：

- 播放、暂停、单步、时间轴跳转和 0.5×–4× 速度；
- Stock、Waste、Foundation 和七列 Tableau；
- Draw-3 的 Waste 三张分组，并只标记顶牌为可用；
- 动作执行前后牌面、合法动作、公开历史和进展指标；
- 选中动作的概率、confidence 和决策延迟；
- 对 `cycle_stagnation`、`turn_cap` 等终止原因的明确解释；
- 在浏览器本地展示 `summary.csv` 或 `runs.csv`，不会上传数据。

录制一局 Jev Replay：

```powershell
$env:TYPESAFE_API_KEY = "your-key"
python record_game.py --agent jev_progress --seed 37 --output web/replay.json
python -m http.server 8000 -d web
```

然后访问：

```text
http://localhost:8000/?replay=replay.json
```

`web/replay.json` 已被 Git 忽略；仓库自带经过审查的
`web/replay.example.json`。Replay schema v2 保存对齐的动作前后状态、合法动作、
公开历史、进展、概率和最终选择，不包含暗牌身份。

已有 v2 决策日志可以在不重新调用 Jev 的情况下导出：

```powershell
python -m benchmark.export_replays results/<run-directory>
```

主页面和 [`web/summary.html`](web/summary.html) 都可以在本地读取 `summary.csv` 与
`runs.csv`。

## 仓库结构

```text
agents/                        Random、Heuristic 与 Jev Agent
benchmark/                     Runner、指标、Replay 格式与 seed 合同
benchmark/seeds/               开发集与留出评测集
solitaire/                     Klondike 状态、规则与合法动作
tests/                         规则、可见性、确定性、Runner 与网页测试
web/                           Replay 与 CSV 查看器
record_game.py                 录制单局网页 Replay
run_benchmark.py               Benchmark 入口
run_game.py                    本地单局调试入口
```

## 正确性与 CI

测试覆盖的核心不变量包括：

- 相同 seed 产生相同牌局；
- 52 张牌始终唯一且不会丢失；
- 所有生成动作都合法，并在执行后保持状态不变量；
- 暗牌身份和 Stock 顺序不会进入 Agent Observation；
- 公开历史和进展字段只包含可见事实；
- Draw-1 与 Draw-3 回收时不洗牌并保持正确抽牌顺序；
- 完整状态哈希包含 Tableau、Foundation、Stock 和 Waste 的完整顺序；
- 暴露暗牌在同一次状态转移中自动翻开；
- Random 与 Heuristic 可复现；
- 四种 Jev 条件的输入彼此隔离；
- 候选顺序不受重访 step、输入枚举顺序和 Guard 子集影响；
- 缺少 key 或 API 失败时不会静默 fallback；
- 中断运行只能从经过验证的状态继续；
- Replay 的状态、候选项、选择和结果严格对齐；
- 留出 seed 集可重新生成、无重复且不与开发集重叠。

运行完整检查：

```powershell
python -m unittest discover -s tests -v
python -m benchmark.generate_seed_set --check
node tests/test_web_summary.js
```

GitHub Actions 还会检查 JavaScript 语法、JSON 文件和空白格式。

## 结果解释边界

- 100 局适合 v0.1 探索，不足以支撑广泛的能力结论。
- 所有条件必须在相同 seed 上进行配对比较。
- 固定牌局不能保证远程 Jev 响应确定；估计策略方差需要重复运行。
- Jev 延迟包括编码、网络传输、解析、重试和退避。
- 本地基线运行时间不能直接解释为与模型延迟可比。
- confidence 是模型输出，不等于校准后的动作正确率。
- 没有完整信息 solver 时，策略失败不能证明底层牌局原本可解。

## 可选后续方向

以下内容不是 v0.1 的完成条件：

- 独立运行并发布 `eval-v0.1` 结果和带注释的失败 Replay；
- 增加 paired bootstrap 置信区间，并对每个 seed 重复运行 Jev；
- 比较 Jev + heuristic features 与有限步 lookahead；
- 加入完整信息 solver，区分策略失败和牌局不可解。

## 参考

- [TypeSafe SDK](https://github.com/typesafe-ai/typesafe-sdk-js)
- [Jev API Reference](https://jev-agent.com/api-reference)
- [Jev Game Benchmark](https://jev-agent.com/game-benchmark)

## License

[MIT](LICENSE)
