# Jev × Klondike Benchmark

[![Tests](https://github.com/YUUM321/jev-klondike-benchmark/actions/workflows/tests.yml/badge.svg)](https://github.com/YUUM321/jev-klondike-benchmark/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> A reproducible benchmark for studying fast model decisions, limited public
> memory, and long-horizon failure modes in Klondike Solitaire.

一个可复现的 Klondike Solitaire（经典纸牌接龙）基准，用于比较 **Jev**、随机策略和轻量人工启发式策略在同一批牌局上的表现。

项目关注的不只是胜率，还记录每一步决策、可见状态、候选动作、置信度、响应延迟和失败轨迹，以研究一个核心问题：

> 在看不到暗牌、且只能从合法动作中选择的条件下，Jev 的快速决策能力可以把 Klondike 玩到什么程度？它又会在哪些局面中陷入循环或高置信度失败？

## 项目状态

| 模块 | 状态 |
| --- | --- |
| Klondike Draw-1 / Draw-3 引擎 | 完成 |
| Random / Heuristic / Jev Agent | 完成 |
| 可见信息隔离与规则测试 | 完成 |
| 网页 Replay 播放器 | 完成 |
| 100 局冻结评测集 | 完成 |
| 正式 Jev × Baselines 结果 | **待运行** |

当前仓库包含完整的 v0.1 实验基础设施，但尚未发布正式 100 局结果。README 中不会预先填写或推断 Jev 的表现。

## 为什么选择 Klondike

Klondike 的单步动作通常不难判断是否合法，真正困难的是长期后果：一个眼前合理的动作，可能在十几步后锁死关键牌；Stock 回收还允许 Agent 在合法状态之间反复循环。Draw-3 中，移走一张 Waste 牌会重新改变下一轮的三张分组，进一步增加了规划难度。

这使它适合观察：

- 局部直觉能否转化为长期进展；
- Agent 是否主动创造翻开暗牌的机会；
- Agent 是否会反复撤销已经做过的决定；
- 简单规则和快速模型决策之间有多大差距；
- 延迟、置信度与最终结果之间是否存在关系。

## Benchmark 设计

### 游戏规则

- Klondike Draw-1 或 Draw-3，默认 Draw-1；不同 draw count 视为独立实验条件；
- Stock 可无限次回收，回收时不洗牌；
- Tableau 按点数递减、红黑交替排列；
- 空列只接受 K 或以 K 开头的合法序列；
- Foundation 按同花色从 A 到 K；
- Foundation 顶牌可以移回 Tableau；
- Tableau 暗牌暴露后在同一次状态转移中自动翻开；
- 只有 Waste 顶牌可以移动；
- 52 张牌全部进入 Foundation 即获胜。

### 信息边界

引擎持有完整牌局，但 Agent 只能收到玩家可见的 `Observation`：

- 暗牌统一显示为 `XX`；
- 不提供 Stock 内部顺序；
- 不提供完整状态哈希或牌局 seed；
- 所有合法动作由引擎生成，Agent 只能从候选项中选择。

所有 Agent 还会获得同一份、仅由可见信息计算的公开历史：

- 当前可见局面是第几次到达；
- 该可见局面下此前尝试过哪些动作；
- 最近 8 个已执行动作。

公开历史使用 `visible_state_hash` 建立身份，不使用包含暗牌和完整 Stock
顺序的内部 `state_hash`。Heuristic 不再维护 Jev 无法访问的私有循环记忆。

这个边界由测试覆盖，避免 Jev 或基线策略通过接口意外读取隐藏信息。

### 对比 Agent

| Agent | 说明 |
| --- | --- |
| `RandomAgent` | 在合法动作中均匀随机选择；策略随机数可复现 |
| `HeuristicAgent` | 优先翻暗牌、安全进入 Foundation、减少明显循环的轻量规则基线 |
| `JevAgent` | 通过 System One Choice API 在预定义合法动作中选择；API 失败时不使用替代策略 |

Jev 使用固定的简短指令，不注入 HeuristicAgent 的具体规则：

```text
Goal: maximize the probability of eventually winning this Klondike game.
Choose exactly one of the supplied legal actions.
Consider future flexibility, hidden-card revelation, and dead-end risk.
```

请求同时附带明确的规则合同，包括 Draw 数量、无洗牌无限回收、空列只接收
K/K 序列、自动翻开暴露暗牌，以及 Foundation 顶牌可以撤回 Tableau；不依赖
不同实现可能解释不一致的“standard Klondike”简称。

## 评测指标

| 类别 | 指标 |
| --- | --- |
| 结果 | `win`、`termination_reason` |
| 进展 | `foundation_cards`、`hidden_cards_revealed` |
| 行为 | `steps`、`repeated_states`、`unique_states_visited`、`revisit_rate` |
| 速度 | `elapsed_seconds`、非强制决策 latency total / mean / median / P95 |
| Jev 诊断 | confidence、完整概率分布、模型版本、usage、重试次数、请求哈希 |

只有一个合法动作时，该步骤标记为 `forced`，并在逐局结果中累计为 `forced_decisions`，不进入决策延迟和 confidence 分析。

终止原因分开保留：

| 原因 | 定义 |
| --- | --- |
| `win` | 52 张牌全部进入 Foundation |
| `hard_dead_end` | 引擎没有任何合法动作 |
| `cycle_stagnation` | 连续 50 次状态转移都没有到达此前未见的新状态 |
| `turn_cap` | 达到 2,000 次决策的保护上限 |
| `agent_error` | Agent、API 或响应校验失败 |

`cycle_stagnation` 表示当前策略陷入循环，不等价于证明牌局无解。
`agent_error` 属于未完成运行，不计入胜率分母，也不会进入
`high_confidence_losses.jsonl`。

## 快速开始

要求 Python 3.10+。游戏引擎、基线和测试只使用 Python 标准库。

```powershell
cd jev-klondike-benchmark
python -m unittest discover -s tests -v
python run_benchmark.py --agents random heuristic
```

默认使用开发 seed，不会意外在正式评测集上运行。

### 运行一局

```powershell
python run_game.py --agent heuristic --seed 37
python run_game.py --agent heuristic --seed 37 --draw-count 3
```

### 运行 Jev

设置 TypeSafe API key：

```powershell
$env:TYPESAFE_API_KEY = "your-key"
```

API key 仅在运行时从环境变量读取，不会写入 manifest、Replay 或结果文件。
仓库只提交值为空的 `.env.example`；本地 `.env`、`.env.*` 和常见私钥文件均被忽略。

如果所在环境通过本地 HTTPS 代理访问 API，先设置代理变量；Jev Agent 会显式使用该代理并兼容 TLS 1.2：

```powershell
$env:HTTPS_PROXY = "http://proxy-host:port"
$env:HTTP_PROXY = "http://proxy-host:port"
```

先在开发集运行一局 smoke test：

```powershell
python run_benchmark.py --agents jev --limit 1
```

候选动作的排列 seed 会写入 manifest。正式评测前可在少量开发牌局上检查
位置敏感性，而不必立刻把完整评测成本扩大三倍：

```powershell
foreach ($orderSeed in 0, 1, 2) {
  python run_benchmark.py --agents jev --limit 10 `
    --jev-option-order-seed $orderSeed `
    --output-dir "results/order-smoke-$orderSeed"
}
```

若三个排列的结果差异明显，应把 option-order seed 升级为正式实验变量；否则
在正式 v0.1 中固定并报告一个 seed。

运行冻结的正式评测集：

```powershell
python run_benchmark.py --seed-set eval-v0.1 --draw-count 1 --agents random heuristic jev
```

Draw-3 必须作为单独实验运行，不能与 Draw-1 混入同一个 summary：

```powershell
python run_benchmark.py --seed-set eval-v0.1 --draw-count 3 --agents random heuristic jev
```

Jev 会产生真实网络请求，可能带来 API 费用。仓库不会在缺少 key 或请求失败时把其他策略的结果记到 Jev 名下。

## 冻结 Seed 与可复现性

仓库维护两套 seed：

- [`benchmark/seeds/dev.txt`](benchmark/seeds/dev.txt)：0–99，用于开发、测试和调参；
- [`benchmark/seeds/eval-v0.1.txt`](benchmark/seeds/eval-v0.1.txt)：100 个正式评测 seed，不依据任何 Agent 结果筛选。

正式评测集由公开 master seed 和版本无关的 SHA-256 counter 算法生成。完整合同及文件哈希记录在 [`benchmark/seeds/eval-v0.1.json`](benchmark/seeds/eval-v0.1.json)。

验证冻结文件：

```powershell
python -m benchmark.generate_seed_set --check
```

每次 benchmark 运行还会在 `manifest.json` 中保存：

- 实际 seed 列表与 seed 文件 SHA-256；
- Python、操作系统和完整命令行；
- Git commit SHA 与运行时工作区是否存在未提交修改；
- 游戏规则与终止参数；
- Jev 模型、候选顺序和请求配置；
- 计时范围及 percentile 算法。

## 输出文件

每次运行创建独立的 `results/<UTC timestamp>/`：

```text
manifest.json                 实验配置与复现信息
runs.jsonl                    逐局原始结果
runs.csv                      逐局指标
summary.csv                   按 Agent 汇总的结果与延迟
decisions.jsonl               Jev 的逐步观察、候选项和选择
high_confidence_losses.jsonl  高置信度失败的候选审查记录
replays/<agent>-seed-<n>.json 自动生成的逐局网页 Replay
```

CSV 用于统计展示，JSONL 用于保存可流式追加的原始记录，`replays/*.json` 才是牌桌播放器直接读取的逐帧文件。三者内容层级不同，不能互相替代。

`high_confidence_losses.jsonl` 只用于定位值得复查的步骤。一次高置信度选择出现在失败牌局中，并不能单独证明该选择导致了失败。

## Replay Viewer

仓库包含一个零构建依赖的 HTML/CSS/JavaScript 播放器：

```powershell
python -m http.server 8000 -d web
```

打开 [http://localhost:8000](http://localhost:8000) 即可查看内置示例，也可以拖入自己的文件。播放器支持：

- 播放、暂停、单步和时间轴跳转；
- 0.5×–4× 播放速度；
- Stock、Waste、Foundation 和七列 Tableau；Draw-3 的当前三张会扇形显示，最上层牌标记为可用；
- 合法动作、选中动作、概率与 confidence；
- 每一步明确区分动作执行前与执行后牌面，避免概率和画面错位；
- 翻牌、Foundation 变化、公开历史和当前决策耗时；
- `summary.csv` 与 `runs.csv` 的 Agent 汇总视图。

录制一局真实 Jev replay：

```powershell
$env:TYPESAFE_API_KEY = "your-key"
python record_game.py --agent jev --seed 37 --output web/replay.json
python -m http.server 8000 -d web
```

`web/replay.json` 是本地生成文件，已被 Git 忽略；仓库展示使用经过审查的
`web/replay.example.json`。

然后访问：

```text
http://localhost:8000/?replay=replay.json
```

Replay schema v2 同时保存每次决策的 `state_before` 与 `state_after`，并把当时
的候选动作、概率和选择绑定在同一帧。它只保存 Agent 当时可见的状态，不包含
暗牌身份，也不会重新执行或推断动作。播放器仍可读取旧 schema v1，并在浏览器
内转换为新的前后状态语义。

每次启用决策日志的 benchmark 都会自动写出 `replays/`，无需再次调用 Jev。旧结果也可以从原始 JSONL 离线导出：

```powershell
python -m benchmark.export_replays results/<run-directory>
```

要直接查看 CSV，可以在主页面选择“打开结果 CSV”，或双击 [`web/summary.html`](web/summary.html)。两者均支持 `summary.csv` 和 `runs.csv`，文件只在浏览器本地读取。

## 项目结构

```text
agents/                        Random、Heuristic 与 Jev Agent
benchmark/                     Runner、指标、Replay 格式与 seed 合同
benchmark/seeds/               开发集与冻结评测集
solitaire/                     Klondike 状态、规则与合法动作
tests/                         规则、可见性、确定性与 Runner 测试
web/                           Replay Viewer
record_game.py                 生成网页可读的 replay.json
run_benchmark.py               Benchmark 入口
run_game.py                    单局本地调试入口
```

## 正确性测试

测试覆盖的关键不变量包括：

- 相同 seed 产生相同初始牌局；
- 52 张牌始终唯一且不会丢失；
- 所有生成动作都合法，并在执行后保持规则不变量；
- 暗牌身份和 Stock 顺序不会进入 Agent Observation；
- 所有 Agent 获得相同的、仅基于可见状态的有限历史；
- Draw-1 与 Draw-3 回收后保持正确抽牌顺序且不洗牌；
- Draw-3 每次显示当前一至三张牌，并且只有 Waste 顶牌可以移动；
- 完整状态哈希包含 Tableau、Foundation、Stock 和 Waste 的完整顺序；
- 暴露暗牌在同一次状态转移中自动翻开；
- Random 与 Heuristic 在相同 seed 下可复现；
- Jev 缺少 key 或 API 失败时不会静默 fallback；
- `agent_error` 不会被计作普通 loss 或高置信失败；
- Replay 中动作前状态、候选动作、选择和动作后状态严格对齐；
- 正式 seed 集可重新生成、无重复且不与开发集重叠。

运行测试：

```powershell
python -m unittest discover -s tests -v
```

## 结果解释与限制

- 100 局适合 v0.1 探索和失败案例分析，不足以支撑广泛的总体能力结论；
- 三个 Agent 必须在相同 seed 上进行配对比较，不能只比较彼此独立的平均值；
- Seed 固定发牌，但不保证远程 Jev 调用完全确定；后续版本应增加每个 seed 的重复运行；
- Jev 延迟包含请求编码、网络往返、响应解析、重试和退避，受运行地区与服务负载影响；
- 本地基线的执行时间只是工程参照，不应与远程 API 延迟一起解释为策略能力；
- `confidence` 是模型输出，需要单独做 calibration 分析，不能直接视为动作正确率；
- 本项目尚未包含判断牌局理论可解性的完整信息搜索器。

## Roadmap

- [ ] 完成并发布 `eval-v0.1` 的 100 局正式结果；
- [ ] 发布至少一个带注释的 Jev 失败 replay；
- [ ] 增加 paired bootstrap 置信区间；
- [ ] 对每个 seed 重复运行 Jev，估计策略方差；
- [ ] 比较 Pure Jev、Jev + heuristic features 和有限步 lookahead；
- [ ] 加入完整信息 solver，用于区分策略失败与不可解牌局。

## 参考

- [TypeSafe SDK](https://github.com/typesafe-ai/typesafe-sdk-js)
- [Jev API Reference](https://jev-agent.com/api-reference)
- [Jev Game Benchmark](https://jev-agent.com/game-benchmark)

## License

[MIT](LICENSE)
