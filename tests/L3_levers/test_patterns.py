"""Turn-pattern families, week permutations, go splits, and the requirement check."""
import json
import sys
from pathlib import Path
from random import Random

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from helpers import ROOT, example  # noqa: E402
from tps import web_api  # noqa: E402
from tps.L3_levers.patterns import (  # noqa: E402
    DIAGNOSTIC, FAMILIES, analyze, classify, daily_compositions, generate, split_day, week_targets,
)
from tps.L0_inputs.rules import commit_aircraft, day_spares  # noqa: E402
from tps.L4_evidence.runs import run_plan  # noqa: E402
from tps.L0_inputs.schemas import DayPlan, load_scenario  # noqa: E402
from tps.L3_levers.sweep import plan_sweep  # noqa: E402

THREE_GO = json.loads((ROOT / "configs" / "public" / "synthetic_3go.json").read_text())


# [P-3]
@pytest.mark.parametrize("week, family", [
    ((8, 8, 8, 8, 8), "Flat Turns"),
    ((9, 8, 7, 6, 5), "Waterfall"),
    ((9, 9, 7, 7, 5), "Step-Down"),
    ((5, 6, 7, 8, 9), "Reverse Waterfall"),
    ((5, 5, 7, 7, 9), "Step-Up"),
    ((6, 9, 6, 9, 6), "Sawtooth"),
    ((8, 8, 4, 8, 8), "Recovery Valley"),
    ((6, 7, 9, 7, 6), "Midweek Spike"),
    ((9, 9, 9, 1, 1), "Compressed Surge"),
])
def test_classify(week, family):
    assert classify(week) == family


def test_every_family_is_known_and_diagnostic_ones_are_marked():
    assert DIAGNOSTIC <= set(FAMILIES)
    assert {"Reverse Waterfall", "Back-Loaded Push", "Compressed Surge"} == DIAGNOSTIC


# [P-2]
def test_compositions_respect_total_cap_and_day_to_day_limit():
    weeks = daily_compositions(36, 5, 1, 9, 2, Random(0))
    assert weeks and len(set(weeks)) == len(weeks)
    for week in weeks:
        assert sum(week) == 36 and max(week) <= 9 and min(week) >= 1
        assert all(abs(a - b) <= 2 for a, b in zip(week, week[1:]))


def test_large_spaces_are_sampled_not_listed():
    weeks = daily_compositions(150, 5, 1, 60, None, Random(0))
    assert 0 < len(weeks) <= 4000 and all(sum(w) == 150 for w in weeks)


# [P-4]
@pytest.mark.parametrize("total, goes, style, expected", [
    (9, 2, "step", (6, 3, 0, 0)), (9, 2, "even", (5, 4, 0, 0)),
    (12, 3, "step", (6, 4, 2, 0)), (12, 3, "even", (4, 4, 4, 0)),
    (10, 4, "step", (4, 3, 2, 1)), (2, 3, "even", (1, 1, 0, 0)),
])
def test_split_day(total, goes, style, expected):
    assert split_day(total, goes, style) == expected


# [P-1]
def test_targets_band_includes_requirement_and_stays_sane():
    targets = week_targets(example())
    assert 36 in targets and targets == sorted(targets)
    assert max(week_targets(THREE_GO)) <= 1.5 * 60   # capped at 1.5x the larger of requirement and plan
    assert week_targets(example(), mode="requirement") == [36]
    assert week_targets(example(), mode="custom", custom=[30, 40, 500]) == [30, 40]


# [P-5]
def test_generated_weeks_fit_the_rules_and_cover_families():
    gen = generate(THREE_GO, budget=120, seed=1)
    scenario = load_scenario(THREE_GO)
    commit = commit_aircraft(scenario.inventory.pai, scenario.rules)
    families = set()
    for c in gen["candidates"]:
        families.add(c["family"])
        for day, plan in c["patch"]["schedule"].items():
            p = DayPlan(plan["first_go"], plan["second_go"], plan["third_go"], plan["fourth_go"])
            assert p.first_go + day_spares(p, scenario.rules) <= commit
            assert list(p.goes) == sorted(p.goes, reverse=True)
        if not c["is_current"]:
            assert c["patch"]["required_sorties"] == c["weekly_sorties"] == sum(c["totals"])
    assert len(families) >= 8
    assert sum(c["is_current"] for c in gen["candidates"]) == 1


def _screen(config, budget=60, weeks=300):
    gen = generate(config, budget=budget, seed=3)
    jobs = plan_sweep(config, gen["candidates"], 3)["jobs"]
    return gen, [{**c, "index": j["index"], "metrics": run_plan(j["config"], weeks, 3, example_weeks=0)["metrics"]}
                 for c, j in zip(gen["candidates"], jobs)]


# [P-6]
def test_analysis_never_recommends_diagnostic_families():
    gen, results = _screen(example())
    a = analyze(example(), results, 0.85)
    for row in a["per_target"]:
        assert row["best"] is None or not row["best"]["diagnostic"]
    assert a["focus_target"] == 36
    assert a["verdict"] and "36 sorties a week" in a["verdict"][0]
    assert a["current"] and a["current"]["weekly_sorties"] == 39
    assert set(a["confirm"]) <= set(range(len(results)))


# [P-6]
def test_verdict_reports_the_shortfall_when_the_requirement_is_out_of_reach():
    config = example(required_sorties=44)   # push the requirement up against a demanding bar
    gen, results = _screen(config)
    a = analyze(config, results, 0.99)
    text = " ".join(a["verdict"])
    assert "No pattern tested flies" in text or "sustains up to" in text or "None of the weekly targets" in text


def test_web_api_round_trip():
    gen = json.loads(web_api.patterns_generate(json.dumps(example()), json.dumps({"budget": 30, "seed": 2})))
    assert gen["candidates"] and gen["targets"]
