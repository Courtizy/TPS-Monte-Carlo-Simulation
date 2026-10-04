"""Risk by go, convergence, break-even margins, moving a sortie, and the efficient frontier."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from helpers import example  # noqa: E402
from tps import web_api  # noqa: E402
from tps.L3_levers.levers import build_levers  # noqa: E402
from tps.L3_levers.patterns import efficient_frontier  # noqa: E402
from tps.L4_evidence.runs import run_plan  # noqa: E402
from tps.L0_inputs.schemas import load_scenario, plan_warnings  # noqa: E402
from tps.L3_levers.sensitivity import break_even, describe  # noqa: E402
from tps.L3_levers.sweep import apply_patch  # noqa: E402


# [M-10]
def test_go_risk_and_daily_use():
    r = run_plan(example(), 800, 2)
    wed = r["metrics"]["daily"]["Wed"]
    assert wed["planned_by_go"][:2] == [5, 3] and wed["spares_planned"] == 1
    assert all(v is None or 0 <= v <= 1 for v in wed["go_miss_share"])
    assert wed["go_miss_share"][2] is None            # no third go planned
    assert 0 <= wed["mean_spares_used"] <= 1
    assert r["plan_facts"]["commit"] == 9 and r["plan_facts"]["spares_per_week"] == 7


# [M-11]
def test_convergence_series_ends_at_the_answer():
    m = run_plan(example(), 1000, 4)["metrics"]
    series = m["convergence"]
    assert series[-1][0] == 1000 and series[-1][1] == pytest.approx(m["probability_success"])
    assert all(low <= p <= high for _, p, low, high in series)
    assert [n for n, *_ in series] == sorted(n for n, *_ in series)


# [M-12]
def test_break_even_finds_the_crossing():
    config = example()
    r = break_even(config, "break_rate", 9, 600, 0.85)
    assert r["status"] in ("holds_until", "reaches_at", "holds_across_range", "cannot_reach")
    if r["status"] == "holds_until":
        assert r["value"] > r["current"]
        above = [p for x, p in r["points"] if x <= r["value"] - 0.01]
        assert min(above) >= 0.85 - 0.03    # same seed: success stays near or above the bar before the edge
    easy = example(rates={"break_rate": 0.0, "ground_abort_rate": 0.0})
    assert break_even(easy, "mc_rate", 9, 200, 0.85)["status"] in ("holds_until", "holds_across_range")
    assert "until" in describe({**r, "status": "holds_until", "value": 0.31, "worse": "up", "event_mode": "Fully Random"})
    sentence = json.loads(web_api.break_even(json.dumps(config), "fix_speed", 9, 200, 0.85))["sentence"]
    assert "fix rates" in sentence


# [L-2]
def test_moves_keep_weekly_sorties_and_rules():
    config = example()
    metrics = run_plan(config, 800, 3)["metrics"]
    moves = [v for v in build_levers(config, metrics) if v["label"].startswith("Move one sortie")]
    assert moves and all(v["group"] == "scheduling" for v in moves)
    before = sum(p.daily_sorties for p in load_scenario(config).schedule.values())
    for move in moves:
        moved = load_scenario(apply_patch(config, move["patch"]))
        assert sum(p.daily_sorties for p in moved.schedule.values()) == before
        assert not [w for w in plan_warnings(moved) if "above commit" in w or "larger than" in w]
    groups = {v["group"] for v in build_levers(config, metrics)}
    assert {"baseline", "maintenance", "scheduling"} <= groups


# [P-7]
def test_frontier_keeps_only_unbeaten_patterns():
    items = [
        {"weekly_sorties": 40, "success": 0.90, "resources": 5},
        {"weekly_sorties": 40, "success": 0.95, "resources": 8},
        {"weekly_sorties": 40, "success": 0.89, "resources": 6},   # beaten by the first on every count
        {"weekly_sorties": 45, "success": 0.86, "resources": 9},
        {"weekly_sorties": 36, "success": 0.90, "resources": 5},   # beaten by the first
    ]
    front = efficient_frontier(items)
    assert [(i["weekly_sorties"], i["success"]) for i in front] == [(40, 0.90), (40, 0.95), (45, 0.86)]
