"""JSON-in, JSON-out functions the browser worker calls through Pyodide."""
from __future__ import annotations

import json

from tps_core import _build
from tps_core.levers import build_levers, sustainable_candidates
from tps_core.patterns import analyze as analyze_patterns, generate as generate_patterns
from tps_core.replay import replay as replay_week
from tps_core.runs import run_plan, verify_record
from tps_core.schemas import ConfigError, load_scenario, plan_warnings, validate_config
from tps_core.sweep import plan_sweep
from tps_core.version import __version__


def _optional_int(value) -> int | None:
    """A whole number, or None for missing. In Pyodide, a JavaScript null or undefined
    arrives as a JsNull / JsUndefined object rather than None, so treat those as missing too."""
    if value is None or type(value).__name__ in ("JsNull", "JsUndefined"):
        return None
    return int(value)


def build_info() -> str:
    return json.dumps({"model_version": __version__, "build_commit": _build.COMMIT, "built_at": _build.BUILT_AT})


def check(config_json: str) -> str:
    try:
        config = json.loads(config_json)
    except json.JSONDecodeError as error:
        return json.dumps({"errors": [f"Not valid JSON: {error}"], "warnings": []})
    errors = validate_config(config)
    warnings = [] if errors else plan_warnings(load_scenario(config))
    return json.dumps({"errors": errors, "warnings": warnings})


def run(config_json: str, iterations: int, seed) -> str:
    try:
        record = run_plan(json.loads(config_json), int(iterations), _optional_int(seed))
    except ConfigError as error:
        return json.dumps({"errors": error.errors})
    return json.dumps(record)


def verify(record_json: str) -> str:
    try:
        return json.dumps(verify_record(json.loads(record_json)))
    except (ConfigError, KeyError, TypeError, ValueError) as error:
        return json.dumps({"identical": False, "problems": [f"This file isn't a readable run record: {error}"]})


def sweep_jobs(config_json: str, variants_json: str, seed) -> str:
    return json.dumps(plan_sweep(json.loads(config_json), json.loads(variants_json), _optional_int(seed)))


def levers(config_json: str, metrics_json: str) -> str:
    return json.dumps(build_levers(json.loads(config_json), json.loads(metrics_json)))


def candidates(config_json: str) -> str:
    return json.dumps(sustainable_candidates(json.loads(config_json)))


def patterns_generate(config_json: str, options_json: str) -> str:
    options = json.loads(options_json)
    return json.dumps(generate_patterns(
        json.loads(config_json),
        mode=options.get("mode", "band"),
        custom=options.get("custom"),
        budget=int(options.get("budget", 180)),
        split_styles=tuple(options.get("splits", ["step", "even"])),
        seed=int(options.get("seed", 0)),
    ))


def patterns_analyze(config_json: str, results_json: str, success_target: float) -> str:
    return json.dumps(analyze_patterns(json.loads(config_json), json.loads(results_json), float(success_target)))


def replay(config_json: str, seed: int, week_index: int) -> str:
    try:
        return json.dumps(replay_week(json.loads(config_json), int(seed), int(week_index)))
    except (ConfigError, ValueError) as error:
        return json.dumps({"errors": getattr(error, "errors", [str(error)])})


def tempo(sute_json: str, pai: int, flying_days: int) -> str:
    """Live check for the form: what the deployed figures work out to [M-9]."""
    from tps_core.tempo import home_requirements, solve_tempo
    result = solve_tempo(json.loads(sute_json))
    if result["sute"] and pai:
        result["requirements"] = home_requirements(result["sute"], int(pai), int(flying_days))
    return json.dumps(result)


def break_even(config_json: str, name: str, seed: int, iterations: int, bar: float) -> str:
    from tps_core.sensitivity import break_even as find, describe
    result = find(json.loads(config_json), str(name), int(seed), int(iterations), float(bar))
    result["sentence"] = describe(result)
    return json.dumps(result)


def backtest_prepare(csv_text: str, config_json: str, lookback: int) -> str:
    from tps_core.backtest import prepare
    try:
        return json.dumps(prepare(str(csv_text), json.loads(config_json), int(lookback)))
    except (ValueError, KeyError) as error:
        return json.dumps({"errors": [str(error)]})


def backtest_summarize(prepared_json: str, metrics_json: str) -> str:
    from tps_core.backtest import summarize
    return json.dumps(summarize(json.loads(prepared_json), json.loads(metrics_json)))


def backtest_synthetic(config_json: str, weeks: int, seed: int) -> str:
    from tps_core.backtest import synthetic_history
    return json.dumps({"csv": synthetic_history(json.loads(config_json), int(weeks), int(seed))})


def backtest_template(config_json: str) -> str:
    from tps_core.backtest import template
    return json.dumps({"csv": template(json.loads(config_json))})
