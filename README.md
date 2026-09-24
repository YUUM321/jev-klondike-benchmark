# Jev × Klondike Benchmark

一个可复现的 Klondike Draw‑1 benchmark：让 Jev、随机策略和一个很小的人工启发式策略，在同一批牌局上做选择，并保留 Jev 的逐步决策、概率、置信度与失败案例。

这不是“做一个接龙游戏”。v0.1 的研究问题是：

> 在只有玩家可见信息、只能从完整合法动作集合中选择的条件下，Jev 的快速直觉策略相对随机和简单手写规则表现如何？它会在哪里高置信度地走向失败？

## v0.1 实验合同

- Klondike Draw‑1，stock 无限次回收。
- 暴露的 tableau 暗牌自动翻开；允许 foundation 回撤到 tableau。
- `benchmark/seeds/dev.txt` 是已经影响过实现和启发式的开发集（0–99）；它不再冒充未见测试集。
- `benchmark/seeds/eval-v0.1.txt` 是正式冻结的 100 局评测集，由公开 master seed 和版本无关的 SHA-256 算法生成，未依据任何 agent 结果筛选。
- 三个 agent 看见同一批牌局；Random 的策略随机数也由牌局 seed 派生。
- 引擎持有完整牌局，但 runner 只向 agent 传递独立的 `Observation`；其中只有 visible state、公开 step、可见状态 hash 和合法动作标签，暗牌统一为 `XX`。Agent 无法访问 engine、Stock 顺序或暗牌身份。
- 引擎生成全部合法动作，agent 不能自由生成动作。
- Jev 使用一个 `Choice` 问题；没有 API fallback。网络错误、无效返回和缺少 key 都记为失败，不会偷偷改成“选第一项”。
- Jev 的合法动作顺序默认只按公开的 `option_order_seed + step + visible_state_hash` 做确定性打乱，不依赖牌局 seed 或完整 state hash。可用 `--jev-option-order canonical` 做消融实验。
- 主指标：`win`、`foundation_cards`、`hidden_cards_revealed`、`steps`、`repeated_states`、`unique_states_visited` 和 `revisit_rate`。
- 额外记录：`termination_reason`、agent 错误、Jev 模型版本、延迟、usage 和请求哈希。

Jev 当前是结构化决策模型，不输出自然语言；它的 Choice 接口接收预定义候选项并返回选择、概率分布和 confidence。仓库使用 TypeSafe 的 `POST /v1/systemone` HTTP 合同，而不是 Chat Completions。参考：[TypeSafe SDK](https://github.com/typesafe-ai/typesafe-sdk-js)、[API shape](https://jev-agent.com/api-reference)、[独立游戏 benchmark](https://jev-agent.com/game-benchmark)。

## 为什么与最初草案略有不同

1. “没有推进动作”不能只看当前一步。stock 顶牌暂时不可用，不代表整轮 stock 都无解。因此 `is_dead_end()` 只报告真正没有合法动作的硬死局；runner 用历史来检测软死局。
2. 连续 50 步既无新暗牌、foundation 新高点，也无全局新状态时，记为 `cycle_stagnation`。接龙允许循环，所以不同的新排列不能被简单判为死局。
3. 每个 agent 使用同一个 2,000 次决策预算。用尽预算记为 `turn_cap`，不冒充“牌局无解”；判断真正不可解需要另外的求解器。
4. Random 仍保留为最低基线，但结论不能只写“Jev 胜过随机”。Heuristic 才是最低限度有信息量的参照。
5. Jev API 失败时不降级。静默 fallback 会把 fallback 的能力记到 Jev 头上，是这类 benchmark 最危险的污染。
6. 100 局只适合探索和案例发现，不足以支持很强的总体结论。发布时应同时给原始逐局结果，不只给胜率。

## 快速开始

要求 Python 3.10+，运行引擎和测试不需要第三方依赖。

```powershell
python -m unittest discover -s tests -v
python run_benchmark.py --agents random heuristic
```

默认使用 `dev`，防止开发时意外反复查看正式评测集。规则、prompt 和 agent 全部冻结后，正式运行必须显式指定：

```powershell
python run_benchmark.py --seed-set eval-v0.1 --agents random heuristic
```

评测集的生成合同是 `SHA256(namespace + NUL + master_seed + NUL + counter)`，依次取前 8 字节并映射到 `[0, 2^31)`，保留前 100 个不重复值。这里的上界是二的幂，不产生模偏差。该方法不依赖 Python `random` 的具体版本；`manifest.json` 会同时记录 seed 文件哈希和完整生成合同。

运行真实 Jev：

```powershell
$env:TYPESAFE_API_KEY = "your-key"
python run_benchmark.py --seed-set eval-v0.1 --agents random heuristic jev
```

Jev 是付费网络调用，所以默认命令只跑本地两个 baseline；必须显式把 `jev` 加到 `--agents`。先做一局 smoke test：

```powershell
python run_benchmark.py --agents jev --limit 1
```

可用参数：

```text
--seed-set dev|eval-v0.1     使用仓库内的命名 seed 集（默认 dev）
--seeds PATH                 使用自定义 seed 文件；不能与 --seed-set 同用
--limit N                    只跑前 N 局
--stagnation-steps 50        软死局窗口
--max-steps 2000             每局安全上限
--log-decisions jev|all|none 决策日志范围
--jev-model jev-latest       请求的模型别名/版本
--jev-base-url URL           System One API host
--jev-option-order seeded|canonical
--jev-option-order-seed 0    公开、固定的候选顺序 seed
```

## 输出

每次运行创建独立的 `results/<UTC timestamp>/`：

```text
manifest.json                 完整实验配置、seed set、文件哈希和环境信息
runs.jsonl                    每个 agent × seed 的逐局结果
runs.csv                      逐局指标与 termination_reason
summary.csv                   聚合指标、终止原因分布与 revisit 指标
decisions.jsonl               默认只含 Jev 的逐步观察和选择
high_confidence_losses.jsonl  confidence > 0.9 且最终失败的非 forced 决策
```

重放某个失败案例：

```powershell
python -m benchmark.replay results/20260924T000000Z/decisions.jsonl --agent jev --seed 37
```

也可以限制步骤范围：

```powershell
python -m benchmark.replay results/20260924T000000Z/decisions.jsonl --seed 37 --from-step 35 --to-step 50
```

`high_confidence_losses.jsonl` 是候选审查集，不自动声称“这一步就是致败手”。只有一个合法动作时不会调用 Jev，日志标记 `forced: true` 且 `confidence: null`，不会进入 confidence 或 calibration 分析。最终失败可能由后续动作或牌局本身造成，需要 replay 人工检查或用搜索 oracle 做反事实分析。

## 网页回放

仓库包含一个纯 HTML/CSS/JavaScript 回放器，不需要前端构建工具。先启动本地静态服务器：

```powershell
python -m http.server 8000 -d web
```

访问 [http://localhost:8000](http://localhost:8000)。默认会载入一段 16 步的 Heuristic 界面示例，也可以点击“打开 replay.json”或把文件拖进页面。播放器支持：

- 播放、暂停、前后单步、时间轴和 0.5×–4× 速度；
- stock、waste、foundation 和七列 tableau 的逐帧状态；
- Jev 选中的动作、confidence、完整候选数和概率前八项；
- 翻暗牌、foundation 变化、局面指标和合法动作列表；
- 键盘空格播放/暂停，左右方向键单步。

实际录制一局 Jev 并让网页播放：

```powershell
$env:TYPESAFE_API_KEY = "your-key"
python record_game.py --agent jev --seed 37 --output web/replay.json
python -m http.server 8000 -d web
```

然后访问：

```text
http://localhost:8000/?replay=replay.json
```

完整数据流是：

```text
Jev 只能从引擎给出的合法动作中选择
→ runner 记录每一步玩家可见状态与 Jev 返回值
→ record_game.py 写出 replay.json
→ 网页逐帧读取并播放，不重新执行或推断动作
```

`replay.json` 只保存 agent 当时可见的牌局；`XX` 没有暗牌身份。因此网页本身也不会泄漏未来暗牌。格式版本固定为 `schema_version: 1`，定义见 `web/replay.schema.json`。

## 结构

```text
solitaire/engine.py           完整规则、可见状态、合法动作、hash
agents/random_agent.py        可复现的均匀随机基线
agents/heuristic_agent.py     翻暗牌/安全上 foundation/去循环
agents/jev_agent.py           严格的 System One Choice 适配器
benchmark/runner.py           终止条件与逐步日志
benchmark/metrics.py          聚合结果
benchmark/replay.py           文本 replay
benchmark/replay_format.py    稳定的网页 replay schema
benchmark/seeds/dev.txt       0–99 开发集，不用于最终无泄漏评测
benchmark/seeds/eval-v0.1.txt 正式冻结的 100 局评测集
benchmark/seeds/eval-v0.1.json 生成合同与 seed 文件 SHA-256
benchmark/seed_sets.py        稳定 seed 生成与读取逻辑
benchmark/generate_seed_set.py 重现/校验正式评测集
tests/                        规则、可见性、确定性和 runner 测试
run_game.py                   单局本地调试
run_benchmark.py              完整实验入口
record_game.py                单局运行并生成 replay.json
web/                          HTML/CSS/JS 可视化播放器
```

## 冻结的 Pure Jev 输入

Jev 的 state 只有规则名与玩家可见状态；问题指令保持短且不注入手写策略：

```text
Goal: maximize the probability of eventually winning this Klondike game.
Choose exactly one of the supplied legal actions.
Consider future flexibility, hidden-card revelation, and dead-end risk.
```

每个 Choice option 的描述仅说明动作本身，例如：

```text
7H: tableau 0 -> tableau 3 (1 card)
5D: waste -> tableau 1
draw one card from stock
```

不要在跑完部分结果后修改这段 prompt 再把数据混进同一 summary。修改 prompt、模型版本、动作顺序或终止条件，都应视为新的实验条件。

## 测试覆盖的关键不变量

- 同 seed 得到完全相同的初始牌局和 state hash。
- 52 张牌始终唯一且不丢失。
- 所有生成动作都能合法应用并保持 tableau/foundation 不变量。
- face-down 身份不会出现在 visible state。
- stock recycle 恢复正确的 Draw‑1 顺序。
- 完整 state hash 能区分玩家画面相同但 Stock 内部顺序不同的状态。
- Agent 接口不暴露 engine 或暗牌，候选顺序不依赖隐藏状态。
- Tableau 的每个合法 face-up 后缀都能生成，非法来源不会混入。
- 暴露暗牌在同一个 transition 内自动翻开。
- win 判断、hash 稳定性和非法动作拒绝。
- Random 与 Heuristic 在相同 seed 下可复现。
- Jev 缺 key 时严格失败，不使用 fallback。

## 下一步，而不是现在塞进 v0.1

在先看完 v0.1 的逐局数据后，再新增独立实验条件：

1. Pure Jev
2. Jev + 显式 heuristic features
3. Jev + 1-step lookahead
4. Jev + 3-step lookahead

更严谨的 v0.2 还应加入：多次 Jev 重复运行以估计策略方差、paired bootstrap 置信区间、可解性/search oracle、prompt 与模型版本消融，以及 API 成本和端到端延迟分布。

## 结果发布检查表

- 公布 `manifest.json`、`runs.jsonl`，不要只贴 summary。
- 正式结果只使用 `--seed-set eval-v0.1`；不得按胜负、难度或异常程度删除牌局。
- 可用 `python -m benchmark.generate_seed_set --check` 验证评测集未被改写。
- 同一 seed 上比较 agent，报告逐 seed 的配对差异；100 局胜率接近 50% 时，单一胜率的 95% 抽样误差约为 ±10 个百分点。
- seed 只固定发牌，不保证 Jev 调用本身确定；v0.1 单次运行需声明这一限制，后续应对每个 seed 重复 Jev 调用以估计策略方差。
- agent error 不进入胜率分母，但必须单独报告数量。
- 不把 100 局的差异写成普遍能力结论。
- 不把 confidence 当成“这一步正确的概率”；单独检验 calibration。
- 至少 replay 一个真实失败案例，并说明为什么认为某一步值得怀疑。
- 若 API 返回的实际模型版本不同于请求别名，以日志中的返回版本为准。

## License

MIT
