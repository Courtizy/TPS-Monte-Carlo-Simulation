"""Run a plan and produce an auditable run record.

A run record holds the full config, its fingerprint, the model version and
build commit, the seed, the metrics, and a few example weeks. verify_record()
re-runs a record and checks the metrics come out identical.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from random import Random, SystemRandom
from typing import Any

from tps_core import _build
from tps_core.L1_engine.engine import compile_plan, run_compiled_week
from tps_core.L2_metrics.metrics import summarize
from tps_core.L1_engine.replay import pick_weeks
from tps_core.L0_inputs.schemas import fingerprint, load_scenario, plan_warnings
from tps_core.version import __version__

RECORD_VERSION = "1"
EXAMPLE_FIELDS = (
    "day", "planned_sorties", "sorties_flown", "lost_sorties", "code_3", "ground_abort",
    "covered_ground_abort", "mc_aircraft_for_flying", "available_eod", "aircraft_required",
    "adds_2407", "spares_used", "repeat_recur_events", "planned_by_go", "flown_by_go",
)
MAX_ITERATIONS = 200_000


def new_seed() -> int:
    return SystemRandom().randrange(2**31)


def simulate(config: dict[str, Any], iterations: int, seed: int) -> tuple[list, Any]:
    scenario = load_scenario(config)
    plan = compile_plan(scenario)
    rng = Random(seed)
    return [run_compiled_week(plan, rng) for _ in range(iterations)], scenario


# [A-1]
def run_plan(config: dict[str, Any], iterations: int = 10_000, seed: int | None = None,
             example_weeks: int = 3) -> dict[str, Any]:
    if not 1 <= int(iterations) <= MAX_ITERATIONS:
        raise ValueError(f"iterations must be between 1 and {MAX_ITERATIONS:,}")
    seed = new_seed() if seed is None else int(seed)
    config = copy.deepcopy(config)
    weeks, scenario = simulate(config, int(iterations), seed)
    metrics = summarize(weeks, scenario.rules.flying_days, scenario.rules.all_days,
                        sute_target=scenario.sute_target, sute_ceiling=scenario.sute_ceiling,
                        sute_basis=scenario.sute_basis)
    return {
        "record_version": RECORD_VERSION,
        "model_version": __version__,
        "build_commit": _build.COMMIT,
        "built_at": _build.BUILT_AT,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "name": scenario.name,
        "config": config,
        "config_fingerprint": fingerprint(config),
        "required_sorties": scenario.required_sorties,
        "required_from_sute": scenario.required_from_sute,
        "tempo": _tempo(config),
        "plan_facts": _plan_facts(scenario),
        "goes_per_day": scenario.goes_per_day,
        "go_times": [list(pair) for pair in scenario.options.go_times],
        "iterations": int(iterations),
        "seed": seed,
        "warnings": plan_warnings(scenario),
        "metrics": metrics,
        "metrics_fingerprint": fingerprint(metrics),
        # Weeks worth watching in the play-by-play (0-based); results are unchanged. [X-3]
        "replay_weeks": pick_weeks(weeks, scenario.rules.flying_days),
        "example_weeks": [
            {"week": i + 1, "days": [{k: day[k] for k in EXAMPLE_FIELDS} for day in weeks[i][0]]}
            for i in range(min(example_weeks, len(weeks)))
        ],
    }


def verify_record(record: dict[str, Any]) -> dict[str, Any]:
    """Re-run a record from its config and seed; report whether results match exactly."""
    problems = []
    if fingerprint(record.get("config")) != record.get("config_fingerprint"):
        problems.append("The config was changed after the run (fingerprint differs).")
    if fingerprint(record.get("metrics")) != record.get("metrics_fingerprint"):
        problems.append("The stored metrics were changed after the run (fingerprint differs).")
    rerun = run_plan(record["config"], record["iterations"], record["seed"], example_weeks=0)
    identical = rerun["metrics_fingerprint"] == record.get("metrics_fingerprint")
    same_version = record.get("model_version") == __version__
    if not identical:
        problems.append(
            "Re-running gives different metrics."
            + ("" if same_version else f" The record was made with model {record.get('model_version')}; this is {__version__}.")
        )
    return {
        "identical": identical and not problems,
        "same_model_version": same_version,
        "record_model_version": record.get("model_version"),
        "current_model_version": __version__,
        "expected_fingerprint": record.get("metrics_fingerprint"),
        "rerun_fingerprint": rerun["metrics_fingerprint"],
        "problems": problems,
    }


def _tempo(config: dict[str, Any]) -> dict[str, Any] | None:
    """The deployed tempo as worked out from the config's figures [M-9]."""
    from tps_core.L0_inputs.tempo import solve_tempo
    return solve_tempo(config["sute"]) if config.get("sute") else None


def _plan_facts(scenario) -> dict[str, Any]:
    """What the plan asks of the unit before any luck: commit, front line, and scheduled spares."""
    from tps_core.L0_inputs.rules import aircraft_required, commit_aircraft, day_spares
    rules = scenario.rules
    days = [d for d in rules.flying_days if scenario.schedule[d].daily_sorties]
    return {
        "commit": commit_aircraft(scenario.inventory.pai, rules),
        "max_front_line": max((aircraft_required(scenario.schedule[d], rules) for d in days), default=0),
        "spares_per_week": sum(day_spares(scenario.schedule[d], rules) for d in days),
        "weekend_hours": dict(scenario.options.weekend_coverage_hours),
        "allow_2407_adds": scenario.options.allow_2407_adds,
    }
