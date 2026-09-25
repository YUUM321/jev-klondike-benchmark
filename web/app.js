"use strict";

const SUITS = { S: "♠", H: "♥", D: "♦", C: "♣" };
const SUIT_ORDER = ["S", "H", "D", "C"];
const ui = Object.fromEntries(
  [
    "load-status", "replay-file", "run-title", "agent-badge", "seed-badge",
    "result-badge", "stock", "waste", "foundations", "tableau", "previous",
    "play", "next", "timeline", "step-label", "progress-label", "speed",
    "confidence-ring", "action", "event-chips", "candidate-count",
    "probabilities", "foundation-metric", "stock-metric", "hidden-metric",
    "states-metric", "foundation-peak-metric", "reveal-age-metric",
    "foundation-age-metric", "stock-pass-metric", "legal-toggle", "legal-title",
    "legal-count", "legal-actions", "drop-overlay",
    "summary-file", "summary-panel", "summary-description", "summary-cards",
    "summary-row-count", "summary-table", "back-to-replay", "state-phase",
    "termination-notice", "termination-title", "termination-copy"
  ].map((id) => [id, document.getElementById(id)])
);

let replay = null;
let frameIndex = 0;
let framePhase = "before";
let timer = null;

const SUMMARY_COLUMNS = [
  ["agent", "Agent"],
  ["games", "Games"],
  ["wins", "Wins"],
  ["win_rate", "Win rate"],
  ["mean_foundation_cards", "Foundation"],
  ["mean_max_foundation_cards_seen", "Foundation peak"],
  ["mean_hidden_cards_revealed", "Hidden revealed"],
  ["mean_steps", "Steps"],
  ["cycle_stagnation_rate", "Cycle rate"],
  ["mean_revisit_rate", "Revisit rate"],
  ["draw_rate", "DRAW rate"],
  ["recycle_rate", "RECYCLE rate"],
  ["mean_decision_latency_ms", "Mean latency"],
  ["mean_game_p95_decision_latency_ms", "P95 latency"],
  ["agent_errors", "Errors"],
];

function parseCard(code) {
  if (!code || code === "-" || code === "XX") return null;
  return { rank: code.slice(0, -1), suit: code.slice(-1) };
}

function makeCard(code, { tableau = false, index = 0 } = {}) {
  const card = document.createElement("div");
  card.className = `card${tableau ? " tableau-card" : ""}`;
  if (tableau) card.style.setProperty("--i", index);
  if (code === "XX") {
    card.classList.add("back");
    card.setAttribute("aria-label", "Face-down card");
    return card;
  }
  const parsed = parseCard(code);
  if (!parsed) {
    card.className = "empty-slot";
    return card;
  }
  const symbol = SUITS[parsed.suit];
  if (parsed.suit === "H" || parsed.suit === "D") card.classList.add("red");
  card.setAttribute("aria-label", `${parsed.rank}${parsed.suit}`);

  const corner = document.createElement("span");
  corner.className = "card-corner";
  const rank = document.createElement("span");
  rank.textContent = parsed.rank;
  const suit = document.createElement("span");
  suit.className = "suit";
  suit.textContent = symbol;
  corner.append(rank, suit);

  const center = document.createElement("span");
  center.className = "card-center";
  center.textContent = symbol;
  card.append(corner, center);
  return card;
}

function renderPileSlot(element, code, count = null) {
  element.replaceChildren();
  element.append(makeCard(code));
  if (count !== null && count > 0) {
    const badge = document.createElement("span");
    badge.className = "stock-count";
    badge.textContent = String(count);
    element.append(badge);
  }
}

function renderWaste(state) {
  const codes = Array.isArray(state.waste_visible) && state.waste_visible.length
    ? state.waste_visible
    : (state.waste && state.waste !== "-" ? [state.waste] : []);
  ui.waste.replaceChildren();
  ui.waste.classList.toggle("waste-fan-slot", codes.length > 1);
  if (!codes.length) {
    ui.waste.append(makeCard("-"));
    return;
  }
  codes.forEach((code, index) => {
    const card = makeCard(code);
    card.classList.add("waste-fan-card");
    if (index === codes.length - 1) card.classList.add("playable-card");
    card.style.setProperty("--fan-index", index);
    card.style.zIndex = String(index + 1);
    ui.waste.append(card);
  });
}

function countFoundation(state) {
  return Object.values(state.foundation).reduce((sum, code) => {
    const card = parseCard(code);
    if (!card) return sum;
    const ranks = { A: 1, J: 11, Q: 12, K: 13 };
    return sum + (ranks[card.rank] || Number(card.rank));
  }, 0);
}

function renderBoard(state) {
  renderPileSlot(ui.stock, state.stock_count > 0 ? "XX" : "-", state.stock_count);
  renderWaste(state);

  ui.foundations.replaceChildren();
  for (const suit of SUIT_ORDER) {
    const wrap = document.createElement("div");
    wrap.className = "pile-wrap";
    wrap.dataset.suit = SUITS[suit];
    const label = document.createElement("span");
    label.className = "pile-label";
    label.textContent = suit;
    const slot = document.createElement("div");
    slot.className = "card-slot";
    renderPileSlot(slot, state.foundation[suit]);
    wrap.append(label, slot);
    ui.foundations.append(wrap);
  }

  ui.tableau.replaceChildren();
  for (const pile of state.tableau) {
    const column = document.createElement("div");
    column.className = "tableau-column";
    if (pile.length === 0) column.append(makeCard("-"));
    pile.forEach((code, index) => column.append(makeCard(code, { tableau: true, index })));
    ui.tableau.append(column);
  }
}

function renderProbabilities(frame) {
  const entries = Object.entries(frame.probabilities || {}).sort((a, b) => b[1] - a[1]);
  ui.probabilities.replaceChildren();
  if (!entries.length) {
    const empty = document.createElement("p");
    empty.className = "empty-copy";
    empty.textContent = frame.step === 0 ? "初始牌局，还没有决策。" : "这个 agent 没有返回概率分布。";
    ui.probabilities.append(empty);
    return;
  }
  for (const [name, value] of entries.slice(0, 8)) {
    const row = document.createElement("div");
    row.className = "probability-row";
    const label = document.createElement("span");
    label.className = "probability-name";
    label.title = name;
    label.textContent = name;
    const probability = document.createElement("span");
    probability.className = "probability-value";
    probability.textContent = `${(value * 100).toFixed(1)}%`;
    const track = document.createElement("div");
    track.className = "probability-track";
    const fill = document.createElement("div");
    fill.className = "probability-fill";
    fill.style.setProperty("--p", `${Math.max(1, value * 100)}%`);
    track.append(fill);
    row.append(label, probability, track);
    ui.probabilities.append(row);
  }
}

function phaseLegalActions(frame, phase) {
  if (phase === "after") return frame.legal_actions_after || [];
  return frame.legal_actions_before || frame.legal_actions || [];
}

function phasePublicHistory(frame, phase) {
  if (phase === "after") return frame.public_history_after || {};
  return frame.public_history_before || frame.public_history || {};
}

function phaseProgress(frame, phase) {
  if (phase === "after") return frame.progress_after || {};
  return frame.progress_before || frame.progress || {};
}

function renderLegalActions(frame, phase) {
  const actions = phaseLegalActions(frame, phase);
  ui["legal-count"].textContent = String(actions.length);
  ui["legal-title"].textContent = frame.action
    ? (phase === "after" ? "执行后合法动作" : "本次决策候选动作")
    : "初始合法动作";
  ui["legal-actions"].replaceChildren();
  for (const action of actions) {
    const item = document.createElement("li");
    item.textContent = action;
    ui["legal-actions"].append(item);
  }
}

function renderEvents(frame, phase) {
  ui["event-chips"].replaceChildren();
  const events = frame.events || {};
  const labels = [];
  if (phase === "after") {
    if (events.hidden_revealed > 0) labels.push(`翻开 ${events.hidden_revealed} 张暗牌`);
    if (events.foundation_delta > 0) labels.push(`Foundation +${events.foundation_delta}`);
    if (events.foundation_delta < 0) labels.push(`Foundation ${events.foundation_delta}`);
  }
  if (frame.decision_latency_ms != null) {
    labels.push(frame.forced
      ? `规则唯一动作 · ${frame.decision_latency_ms.toFixed(2)} ms`
      : frame.policy_forced
        ? `记忆层唯一未尝试动作 · ${frame.decision_latency_ms.toFixed(2)} ms`
        : `Jev 决策 ${frame.decision_latency_ms.toFixed(1)} ms`);
  }
  const history = phasePublicHistory(frame, phase);
  if ((history.visible_state_visit_count || 1) > 1) {
    labels.push(`第 ${history.visible_state_visit_count} 次到达此局面`);
  }
  const attemptCounts = history.action_attempt_counts || {};
  const totalAttempts = Object.values(attemptCounts).reduce((sum, count) => sum + Number(count), 0);
  const distinctAttempts = Object.keys(attemptCounts).length
    || (history.actions_tried_from_visible_state || []).length;
  if (totalAttempts) {
    labels.push(`此局面已尝试 ${totalAttempts} 次 · ${distinctAttempts} 种动作`);
  } else if (distinctAttempts) {
    labels.push(`此前已试 ${distinctAttempts} 种动作`);
  }
  if ((history.steps_since_new_visible_state || 0) > 0) {
    labels.push(`连续 ${history.steps_since_new_visible_state} 步未见新可见局面`);
  }
  if (!labels.length && frame.step > 0) {
    labels.push(phase === "before" ? "等待执行" : "无结构事件");
  }
  for (const text of labels) {
    const chip = document.createElement("span");
    chip.className = "event-chip";
    chip.textContent = text;
    ui["event-chips"].append(chip);
  }
}

function renderTermination(frame, run, isLast, phase) {
  const show = isLast && phase === "after";
  ui["termination-notice"].hidden = !show;
  if (!show) return;

  const reason = run.termination_reason;
  const stagnationSteps = run.stagnation_steps ?? 50;
  const actions = phaseLegalActions(frame, phase);
  const tried = new Set(phasePublicHistory(frame, phase).actions_tried_from_visible_state || []);
  const untried = actions.filter((action) => !tried.has(action));
  const remaining = actions.length
    ? `停止时仍有 ${actions.length} 个合法动作，其中 ${untried.length} 个在该可见局面尚未尝试。`
    : "停止时没有合法动作。";
  const copy = {
    win: "52 张牌已全部进入 Foundation。",
    hard_dead_end: "规则层面已无合法动作。",
    cycle_stagnation: `连续 ${stagnationSteps} 次状态转移都未访问新状态，运行器在进入此局面后截停，没有再向 Jev 请求下一次决策。${remaining}这不表示牌局本身无解。`,
    turn_cap: `达到运行步数上限，运行器在进入此局面后截停。${remaining}`,
    agent_error: "Agent 或 API 出错，运行在此处中断。",
  };
  const title = {
    win: "游戏完成",
    hard_dead_end: "硬死局",
    cycle_stagnation: "循环停滞：并非无动作",
    turn_cap: "达到步数上限",
    agent_error: "运行异常中断",
  };
  ui["termination-title"].textContent = title[reason] || "运行结束";
  ui["termination-copy"].textContent = copy[reason] || reason;
  ui["termination-notice"].dataset.reason = reason;
}

function render() {
  if (!replay) return;
  const frame = replay.frames[frameIndex];
  const run = replay.run;
  const last = replay.frames.length - 1;
  const state = framePhase === "after" ? frame.state_after : frame.state_before;
  renderBoard(state);
  renderProbabilities(frame);
  const candidateCount = frame.decision_metadata?.candidate_count
    ?? phaseLegalActions(frame, "before").length;
  ui["candidate-count"].textContent = `${candidateCount} candidates`;
  renderLegalActions(frame, framePhase);
  renderEvents(frame, framePhase);
  renderTermination(frame, run, frameIndex === last, framePhase);

  ui["run-title"].textContent = `${replay.game.name} ${replay.game.variant}`;
  ui["agent-badge"].textContent = run.agent.toUpperCase();
  ui["seed-badge"].textContent = `seed ${run.seed}`;
  const termination = run.termination_reason;
  ui["result-badge"].textContent = run.win ? "WIN" : termination.replaceAll("_", " ").toUpperCase();
  ui["result-badge"].className = `badge ${run.win ? "win" : "loss"}`;
  ui.action.textContent = frame.action || "初始牌局";
  ui["state-phase"].textContent = framePhase === "after" ? "执行后" : "执行前";
  ui["state-phase"].setAttribute("aria-pressed", String(framePhase === "after"));
  ui["state-phase"].disabled = !frame.action;
  ui["confidence-ring"].textContent = frame.confidence == null ? "—" : `${Math.round(frame.confidence * 100)}%`;
  ui["confidence-ring"].style.borderColor = frame.confidence == null
    ? "rgba(200,243,106,.22)"
    : `rgba(200,243,106,${0.25 + frame.confidence * 0.7})`;

  const foundation = countFoundation(state);
  const hidden = state.tableau.flat().filter((card) => card === "XX").length;
  const progress = phaseProgress(frame, framePhase);
  ui["foundation-metric"].textContent = `${foundation} / 52`;
  ui["stock-metric"].textContent = String(state.stock_count);
  ui["hidden-metric"].textContent = String(hidden);
  ui["states-metric"].textContent = frameIndex === last
    ? String(run.unique_states_visited ?? "—")
    : "live";
  ui["foundation-peak-metric"].textContent = String(progress.max_foundation_cards_seen ?? foundation);
  ui["reveal-age-metric"].textContent = String(progress.steps_since_hidden_reveal ?? "—");
  ui["foundation-age-metric"].textContent = String(progress.steps_since_foundation_increase ?? "—");
  ui["stock-pass-metric"].textContent = String(progress.stock_passes_since_structural_progress ?? "—");

  ui.timeline.max = String(last);
  ui.timeline.value = String(frameIndex);
  const phaseLabel = frame.action ? (framePhase === "after" ? "执行后" : "执行前") : "初始";
  ui["step-label"].textContent = `STEP ${frame.step} / ${last} · ${phaseLabel}`;
  ui["progress-label"].textContent = `${Math.round((frameIndex / Math.max(1, last)) * 100)}%`;
  ui.previous.disabled = frameIndex === 0 && framePhase === "before";
  ui.next.disabled = frameIndex === last && (framePhase === "after" || !frame.action);
  ui.play.disabled = last === 0;
}

function migrateReplayV1(data) {
  const frames = data.frames.map((frame, index) => {
    const previous = data.frames[Math.max(0, index - 1)];
    return {
      ...frame,
      state_before: index === 0 ? frame.state : previous.state,
      state_after: frame.state,
      legal_actions: index === 0 ? frame.legal_actions : previous.legal_actions,
      legal_actions_before: index === 0 ? frame.legal_actions : previous.legal_actions,
      legal_actions_after: frame.legal_actions || [],
      public_history: frame.public_history || {},
      public_history_before: frame.public_history || {},
      public_history_after: frame.public_history || {},
      progress: frame.progress || {},
      progress_before: frame.progress || {},
      progress_after: frame.progress || {},
      policy_forced: false,
    };
  });
  return { ...data, schema_version: 2, frames };
}

function validateReplay(data) {
  if (data?.schema_version === 1) data = migrateReplayV1(data);
  if (!data || data.schema_version !== 2 || !Array.isArray(data.frames) || !data.frames.length) {
    throw new Error("不支持的 replay 格式：需要 schema_version=2 和非空 frames");
  }
  for (const frame of data.frames) {
    if (!frame.state_before?.foundation || !Array.isArray(frame.state_before?.tableau)
        || !frame.state_after?.foundation || !Array.isArray(frame.state_after?.tableau)) {
      throw new Error(`step ${frame.step ?? "?"} 缺少执行前或执行后的可见牌局状态`);
    }
  }
  return data;
}

function loadReplay(data, source = "replay.json") {
  stopPlayback();
  replay = validateReplay(data);
  framePhase = "before";
  ui["summary-panel"].hidden = true;
  document.querySelector(".app-shell").hidden = false;
  const requestedStep = Number(new URLSearchParams(location.search).get("step") || 0);
  frameIndex = Number.isFinite(requestedStep)
    ? Math.min(Math.max(0, requestedStep), replay.frames.length - 1)
    : 0;
  ui["load-status"].textContent = `${source} · ${replay.frames.length} frames`;
  ui["load-status"].classList.add("ready");
  render();
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    const next = text[index + 1];
    if (char === '"') {
      if (quoted && next === '"') {
        field += '"';
        index += 1;
      } else {
        quoted = !quoted;
      }
    } else if (char === "," && !quoted) {
      row.push(field);
      field = "";
    } else if ((char === "\n" || char === "\r") && !quoted) {
      if (char === "\r" && next === "\n") index += 1;
      row.push(field);
      if (row.some((value) => value !== "")) rows.push(row);
      row = [];
      field = "";
    } else {
      field += char;
    }
  }
  if (field !== "" || row.length) {
    row.push(field);
    if (row.some((value) => value !== "")) rows.push(row);
  }
  if (rows.length < 2) throw new Error("CSV 没有可展示的数据行");
  const headers = rows[0].map((header) => header.trim());
  return rows.slice(1).map((values) => Object.fromEntries(
    headers.map((header, index) => [header, (values[index] || "").trim()])
  ));
}

function mean(rows, key) {
  const values = rows
    .map((row) => row[key])
    .filter((value) => value != null && value !== "")
    .map(Number)
    .filter(Number.isFinite);
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : "";
}

function aggregateRuns(rows) {
  const groups = new Map();
  for (const row of rows) {
    const agent = row.agent || "unknown";
    if (!groups.has(agent)) groups.set(agent, []);
    groups.get(agent).push(row);
  }
  return [...groups].map(([agent, games]) => {
    const completed = games.filter((game) => game.termination_reason !== "agent_error");
    const wins = completed.filter((game) => String(game.win).toLowerCase() === "true").length;
    const timed = completed.reduce((sum, game) => sum + Number(game.timed_decisions || 0), 0);
    const latency = completed.reduce((sum, game) => sum + Number(game.decision_latency_ms_total || 0), 0);
    const choices = completed.reduce((sum, game) => sum + Number(game.choice_decisions || 0), 0);
    const draws = completed.reduce((sum, game) => sum + Number(game.draw_choices || 0), 0);
    const recycles = completed.reduce((sum, game) => sum + Number(game.recycle_choices || 0), 0);
    return {
      agent,
      games: games.length,
      completed_games: completed.length,
      wins,
      win_rate: completed.length ? wins / completed.length : 0,
      mean_foundation_cards: mean(completed, "foundation_cards"),
      mean_max_foundation_cards_seen: mean(completed, "max_foundation_cards_seen"),
      mean_hidden_cards_revealed: mean(completed, "hidden_cards_revealed"),
      mean_steps: mean(completed, "steps"),
      cycle_stagnation_rate: completed.length
        ? completed.filter((game) => game.termination_reason === "cycle_stagnation").length / completed.length
        : 0,
      mean_revisit_rate: mean(completed, "revisit_rate"),
      draw_rate: choices ? draws / choices : 0,
      recycle_rate: choices ? recycles / choices : 0,
      mean_decision_latency_ms: timed ? latency / timed : "",
      mean_game_p95_decision_latency_ms: mean(completed, "decision_latency_ms_p95"),
      agent_errors: games.length - completed.length,
    };
  });
}

function normalizeCsv(rows) {
  const headers = new Set(Object.keys(rows[0] || {}));
  if (["agent", "games", "win_rate"].every((key) => headers.has(key))) {
    return { kind: "summary.csv", rows };
  }
  if (["seed", "agent", "termination_reason"].every((key) => headers.has(key))) {
    return { kind: "runs.csv", rows: aggregateRuns(rows) };
  }
  throw new Error("无法识别 CSV：请选择 benchmark 生成的 summary.csv 或 runs.csv");
}

function displaySummaryValue(key, value) {
  if (value == null || value === "") return "—";
  if (key === "agent") return String(value).toUpperCase();
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  if (key.includes("rate")) return `${(number * 100).toFixed(1)}%`;
  if (key.includes("latency")) return `${number.toFixed(1)} ms`;
  return Number.isInteger(number) ? String(number) : number.toFixed(2);
}

function makeSummaryMetric(label, value) {
  const metric = document.createElement("div");
  metric.className = "summary-metric";
  const name = document.createElement("span");
  name.className = "summary-metric-label";
  name.textContent = label;
  const number = document.createElement("strong");
  number.textContent = value;
  metric.append(name, number);
  return metric;
}

function renderSummary(rows, source = "summary.csv", kind = "summary.csv") {
  if (!rows.length) throw new Error("CSV 没有 Agent 数据");
  stopPlayback();
  ui["summary-panel"].hidden = false;
  document.querySelector(".app-shell").hidden = true;
  ui["load-status"].textContent = `${source} · ${rows.length} agents`;
  ui["load-status"].classList.add("ready");
  ui["summary-description"].textContent = kind === "runs.csv"
    ? "已从逐局 runs.csv 在浏览器内生成 Agent 汇总。"
    : "配对评测汇总；百分比和延迟直接来自 runner 输出。";
  ui["summary-row-count"].textContent = `${rows.length} agents`;

  ui["summary-cards"].replaceChildren();
  for (const row of rows) {
    const card = document.createElement("article");
    card.className = "summary-agent-card";
    const heading = document.createElement("div");
    heading.className = "summary-agent-heading";
    const title = document.createElement("h2");
    title.textContent = String(row.agent || "unknown").toUpperCase();
    const status = document.createElement("span");
    status.className = `summary-result ${Number(row.wins || 0) > 0 ? "positive" : ""}`;
    status.textContent = `${row.wins || 0} wins`;
    heading.append(title, status);
    const rate = Number(row.win_rate || 0);
    const bar = document.createElement("div");
    bar.className = "summary-win-bar";
    const fill = document.createElement("div");
    fill.style.width = `${Math.max(0, Math.min(100, rate * 100))}%`;
    bar.append(fill);
    const metrics = document.createElement("div");
    metrics.className = "summary-metrics-grid";
    metrics.append(
      makeSummaryMetric("Win rate", displaySummaryValue("win_rate", row.win_rate)),
      makeSummaryMetric("Foundation", displaySummaryValue("mean_foundation_cards", row.mean_foundation_cards)),
      makeSummaryMetric("Steps", displaySummaryValue("mean_steps", row.mean_steps)),
      makeSummaryMetric("Cycle rate", displaySummaryValue("cycle_stagnation_rate", row.cycle_stagnation_rate)),
      makeSummaryMetric("DRAW rate", displaySummaryValue("draw_rate", row.draw_rate)),
      makeSummaryMetric("RECYCLE rate", displaySummaryValue("recycle_rate", row.recycle_rate)),
      makeSummaryMetric("Mean latency", displaySummaryValue("mean_decision_latency_ms", row.mean_decision_latency_ms)),
      makeSummaryMetric("Errors", displaySummaryValue("agent_errors", row.agent_errors)),
    );
    card.append(heading, bar, metrics);
    ui["summary-cards"].append(card);
  }

  const head = ui["summary-table"].querySelector("thead");
  const body = ui["summary-table"].querySelector("tbody");
  head.replaceChildren();
  body.replaceChildren();
  const headerRow = document.createElement("tr");
  for (const [, label] of SUMMARY_COLUMNS) {
    const cell = document.createElement("th");
    cell.textContent = label;
    headerRow.append(cell);
  }
  head.append(headerRow);
  for (const row of rows) {
    const tableRow = document.createElement("tr");
    for (const [key] of SUMMARY_COLUMNS) {
      const cell = document.createElement("td");
      cell.textContent = displaySummaryValue(key, row[key]);
      tableRow.append(cell);
    }
    body.append(tableRow);
  }
}

async function loadSummaryFile(file) {
  try {
    const normalized = normalizeCsv(parseCsv(await readFileText(file)));
    renderSummary(normalized.rows, file.name, normalized.kind);
  } catch (error) {
    ui["load-status"].textContent = error.message;
    ui["load-status"].classList.remove("ready");
  }
}

function readFileText(file) {
  if (typeof file.text === "function") return file.text();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("无法读取文件"));
    reader.readAsText(file);
  });
}

async function loadFile(file) {
  try {
    if (file.name.toLowerCase().endsWith(".jsonl")) {
      throw new Error("JSONL 是原始日志，不能直接播放；请打开 results/.../replays/ 中的 replay JSON");
    }
    loadReplay(JSON.parse(await readFileText(file)), file.name);
  } catch (error) {
    ui["load-status"].textContent = error.message;
    ui["load-status"].classList.remove("ready");
  }
}

function stopPlayback() {
  if (timer) window.clearInterval(timer);
  timer = null;
  ui.play.innerHTML = "▶ <span>播放</span>";
}

function togglePlayback() {
  if (!replay) return;
  if (timer) return stopPlayback();
  if (frameIndex >= replay.frames.length - 1 && framePhase === "after") {
    frameIndex = 0;
    framePhase = "before";
  }
  ui.play.innerHTML = "Ⅱ <span>暂停</span>";
  timer = window.setInterval(() => {
    const frame = replay.frames[frameIndex];
    if (frame.action && framePhase === "before") {
      framePhase = "after";
    } else if (frameIndex < replay.frames.length - 1) {
      frameIndex += 1;
      framePhase = "before";
    } else {
      return stopPlayback();
    }
    render();
  }, Math.max(100, Number(ui.speed.value) / 2));
  render();
}

function previousPhase() {
  stopPlayback();
  if (framePhase === "after") {
    framePhase = "before";
  } else if (frameIndex > 0) {
    frameIndex -= 1;
    framePhase = replay.frames[frameIndex].action ? "after" : "before";
  }
  render();
}

function nextPhase() {
  if (!replay) return;
  stopPlayback();
  const frame = replay.frames[frameIndex];
  if (frame.action && framePhase === "before") {
    framePhase = "after";
  } else if (frameIndex < replay.frames.length - 1) {
    frameIndex += 1;
    framePhase = "before";
  }
  render();
}

ui["replay-file"].addEventListener("change", (event) => {
  const [file] = event.target.files;
  if (file) loadFile(file);
  event.target.value = "";
});
ui["summary-file"].addEventListener("change", (event) => {
  const [file] = event.target.files;
  if (file) loadSummaryFile(file);
  event.target.value = "";
});
ui["back-to-replay"].addEventListener("click", () => {
  if (!replay) {
    window.location.href = window.location.pathname;
    return;
  }
  ui["summary-panel"].hidden = true;
  document.querySelector(".app-shell").hidden = false;
  ui["load-status"].textContent = "Replay 已载入";
});
ui.previous.addEventListener("click", previousPhase);
ui.next.addEventListener("click", nextPhase);
ui.play.addEventListener("click", togglePlayback);
ui.timeline.addEventListener("input", () => { stopPlayback(); frameIndex = Number(ui.timeline.value); framePhase = "before"; render(); });
ui.speed.addEventListener("change", () => { if (timer) { stopPlayback(); togglePlayback(); } });
ui["state-phase"].addEventListener("click", () => {
  if (!replay?.frames[frameIndex]?.action) return;
  stopPlayback();
  framePhase = framePhase === "before" ? "after" : "before";
  render();
});
ui["legal-toggle"].addEventListener("click", () => {
  const expanded = ui["legal-toggle"].getAttribute("aria-expanded") === "true";
  ui["legal-toggle"].setAttribute("aria-expanded", String(!expanded));
  ui["legal-actions"].hidden = expanded;
});

document.addEventListener("keydown", (event) => {
  if (!replay || event.target.matches("input, select")) return;
  if (event.code === "Space") { event.preventDefault(); togglePlayback(); }
  if (event.key === "ArrowLeft") previousPhase();
  if (event.key === "ArrowRight") nextPhase();
});

for (const eventName of ["dragenter", "dragover"]) {
  document.addEventListener(eventName, (event) => { event.preventDefault(); ui["drop-overlay"].hidden = false; });
}
document.addEventListener("dragleave", (event) => {
  if (event.relatedTarget === null) ui["drop-overlay"].hidden = true;
});
document.addEventListener("drop", (event) => {
  event.preventDefault();
  ui["drop-overlay"].hidden = true;
  const [file] = event.dataTransfer.files;
  if (!file) return;
  if (file.name.toLowerCase().endsWith(".csv")) loadSummaryFile(file);
  else loadFile(file);
});

async function loadDefault() {
  const params = new URLSearchParams(location.search);
  const summarySource = params.get("summary");
  if (summarySource) {
    try {
      const response = await fetch(summarySource);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const normalized = normalizeCsv(parseCsv(await response.text()));
      renderSummary(normalized.rows, summarySource, normalized.kind);
    } catch (error) {
      ui["load-status"].textContent = `无法加载 summary.csv：${error.message}`;
    }
    return;
  }
  const source = params.get("replay") || "replay.example.json";
  try {
    const response = await fetch(source);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    loadReplay(await response.json(), source);
  } catch {
    ui["load-status"].textContent = "打开 replay.json 开始";
  }
}

loadDefault();
