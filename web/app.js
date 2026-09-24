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
    "states-metric", "legal-toggle", "legal-count", "legal-actions", "drop-overlay"
  ].map((id) => [id, document.getElementById(id)])
);

let replay = null;
let frameIndex = 0;
let timer = null;

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
  renderPileSlot(ui.waste, state.waste);

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

function renderLegalActions(frame) {
  const actions = frame.legal_actions || [];
  ui["legal-count"].textContent = String(actions.length);
  ui["candidate-count"].textContent = `${actions.length} candidates`;
  ui["legal-actions"].replaceChildren();
  for (const action of actions) {
    const item = document.createElement("li");
    item.textContent = action;
    ui["legal-actions"].append(item);
  }
}

function renderEvents(frame) {
  ui["event-chips"].replaceChildren();
  const events = frame.events || {};
  const labels = [];
  if (events.hidden_revealed > 0) labels.push(`翻开 ${events.hidden_revealed} 张暗牌`);
  if (events.foundation_delta > 0) labels.push(`Foundation +${events.foundation_delta}`);
  if (events.foundation_delta < 0) labels.push(`Foundation ${events.foundation_delta}`);
  if (!labels.length && frame.step > 0) labels.push("无结构事件");
  for (const text of labels) {
    const chip = document.createElement("span");
    chip.className = "event-chip";
    chip.textContent = text;
    ui["event-chips"].append(chip);
  }
}

function render() {
  if (!replay) return;
  const frame = replay.frames[frameIndex];
  const run = replay.run;
  const last = replay.frames.length - 1;
  renderBoard(frame.state);
  renderProbabilities(frame);
  renderLegalActions(frame);
  renderEvents(frame);

  ui["run-title"].textContent = `${replay.game.name} ${replay.game.variant}`;
  ui["agent-badge"].textContent = run.agent.toUpperCase();
  ui["seed-badge"].textContent = `seed ${run.seed}`;
  ui["result-badge"].textContent = run.win ? "WIN" : run.stop_reason.replaceAll("_", " ").toUpperCase();
  ui["result-badge"].className = `badge ${run.win ? "win" : "loss"}`;
  ui.action.textContent = frame.action || "初始牌局";
  ui["confidence-ring"].textContent = frame.confidence == null ? "—" : `${Math.round(frame.confidence * 100)}%`;
  ui["confidence-ring"].style.borderColor = frame.confidence == null
    ? "rgba(200,243,106,.22)"
    : `rgba(200,243,106,${0.25 + frame.confidence * 0.7})`;

  const foundation = countFoundation(frame.state);
  const hidden = frame.state.tableau.flat().filter((card) => card === "XX").length;
  ui["foundation-metric"].textContent = `${foundation} / 52`;
  ui["stock-metric"].textContent = String(frame.state.stock_count);
  ui["hidden-metric"].textContent = String(hidden);
  ui["states-metric"].textContent = frameIndex === last ? String(run.unique_states ?? "—") : "live";

  ui.timeline.max = String(last);
  ui.timeline.value = String(frameIndex);
  ui["step-label"].textContent = `STEP ${frame.step} / ${last}`;
  ui["progress-label"].textContent = `${Math.round((frameIndex / Math.max(1, last)) * 100)}%`;
  ui.previous.disabled = frameIndex === 0;
  ui.next.disabled = frameIndex === last;
  ui.play.disabled = last === 0;
}

function validateReplay(data) {
  if (!data || data.schema_version !== 1 || !Array.isArray(data.frames) || !data.frames.length) {
    throw new Error("不支持的 replay 格式：需要 schema_version=1 和非空 frames");
  }
  for (const frame of data.frames) {
    if (!frame.state?.foundation || !Array.isArray(frame.state?.tableau)) {
      throw new Error(`step ${frame.step ?? "?"} 缺少可见牌局状态`);
    }
  }
  return data;
}

function loadReplay(data, source = "replay.json") {
  stopPlayback();
  replay = validateReplay(data);
  const requestedStep = Number(new URLSearchParams(location.search).get("step") || 0);
  frameIndex = Number.isFinite(requestedStep)
    ? Math.min(Math.max(0, requestedStep), replay.frames.length - 1)
    : 0;
  ui["load-status"].textContent = `${source} · ${replay.frames.length} frames`;
  ui["load-status"].classList.add("ready");
  render();
}

async function loadFile(file) {
  try {
    loadReplay(JSON.parse(await file.text()), file.name);
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
  if (frameIndex >= replay.frames.length - 1) frameIndex = 0;
  ui.play.innerHTML = "Ⅱ <span>暂停</span>";
  timer = window.setInterval(() => {
    if (frameIndex >= replay.frames.length - 1) return stopPlayback();
    frameIndex += 1;
    render();
  }, Number(ui.speed.value));
  render();
}

ui["replay-file"].addEventListener("change", (event) => {
  const [file] = event.target.files;
  if (file) loadFile(file);
});
ui.previous.addEventListener("click", () => { stopPlayback(); frameIndex = Math.max(0, frameIndex - 1); render(); });
ui.next.addEventListener("click", () => { if (!replay) return; stopPlayback(); frameIndex = Math.min(replay.frames.length - 1, frameIndex + 1); render(); });
ui.play.addEventListener("click", togglePlayback);
ui.timeline.addEventListener("input", () => { stopPlayback(); frameIndex = Number(ui.timeline.value); render(); });
ui.speed.addEventListener("change", () => { if (timer) { stopPlayback(); togglePlayback(); } });
ui["legal-toggle"].addEventListener("click", () => {
  const expanded = ui["legal-toggle"].getAttribute("aria-expanded") === "true";
  ui["legal-toggle"].setAttribute("aria-expanded", String(!expanded));
  ui["legal-actions"].hidden = expanded;
});

document.addEventListener("keydown", (event) => {
  if (!replay || event.target.matches("input, select")) return;
  if (event.code === "Space") { event.preventDefault(); togglePlayback(); }
  if (event.key === "ArrowLeft") { stopPlayback(); frameIndex = Math.max(0, frameIndex - 1); render(); }
  if (event.key === "ArrowRight") { stopPlayback(); frameIndex = Math.min(replay.frames.length - 1, frameIndex + 1); render(); }
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
  if (file) loadFile(file);
});

async function loadDefault() {
  const source = new URLSearchParams(location.search).get("replay") || "replay.example.json";
  try {
    const response = await fetch(source);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    loadReplay(await response.json(), source);
  } catch {
    ui["load-status"].textContent = "打开 replay.json 开始";
  }
}

loadDefault();
