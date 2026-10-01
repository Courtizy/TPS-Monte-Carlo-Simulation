"use strict";
/* Turn Pattern Sustainability, proof of concept.
   The page edits a config, sends it to Python workers (worker.js), and shows
   the run record that comes back. Run history is kept in this browser only. */

const HISTORY_KEY = "tps.history.v1";
const HISTORY_LIMIT = 25;
const RATE_IDS = ["mc_rate", "break_rate", "ground_abort_rate"];
const GO_NAMES = ["first_go", "second_go", "third_go", "fourth_go"];
const LEGACY_FIX = [["fix_8hr_rate", 8], ["fix_12hr_rate", 12], ["fix_24hr_rate", 24]];
const COVERAGE = [
  [0, "No duty"], [8, "One 8-hour shift"], [12, "One 12-hour shift"],
  [16, "Two 8-hour shifts"], [24, "Around the clock"],
];
const COMPONENT_NAMES = {
  every_day_flown: "Every day's planned sorties flown",
  meets_required_sorties: "Required weekly sorties met",
  aircraft_ready_every_day: "Front-line aircraft ready every day",
  plan_within_commit: "Plan within commit every day",
  next_monday_recovery: "Enough aircraft ready next Monday",
  backlog_within_limit: "Repair backlog within limit",
};
const FAILURE_NAMES = {
  "Daily Schedule Miss": "A day's planned sorties not all flown",
  "Full Schedule Not Flown": "Full schedule not flown",
  "Sortie Shortfall": "Weekly required sorties missed",
  "Aircraft Availability": "Not enough aircraft ready for a day",
  "TTP Commit": "Plan above commit",
  "Recovery": "Too few aircraft ready next Monday",
  "Repair Backlog": "Repair backlog above limit",
};

const $ = (id) => document.getElementById(id);

/* ------------------------------------------------------------ DOM helper
   Builds elements with textContent only, so text from files is never parsed as HTML. */
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

/* ------------------------------------------------------------ workers */
class PythonWorker {
  constructor() {
    this.worker = new Worker("worker.js");
    this.pending = new Map();
    this.next = 1;
    this.worker.onmessage = (event) => {
      const { id, ok, result, error } = event.data;
      const job = this.pending.get(id);
      if (!job) return;
      this.pending.delete(id);
      ok ? job.resolve(result) : job.reject(new Error(error));
    };
    this.worker.onerror = (event) => {
      for (const job of this.pending.values()) job.reject(new Error(event.message || "The model worker stopped."));
      this.pending.clear();
    };
  }
  request(type, payload = {}) {
    const id = this.next++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.worker.postMessage({ id, type, payload });
    });
  }
}

const main = new PythonWorker();
const pool = [main];
let busy = false;

function poolSize() {
  const cores = navigator.hardwareConcurrency || 2;
  return Math.min(4, Math.max(1, cores - 1));
}

/* ------------------------------------------------------------ number helpers */
const toPct = (share) => (share === undefined || share === null ? "" : Math.round(share * 1000) / 10);
const fromPct = (text) => Number((Number(text) / 100).toFixed(4));
const pctText = (share, digits = 0) => `${(share * 100).toFixed(digits)}%`;
const one = (value) => (Math.round(value * 10) / 10).toFixed(1);
const whole = (value) => Number(value).toLocaleString("en-US");

/* ------------------------------------------------------------ state */
let config = null;
let lastRecord = null;

function flyingDays(cfg) {
  return (cfg.rules && cfg.rules.flying_days) || ["Mon", "Tue", "Wed", "Thu", "Fri"];
}

function autoSpares(first, spareRate) {
  return Math.max(0, Math.ceil(first * spareRate - 1e-9));
}

/* ------------------------------------------------------------ config <-> form */
function goProfile(cfg) {
  const options = cfg.options || {};
  if (options.go_profile) return { ...options.go_profile };
  const schedule = Object.values(cfg.schedule || {});
  const used = Math.max(1, ...schedule.map((p) => GO_NAMES.filter((n) => (p[n] || 0) > 0).length));
  if (options.go_times && options.go_times.length) {
    const t = options.go_times;
    return { goes_per_day: t.length, sortie_hours: t[0][1] - t[0][0], turn_hours: t.length > 1 ? t[1][0] - t[0][1] : 8 };
  }
  return { goes_per_day: used, sortie_hours: 2, turn_hours: 8 };
}

function goTimes(profile) {
  const times = [];
  let launch = 0;
  for (let g = 0; g < profile.goes_per_day; g++) {
    const land = launch + profile.sortie_hours;
    times.push([launch, land]);
    launch = land + profile.turn_hours;
  }
  return times;
}

const clock = (hours) => `${Math.floor(hours)}:${String(Math.round((hours % 1) * 60)).padStart(2, "0")}`;

function fixWindows(cfg) {
  const rates = cfg.rates || {};
  if (rates.fix_windows) return rates.fix_windows.map((w) => ({ ...w }));
  return LEGACY_FIX.filter(([key]) => key in rates).map(([key, hours]) => ({ hours, rate: rates[key] }));
}

function windowRow(win) {
  return el("tr", {},
    el("td", {}, el("input", { type: "number", min: 0.25, step: 0.25, inputmode: "decimal", "data-window": "hours", value: win.hours, "aria-label": "Fixed within, hours" })),
    el("td", {}, el("span", { class: "pct" }, el("input", { type: "number", min: 0, max: 100, step: 0.1, inputmode: "decimal", "data-window": "rate", value: toPct(win.rate), "aria-label": "Share fixed, percent" }), el("span", { text: "%" }))),
    el("td", {}, el("button", { type: "button", class: "link-button remove-window", text: "Remove" })),
  );
}

function buildGrid(cfg, goes) {
  const head = $("grid-head");
  head.replaceChildren(el("th", { scope: "col", text: "Day" }),
    ...Array.from({ length: goes }, (_, g) => el("th", { scope: "col", text: `Go ${g + 1}` })),
    el("th", { scope: "col", text: "Spares" }));
  const body = $("grid-body");
  body.replaceChildren();
  for (const day of flyingDays(cfg)) {
    const plan = (cfg.schedule && cfg.schedule[day]) || {};
    const input = (field, value, label) => el("input", {
      type: "number", min: 0, step: 1, inputmode: "numeric", "data-day": day, "data-field": field,
      value: value ?? "", "aria-label": `${day} ${label}`,
    });
    body.append(el("tr", {},
      el("th", { scope: "row", text: day }),
      GO_NAMES.slice(0, goes).map((name, g) => el("td", {}, input(name, plan[name] ?? 0, `go ${g + 1}`))),
      el("td", { class: "auto" }, input("spares", plan.spares ?? "", "spares")),
    ));
  }
}

function configToForm(cfg) {
  $("name").value = cfg.name || "";
  $("pai").value = cfg.inventory.pai;
  const profile = goProfile(cfg);
  $("goes_per_day").value = String(profile.goes_per_day);
  $("sortie_hours").value = profile.sortie_hours;
  $("turn_hours").value = profile.turn_hours;
  const sute = cfg.sute || {};
  $("sute_monthly").value = sute.monthly_sorties_per_aircraft ?? "";
  $("sute_days").value = sute.om_days ?? "";
  $("sute_ceiling").value = sute.surge_ceiling ?? "";
  const derived = !("required_sorties" in cfg) && Boolean(cfg.sute);
  $("required_from_sute").checked = derived;
  $("required").value = derived ? "" : (cfg.required_sorties ?? "");
  for (const id of RATE_IDS) $(id).value = toPct(cfg.rates[id]);
  $("window-body").replaceChildren(...fixWindows(cfg).map(windowRow));
  $("commit_rate").value = toPct(cfg.rules.commit_rate);
  $("spare_rate").value = toPct(cfg.rules.spare_rate);
  $("first_day_fix_hours").value = cfg.rules.first_day_fix_hours ?? 8;
  const options = cfg.options || {};
  $("event_mode").value = options.event_mode || "Fixed Count Random Placement";
  $("fix_mode").value = options.fix_mode || "Random";
  const weekend = options.weekend_coverage_hours || {};
  $("sat_hours").value = String(weekend.Sat ?? 24);
  $("sun_hours").value = String(weekend.Sun ?? 24);
  $("repeat_rate").value = toPct(options.repeat_rate ?? 0);
  $("recur_rate").value = toPct(options.recur_rate ?? 0);
  $("allow_2407_adds").checked = Boolean(options.allow_2407_adds);
  buildGrid(cfg, profile.goes_per_day);
  updateTotals();
  $("config-json").value = JSON.stringify(cfg, null, 2);
}

function numberOr(id, fallback) {
  const text = $(id).value.trim();
  return text === "" ? fallback : Number(text);
}

function formToConfig() {
  const cfg = structuredClone(config);
  cfg.name = $("name").value.trim();
  cfg.inventory = { ...cfg.inventory, pai: numberOr("pai", 0) };
  const goes = Number($("goes_per_day").value);

  cfg.options = cfg.options || {};
  delete cfg.options.go_times;
  cfg.options.go_profile = { goes_per_day: goes, sortie_hours: numberOr("sortie_hours", 0), turn_hours: numberOr("turn_hours", 0) };

  const monthly = numberOr("sute_monthly", null), days = numberOr("sute_days", null);
  if (monthly !== null && days !== null) {
    cfg.sute = { monthly_sorties_per_aircraft: monthly, om_days: days, surge_ceiling: numberOr("sute_ceiling", null) };
  } else {
    delete cfg.sute;
  }
  if ($("required_from_sute").checked && cfg.sute) delete cfg.required_sorties;
  else cfg.required_sorties = numberOr("required", 0);

  for (const id of RATE_IDS) cfg.rates[id] = fromPct($(id).value || 0);
  for (const [key] of LEGACY_FIX) delete cfg.rates[key];
  cfg.rates.fix_windows = [...$("window-body").querySelectorAll("tr")].map((row) => ({
    hours: Number(row.querySelector('[data-window="hours"]').value || 0),
    rate: fromPct(row.querySelector('[data-window="rate"]').value || 0),
  }));

  cfg.rules.commit_rate = fromPct($("commit_rate").value || 0);
  cfg.rules.spare_rate = fromPct($("spare_rate").value || 0);
  cfg.rules.first_day_fix_hours = numberOr("first_day_fix_hours", 8);

  cfg.options.event_mode = $("event_mode").value;
  cfg.options.fix_mode = $("fix_mode").value;
  cfg.options.weekend_coverage_hours = {
    ...(cfg.options.weekend_coverage_hours || {}),
    Sat: Number($("sat_hours").value), Sun: Number($("sun_hours").value),
  };
  cfg.options.repeat_rate = fromPct($("repeat_rate").value || 0);
  cfg.options.recur_rate = fromPct($("recur_rate").value || 0);
  cfg.options.allow_2407_adds = $("allow_2407_adds").checked;

  cfg.schedule = cfg.schedule || {};
  for (const day of flyingDays(cfg)) {
    const plan = { ...(cfg.schedule[day] || {}) };
    for (const name of GO_NAMES.slice(goes)) delete plan[name];   // goes beyond the profile
    cfg.schedule[day] = plan;
  }
  for (const input of $("grid-body").querySelectorAll("input")) {
    const { day, field } = input.dataset;
    const text = input.value.trim();
    if (field === "spares") {
      if (text === "") delete cfg.schedule[day].spares; else cfg.schedule[day].spares = Number(text);
    } else {
      cfg.schedule[day][field] = text === "" ? 0 : Number(text);
    }
  }
  return cfg;
}

function updateTotals() {
  const goes = Number($("goes_per_day").value);
  const spareRate = fromPct($("spare_rate").value || 0);
  const totals = new Array(goes).fill(0);
  for (const input of $("grid-body").querySelectorAll("input")) {
    const g = GO_NAMES.indexOf(input.dataset.field);
    if (g >= 0) totals[g] += Number(input.value || 0);
  }
  for (const input of $("grid-body").querySelectorAll('input[data-field="spares"]')) {
    const first = $("grid-body").querySelector(`input[data-day="${input.dataset.day}"][data-field="first_go"]`);
    input.placeholder = String(autoSpares(Number(first.value || 0), spareRate));
    input.title = "Blank uses the spare rate";
  }
  const weekly = totals.reduce((a, b) => a + b, 0);
  const pai = numberOr("pai", 0);
  const days = flyingDays(config).length;
  const planned = pai && days ? weekly / (pai * days) : 0;
  $("grid-foot").replaceChildren(el("th", { scope: "row", text: "Week" }), ...totals.map((t) => el("td", { text: String(t) })),
    el("td", { text: `${weekly} sorties` }));

  const profile = { goes_per_day: goes, sortie_hours: numberOr("sortie_hours", 0), turn_hours: numberOr("turn_hours", 0) };
  const times = goTimes(profile);
  const dayLength = times.length ? times[times.length - 1][1] : 0;
  $("go-times-note").textContent = dayLength > 24
    ? `These goes need ${dayLength} hours, more than one day. Shorten the sorties or turns.`
    : `Launches at ${times.map(([launch]) => clock(launch)).join(", ")} after the first launch; the last go lands at ${clock(dayLength)}.`;

  const monthly = numberOr("sute_monthly", null), omDays = numberOr("sute_days", null);
  const ceiling = numberOr("sute_ceiling", null);
  const derivedBox = $("required_from_sute");
  derivedBox.disabled = monthly === null || omDays === null;
  if (derivedBox.disabled) derivedBox.checked = false;
  $("required").disabled = derivedBox.checked;
  if (monthly !== null && omDays) {
    const target = monthly / omDays;
    const required = Math.ceil(Math.round(target * pai * days * 1e9) / 1e9);
    if (derivedBox.checked) $("required").value = String(required);
    $("sute-note").textContent = `Deployed SUTE ${target.toFixed(2)}, so ${required} sorties a week at home. This plan: ${planned.toFixed(2)}` +
      (ceiling ? `, ${planned > ceiling ? "above" : "within"} the ${ceiling.toFixed(2)} surge ceiling.` : ".");
  } else {
    $("sute-note").textContent = `This plan flies a daily SUTE of ${planned.toFixed(2)} per PAI. Add the deployed tempo to compare.`;
  }
}

/* ------------------------------------------------------------ messages */
const FIELD_LABELS = {
  "inventory.pai": "Aircraft assigned (PAI)", "required_sorties": "Required sorties",
  "rates.mc_rate": "Mission capable", "rates.break_rate": "Break (Code 3)", "rates.ground_abort_rate": "Ground abort",
  "rates.fix_8hr_rate": "Fixed within 8 hours", "rates.fix_12hr_rate": "Fixed within 12 hours",
  "rates.fix_24hr_rate": "Fixed within 24 hours", "rules.commit_rate": "Commit rate", "rules.spare_rate": "Spare rate",
  "options.repeat_rate": "Repeat", "options.recur_rate": "Recur",
};
const WINDOW_TEXT = [[/^rates\.fix_windows\[(\d+)\]\.hours must be above the window before it$/, (m, i) => `Fix window ${Number(i) + 1}: hours must be longer than the window above it`],
  [/^rates\.fix_windows\[(\d+)\]\.rate must be between 0 and 1$/, (m, i) => `Fix window ${Number(i) + 1}: share fixed must be between 0% and 100%`],
  [/^options\.go_profile\.(\w+) must be a positive number of hours$/, (m, k) => `${k === "sortie_hours" ? "Sortie length" : "Turn window"} must be more than 0 hours`],
  [/^schedule\.(\w+) plans more goes than the (\d+) per day the go profile allows$/, "$1 plans more goes than the $2 your unit flies"]];
const friendly = (text) => WINDOW_TEXT.reduce((t, [pattern, to]) => t.replace(pattern, to), text)
  .replace(/^([a-z_]+(?:\.[a-z_0-9]+)?) must be between 0 and 1$/, (m, key) => (FIELD_LABELS[key] ? `${FIELD_LABELS[key]} must be between 0% and 100%` : m))
  .replace(/^(inventory\.pai|required_sorties) must be/, (m, key) => `${FIELD_LABELS[key]} must be`)
  .replace(/^schedule\.(\w+)\.second_go/, "$1 turns").replace(/^schedule\.(\w+)\.first_go/, "$1 first go")
  .replace(/^schedule\.(\w+)\.spares/, "$1 spares").replace(/^schedule\.(\w+): /, "$1: ")
  .replace("options.repeat_rate + recur_rate must not exceed 1", "Repeat + recur must not exceed 100%");

function showMessages({ errors = [], warnings = [], ok = null }) {
  const box = $("messages");
  box.replaceChildren();
  if (errors.length) {
    box.append(el("div", { class: "message message-error", role: "alert" },
      el("strong", { text: "Fix these before running:" }), el("ul", {}, errors.map((e) => el("li", { text: friendly(e) })))));
  }
  if (warnings.length) {
    box.append(el("div", { class: "message message-warn" },
      el("strong", { text: "The plan runs, but it breaks these rules:" }), el("ul", {}, warnings.map((w) => el("li", { text: w })))));
  }
  if (ok) box.append(el("div", { class: "message message-ok", text: ok }));
}

let checkTimer = null;
function scheduleCheck() {
  clearTimeout(checkTimer);
  checkTimer = setTimeout(async () => {
    config = formToConfig();
    $("config-json").value = JSON.stringify(config, null, 2);
    try {
      showMessages(await main.request("check", { config: JSON.stringify(config) }));
    } catch (error) {
      showMessages({ errors: [error.message] });
    }
  }, 300);
}

/* ------------------------------------------------------------ run */
function setBusy(state, label) {
  busy = state;
  $("run").disabled = state;
  document.querySelectorAll("[data-needs-idle]").forEach((button) => { button.disabled = state; });
  $("run").textContent = state ? label : `Simulate ${whole($("iterations").value)} weeks`;
}

async function runPlan() {
  if (busy) return;
  config = formToConfig();
  const iterations = Number($("iterations").value);
  const seedText = $("seed").value.trim();
  setBusy(true, "Simulating…");
  try {
    const record = await main.request("run", {
      config: JSON.stringify(config), iterations, seed: seedText === "" ? null : Number(seedText),
    });
    if (record.errors) { showMessages({ errors: record.errors }); return; }
    showMessages({ warnings: record.warnings || [] });
    lastRecord = record;
    saveToHistory(record);
    renderResult(record);
  } catch (error) {
    showMessages({ errors: [`The run stopped: ${error.message}`] });
  } finally {
    setBusy(false);
  }
}

/* ------------------------------------------------------------ result view */
const SVG_NS = "http://www.w3.org/2000/svg";
function svg(tag, attrs = {}, ...children) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "text") node.textContent = value; else node.setAttribute(key, String(value));
  }
  for (const child of children.flat()) if (child) node.append(child);
  return node;
}

const CAUSES = [
  ["lost_abort_uncovered", "Ground aborts used up the spares"],
  ["lost_turn_short", "No aircraft back in time for a turn"],
  ["lost_first_go_short", "Day started short of aircraft"],
];
const TARGETS = [[0.70, "70% (Yellow)"], [0.85, "85% (Green)"], [0.95, "95%"]];
const insight = { key: null, fixes: null, search: null, target: 0.85 };

function sortieRange(m) {
  const d = m.distributions.sorties_flown;
  const low = Math.round(d.p10), high = Math.round(d.p90);
  return low === high ? `${low} of ${m.plan.planned_sorties} planned` : `${low} to ${high} of ${m.plan.planned_sorties} planned`;
}

function barList(entries, digits = 1) {
  return el("ul", { class: "bars" }, entries.map(([label, share, note]) => el("li", {},
    el("span", {}, label, note ? el("span", { class: "bar-note", text: ` ${note}` }) : null),
    el("span", { class: "num", text: pctText(share, digits) }),
    el("span", { class: "bar", "aria-hidden": "true" }, el("span", { style: `width:${(share * 100).toFixed(1)}%` })),
  )));
}

function riskLevel(share) {
  return share >= 0.10 ? "high" : share >= 0.02 ? "watch" : "low";
}

/* Fleet margin: aircraft ready at each day's first go (typical range) against aircraft needed. */
function marginPoints(record) {
  const m = record.metrics;
  const flying = flyingDays(record.config).filter((d) => m.daily[d]);
  const points = flying.map((d) => ({
    day: d, p10: m.daily[d].ready_p10, p50: m.daily[d].ready_p50, p90: m.daily[d].ready_p90,
    needed: m.daily[d].aircraft_needed, risk: m.daily[d].share_missing_schedule,
  }));
  const nm = m.distributions.next_monday_ready;
  points.push({ day: "Next Mon", p10: nm.p10, p50: nm.p50, p90: nm.p90, needed: m.recovery.target, risk: m.recovery.share_short });
  return points;
}

function marginChart(record) {
  const points = marginPoints(record);
  const W = 640, H = 260, left = 40, right = 16, top = 20, bottom = 36;
  const startMc = record.example_weeks && record.example_weeks[0] ? record.example_weeks[0].days[0].mc_aircraft_for_flying : 0;
  const yMax = Math.max(4, Math.ceil(Math.max(startMc, ...points.map((p) => Math.max(p.p90, p.needed))) + 1));
  const step = (W - left - right) / points.length;
  const x = (i) => left + step * (i + 0.5);
  const y = (v) => top + (H - top - bottom) * (1 - v / yMax);
  const tickEvery = yMax > 20 ? 5 : yMax > 10 ? 2 : 1;
  const ticks = [];
  for (let v = 0; v <= yMax; v += tickEvery) ticks.push(v);
  const band = points.map((p, i) => `${x(i)},${y(p.p90)}`).concat(points.slice().reverse().map((p, i) => `${x(points.length - 1 - i)},${y(p.p10)}`)).join(" ");
  const median = points.map((p, i) => `${x(i)},${y(p.p50)}`).join(" ");
  const tight = points.reduce((a, p) => (p.p10 - p.needed < a.p10 - a.needed ? p : a));
  const label = `Aircraft ready compared with aircraft needed. Tightest: ${tight.day}, typically ${Math.round(tight.p50)} ready for ${tight.needed} needed; in the worst 10% of weeks, ${Math.round(tight.p10)} or fewer.`;
  return el("figure", { class: "chart" },
    svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": label, class: "margin-svg" },
      ticks.map((v) => svg("g", {},
        svg("line", { x1: left, x2: W - right, y1: y(v), y2: y(v), class: "grid-line" }),
        svg("text", { x: left - 8, y: y(v) + 4, "text-anchor": "end", class: "axis-text", text: String(v) }))),
      svg("polygon", { points: band, class: "band-area" }),
      svg("polyline", { points: median, class: "median-line" }),
      points.map((p, i) => svg("g", {},
        svg("line", { x1: x(i) - step * 0.28, x2: x(i) + step * 0.28, y1: y(p.needed), y2: y(p.needed), class: `needed-line needed-${riskLevel(p.risk)}` }),
        svg("circle", { cx: x(i), cy: y(p.p50), r: 4.5, class: "median-dot" }),
        svg("text", { x: x(i), y: H - bottom + 20, "text-anchor": "middle", class: "day-text", text: p.day }))),
    ),
    el("figcaption", { class: "legend" },
      el("span", {}, el("span", { class: "key key-band" }), "Aircraft ready, middle 80% of weeks"),
      el("span", {}, el("span", { class: "key key-median" }), "Typical week"),
      el("span", {}, el("span", { class: "key key-needed" }), "Needed (first go + spares; Monday recovery target)"),
    ),
    el("p", { class: "chart-note", text: `Tightest margin: ${tight.day}. Typically ${Math.round(tight.p50)} aircraft ready for ${tight.needed} needed, and ${Math.round(tight.p10)} or fewer in the worst 10% of weeks.` }),
  );
}

function riskStrip(record) {
  const points = marginPoints(record);
  return el("div", {},
    el("ol", { class: "risk-strip", "aria-label": "Chance each day misses its plan" }, points.map((p) => el("li", { class: `risk risk-${riskLevel(p.risk)}` },
      el("span", { class: "risk-day", text: p.day }),
      el("span", { class: "risk-num", text: p.risk < 0.0005 ? "0%" : pctText(p.risk, p.risk < 0.1 ? 1 : 0) }),
    ))),
    el("p", { class: "note", text: "Chance the day misses any planned sortie. For next Monday: chance too few aircraft are ready. Under 2% is low, 2 to 10% is worth watching, 10% or more is high." }),
  );
}

function causesView(m) {
  const all = m.causes.all_weeks;
  const lostPerWeek = m.causes.mean_lost_per_week;
  const pieces = [];
  if (all.lost_sorties) {
    pieces.push(el("p", { text: `About ${lostPerWeek.toFixed(2)} sorties are lost in an average week. Here is where they come from:` }));
    pieces.push(barList(CAUSES.map(([key, label]) => [label, all.shares[key]]), 0));
  } else {
    pieces.push(el("p", { text: "No sorties were lost in any simulated week." }));
  }
  const onlyRecovery = m.recovery.weeks_failing_only_recovery;
  if (onlyRecovery) {
    pieces.push(el("p", { class: "note", text: `${whole(onlyRecovery)} weeks flew everything but failed only because too few aircraft were ready next Monday (${m.recovery.target} needed).` }));
  }
  return pieces;
}

function goesView(m) {
  const goes = m.goes;
  if (!goes || !goes.by_go.length) return null;
  const pieces = [el("h3", { text: goes.by_go.length > 1 ? "Sorties flown by go" : "Sorties flown" })];
  pieces.push(barList(goes.by_go.map((g) => [`Go ${g.go}`, g.share_flown, `(${whole(g.flown)} of ${whole(g.planned)})`]), 1));
  const facts = [`Sortie generation effectiveness ${pctText(goes.sortie_generation_effectiveness, 1)} of scheduled sorties flown`];
  if (goes.turn_success_rate !== null) facts.push(`turn success ${pctText(goes.turn_success_rate, 1)} for goes after the first`);
  pieces.push(el("p", { class: "note", text: `${facts.join("; ")}.` }));
  return pieces;
}

function suteView(m) {
  const sute = m.sute;
  if (!sute) return null;
  const marks = [sute.planned, sute.flown.p10, sute.flown.p90, sute.target, sute.ceiling].filter((v) => v !== null && v !== undefined);
  const span = Math.max(0.05, Math.max(...marks) - Math.min(...marks));
  const min = Math.max(0, Math.min(...marks) - span * 0.6), max = Math.max(...marks) + span * 0.6;
  const W = 640, H = 92, left = 16, right = 16, y = 40;
  const x = (v) => left + (W - left - right) * ((v - min) / (max - min));
  const tick = (value, label, cls, above) => svg("g", {},
    svg("line", { x1: x(value), x2: x(value), y1: y - 16, y2: y + 16, class: cls }),
    svg("text", { x: x(value), y: above ? y - 22 : y + 32, "text-anchor": "middle", class: "axis-text", text: `${label} ${value.toFixed(2)}` }));
  const summary = `Daily SUTE per PAI: planned ${sute.planned.toFixed(2)}, flown ${sute.flown.p10.toFixed(2)} to ${sute.flown.p90.toFixed(2)} in the middle 80% of weeks` +
    (sute.target ? `, deployed target ${sute.target.toFixed(2)}` : "") + (sute.ceiling ? `, surge ceiling ${sute.ceiling.toFixed(2)}` : "") + ".";
  return [
    el("h3", { text: "Training tempo (daily SUTE per PAI)" }),
    el("figure", { class: "chart" },
      svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": summary, class: "sute-svg" },
        svg("line", { x1: left, x2: W - right, y1: y, y2: y, class: "grid-line" }),
        sute.target ? svg("rect", { x: x(sute.target), y: y - 8, width: Math.max(0, (sute.ceiling ? x(sute.ceiling) : W - right) - x(sute.target)), height: 16, class: "sute-band" }) : null,
        svg("rect", { x: x(sute.flown.p10), y: y - 5, width: Math.max(2, x(sute.flown.p90) - x(sute.flown.p10)), height: 10, class: "sute-flown" }),
        sute.target ? tick(sute.target, "Deployed", "needed-line", false) : null,
        sute.ceiling ? tick(sute.ceiling, "Ceiling", "needed-line needed-high", false) : null,
        tick(sute.planned, "Planned", "median-line", true),
      ),
      el("figcaption", { class: "legend" },
        el("span", {}, el("span", { class: "key key-flown" }), "Flown, middle 80% of weeks"),
        sute.target ? el("span", {}, el("span", { class: "key key-bandtarget" }), sute.ceiling ? "Deployed target to surge ceiling" : "At or above deployed target") : null),
    ),
    el("p", { class: "chart-note", text: sute.target
      ? `The SUTE actually flown meets the deployed target in ${pctText(sute.share_weeks_meeting_target)} of weeks.` + (sute.planned_above_ceiling ? " The plan is above the surge ceiling." : "")
      : "Add the deployed tempo in the plan to compare against a target." }),
  ];
}

function suteCurve(record, results) {
  const W = 640, H = 240, left = 44, right = 16, top = 16, bottom = 40;
  const pts = results.map((r) => ({ x: r.sute, y: r.record.metrics.probability_success, label: r.label, pass: r.record.metrics.probability_success >= insight.target }));
  const sute = record.metrics.sute;
  const xs = pts.map((p) => p.x).concat([sute.target, sute.ceiling, sute.planned].filter((v) => v));
  const xMin = Math.min(...xs) * 0.9, xMax = Math.max(...xs) * 1.05;
  const X = (v) => left + (W - left - right) * ((v - xMin) / (xMax - xMin));
  const Y = (v) => top + (H - top - bottom) * (1 - v);
  const vline = (v, label, cls) => v ? svg("g", {},
    svg("line", { x1: X(v), x2: X(v), y1: top, y2: H - bottom, class: cls }),
    svg("text", { x: X(v) + 4, y: H - bottom - 6, class: "axis-text", text: label })) : null;
  // Frontier: the best success any pattern reaches at each SUTE or below.
  const sorted = pts.slice().sort((a, b) => a.x - b.x);
  const frontier = [];
  for (const p of sorted) {
    const same = frontier.length && Math.abs(frontier[frontier.length - 1].x - p.x) < 1e-9;
    if (same) frontier[frontier.length - 1].y = Math.max(frontier[frontier.length - 1].y, p.y);
    else frontier.push({ x: p.x, y: p.y });
  }
  return el("figure", { class: "chart" },
    svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", class: "margin-svg",
      "aria-label": "Chance of success for each pattern tried, against its daily SUTE, with the best pattern at each SUTE joined as a line." },
      [0, 0.25, 0.5, 0.75, 1].map((v) => svg("g", {},
        svg("line", { x1: left, x2: W - right, y1: Y(v), y2: Y(v), class: "grid-line" }),
        svg("text", { x: left - 8, y: Y(v) + 4, "text-anchor": "end", class: "axis-text", text: pctText(v) }))),
      svg("line", { x1: left, x2: W - right, y1: Y(insight.target), y2: Y(insight.target), class: "needed-line" }),
      vline(sute.target, "Deployed", "needed-line"),
      vline(sute.ceiling, "Ceiling", "needed-line needed-high"),
      svg("polyline", { points: frontier.map((p) => `${X(p.x)},${Y(p.y)}`).join(" "), class: "frontier-line" }),
      pts.map((p) => svg("circle", { cx: X(p.x), cy: Y(p.y), r: 4.5, class: p.pass ? "median-dot" : "dot-miss" }, svg("title", { text: `${p.label}: ${pctText(p.y)} at SUTE ${p.x.toFixed(2)}` }))),
      svg("circle", { cx: X(sute.planned), cy: Y(record.metrics.probability_success), r: 7, class: "dot-plan" }),
      svg("text", { x: (left + W - right) / 2, y: H - 8, "text-anchor": "middle", class: "axis-text", text: "Daily SUTE per PAI" }),
    ),
    el("figcaption", { class: "legend" },
      el("span", {}, el("span", { class: "key key-dot" }), `Meets the ${pctText(insight.target)} target`),
      el("span", {}, el("span", { class: "key key-miss" }), "Falls short"),
      el("span", {}, el("span", { class: "key key-plan" }), "Your plan"),
      el("span", {}, el("span", { class: "key key-frontier" }), "Best pattern at each SUTE")),
  );
}

/* ------------------------------------------------------------ fixes and the sustainable-plan search */
async function runVariants(record, variants, iterations, onProgress) {
  const sweep = await main.request("sweep_jobs", {
    config: JSON.stringify(record.config), variants: JSON.stringify(variants), seed: record.seed,
  });
  while (pool.length < poolSize()) pool.push(new PythonWorker());
  const results = new Array(sweep.jobs.length);
  let next = 0, done = 0;
  await Promise.all(pool.map(async (worker) => {
    while (next < sweep.jobs.length) {
      const job = sweep.jobs[next++];
      // Every variant uses the seed of the run on screen, so differences come from the change, not luck.
      const result = await worker.request("run", { config: JSON.stringify(job.config), iterations, seed: record.seed });
      if (result.errors) throw new Error(`"${job.label}" couldn't run: ${result.errors.join(" ")}`);
      results[job.index] = { ...variants[job.index], record: result };
      onProgress(++done, sweep.jobs.length);
    }
  }));
  return results;
}

async function testFixes(record) {
  if (busy) return;
  setBusy(true, "Testing fixes…");
  const box = $("fixes-out");
  box.replaceChildren(el("p", { class: "note", role: "status", text: "Testing fixes…" }));
  try {
    const variants = await main.request("levers", { config: JSON.stringify(record.config), metrics: JSON.stringify(record.metrics) });
    const results = await runVariants(record, variants, record.iterations, (done, total) => {
      box.firstChild.textContent = `Tested ${done} of ${total}…`;
    });
    insight.fixes = results;
    renderFixes(record);
    renderSummary(record);
  } catch (error) {
    box.replaceChildren(el("p", { class: "message message-error", text: error.message }));
  } finally {
    setBusy(false);
  }
}

function renderFixes(record) {
  const results = insight.fixes;
  const base = results[0].record.metrics.probability_success;
  const ranked = results.slice(1).sort((a, b) => b.record.metrics.probability_success - a.record.metrics.probability_success);
  const row = (item, isBase) => {
    const m = item.record.metrics;
    const delta = (m.probability_success - base) * 100;
    return el("tr", { class: isBase ? "base-row" : "" },
      el("td", {}, el("button", { type: "button", class: "link-button", text: item.label, onclick: () => showRecord(item.record) })),
      el("td", { text: pctText(m.probability_success) }),
      el("td", { class: `delta ${delta > 0.5 ? "up" : delta < -0.5 ? "down" : ""}`, text: isBase ? "" : `${delta >= 0 ? "+" : "\u2212"}${Math.abs(delta).toFixed(1)} pts` }),
      el("td", { class: "nowrap", text: `${(m.ci95_low * 100).toFixed(0)}\u2013${pctText(m.ci95_high)}` }),
      el("td", { class: "cost", text: item.cost }),
    );
  };
  $("fixes-out").replaceChildren(
    el("div", { class: "table-wrap" }, el("table", { class: "data-table fixes-table" },
      el("thead", {}, el("tr", {}, ["Change", "Success", "Effect", "95% range", "Trade-off"].map((t) => el("th", { text: t })))),
      el("tbody", {}, row(results[0], true), ranked.map((item) => row(item, false))),
    )),
    el("p", { class: "note", text: `Each change ran ${whole(record.iterations)} weeks with the same seed as the run shown (${record.seed}). Select a change to see its full results.` }),
  );
}

/* ------------------------------------------------------------ turn-pattern search */
const SPLIT_CHOICES = [["step,even", "Try both"], ["step", "Stepped down by go"], ["even", "Even across goes"]];
const TARGET_MODES = [["band", "Around the requirement"], ["requirement", "The requirement only"], ["custom", "My own list"]];
const BUDGETS = [[90, "90 (quick)"], [180, "180"], [360, "360 (thorough)"]];

function patternPayload(results) {
  return results.map((r, index) => {
    const { patch, record, ...meta } = r;
    return { ...meta, index, metrics: record.metrics };
  });
}

async function testPatterns(record) {
  if (busy) return;
  setBusy(true, "Testing patterns…");
  const box = $("search-out");
  const status = el("p", { class: "note", role: "status", text: "Building candidate weeks…" });
  box.replaceChildren(status);
  try {
    const custom = $("custom-targets").value.split(/[\s,]+/).map(Number).filter((n) => Number.isFinite(n) && n > 0);
    const options = {
      mode: $("target-mode").value, custom, budget: Number($("pattern-budget").value),
      splits: $("split-mode").value.split(","), seed: record.seed,
    };
    const gen = await main.request("patterns_generate", { config: JSON.stringify(record.config), options: JSON.stringify(options) });
    if (!gen.candidates.length) { box.replaceChildren(el("p", { text: "No weekly pattern fits the commit, go, and daily limits at these targets." })); return; }
    const screenWeeks = Math.min(1000, record.iterations);
    const results = await runVariants(record, gen.candidates, screenWeeks, (done, total) => {
      status.textContent = `Screened ${done} of ${total} patterns at ${whole(screenWeeks)} weeks each…`;
    });
    let analysis = await main.request("patterns_analyze", { config: JSON.stringify(record.config), results: JSON.stringify(patternPayload(results)), target: insight.target });
    if (analysis.confirm.length && record.iterations > screenWeeks) {
      const subset = analysis.confirm.map((i) => gen.candidates[i]);
      const confirmed = await runVariants(record, subset, record.iterations, (done, total) => {
        status.textContent = `Confirming the ${total} leading patterns at ${whole(record.iterations)} weeks: ${done} done…`;
      });
      analysis.confirm.forEach((i, k) => { results[i] = { ...confirmed[k], confirmed: true }; });
      analysis = await main.request("patterns_analyze", { config: JSON.stringify(record.config), results: JSON.stringify(patternPayload(results)), target: insight.target });
    }
    insight.search = { gen, results, analysis, screenWeeks };
    renderSearch(record);
    renderSummary(record);
  } catch (error) {
    box.replaceChildren(el("p", { class: "message message-error", text: error.message }));
  } finally {
    setBusy(false);
  }
}

async function reanalyze(record) {
  if (!insight.search) return;
  insight.search.analysis = await main.request("patterns_analyze", {
    config: JSON.stringify(record.config), results: JSON.stringify(patternPayload(insight.search.results)), target: insight.target,
  });
  renderSearch(record);
  renderSummary(record);
}

function patternButton(item) {
  const result = insight.search.results[item.index];
  return el("button", { type: "button", class: "link-button", text: item.detail, onclick: () => showRecord(result.record) });
}

function renderSearch(record) {
  const { gen, results, analysis, screenWeeks } = insight.search;
  const tested = results.filter((r) => !r.is_current);
  const families = new Set(tested.map((r) => r.family));
  const confirmedCount = results.filter((r) => r.confirmed).length;
  $("search-out").replaceChildren(
    el("div", { class: "verdict" }, analysis.verdict.map((line) => el("p", { text: line }))),
    suteCurve(record, tested),
    el("h3", { text: `Best pattern in each family at ${analysis.focus_target} sorties a week` }),
    el("div", { class: "table-wrap" }, el("table", { class: "data-table family-table" },
      el("thead", {}, el("tr", {}, ["Family", "Pattern (sorties per go, Mon\u2013Fri)", "Success", "95% range", "Where it fails"].map((t) => el("th", { text: t })))),
      el("tbody", {}, analysis.families.map((row) => el("tr", { class: row.diagnostic ? "diagnostic-row" : "" },
        el("td", {}, el("span", { class: "family-name", text: row.family }),
          el("span", { class: "family-note", text: row.diagnostic ? "Diagnostic only: shown, never recommended" : row.family_note })),
        el("td", { class: "pattern-cell" }, patternButton(row), row.confirmed ? el("span", { class: "tag", text: `Confirmed at ${whole(record.iterations)} weeks` }) : null),
        el("td", { class: row.success >= analysis.success_target ? "meets" : "misses", text: pctText(row.success) }),
        el("td", { class: "nowrap", text: `${(row.ci95_low * 100).toFixed(0)}\u2013${pctText(row.ci95_high)}` }),
        el("td", { class: "cost", text: row.fails_short }),
      ))),
    )),
    el("h3", { text: "Best pattern at each weekly target" }),
    el("div", { class: "table-wrap" }, el("table", { class: "data-table" },
      el("thead", {}, el("tr", {}, ["Sorties / week", "SUTE", "Best recommendable pattern", "Success", `Meets ${pctText(analysis.success_target)}`].map((t) => el("th", { text: t })))),
      el("tbody", {}, analysis.per_target.map((row) => el("tr", { class: row.weekly_sorties === analysis.required_sorties ? "base-row" : "" },
        el("td", { text: `${row.weekly_sorties}${row.weekly_sorties === analysis.required_sorties ? " (required)" : ""}` }),
        el("td", { text: row.sute.toFixed(2) }),
        el("td", {}, row.best ? el("span", {}, `${row.best.family} `, patternButton(row.best)) : "None fit"),
        el("td", { text: row.best ? pctText(row.best.success) : "" }),
        el("td", { class: row.meets ? "meets" : "misses", text: row.meets ? "Yes" : "No" }),
      ))),
    )),
    el("p", { class: "note", text: `Screened ${tested.length} weeks across ${families.size} families at ${analysis.per_target.length} weekly targets, ${whole(screenWeeks)} simulated weeks each, all on seed ${record.seed}. ` +
      `${confirmedCount} leading patterns were re-run at ${whole(record.iterations)} weeks. Each tested week is judged on flying its own total; the verdict compares that with the ${analysis.required_sorties} required.` }),
  );
}

/* ------------------------------------------------------------ watch a week (play-by-play) */
const WEEK_CHOICES = [["typical_failure", "Typical failure"], ["typical", "Typical week"], ["worst", "Worst week"], ["recovery_only", "Recovery only"]];
const BAR_LABELS = { fly: "Flying", fix: "In fix", wait: "Waiting for the long-fix day", paused: "Weekend clock paused", down: "Down for the week" };
const watch = { replay: null, zoom: null };

async function loadWeek(record, index) {
  const out = $("watch-out");
  out.replaceChildren(el("p", { class: "note", role: "status", text: `Replaying week ${whole(index + 1)}…` }));
  try {
    const r = await main.request("replay", { config: JSON.stringify(record.config), seed: record.seed, week: index });
    if (r.errors) { out.replaceChildren(el("p", { class: "message message-error", text: r.errors.join(" ") })); return; }
    watch.replay = r;
    watch.zoom = null;
    renderWeek();
  } catch (error) {
    out.replaceChildren(el("p", { class: "message message-error", text: error.message }));
  }
}

function boardSvg(r, zoomDay) {
  const dayIndex = zoomDay === null ? null : r.days.indexOf(zoomDay);
  const start = dayIndex === null ? 0 : 24 * dayIndex;
  const end = dayIndex === null ? r.week_hours : start + 24;
  const W = dayIndex === null ? 1100 : 640, left = 58, right = 10, top = 30, rowH = 18;
  const rows = r.tails.length + 1;
  const H = top + rows * rowH + 8;
  const x = (h) => left + ((Math.min(Math.max(h, start), end) - start) / (end - start)) * (W - left - right);
  const inView = (a, b) => b > start && a < end;
  const parts = [];
  r.days.forEach((day, i) => {
    const a = 24 * i, b = a + 24;
    if (!inView(a, b)) return;
    const flying = r.flying_days.includes(day);
    parts.push(svg("rect", { x: x(a), y: top - 6, width: x(b) - x(a), height: H - top, class: flying ? "day-band" : "day-band weekend" }));
    const label = dayIndex === null
      ? svg("text", { x: (x(a) + x(b)) / 2, y: 14, "text-anchor": "middle", class: "board-day", text: day })
      : svg("text", { x: W - right - 4, y: 14, "text-anchor": "end", class: "board-day", text: `${day} (full week)` });
    label.addEventListener("click", () => { watch.zoom = zoomDay === day ? null : day; renderWeek(); });
    parts.push(label);
    if (flying) r.go_times.forEach(([launch], g) => {
      const t = a + launch;
      if (t >= start && t <= end) parts.push(svg("line", { x1: x(t), x2: x(t), y1: top - 6, y2: H - 4, class: "go-line" }),
        dayIndex !== null ? svg("text", { x: x(t) + 3, y: top - 10, class: "axis-text", text: `Go ${g + 1}` }) : null);
    });
  });
  r.tails.forEach((row, i) => {
    const y = top + i * rowH;
    parts.push(svg("text", { x: 4, y: y + 12, class: "axis-text", text: `Tail ${row.tail}` }));
    for (const bar of row.bars) {
      if (!inView(bar.start, bar.end)) continue;
      const tip = `Tail ${row.tail}: ${BAR_LABELS[bar.kind]}${bar.window ? ` (${bar.window}-hour fix)` : ""}${bar.role && bar.role !== "planned" ? ` as ${bar.role}` : ""}`;
      parts.push(svg("rect", { x: x(bar.start), y: y + 3, width: Math.max(2, x(bar.end) - x(bar.start)), height: rowH - 6, rx: 2, class: `bar bar-${bar.kind}` }, svg("title", { text: tip })));
    }
    for (const mark of row.marks) {
      if (mark.t < start || mark.t > end) continue;
      parts.push(svg("circle", { cx: x(mark.t), cy: y + rowH / 2, r: 4, class: `mark mark-${mark.kind}` },
        svg("title", { text: `Tail ${row.tail}: ${mark.kind === "abort" ? "ground abort" : "Code 3"} on go ${mark.go}` })));
    }
  });
  const lostY = top + r.tails.length * rowH;
  parts.push(svg("text", { x: 4, y: lostY + 12, class: "axis-text lost-label", text: "Lost" }));
  const sortie = r.go_times[0][1] - r.go_times[0][0];
  for (const lost of r.lost) {
    if (lost.t < start || lost.t > end) continue;
    parts.push(svg("rect", { x: x(lost.t), y: lostY + 3, width: Math.max(4, x(lost.t + sortie) - x(lost.t)), height: rowH - 6, rx: 2, class: "bar bar-lost" },
      svg("title", { text: `${lost.day} go ${lost.go}: sortie lost` })));
  }
  return svg("svg", { viewBox: `0 0 ${W} ${H}`, width: dayIndex === null ? W : "100%", role: "img", class: "board-svg",
    "aria-label": `Tail board for week ${r.week}${zoomDay ? `, ${zoomDay}` : ""}: what each aircraft was doing.` }, parts);
}

function renderWeek() {
  const r = watch.replay;
  if (!r) return;
  const zoomable = r.days.filter((d) => d !== r.days[r.days.length - 1]);
  const failed = r.story.find((d) => d.failed);
  $("watch-out").replaceChildren(
    el("div", { class: "week-head" },
      el("span", { class: "week-title", text: `Week ${whole(r.week)}` }),
      el("span", { class: r.succeeds ? "meets" : "misses", text: r.succeeds ? "Succeeded" : `Failed${r.first_failure_day ? `: ${r.first_failure_day}` : ""}` })),
    el("div", { class: "week-tabs", role: "group", "aria-label": "Zoom" },
      el("button", { type: "button", "aria-pressed": String(watch.zoom === null), text: "Full week", onclick: () => { watch.zoom = null; renderWeek(); } }),
      zoomable.map((d) => el("button", { type: "button", "aria-pressed": String(watch.zoom === d), text: d, onclick: () => { watch.zoom = d; renderWeek(); } }))),
    el("div", { class: "board-scroll" }, boardSvg(r, watch.zoom)),
    el("div", { class: "legend" },
      ["fly", "fix", "wait", "paused", "down"].map((k) => el("span", {}, el("span", { class: `key bar-key bar-${k}` }), BAR_LABELS[k])),
      el("span", {}, el("span", { class: "key bar-key bar-lost" }), "Lost sortie"),
      el("span", {}, el("span", { class: "key mark-key mark-abort" }), "Abort"),
      el("span", {}, el("span", { class: "key mark-key mark-break" }), "Code 3")),
    el("p", { class: "note", text: `${r.start_mc} aircraft MC at the start of the week${r.down_at_start ? `; ${r.down_at_start} more were down all week and aren't shown` : ""}. Tap a day to zoom; times are ${r.first_launch_time ? "clock times" : "hours after the day's first launch"}.` }),
    el("h3", { text: r.succeeds ? "How it went" : "Why it failed" }),
    el("ol", { class: "why-chain" }, r.why.map((line, i) => el("li", { class: i === 0 && !r.succeeds ? "why-head" : "", text: line }))),
    el("h3", { text: "The week, step by step" }),
    ...r.story.filter((d) => d.lines.length).map((d) => el("details", { class: "story-day", open: d.failed || (r.succeeds && d === r.story[0]) },
      el("summary", {}, el("span", { class: "story-day-name", text: d.day }), el("span", { class: d.failed ? "misses" : "note", text: d.status })),
      el("ul", { class: "story-lines" }, d.lines.map((line) => el("li", { class: line.tone ? `tone-${line.tone}` : "" },
        el("span", { class: "story-time", text: line.t }), el("span", { text: line.text })))))),
  );
  if (failed && watch.zoom === null) $("watch-out").querySelector(".board-scroll").scrollLeft = 0;
}

function watchSection(record) {
  const picks = record.replay_weeks || {};
  const weekInput = el("input", { id: "week-number", type: "number", min: 1, max: record.iterations, step: 1, inputmode: "numeric", placeholder: "Any week" });
  return el("section", { class: "card no-print", "aria-labelledby": "watch-h" },
    el("h3", { id: "watch-h", text: "Watch a week" }),
    el("p", { class: "note", text: "Replay any simulated week exactly: what each aircraft did, the step-by-step story, and why it failed." }),
    el("div", { class: "row-fields" },
      el("div", { class: "week-tabs", role: "group", "aria-label": "Choose a week" },
        WEEK_CHOICES.filter(([key]) => picks[key] !== null && picks[key] !== undefined).map(([key, label]) =>
          el("button", { type: "button", text: label, onclick: () => loadWeek(record, picks[key]) }))),
      el("label", { class: "field" }, "Week number", weekInput),
      el("button", { type: "button", class: "secondary align-end", text: "Show week", onclick: () => {
        const n = Number(weekInput.value);
        if (!Number.isInteger(n) || n < 1 || n > record.iterations) { showMessages({ errors: [`Choose a week from 1 to ${whole(record.iterations)}.`] }); return; }
        loadWeek(record, n - 1);
      } })),
    el("div", { id: "watch-out" }),
  );
}

/* ------------------------------------------------------------ leadership summary */
function renderSummary(record) {
  const m = record.metrics;
  const weakest = m.weakest_day;
  const nm = m.distributions.next_monday_ready;
  const findings = [m.summary_text];
  if (insight.fixes) {
    const base = insight.fixes[0].record.metrics.probability_success;
    const top = insight.fixes.slice(1).sort((a, b) => b.record.metrics.probability_success - a.record.metrics.probability_success)[0];
    if (top) {
      const delta = (top.record.metrics.probability_success - base) * 100;
      findings.push(delta > 0.5
        ? `Best fix tested: ${top.label.toLowerCase()}, raising success to ${pctText(top.record.metrics.probability_success)} (${delta >= 0 ? "+" : ""}${delta.toFixed(1)} points). Trade-off: ${top.cost.charAt(0).toLowerCase()}${top.cost.slice(1)}.`
        : "None of the fixes tested improved the plan by more than half a point.");
    }
  }
  if (insight.search) findings.push(...insight.search.analysis.verdict.slice(0, 3));
  $("summary").replaceChildren(
    el("div", { class: "summary-head" },
      el("div", {},
        el("h2", { class: "summary-title", text: record.name || "Untitled plan" }),
        el("p", { class: "note", text: `${whole(m.iterations)} simulated weeks, run ${new Date(record.created_at).toLocaleString()}` }),
      ),
      el("button", { type: "button", class: "secondary no-print", text: "Print one-page summary", onclick: () => window.print() }),
    ),
    el("div", { class: "headline" },
      el("span", { class: "big-number", text: pctText(m.probability_success) }),
      el("span", { class: `band band-${m.risk_band}`, text: m.risk_band }),
      el("span", { class: "headline-label", text: "of weeks fly every planned sortie and recover by next Monday" }),
    ),
    el("p", { class: "ci", text: `95% range ${pctText(m.ci95_low, 1)} to ${pctText(m.ci95_high, 1)}.` }),
    el("dl", { class: "key-facts" },
      el("div", {}, el("dt", { text: "Weekly requirement met" }), el("dd", { text: pctText(m.components.meets_required_sorties) }), el("dd", { class: "fact-note", text: `${m.plan.required_sorties} required${record.required_from_sute ? " (from SUTE)" : ""}, ${m.plan.planned_sorties} planned` })),
      el("div", {}, el("dt", { text: "Weakest day" }), el("dd", { text: weakest || "None" }), el("dd", { class: "fact-note", text: weakest ? `misses its plan in ${pctText(m.daily[weakest].share_missing_schedule, 1)} of weeks` : "no day missed its plan" })),
      el("div", {}, el("dt", { text: "Ready next Monday" }), el("dd", { text: String(Math.round(nm.p50)) }), el("dd", { class: "fact-note", text: `typical week; ${m.recovery.target} needed` })),
      m.sute ? el("div", {}, el("dt", { text: "SUTE flown" }), el("dd", { text: m.sute.flown.p50.toFixed(2) }), el("dd", { class: "fact-note", text: m.sute.target ? `typical week; deployed target ${m.sute.target.toFixed(2)}` : `typical week; planned ${m.sute.planned.toFixed(2)}` })) : null,
    ),
    el("ul", { class: "findings" }, findings.map((f) => el("li", { text: f }))),
    el("p", { class: "print-only audit", text: `Run record: seed ${record.seed}, model ${record.model_version}, build ${String(record.build_commit).slice(0, 7)}, results fingerprint ${record.metrics_fingerprint.slice(0, 16)}. Re-run with the record file to verify.` }),
  );
}

function weekBoard(record) {
  const wrap = el("div", {});
  const weeks = record.example_weeks || [];
  if (!weeks.length) return wrap;
  const flying = flyingDays(record.config);
  const target = record.config.success && record.config.success.minimum_monday_aircraft != null
    ? record.config.success.minimum_monday_aircraft
    : Math.max(0, ...weeks[0].days.filter((d) => flying.includes(d.day)).map((d) => d.aircraft_required));
  const board = el("div", { class: "week-board" });
  const tabs = el("div", { class: "week-tabs", role: "group", "aria-label": "Example week" });

  function show(index) {
    for (const [i, button] of [...tabs.children].entries()) button.setAttribute("aria-pressed", String(i === index));
    board.replaceChildren();
    const days = weeks[index].days;
    for (const day of days.filter((d) => flying.includes(d.day))) {
      const clean = Math.max(0, day.sorties_flown - day.code_3);
      const tiles = [
        ...Array(clean).fill("tile tile-flown"),
        ...Array(Math.min(day.code_3, day.sorties_flown)).fill("tile tile-broke"),
        ...Array(day.lost_sorties).fill("tile tile-lost"),
      ];
      const summary = `${day.day}: ${day.sorties_flown} of ${day.planned_sorties} flown, ${day.code_3} broke, ${day.lost_sorties} lost; ${day.mc_aircraft_for_flying} aircraft ready at the start of the day.`;
      board.append(el("div", { class: "week-row", role: "img", "aria-label": summary },
        el("span", { class: "week-day", text: day.day }),
        el("span", { class: "tiles" }, tiles.map((cls) => el("span", { class: cls }))),
        el("span", { class: "week-meta", text: `${day.mc_aircraft_for_flying} ready at start` }),
      ));
    }
    const monday = days[days.length - 1];
    const met = monday.available_eod >= target;
    board.append(el("p", { class: "recovery-line",
      text: `Next Monday: ${monday.available_eod} aircraft ready, ${met ? "meeting" : "short of"} the ${target} needed.` }));
  }

  weeks.forEach((week, i) => tabs.append(el("button", { type: "button", "aria-pressed": "false", onclick: () => show(i), text: `Week ${week.week}` })));
  wrap.append(
    el("h3", { text: "One simulated week, sortie by sortie" }),
    el("p", { class: "note", text: "Each tile is one planned sortie, grouped by outcome rather than launch order." }),
    tabs, board,
    el("div", { class: "legend" },
      el("span", {}, el("span", { class: "tile tile-flown" }), "Flown"),
      el("span", {}, el("span", { class: "tile tile-broke" }), "Flown, then broke"),
      el("span", {}, el("span", { class: "tile tile-lost" }), "Lost: no aircraft"),
    ),
  );
  show(0);
  return wrap;
}

/* ------------------------------------------------------------ full result */
function showRecord(record) {
  lastRecord = record;
  renderResult(record);
  $("result").scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderResult(record) {
  const m = record.metrics;
  const flying = flyingDays(record.config);
  const days = flying.filter((d) => m.daily[d]);
  const failures = Object.entries(m.failures.failure_mode_counts).filter(([mode]) => mode !== "Full Schedule Not Flown");
  const key = record.metrics_fingerprint + record.seed;
  if (insight.key !== key) { insight.key = key; insight.fixes = null; insight.search = null; }

  const targetSelect = el("select", { id: "target", "aria-label": "Success target" },
    TARGETS.map(([value, label]) => el("option", { value, text: label, selected: value === insight.target })));
  targetSelect.addEventListener("change", () => {
    insight.target = Number(targetSelect.value);
    if (insight.search) reanalyze(record);
  });

  $("result").replaceChildren(
    el("section", { id: "summary", class: "card summary-card", "aria-label": "Summary" }),
    el("section", { class: "card", "aria-labelledby": "where-h" },
      el("h3", { id: "where-h", text: "Where the plan runs tight" }),
      marginChart(record),
      riskStrip(record),
      goesView(m),
      suteView(m),
    ),
    el("section", { class: "card", "aria-labelledby": "why-h" },
      el("h3", { id: "why-h", text: "Why sorties are lost" }),
      causesView(m),
    ),
    watchSection(record),
    el("section", { class: "card no-print", "aria-labelledby": "fix-h" },
      el("h3", { id: "fix-h", text: "What would fix it" }),
      el("p", { class: "note", text: "Test the changes a planner can make, ranked by how much each one helps." }),
      el("div", { class: "button-row no-print" },
        el("button", { type: "button", class: "secondary", "data-needs-idle": true, text: "Test fixes", onclick: () => testFixes(record) })),
      el("div", { id: "fixes-out" }),
      el("h3", { text: "Test turn patterns" }),
      el("p", { class: "note", text: "Generates weeks in families leadership will recognize (waterfall, flat, recovery valley, and more), tests each one, and reports what works at the sortie levels that matter." }),
      el("div", { class: "row-fields no-print" },
        el("label", { class: "field" }, "Success bar", targetSelect),
        el("label", { class: "field" }, "Weekly sortie targets",
          el("select", { id: "target-mode" }, TARGET_MODES.map(([v, t]) => el("option", { value: v, text: t })))),
        el("label", { class: "field" }, "Your targets (comma separated)",
          el("input", { id: "custom-targets", type: "text", inputmode: "numeric", placeholder: "e.g. 36, 40, 45" })),
        el("label", { class: "field" }, "Go splits",
          el("select", { id: "split-mode" }, SPLIT_CHOICES.map(([v, t]) => el("option", { value: v, text: t })))),
        el("label", { class: "field" }, "Patterns to screen",
          el("select", { id: "pattern-budget" }, BUDGETS.map(([v, t]) => el("option", { value: v, text: t, selected: v === 180 })))),
        el("button", { type: "button", class: "primary align-end", "data-needs-idle": true, text: "Test turn patterns", onclick: () => testPatterns(record) })),
      el("div", { id: "search-out" }),
    ),
    el("section", { class: "card no-print", "aria-label": "Example week" }, weekBoard(record)),
    el("details", { class: "card details no-print" },
      el("summary", { text: "All the numbers" }),
      el("h3", { text: "How often each check passed" }),
      barList(Object.entries(COMPONENT_NAMES).map(([k, label]) => [label, m.components[k]])),
      failures.length ? el("h3", { text: `Why the ${whole(m.failures.failed_weeks)} failed weeks failed` }) : null,
      failures.length ? el("div", { class: "table-wrap" }, el("table", { class: "data-table" },
        el("thead", {}, el("tr", {}, el("th", { text: "Reason" }), el("th", { text: "Weeks" }), el("th", { text: "Share of failures" }))),
        el("tbody", {}, failures.map(([mode, count]) => el("tr", {},
          el("td", { text: FAILURE_NAMES[mode] || mode }), el("td", { text: whole(count) }),
          el("td", { text: pctText(count / m.failures.failed_weeks) })))))) : null,
      el("h3", { text: "Day by day, averaged over every simulated week" }),
      el("div", { class: "table-wrap" }, el("table", { class: "data-table" },
        el("thead", {}, el("tr", {}, ["Day", "Needed", "Ready (typical)", "Flown", "Lost", "Breaks + aborts", "Weeks missing plan"].map((t) => el("th", { text: t })))),
        el("tbody", {}, days.map((d) => el("tr", {},
          el("td", { text: d }), el("td", { text: String(m.daily[d].aircraft_needed) }),
          el("td", { text: `${Math.round(m.daily[d].ready_p10)}\u2013${Math.round(m.daily[d].ready_p90)}` }),
          el("td", { text: one(m.daily[d].mean_sorties_flown) }), el("td", { text: m.daily[d].mean_lost_sorties.toFixed(2) }),
          el("td", { text: one(m.daily[d].mean_breaks_and_aborts) }), el("td", { text: pctText(m.daily[d].share_missing_schedule, 1) })))))),
      el("h3", { text: "Also worth knowing" }),
      el("div", { class: "table-wrap" }, el("table", { class: "data-table" }, el("tbody", {},
        [
          ["Sorties flown per week (middle 80% of weeks)", sortieRange(m)],
          ["Aircraft still down at week's end (average)", one(m.distributions.repair_backlog.mean)],
          ["2407 adds per week (average)", m.reported.mean_2407_adds_per_week.toFixed(2)],
          ["Days over commit in practice (average)", m.reported.mean_days_over_commit_in_practice.toFixed(2)],
          ["Spare sorties per week (average)", one(m.reported.mean_spare_sorties_per_week)],
          ["Repeat or recur breaks per week (average)", one(m.reported.mean_repeat_recur_breaks_per_week)],
        ].map(([label, value]) => el("tr", {}, el("td", { text: label }), el("td", { text: value })))))),
      el("h3", { text: "Run record" }),
      el("dl", { class: "record-facts" },
        el("dt", { text: "Seed" }), el("dd", { text: String(record.seed) }),
        el("dt", { text: "Model" }), el("dd", { text: `${record.model_version}, build ${String(record.build_commit).slice(0, 7)}` }),
        el("dt", { text: "Config fingerprint" }), el("dd", { text: record.config_fingerprint.slice(0, 16) }),
        el("dt", { text: "Results fingerprint" }), el("dd", { text: record.metrics_fingerprint.slice(0, 16) }),
      ),
      el("div", { class: "button-row" },
        el("button", { type: "button", class: "secondary", text: "Download run record", onclick: () => downloadJson(record, `tps-run-${record.seed}.json`) }),
        el("button", { type: "button", class: "secondary", text: "Load this plan into the form", onclick: () => loadConfig(record.config) }),
      ),
    ),
  );
  renderSummary(record);
  watch.replay = null;
  const picks = record.replay_weeks || {};
  const first = picks.typical_failure ?? picks.typical;
  if (first !== undefined && first !== null) loadWeek(record, first);
  if (insight.fixes) renderFixes(record);
  if (insight.search) renderSearch(record);
  document.querySelectorAll("[data-needs-idle]").forEach((b) => { b.disabled = busy; });
  const result = $("result");
  result.hidden = false;
  result.classList.remove("reveal"); void result.offsetWidth; result.classList.add("reveal");
  $("empty").hidden = true;
}

/* ------------------------------------------------------------ history (this browser only) */
function readHistory() {
  try { return JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]"); } catch { return []; }
}

function writeHistory(items) {
  try { localStorage.setItem(HISTORY_KEY, JSON.stringify(items)); return true; } catch { return false; }
}

function saveToHistory(record) {
  const items = [record, ...readHistory()].slice(0, HISTORY_LIMIT);
  while (items.length && !writeHistory(items)) items.pop();
  renderHistory();
}

function renderHistory() {
  const list = $("history");
  const items = readHistory();
  list.replaceChildren(...items.map((record) => el("li", {},
    el("button", { type: "button", class: "secondary", onclick: () => { lastRecord = record; renderResult(record); } },
      el("span", { class: "h-name", text: record.name || "Untitled plan" }),
      el("span", { class: "h-meta", text: `${pctText(record.metrics.probability_success)} on ${new Date(record.created_at).toLocaleDateString()}` }),
    ))));
  if (!items.length) list.append(el("li", { class: "note", text: "No runs yet." }));
}

/* ------------------------------------------------------------ files */
function downloadJson(data, filename) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const link = el("a", { href: URL.createObjectURL(blob), download: filename });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

async function readJsonFile(input) {
  const file = input.files && input.files[0];
  input.value = "";
  if (!file) return null;
  return JSON.parse(await file.text());
}

async function verifyFile(input) {
  const out = $("verify-result");
  let record;
  try { record = await readJsonFile(input); } catch { out.replaceChildren(el("p", { class: "message message-error", text: "That file isn't valid JSON." })); return; }
  if (!record) return;
  out.replaceChildren(el("p", { class: "note", role: "status", text: "Re-running the record to check it…" }));
  try {
    const result = await main.request("verify", { record: JSON.stringify(record) });
    if (result.identical) {
      out.replaceChildren(el("p", { class: "message message-ok",
        text: `Verified: re-running "${record.name || "this plan"}" with seed ${record.seed} reproduces the same results exactly.` }));
    } else {
      out.replaceChildren(el("div", { class: "message message-error" },
        el("strong", { text: "Not verified." }), el("ul", {}, (result.problems || []).map((p) => el("li", { text: p })))));
    }
  } catch (error) {
    out.replaceChildren(el("p", { class: "message message-error", text: `Couldn't verify: ${error.message}` }));
  }
}

function loadConfig(cfg) {
  config = structuredClone(cfg);
  configToForm(config);
  scheduleCheck();
  $("plan-heading").scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ------------------------------------------------------------ start up */
async function loadExamples() {
  const listing = await (await fetch("examples/index.json", { cache: "no-cache" })).json();
  const picker = $("example-picker");
  picker.replaceChildren(...listing.map((item) => el("option", { value: item.file, text: item.name })));
  const load = async () => loadConfig(await (await fetch(`examples/${picker.value}`, { cache: "no-cache" })).json());
  picker.addEventListener("change", load);
  await load();
}

function wireForm() {
  for (const id of ["sat_hours", "sun_hours"]) {
    $(id).replaceChildren(...COVERAGE.map(([hours, label]) => el("option", { value: hours, text: label })));
  }
  document.querySelector(".plan").addEventListener("input", (event) => {
    if (event.target.id === "config-json" || event.target.id === "seed") return;
    updateTotals();
    scheduleCheck();
  });
  $("goes_per_day").addEventListener("change", () => {
    config = formToConfig();
    configToForm(config);
    scheduleCheck();
  });
  $("required_from_sute").addEventListener("change", () => { updateTotals(); scheduleCheck(); });
  $("add-window").addEventListener("click", () => {
    const rows = [...$("window-body").querySelectorAll("tr")];
    const last = rows.length ? Number(rows[rows.length - 1].querySelector('[data-window="hours"]').value || 0) : 0;
    const lastRate = rows.length ? fromPct(rows[rows.length - 1].querySelector('[data-window="rate"]').value || 0) : 0;
    $("window-body").append(windowRow({ hours: last ? last * 2 : 4, rate: lastRate }));
    scheduleCheck();
  });
  $("window-body").addEventListener("click", (event) => {
    if (!event.target.classList.contains("remove-window")) return;
    if ($("window-body").children.length > 1) { event.target.closest("tr").remove(); scheduleCheck(); }
  });
  $("iterations").addEventListener("change", () => { if (!busy) setBusy(false); });
  $("run").addEventListener("click", runPlan);
  $("apply-json").addEventListener("click", () => {
    try { loadConfig(JSON.parse($("config-json").value)); showMessages({ ok: "Config applied." }); }
    catch (error) { showMessages({ errors: [`The config isn't valid JSON: ${error.message}`] }); }
  });
  $("download-config").addEventListener("click", () => {
    const cfg = formToConfig();
    downloadJson(cfg, `${(cfg.name || "tps-config").replace(/[^\w-]+/g, "-").toLowerCase()}.json`);
  });
  $("open-config").addEventListener("change", async (event) => {
    try { const cfg = await readJsonFile(event.target); if (cfg) loadConfig(cfg); }
    catch { showMessages({ errors: ["That file isn't valid JSON."] }); }
  });
  $("verify-file").addEventListener("change", (event) => verifyFile(event.target));
  $("clear-history").addEventListener("click", () => { writeHistory([]); renderHistory(); });
}

function wireTheme() {
  const buttons = document.querySelectorAll("[data-theme-choice]");
  const current = () => document.documentElement.dataset.theme || "auto";
  const paint = () => buttons.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.themeChoice === current())));
  buttons.forEach((button) => button.addEventListener("click", () => {
    const choice = button.dataset.themeChoice;
    if (choice === "auto") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = choice;
    try { choice === "auto" ? localStorage.removeItem("tps.theme") : localStorage.setItem("tps.theme", choice); } catch { /* not saved */ }
    paint();
  }));
  paint();
}

async function start() {
  wireTheme();
  wireForm();
  renderHistory();
  try {
    await loadExamples();
    const info = await main.request("info");
    $("status").textContent = "Model ready";
    $("status").className = "status status-ready";
    $("build").textContent = `Model ${info.model_version}, build ${String(info.build_commit).slice(0, 7)}`;
    setBusy(false);
  } catch (error) {
    $("status").textContent = `The model didn't load: ${error.message}`;
    $("status").className = "status status-error";
  }
}

start();
