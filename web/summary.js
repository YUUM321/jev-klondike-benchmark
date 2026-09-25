"use strict";

const ui = typeof document === "undefined" ? null : {
  file: document.getElementById("summary-file"),
  status: document.getElementById("summary-status"),
  description: document.getElementById("summary-description"),
  cards: document.getElementById("summary-cards"),
  rowCount: document.getElementById("summary-row-count"),
  table: document.getElementById("summary-table"),
};

const COLUMNS = [
  ["agent", "Agent"], ["games", "Games"], ["wins", "Wins"],
  ["win_rate", "Win rate"], ["mean_foundation_cards", "Foundation"],
  ["mean_max_foundation_cards_seen", "Foundation peak"],
  ["mean_hidden_cards_revealed", "Hidden revealed"], ["mean_steps", "Steps"],
  ["cycle_stagnation_rate", "Cycle rate"], ["mean_revisit_rate", "Revisit rate"],
  ["draw_rate", "DRAW rate"], ["recycle_rate", "RECYCLE rate"],
  ["mean_decision_latency_ms", "Mean latency"],
  ["mean_game_p95_decision_latency_ms", "P95 latency"], ["agent_errors", "Errors"],
];

function parseCsv(text) {
  const rows = [];
  let row = [], field = "", quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index], next = text[index + 1];
    if (char === '"') {
      if (quoted && next === '"') { field += '"'; index += 1; }
      else quoted = !quoted;
    } else if (char === "," && !quoted) { row.push(field); field = ""; }
    else if ((char === "\n" || char === "\r") && !quoted) {
      if (char === "\r" && next === "\n") index += 1;
      row.push(field);
      if (row.some((value) => value !== "")) rows.push(row);
      row = []; field = "";
    } else field += char;
  }
  if (field !== "" || row.length) { row.push(field); if (row.some((value) => value !== "")) rows.push(row); }
  if (rows.length < 2) throw new Error("CSV 没有可展示的数据行");
  const headers = rows[0].map((header) => header.trim());
  return rows.slice(1).map((values) => Object.fromEntries(
    headers.map((header, index) => [header, (values[index] || "").trim()])
  ));
}

function readFileText(file) {
  if (typeof file.text === "function") return file.text();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("无法读取 CSV 文件"));
    reader.readAsText(file);
  });
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
      agent, games: games.length, wins,
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

function displayValue(key, value) {
  if (value == null || value === "") return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  if (key.includes("rate")) return `${(number * 100).toFixed(1)}%`;
  if (key.includes("latency")) return `${number.toFixed(1)} ms`;
  return Number.isInteger(number) ? String(number) : number.toFixed(2);
}

function metric(label, value) {
  const item = document.createElement("div"); item.className = "summary-metric";
  const name = document.createElement("span"); name.className = "summary-metric-label"; name.textContent = label;
  const number = document.createElement("strong"); number.textContent = value;
  item.append(name, number); return item;
}

function render(rows, source, kind) {
  if (!rows.length) throw new Error("CSV 没有 Agent 数据");
  ui.status.textContent = `${source} · ${rows.length} agents`;
  ui.status.classList.add("ready");
  ui.description.textContent = kind === "runs.csv"
    ? "已从逐局 runs.csv 在浏览器内生成汇总；数据不会上传。"
    : "汇总数据在浏览器本地读取，不会上传。";
  ui.rowCount.textContent = `${rows.length} agents`;
  ui.cards.replaceChildren();
  for (const row of rows) {
    const card = document.createElement("article"); card.className = "summary-agent-card";
    const heading = document.createElement("div"); heading.className = "summary-agent-heading";
    const title = document.createElement("h2"); title.textContent = String(row.agent || "unknown").toUpperCase();
    const result = document.createElement("span"); result.className = `summary-result ${Number(row.wins || 0) > 0 ? "positive" : ""}`; result.textContent = `${row.wins || 0} wins`;
    heading.append(title, result);
    const bar = document.createElement("div"); bar.className = "summary-win-bar";
    const fill = document.createElement("div"); fill.style.width = `${Math.max(0, Math.min(100, Number(row.win_rate || 0) * 100))}%`; bar.append(fill);
    const metrics = document.createElement("div"); metrics.className = "summary-metrics-grid";
    metrics.append(
      metric("Win rate", displayValue("win_rate", row.win_rate)),
      metric("Foundation", displayValue("mean_foundation_cards", row.mean_foundation_cards)),
      metric("Steps", displayValue("mean_steps", row.mean_steps)),
      metric("Cycle rate", displayValue("cycle_stagnation_rate", row.cycle_stagnation_rate)),
      metric("DRAW rate", displayValue("draw_rate", row.draw_rate)),
      metric("RECYCLE rate", displayValue("recycle_rate", row.recycle_rate)),
      metric("Mean latency", displayValue("mean_decision_latency_ms", row.mean_decision_latency_ms)),
      metric("Errors", displayValue("agent_errors", row.agent_errors)),
    );
    card.append(heading, bar, metrics); ui.cards.append(card);
  }
  const head = ui.table.querySelector("thead"), body = ui.table.querySelector("tbody");
  head.replaceChildren(); body.replaceChildren();
  const header = document.createElement("tr");
  for (const [, label] of COLUMNS) { const cell = document.createElement("th"); cell.textContent = label; header.append(cell); }
  head.append(header);
  for (const row of rows) {
    const tableRow = document.createElement("tr");
    for (const [key] of COLUMNS) {
      const cell = document.createElement("td");
      cell.textContent = key === "agent" ? String(row[key] || "unknown").toUpperCase() : displayValue(key, row[key]);
      tableRow.append(cell);
    }
    body.append(tableRow);
  }
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { parseCsv, normalizeCsv };
}

if (ui) ui.file.addEventListener("change", async (event) => {
  const [file] = event.target.files; event.target.value = "";
  if (!file) return;
  try {
    const normalized = normalizeCsv(parseCsv(await readFileText(file)));
    render(normalized.rows, file.name, normalized.kind);
  }
  catch (error) { ui.status.textContent = error.message; ui.status.classList.remove("ready"); }
});
