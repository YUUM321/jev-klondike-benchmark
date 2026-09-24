# Jev × Klondike Benchmark

一个可复现的 Klondike Solitaire（经典纸牌接龙）基准，用于比较 **Jev**、随机策略和轻量人工启发式策略在同一批牌局上的表现。

项目关注的不只是胜率，还记录每一步决策、可见状态、候选动作、置信度、响应延迟和失败轨迹，以研究一个核心问题：

> 在看不到暗牌、且只能从合法动作中选择的条件下，Jev 的快速决策能力可以把 Klondike 玩到什么程度？它又会在哪些局面中陷入循环或高置信度失败？

## 项目状态

| 模块 | 状态 |
| --- | --- |
| Klondike Draw-1 引擎 | 完成 |
| Random / Heuristic / Jev Agent | 完成 |
| 可见信息隔离与规则测试 | 完成 |
| 网页 Replay 播放器 | 完成 |
| 100 局冻结评测集 | 完成 |
| 正式 Jev × Baselines 结果 | **待运行** |

当前仓库包含完整的 v0.1 实验基础设施，但尚未发布正式 100 局结果。README 中不会预先填写或推断 Jev 的表现。

## 为什么选择 Klondike

Klondike 的单步动作通常不难判断是否合法，真正困难的是长期后果：一个眼前合理的动作，可能在十几步后锁死关键牌；而 Draw-1 与无限回收又允许 Agent 在合法状态之间反复循环。

这使它适合观察：

- 局部直觉能否转化为长期进展；
- Agent 是否主动创造翻开暗牌的机会；
- Agent 是否会反复撤销已经做过的决定；
- 简单规则和快速模型决策之间有多大差距；
- 延迟、置信度与最终结果之间是否存在关系。

## Benchmark 设计

### 游戏规则

- Klondike Draw-1；
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
```

### 运行 Jev

设置 TypeSafe API key：

```powershell
$env:TYPESAFE_API_KEY = "your-key"
```

先在开发集运行一局 smoke test：

```powershell
python run_benchmark.py --agents jev --limit 1
```

运行冻结的正式评测集：

```powershell
python run_benchmark.py --seed-set eval-v0.1 --agents random heuristic jev
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
```

`high_confidence_losses.jsonl` 只用于定位值得复查的步骤。一次高置信度选择出现在失败牌局中，并不能单独证明该选择导致了失败。

## Replay Viewer

仓库包含一个零构建依赖的 HTML/CSS/JavaScript 播放器：

```powershell
python -m http.server 8000 -d web
```

打开 [http://localhost:8000](http://localhost:8000) 即可查看内置示例，也可以拖入自己的 `replay.json`。播放器支持：

- 播放、暂停、单步和时间轴跳转；
- 0.5×–4× 播放速度；
- Stock、Waste、Foundation 和七列 Tableau；
- 合法动作、选中动作、概率与 confidence；
- 翻牌、Foundation 变化和当前决策耗时。

录制一局真实 Jev replay：

```powershell
$env:TYPESAFE_API_KEY = "your-key"
python record_game.py --agent jev --seed 37 --output web/replay.json
python -m http.server 8000 -d web
```

然后访问：

```text
http://localhost:8000/?replay=replay.json
```

Replay 只保存 Agent 当时可见的状态，不包含暗牌身份，也不会重新执行或推断动作。

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
- Draw-1 回收后保持正确抽牌顺序且不洗牌；
- 完整状态哈希包含 Tableau、Foundation、Stock 和 Waste 的完整顺序；
- 暴露暗牌在同一次状态转移中自动翻开；
- Random 与 Heuristic 在相同 seed 下可复现；
- Jev 缺少 key 或 API 失败时不会静默 fallback；
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
