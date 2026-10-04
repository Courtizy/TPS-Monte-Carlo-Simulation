/* Overview, Results and Method: these pages only display JSON written by scripts/export_site.py.
   No model math here. Run ▸ (#run) loads the planner, which runs the engine itself. */
(() => {
  const REPO = "https://github.com/Courtizy/TPS-Monte-Carlo-Simulation";
  const NS = "http://www.w3.org/2000/svg";
  const pct = (v, d = 0) => (v === null || v === undefined ? "—" : `${(v * 100).toFixed(d)}%`);
  const num = (v, d = 0) => (v === null || v === undefined ? "—" : Number(v).toFixed(d));
  const DAY_NAMES = { Mon: "Monday", Tue: "Tuesday", Wed: "Wednesday", Thu: "Thursday", Fri: "Friday", "Next Mon": "next Monday" };
  const STATUS_ICON = { good: "✓", warning: "!", critical: "✕" };

  function h(tag, attrs = {}, ...kids) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "text") node.textContent = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v === true ? "" : String(v));
    }
    for (const kid of kids.flat(Infinity)) if (kid !== null && kid !== undefined && kid !== false) node.append(kid);
    return node;
  }
  function s(tag, attrs = {}, ...kids) {
    const node = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
    for (const kid of kids.flat(Infinity)) if (kid) node.append(kid);
    return node;
  }
  const statusChip = (level, label) => h("span", { class: `status status--${level}` }, label);

  const state = { index: null, preset: null, changelog: [], pick: { unit: null, scenario: "baseline", recovery: "spares" } };

  async function getJSON(path) {
    const response = await fetch(path, { cache: "no-cache" });
    if (!response.ok) throw new Error(`${path}: ${response.status}`);
    return response.json();
  }

  async function loadPreset() {
    const { unit, scenario, recovery } = state.pick;
    state.preset = await getJSON(`data/preset_${unit}__${scenario}__${recovery}.json`);
  }

  /* ---------------------------------------------------------------- Overview */
  function renderOverview() {
    const p = state.preset, k = p.kpis, sim = p.simulation;
    const binding = p.binding.day === "Next Mon"
      ? "recovery by next Monday"
      : `${DAY_NAMES[p.binding.day] || p.binding.day}: every planned sortie flown`;
    $page("overview").replaceChildren(
      h("section", { class: "ov-hero" },
        h("p", { class: "eyebrow", text: "01 · Operations" }),
        h("h2", { class: "ov-headline", text: "A turn pattern that works on average can still fail most weeks." }),
        h("p", { class: "ov-lead", text: "This model runs the week thousands of times with random breaks and repairs, and reports how often the pattern actually holds: sorties flown, aircraft available, and how fast the fleet recovers." }),
        h("div", { class: "button-row" },
          h("a", { class: "button primary", href: "#results", text: "See results" }),
          h("a", { class: "button secondary", href: "#method", text: "How it works" }))),
      h("section", { class: "card ov-answer" },
        h("p", { class: "eyebrow", text: `Headline · ${p.unit_name}, ${p.scenario_label.toLowerCase()}` }),
        h("p", { class: "ov-big num", text: pct(k.weeks_meeting_every_requirement) }),
        h("p", { text: "of simulated weeks meet every requirement" }),
        h("p", { class: "note", text: `${sim.runs_used.toLocaleString()} runs · seed ${sim.seed} · synthetic inputs` }),
        h("p", {}, statusChip(p.binding.p_day_met >= 0.98 ? "good" : p.binding.p_day_met >= 0.9 ? "warning" : "critical",
          `Binding constraint: ${binding} (${pct(p.binding.p_day_met)})`))),
      h("section", { class: "ov-steps" },
        h("h3", { text: "How it works" }),
        h("ol", { class: "steps" },
          h("li", {}, h("span", { class: "step-n num", text: "01" }), h("strong", { text: "Set the week" }), h("p", { text: "A weekly turn pattern, the unit's rates, spares and commit, and how losses are recovered." })),
          h("li", {}, h("span", { class: "step-n num", text: "02" }), h("strong", { text: "Run it thousands of times" }), h("p", { text: "Random breaks, aborts and fix times each run, seeded so results repeat exactly." })),
          h("li", {}, h("span", { class: "step-n num", text: "03" }), h("strong", { text: "Score every week" }), h("p", { text: "A week passes only if every planned sortie flies, the weekly requirement is met, and enough aircraft are ready next Monday." })))),
      h("section", { class: "ov-two" },
        h("div", { class: "card" }, h("h3", { text: "What it can't tell you" }),
          h("p", { text: "Inputs are public or synthetic, so results show the method, not any unit's readiness. Breaks are drawn independently; real fleets have correlated failures. Parts supply and manpower limits aren't modeled yet." })),
        h("div", { class: "card" }, h("h3", { text: "Built on" }),
          h("p", { text: "A Python Monte Carlo engine, standard library only. These pages show results the engine precomputed from synthetic inputs; Run ▸ runs the same engine in your browser." }),
          h("p", {}, h("a", { href: REPO, text: "Code on GitHub" }), " · ", h("a", { href: `${REPO}/blob/main/docs/MODEL_LOGIC.md`, text: "Model logic" })))),
    );
  }

  /* ---------------------------------------------------------------- Results */
  function chooser(label, key, options) {
    return h("div", { class: "chooser" },
      h("p", { class: "eyebrow", text: label }),
      h("div", { class: "chips", role: "group", "aria-label": label },
        options.map((o) => h("button", { type: "button", "aria-pressed": String(state.pick[key] === o.id), title: o.note || "",
          onclick: async () => { state.pick[key] = o.id; await loadPreset(); renderResults(); } }, o.label || o.name))));
  }

  function availabilityChart(days) {
    const W = 640, H = 260, left = 40, right = 12, top = 16, bottom = 34;
    const yMax = Math.max(4, Math.ceil(Math.max(...days.map((d) => Math.max(d.available_p90, d.needed))) + 1));
    const step = (W - left - right) / days.length;
    const x = (i) => left + step * (i + 0.5);
    const y = (v) => top + (H - top - bottom) * (1 - v / yMax);
    const ticks = [];
    for (let v = 0; v <= yMax; v += yMax > 12 ? 2 : 1) ticks.push(v);
    const bar = step * 0.42;
    return h("figure", { class: "chart" },
      s("svg", { viewBox: `0 0 ${W} ${H}`, class: "res-chart", role: "img",
        "aria-label": `Aircraft available against the requirement for each day. ${days.map((d) => `${d.day}: median ${num(d.available_p50)} available, ${d.needed} needed`).join("; ")}.` },
        ticks.map((v) => s("g", {},
          s("line", { x1: left, x2: W - right, y1: y(v), y2: y(v), class: "grid-line" }),
          s("text", { x: left - 6, y: y(v) + 4, "text-anchor": "end", class: "axis-text" }, document.createTextNode(String(v))))),
        days.map((d, i) => s("g", {},
          s("rect", { x: x(i) - bar / 2, y: y(d.available_p50), width: bar, height: Math.max(0, y(0) - y(d.available_p50)), class: "res-bar" }),
          s("line", { x1: x(i), x2: x(i), y1: y(d.available_p10), y2: y(d.available_p90), class: "res-range" }),
          s("line", { x1: x(i) - 6, x2: x(i) + 6, y1: y(d.available_p10), y2: y(d.available_p10), class: "res-range" }),
          s("line", { x1: x(i) - 6, x2: x(i) + 6, y1: y(d.available_p90), y2: y(d.available_p90), class: "res-range" }),
          s("line", { x1: x(i) - step * 0.45, x2: x(i) + step * 0.45, y1: y(d.needed), y2: y(d.needed), class: "res-need" }),
          s("text", { x: x(i), y: H - 12, "text-anchor": "middle", class: "day-text" }, document.createTextNode(d.day))))),
      h("figcaption", { class: "legend" },
        h("span", {}, h("span", { class: "key key-bar" }), "Median available"),
        h("span", {}, h("span", { class: "key key-range" }), "10–90% range"),
        h("span", {}, h("span", { class: "key key-need" }), "Required (first go + spares; next Monday: recovery target)")));
  }

  function renderResults() {
    const p = state.preset, k = p.kpis, sim = p.simulation, inp = sim.inputs, idx = state.index;
    const windows = inp.fix_windows.map((w) => `${w.hours} h ${pct(w.rate)}`).join(", ");
    const weekend = inp.weekend_hours || {};
    const hours = (v) => (v === undefined ? "24 h" : v === 0 ? "none" : `${v} h`);
    const kpi = (label, value, note, main) => h("div", { class: `kpi${main ? " kpi--main" : ""}` },
      h("p", { class: "kpi-label", text: label }), h("p", { class: "kpi-value num", text: value }), note ? h("p", { class: "note", text: note }) : null);
    $page("results").replaceChildren(h("div", { class: "res-grid" },
      h("aside", { class: "res-left" },
        chooser("Unit", "unit", idx.units),
        chooser("Scenario", "scenario", idx.scenarios),
        chooser("Recovery model", "recovery", idx.recovery),
        h("p", { class: "note", text: `${p.scenario_note} ${p.recovery_note}` }),
        h("h3", { text: "Key assumptions" }),
        h("dl", { class: "assumptions" },
          [["Aircraft (PAI)", inp.pai], ["Mission capable", pct(inp.mc_rate, 1)], ["Break / abort", `${pct(inp.break_rate, 1)} / ${pct(inp.ground_abort_rate, 1)}`],
           ["Fixed within", windows], ["Commit / spares", `${pct(inp.commit_rate)} / ${pct(inp.spare_rate)}`], ["Goes per day", inp.goes_per_day],
           ["Sorties planned / required", `${inp.weekly_sorties} / ${inp.required_sorties}`], ["Weekend repairs", `Sat ${hours(weekend.Sat)}, Sun ${hours(weekend.Sun)}`],
           ["Fleet flex (2407 adds)", inp.fleet_flex ? "Allowed" : "Not allowed"]].map(([a, b]) => [h("dt", { text: a }), h("dd", { class: "num", text: String(b) })])),
        h("p", { class: "note", text: `Precomputed by the engine · ${sim.runs_used.toLocaleString()} runs · seed ${sim.seed}` }),
        h("p", { class: "note", text: `Generated ${new Date(p.generated_at).toLocaleString()} · model ${p.model_version}` }),
        h("p", {}, h("a", { href: `data/preset_${p.id}.json`, download: `tps_${p.id}.json`, text: "Download results (JSON)" }))),
      h("div", { class: "res-right" },
        h("div", { class: "kpis" },
          kpi("Weeks meeting every requirement", pct(k.weeks_meeting_every_requirement), `95% range ${pct(k.ci95[0])}–${pct(k.ci95[1])}`, true),
          kpi("Sortie compliance", pct(k.sortie_compliance, 1), "scheduled sorties flown"),
          kpi("Aircraft available, median", num(k.available_median), "at each day's first launch"),
          kpi("Ready next Monday, median", num(k.ready_next_monday_median), `${k.recovery_target} needed`)),
        h("section", { class: "card" }, h("h3", { text: "Aircraft available vs. requirement, by day" }), h("div", { id: "res-chart-slot" })),
        h("section", { class: "card" }, h("h3", { text: "Day by day" }),
          h("div", { class: "table-wrap" }, h("table", { class: "data-table" },
            h("thead", {}, h("tr", {}, ["Day", "Sorties planned", "P(day met)", "Available, median", "Status"].map((t) => h("th", { text: t })))),
            h("tbody", {}, p.days.map((d) => h("tr", {},
              h("td", { text: d.day === "Next Mon" ? "Next Mon (recovery)" : d.day }),
              h("td", { class: "num", text: d.day === "Next Mon" ? "—" : String(d.sorties_planned) }),
              h("td", { class: "num", text: pct(d.p_day_met, 1) }),
              h("td", { class: "num", text: `${num(d.available_p50)} (need ${d.needed})` }),
              h("td", {}, statusChip(d.status, d.status_label)))))))),
        h("p", { class: "note", text: p.summary }))));
    drawWhenVisible(() => $("#res-chart-slot").replaceChildren(availabilityChart(p.days)));
  }

  /* ---------------------------------------------------------------- Method */
  function renderMethod() {
    const p = state.preset, inp = p.simulation.inputs;
    const sections = [
      ["problem", "Problem", [h("p", { text: "Turn patterns are usually checked against averages. Averages hide how often a week actually fails. The question here is direct: for a given weekly pattern, what's the probability it holds?" })]],
      ["inputs", "Inputs and sources", [
        h("div", { class: "table-wrap" }, h("table", { class: "data-table" },
          h("thead", {}, h("tr", {}, ["Input", "Value", "Source", "Status"].map((t) => h("th", { text: t })))),
          h("tbody", {}, [
            ["Weekly turn pattern", "per preset", "Synthetic example units", "Set"],
            ["Maintenance event rates", `MC ${pct(inp.mc_rate)}, break ${pct(inp.break_rate)}, abort ${pct(inp.ground_abort_rate)}`, "Synthetic", "Synthetic"],
            ["Planning constraints", `Commit ${pct(inp.commit_rate)}, spares ${pct(inp.spare_rate)}`, "Synthetic", "Synthetic"],
            ["Fix windows", inp.fix_windows.map((w) => w.hours).join(" · ") + " h", "Model setting", "Set"],
          ].map((r) => h("tr", {}, r.map((c) => h("td", { text: c })))))) ),
        h("p", { class: "note", text: "Values tied to policy appear here only after the public-release review." })]],
      ["model", "The model", [
        h("ol", { class: "steps" },
          h("li", {}, h("strong", { text: "Simulate" }), h("p", { text: "Each run draws breaks, aborts and fix times for every aircraft and every sortie, on a timeline of goes." })),
          h("li", {}, h("strong", { text: "Recover" }), h("p", { text: "Scheduled spares cover losses, or fleet flex also lets idle mission-capable aircraft step in, within each fix window." })),
          h("li", {}, h("strong", { text: "Score" }), h("p", { text: "A week passes only if sorties, the schedule, availability, commit, recovery and backlog all hold." }))),
        h("p", {}, "Full detail, rule by rule: ", h("a", { href: `${REPO}/blob/main/docs/MODEL_LOGIC.md`, text: "MODEL_LOGIC.md" }))]],
      ["validation", "Validation", [
        h("ul", { class: "checklist" }, [
          ["Same seed reproduces the same results, and run records can be re-verified", "Done"],
          ["The fast engine matches the readable reference engine on randomized scenarios", "Done"],
          ["Golden outputs unchanged through the move to the kit layout", "Done"],
          ["Simple cases match hand-worked examples (for example, a 2-hour fix makes a 3-hour turn)", "Done"],
          ["Every rule documented and tied to its code and a test", "Done"],
          ["Sensitivity: how far each rate can slip before the plan fails (in Run ▸)", "Done"],
          ["Backtest against real past weeks", "Planned"],
        ].map(([t, st]) => h("li", {}, h("span", { class: `check-status check-${st.toLowerCase()}`, text: st }), h("span", { text: t })))),
        h("p", { class: "note", text: "Done means covered by tests that run on every deploy." })]],
      ["limits", "Limits", [h("p", { text: "Public or synthetic inputs only, so results show the method, not any unit's readiness. Breaks are independent draws; real fleets have correlated failures. Parts supply and manpower aren't modeled yet. Sorties that cross midnight or leave home station (mobility, bomber) aren't supported." })]],
      ["changelog", "Changelog", [
        h("ul", { class: "changelog" }, state.changelog.slice(0, 4).map((c) => h("li", {},
          h("span", { class: "num", text: c.version }), ` · ${c.date} · `, c.changes[0] || ""))),
        h("p", {}, h("a", { href: `${REPO}/blob/main/CHANGELOG.md`, text: "Full changelog" }))]],
    ];
    const phone = window.matchMedia("(max-width: 720px)").matches;
    $page("method").replaceChildren(h("div", { class: "method-grid" },
      h("nav", { class: "method-nav", "aria-label": "On this page" },
        h("p", { class: "eyebrow", text: "On this page" }),
        sections.map(([id, title]) => h("button", { type: "button", class: "link-button", text: title,
          onclick: () => { const d = $(`#m-${id}`); d.open = true; d.scrollIntoView({ behavior: "smooth", block: "start" }); } }))),
      h("div", { class: "method-body" }, sections.map(([id, title, body], i) => h("details", { id: `m-${id}`, class: "card method-section", open: !phone || i === 0 },
        h("summary", {}, h("h3", { text: title })), body)))));
  }

  /* ---------------------------------------------------------------- routing */
  const PAGES = ["overview", "results", "method", "run"];
  const $ = (sel) => document.querySelector(sel);
  const $page = (name) => document.getElementById(`page-${name}`);
  let pendingDraw = null;
  function drawWhenVisible(fn) { pendingDraw = fn; if (!$page("results").hidden) { requestAnimationFrame(() => { fn(); pendingDraw = null; }); } }

  function route() {
    const page = PAGES.includes(location.hash.slice(1)) ? location.hash.slice(1) : "overview";
    PAGES.forEach((name) => { $page(name).hidden = name !== page; });
    document.querySelectorAll(".app-tabs a[data-page]").forEach((a) => {
      if (a.dataset.page === page) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    if (page === "run" && window.startPlanner) window.startPlanner();
    if (page === "results" && pendingDraw) requestAnimationFrame(() => { pendingDraw(); pendingDraw = null; });
    window.scrollTo(0, 0);
  }

  async function init() {
    try {
      state.index = await getJSON("data/presets.json");
      state.changelog = await getJSON("data/changelog.json").catch(() => []);
      const [unit, scenario, recovery] = state.index.default.split("__");
      state.pick = { unit, scenario, recovery };
      await loadPreset();
      renderOverview(); renderResults(); renderMethod();
    } catch (error) {
      $page("overview").replaceChildren(h("p", { class: "message message-error", text: `The results didn't load (${error.message}). Run scripts/export_site.py to build them.` }));
    }
    window.addEventListener("hashchange", route);
    route();
  }
  init();
})();
