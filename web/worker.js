/* Runs the tps_core Python package inside the browser with Pyodide.
   Each worker holds its own Python; the page sends requests and gets JSON back.
   Nothing is sent to any server: the model and the data stay in this browser. */

const PYODIDE_VERSION = "0.29.4";
importScripts(`https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/pyodide.js`);

async function boot() {
  const pyodide = await loadPyodide();
  const response = await fetch("tps_core.zip", { cache: "no-cache" });
  if (!response.ok) throw new Error(`Couldn't load the model package (HTTP ${response.status}).`);
  pyodide.unpackArchive(await response.arrayBuffer(), "zip", { extractDir: "/home/pyodide/pkg" });
  pyodide.runPython("import sys; sys.path.insert(0, '/home/pyodide/pkg')");
  return pyodide.pyimport("tps_core.web_api");
}

const ready = boot();

self.onmessage = async (event) => {
  const { id, type, payload } = event.data;
  try {
    const api = await ready;
    let text;
    if (type === "info") text = api.build_info();
    else if (type === "check") text = api.check(payload.config);
    else if (type === "run") text = api.run(payload.config, payload.iterations, payload.seed ?? undefined);
    else if (type === "verify") text = api.verify(payload.record);
    else if (type === "sweep_jobs") text = api.sweep_jobs(payload.config, payload.variants, payload.seed ?? undefined);
    else if (type === "levers") text = api.levers(payload.config, payload.metrics);
    else if (type === "candidates") text = api.candidates(payload.config);
    else if (type === "patterns_generate") text = api.patterns_generate(payload.config, payload.options);
    else if (type === "break_even") text = api.break_even(payload.config, payload.input, payload.seed, payload.iterations, payload.bar);
    else if (type === "backtest_prepare") text = api.backtest_prepare(payload.csv, payload.config, payload.lookback);
    else if (type === "backtest_summarize") text = api.backtest_summarize(payload.prepared, payload.metrics);
    else if (type === "backtest_synthetic") text = api.backtest_synthetic(payload.config, payload.weeks, payload.seed);
    else if (type === "backtest_template") text = api.backtest_template(payload.config);
    else if (type === "tempo") text = api.tempo(payload.sute, payload.pai, payload.days);
    else if (type === "replay") text = api.replay(payload.config, payload.seed, payload.week);
    else if (type === "patterns_analyze") text = api.patterns_analyze(payload.config, payload.results, payload.target);
    else throw new Error(`Unknown request: ${type}`);
    self.postMessage({ id, ok: true, result: JSON.parse(text) });
  } catch (error) {
    self.postMessage({ id, ok: false, error: String((error && error.message) || error) });
  }
};
