"""Margin, causes, levers, and the sustainable-plan search (model 0.2)."""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from helpers import example  # noqa: E402
from test_engine_equivalence import _random_config  # noqa: E402
from tps_core.L1_engine.engine import compile_plan, run_compiled_week  # noqa: E402
from tps_core.L3_levers.levers import build_levers, sustainable_candidates  # noqa: E402
from tps_core.L4_evidence.runs import run_plan  # noqa: E402
from tps_core.L0_inputs.schemas import load_scenario, plan_warnings, validate_config  # noqa: E402
from tps_core.L3_levers.sweep import apply_patch  # noqa: E402

CAUSES = ("lost_first_go_short", "lost_turn_short", "lost_abort_uncovered")


# [M-5]
def test_causes_always_add_up_to_lost_sorties():
    cases = random.Random(5)
    for _ in range(120):
        scenario = load_scenario(_random_config(cases))
        plan, rng = compile_plan(scenario), random.Random(cases.randrange(10**9))
        for _ in range(10):
            for day in run_compiled_week(plan, rng)[0]:
                assert sum(day[k] for k in CAUSES) == day["lost_sorties"]


# [R-1]
def test_short_fleet_is_blamed_on_the_first_go():
    config = example(inventory={"pai": 4}, rates={"mc_rate": 1.0, "break_rate": 0.0, "ground_abort_rate": 0.0},
                     schedule={"Mon": {"first_go": 6, "second_go": 0}}, rules={"spare_rate": 0.0})
    monday = run_plan(config, 50, 1)["metrics"]["daily"]["Mon"]
    assert monday["mean_lost_first_go_short"] == 2 and monday["share_short_aircraft"] == 1.0


# [M-2]
def test_margin_fields_are_ordered_and_sensible():
    m = run_plan(example(), 2000, 3)["metrics"]
    for day, stats in m["daily"].items():
        assert stats["ready_p10"] <= stats["ready_p50"] <= stats["ready_p90"]
    assert m["daily"]["Mon"]["aircraft_needed"] == 6 + 2
    assert m["recovery"]["target"] == 8
    assert m["weakest_day"] in ("Mon", "Tue", "Wed", "Thu", "Fri", None)
    shares = m["causes"]["all_weeks"]["shares"]
    assert abs(sum(shares.values()) - 1) < 1e-9 or m["causes"]["all_weeks"]["lost_sorties"] == 0


# [L-1]
def test_levers_are_valid_configs_with_costs():
    config = example()
    metrics = run_plan(config, 2000, 3)["metrics"]
    levers = build_levers(config, metrics)
    assert levers[0]["kind"] == "baseline"
    for lever in levers:
        patched = apply_patch(config, lever["patch"])
        assert validate_config(patched) == [], lever["label"]
        assert lever["cost"]
    labels = [lever["label"] for lever in levers]
    assert "Allow 2407 adds" in labels and "Weekend repairs around the clock" in labels


def test_more_spares_everywhere_notes_the_higher_recovery_target():
    config = example()
    levers = build_levers(config, run_plan(config, 1000, 3)["metrics"])
    every = next(lv for lv in levers if lv["label"] == "One more spare every day")
    assert "recovery target" in every["cost"]


def test_candidates_fit_the_rules_and_run():
    config = example()
    candidates = sustainable_candidates(config)
    assert candidates and candidates[0]["weekly_sorties"] >= candidates[-1]["weekly_sorties"]
    for candidate in candidates:
        scenario = load_scenario(apply_patch(config, candidate["patch"]))
        rule_breaks = [w for w in plan_warnings(scenario) if "Required sorties" not in w]
        assert rule_breaks == [], (candidate["label"], rule_breaks)
