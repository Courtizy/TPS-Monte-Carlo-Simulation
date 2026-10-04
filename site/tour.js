/* Guided tours. The results tour switches presets; the planner tour edits the plan and runs the engine.
   Every number in the text is read from the page at that moment, never typed in.
   ← → move, Esc closes. Each tour puts back what it changed. */
(() => {
  const pct = (v) => `${Math.round(v * 100)}%`;
  const pts = (a, b) => { const d = Math.round((b - a) * 100); return d === 0 ? "no change" : `${d > 0 ? "+" : "−"}${Math.abs(d)} points`; };
  const q = (sel) => document.querySelector(sel);
  // 2407 adds per week, said the way a planner would: "0.4 a week", or "about one every 25 weeks" when rare.
  const perWeek = (v) => (v >= 0.95 ? `about ${v.toFixed(1)} a week` : v >= 0.005 ? `about one every ${Math.round(1 / v)} weeks` : "almost never");
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  async function waitFor(test, timeout = 120000) {
    const start = Date.now();
    while (Date.now() - start < timeout) { const v = test(); if (v) return v; await sleep(150); }
    throw new Error("timed out");
  }
  const go = async (page) => { if (location.hash !== `#${page}`) { location.hash = page; await sleep(250); } };

  /* ------------------------------------------------ results tour */
  const site = () => window.tpsSite;
  const kpi = () => site().preset().kpis;
  const dayRow = (name) => site().preset().days.find((d) => d.day === name);
  const RESULTS = [
    { page: "overview", target: ".ov-answer", title: "The answer first",
      text: () => `For the default preset, ${pct(kpi().weeks_meeting_every_requirement)} of simulated weeks meet every requirement: every planned sortie flown, the weekly total met, and enough aircraft ready next Monday.` },
    { page: "overview", target: ".ov-answer .status", title: "Where it breaks",
      text: () => "The binding constraint is the requirement most likely to fail. The rest of the tour shows what moves it." },
    { page: "results", action: () => site().pick(site().defaultPick()), target: ".res-left", title: "Pick what to look at",
      text: "Choose a unit, a scenario and a recovery model. Each combination was run by the engine ahead of time; nothing is calculated in your browser here." },
    { page: "results", target: ".kpis", title: "Four numbers",
      text: () => `Weeks meeting every requirement (${pct(kpi().weeks_meeting_every_requirement)}), sorties actually flown against scheduled, aircraft available at a typical first launch, and aircraft ready next Monday against the ${kpi().recovery_target} needed.` },
    { page: "results", target: "#res-chart-slot", title: "Margin by day",
      text: "Bars are the median aircraft available at each day's first launch; whiskers show the middle 80% of weeks; the dashed line is what the day needs. Where a whisker dips below its line, bad weeks run short." },
    { page: "results", target: "#page-results .data-table", title: "Day by day",
      text: "The chance each day flies its full plan, and a status with its label: on track, at risk, or shortfall. Next Monday is the recovery check." },
    { page: "results", target: ".kpi--main", title: "Change the recovery model",
      action: async (ctx) => { ctx.base = kpi().weeks_meeting_every_requirement; ctx.baseAdds = kpi().adds_2407_per_week; await site().pick({ recovery: "flex" }); },
      text: (ctx) => `Switched to fleet flex: ${pct(ctx.base)} → ${pct(kpi().weeks_meeting_every_requirement)} (${pts(ctx.base, kpi().weeks_meeting_every_requirement)}). Idle mission-capable aircraft now cover losses the spares couldn't, using an unplanned aircraft (2407 add) ${perWeek(kpi().adds_2407_per_week)}.` },
    { page: "results", target: "#page-results tbody tr:last-child", title: "Short on weekend repairs",
      action: async (ctx) => { await site().pick({ recovery: "spares", scenario: "baseline" }); ctx.monBase = dayRow("Next Mon").p_day_met;
        await site().pick({ scenario: "short_staffed" }); },
      text: (ctx) => `Short-staffed recovery removes weekend repair hours and slows every fix: the chance of enough aircraft next Monday goes ${pct(ctx.monBase)} → ${pct(dayRow("Next Mon").p_day_met)}. Recovery, not the flying days, is what this lever hits.` },
    { page: "results", target: ".kpi--main", title: "Ask for more flying",
      action: async (ctx) => { await site().pick({ scenario: "baseline" }); ctx.surgeBase = kpi().weeks_meeting_every_requirement;
        ctx.sortiesBase = site().preset().simulation.inputs.weekly_sorties; await site().pick({ scenario: "surge" }); },
      text: (ctx) => {
        const now = kpi().weeks_meeting_every_requirement, sorties = site().preset().simulation.inputs.weekly_sorties;
        const why = now >= ctx.surgeBase
          ? " It can rise: a bigger first go rounds up to another scheduled spare, which can cover more aborts."
          : " More sorties means more breaks and aborts to absorb with the same fleet.";
        return `A surge week plans ${sorties} sorties instead of ${ctx.sortiesBase}: ${pct(ctx.surgeBase)} → ${pct(now)}.${why}`;
      } },
    { page: "results", target: ".res-left .chooser", title: "A different unit",
      action: async (ctx) => { await site().pick({ scenario: "baseline", recovery: "spares" }); ctx.unitBase = kpi().weeks_meeting_every_requirement;
        ctx.unitName = site().preset().unit_name; const other = site().preset().unit === "synthetic_3go" ? "synthetic_4go" : "synthetic_3go";
        await site().pick({ unit: other }); },
      text: (ctx) => {
        const now = kpi().weeks_meeting_every_requirement, goes = site().preset().simulation.inputs.goes_per_day;
        const why = now < ctx.unitBase
          ? ` With ${goes} goes a day, turns are shorter, so a broken aircraft has less time to be fixed before it's needed again.`
          : ` Its plan leaves more slack for its fleet, even with ${goes} goes a day.`;
        return `Same baseline week and recovery model on ${site().preset().unit_name}: ${pct(now)}, against ${pct(ctx.unitBase)} for ${ctx.unitName}.${why}`;
      } },
    { page: "results", target: ".res-left .assumptions", title: "What went in",
      text: () => `Every preset lists its inputs and how it was run (${site().preset().simulation.runs_used.toLocaleString()} runs, seed ${site().preset().simulation.seed}). Download the JSON to check any number.` },
    { page: "method", target: "#m-validation", title: "How far to trust it",
      action: () => { const d = q("#m-validation"); if (d) d.open = true; },
      text: "Done means covered by tests that run on every deploy. Backtesting against real weeks is still planned, so these results show the method, not any unit's readiness." },
    { page: "method", target: ".tour-strip", title: "Try it yourself",
      action: () => site().pick(site().defaultPick()),
      text: "The planner tour runs the engine on a plan you can edit. Use public or synthetic values only." , next: "planner" },
  ];

  /* ------------------------------------------------ planner tour */
  const record = () => (typeof lastRecord !== "undefined" ? lastRecord : null);
  async function runPlanner(ctx, change) {
    if (typeof setPlanCollapsed === "function") setPlanCollapsed(false);
    const cfg = structuredClone(ctx.original);
    if (change) change(cfg);
    loadConfig(cfg);
    await sleep(300);
    q("#seed").value = "42";
    q("#iterations").value = "1000";
    const before = record();
    await waitFor(() => !q("#run").disabled);
    q("#run").click();
    await waitFor(() => record() && record() !== before && !q("#run").disabled, 180000);
    await sleep(400);
    return record().metrics;
  }
  const openSection = (key) => { if (typeof setPlanCollapsed === "function") setPlanCollapsed(false); const d = q(`details[data-sec="${key}"]`); if (d) d.open = true; };
  const PLANNER = [
    { page: "run", target: ".run-intro", title: "Your own week",
      action: async () => { await waitFor(() => !q("#run").disabled, 120000); },
      text: "The planner runs the same engine in your browser. Nothing is sent to a server, but use public or synthetic values only." },
    { page: "run", target: "#example-picker", title: "Start from an example",
      action: async (ctx) => {
        if (typeof setPlanCollapsed === "function") setPlanCollapsed(false);
        const pick = q("#example-picker"); pick.value = "synthetic_week.json"; pick.dispatchEvent(new Event("change"));
        await sleep(800); ctx.original = formToConfig(); },
      text: "The synthetic 2-go unit: 18 aircraft, two goes a day. Every field below is an input you can change." },
    { page: "run", target: "#grid-body", title: "The week's plan",
      action: () => openSection("plan"),
      text: "Sorties on each go, each day. Later goes fly aircraft back from earlier goes. Grey spares come from the spare rate." },
    { page: "run", target: "#summary", title: "Run it",
      action: async (ctx) => { ctx.base = await runPlanner(ctx); },
      text: (ctx) => `1,000 simulated weeks: ${pct(ctx.base.probability_success)} meet every requirement. The weakest day is ${ctx.base.weakest_day || "none"}.` },
    { page: "run", target: "section.card:has(#where-h)", title: "Where it runs tight",
      text: "Aircraft ready against aircraft needed each day, and each day's chance of missing its plan." },
    { page: "run", target: "section.card:has(#why-h)", title: "Why sorties are lost",
      text: () => { const c = record().metrics.causes; return c.main_cause ? `Every lost sortie is traced to a cause. Here the biggest is ${{ lost_abort_uncovered: "ground aborts using up the spares", lost_turn_short: "breaks not fixed before the next go", lost_first_go_short: "days starting short of aircraft" }[c.main_cause]}.` : "No sorties were lost in these weeks."; } },
    { page: "run", target: "#watch-out", title: "Watch a week",
      action: async () => { await waitFor(() => q("#watch-out .board-svg"), 60000); },
      text: "One failed week replayed exactly: what every aircraft did, step by step, and why it fell short." },
    { page: "run", target: "#summary", title: "Let idle aircraft cover losses",
      action: async (ctx) => { ctx.flex = await runPlanner(ctx, (c) => { c.options.allow_2407_adds = true; }); },
      text: (ctx) => `Allowing 2407 adds: ${pct(ctx.base.probability_success)} → ${pct(ctx.flex.probability_success)} (${pts(ctx.base.probability_success, ctx.flex.probability_success)}), using an unplanned aircraft ${perWeek(ctx.flex.reported.mean_2407_adds_per_week)}.` },
    { page: "run", target: "#summary", title: "Break more often",
      action: async (ctx) => { ctx.breaks = await runPlanner(ctx, (c) => { c.rates.break_rate = Math.min(0.9, c.rates.break_rate + 0.05); }); },
      text: (ctx) => `The same plan with breaks 5 points more likely (${pct(ctx.original.rates.break_rate)} → ${pct(Math.min(0.9, ctx.original.rates.break_rate + 0.05))}): ${pct(ctx.base.probability_success)} → ${pct(ctx.breaks.probability_success)}. Back to the original plan next.` },
    { page: "run", target: "#fixes-out", title: "What would fix it",
      action: async (ctx) => { await runPlanner(ctx); q("section.card:has(#fix-h) button.secondary").click(); await waitFor(() => q("#fixes-out table"), 180000); },
      text: () => { const row = q("#fixes-out tbody tr:nth-child(2)"); return row ? `Each change runs on the same seed, so the difference comes from the change. Top of the list: ${row.querySelector("td").textContent}.` : "Each change runs on the same seed, so the difference comes from the change."; } },
    { page: "run", target: ".view-toggle", title: "Three views of the same run",
      action: async () => { q(".view-toggle button[data-view='lead']").click(); await sleep(800); },
      text: "Leadership sees the verdict, what the plan costs, and the decisions. Planner and Analyst add the detail and the evidence." },
    { page: "run", target: "section.card:has(#patterns-h)", title: "Search turn patterns",
      action: async () => { q(".view-toggle button[data-view='plan']").click(); await sleep(500); },
      text: "Tests many week shapes (waterfall, flat, recovery valley and more) at the sortie levels you choose, and says which hold." },
    { page: "run", target: "#backtest", title: "Check it against past weeks",
      text: "Load a history file, or try the synthetic history, to see whether weeks rated 80% held about 80% of the time. Public or synthetic history only on this site." },
    { page: "run", target: ".run-intro", title: "Your turn",
      action: async (ctx) => { loadConfig(ctx.original); await sleep(300); },
      text: "The plan is back as it was. Change any input and run it again." },
  ];

  /* ------------------------------------------------ the tour box */
  const TOURS = { results: RESULTS, planner: PLANNER };
  let tour = null;

  function box() {
    let el = q("#tour-box");
    if (!el) {
      el = document.createElement("div");
      el.id = "tour-box"; el.className = "tour-box"; el.setAttribute("role", "dialog"); el.setAttribute("aria-live", "polite"); el.setAttribute("aria-label", "Guided tour");
      el.innerHTML = '<p class="tour-count"></p><h3 class="tour-title"></h3><p class="tour-text"></p>' +
        '<div class="tour-buttons"><button type="button" class="secondary small" data-act="back">← Back</button>' +
        '<button type="button" class="primary small" data-act="next">Next →</button><button type="button" class="link-button" data-act="close">Close</button></div>';
      el.addEventListener("click", (e) => { const act = e.target.dataset.act; if (act === "next") step(1); if (act === "back") step(-1); if (act === "close") end(); });
      document.body.append(el);
    }
    return el;
  }
  function clearFocus() { document.querySelectorAll(".tour-target").forEach((n) => n.classList.remove("tour-target")); }

  async function show(i) {
    const steps = TOURS[tour.name];
    tour.i = Math.max(0, Math.min(steps.length - 1, i));
    const s = steps[tour.i], el = box();
    el.querySelector(".tour-count").textContent = `${tour.name === "results" ? "Results" : "Planner"} tour · ${tour.i + 1} of ${steps.length}`;
    el.querySelector(".tour-title").textContent = s.title;
    el.querySelector(".tour-text").textContent = "Working…";
    el.querySelectorAll("button").forEach((b) => { b.disabled = true; });
    clearFocus();
    const token = (tour.token = (tour.token || 0) + 1);
    try {
      await go(s.page);
      if (s.action) await s.action(tour.ctx);
      if (!tour || tour.token !== token) return;
      const target = q(s.target);
      if (target) { target.classList.add("tour-target"); target.scrollIntoView({ behavior: "smooth", block: "center" }); }
      el.querySelector(".tour-text").textContent = typeof s.text === "function" ? s.text(tour.ctx) : s.text;
    } catch (error) {
      el.querySelector(".tour-text").textContent = `This step couldn't finish (${error.message}). Use Next to keep going.`;
    }
    el.querySelectorAll("button").forEach((b) => { b.disabled = false; });
    el.querySelector("[data-act=back]").disabled = tour.i === 0;
    const last = tour.i === steps.length - 1;
    el.querySelector("[data-act=next]").textContent = last ? (s.next ? "Start the planner tour →" : "Finish") : "Next →";
  }
  function step(d) {
    const steps = TOURS[tour.name];
    if (d > 0 && tour.i === steps.length - 1) { const next = steps[tour.i].next; end(); if (next) start(next); return; }
    show(tour.i + d);
  }
  function start(name) { end(); tour = { name, i: 0, ctx: {} }; show(0); }
  function end() {
    if (!tour) return;
    const { name, ctx } = tour;
    tour = null; clearFocus();
    const el = q("#tour-box"); if (el) el.remove();
    // Put back what the tour changed.
    if (name === "results" && site() && site().ready()) site().pick(site().defaultPick());
    if (name === "planner" && ctx.original && typeof loadConfig === "function") loadConfig(ctx.original);
  }
  document.addEventListener("keydown", (e) => {
    if (!tour || e.target.closest("input, select, textarea")) return;
    if (e.key === "ArrowRight") step(1);
    if (e.key === "ArrowLeft" && tour.i > 0) step(-1);
    if (e.key === "Escape") end();
  });
  document.addEventListener("click", (e) => { const b = e.target.closest("[data-tour]"); if (b) start(b.dataset.tour); });
  window.tpsTour = { start, end };
})();
