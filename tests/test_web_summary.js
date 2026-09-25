"use strict";

const assert = require("node:assert/strict");
const { normalizeCsv, parseCsv } = require("../web/summary.js");

const csv = [
  "seed,agent,win,termination_reason,foundation_cards,max_foundation_cards_seen,hidden_cards_revealed,steps,revisit_rate,timed_decisions,decision_latency_ms_total,decision_latency_ms_p95,choice_decisions,draw_choices,recycle_choices",
  "0,jev_progress,false,cycle_stagnation,8,11,9,90,0.5,80,2400,45,75,30,6",
  "1,jev_progress,true,win,52,52,21,140,0.2,120,3600,50,110,22,3",
].join("\n");

const normalized = normalizeCsv(parseCsv(csv));
assert.equal(normalized.kind, "runs.csv");
assert.equal(normalized.rows.length, 1);

const [summary] = normalized.rows;
assert.equal(summary.agent, "jev_progress");
assert.equal(summary.mean_max_foundation_cards_seen, 31.5);
assert.equal(summary.draw_rate, 52 / 185);
assert.equal(summary.recycle_rate, 9 / 185);
assert.equal(summary.mean_decision_latency_ms, 30);

console.log("web summary aggregation contract: PASS");
