"""Backtesting: reading history, rates from earlier weeks only, observable success, and scoring."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import example  # noqa: E402
from tps_core import web_api  # noqa: E402
from tps_core.backtest import parse_history, prepare, summarize, synthetic_history, trailing_rates  # noqa: E402
from tps_core.runs import run_plan  # noqa: E402

HEADER = "week_start,day,pai,mc_at_start,next_monday_mc,required_sorties,planned_go1,planned_go2,spares,flown_go1,flown_go2,breaks,aborts,fixed_8h,fixed_24h\n"


def _week(start, breaks, aborts=0, flown_short=0, mc=14, next_mc=12):
    rows = []
    for i, day in enumerate(("Mon", "Tue", "Wed", "Thu", "Fri")):
        head = f"{start},{day},18,{mc},{next_mc},30" if i == 0 else f"{start},{day},,,,"
        flown2 = 2 - (flown_short if day == "Wed" else 0)
        rows.append(f"{head},4,2,1,4,{flown2},{breaks},{aborts},{breaks},{breaks + aborts}")
    return "\n".join(rows) + "\n"


# [B-1]
def test_rates_come_only_from_earlier_weeks():
    text = HEADER + _week("2025-01-06", 1) + _week("2025-01-13", 1) + _week("2025-01-20", 6)
    history = parse_history(text)
    assert [w["week_start"] for w in history["weeks"]] == ["2025-01-06", "2025-01-13", "2025-01-20"]
    rates = trailing_rates(history["weeks"], 2, history["windows"], lookback=4, min_history=2)
    assert rates["break_rate"] == pytest.approx(10 / 60)       # weeks 1-2 only: 5 breaks each over 30 planned
    assert rates["mc_rate"] == pytest.approx(14 / 18)
    assert [w["rate"] for w in rates["fix_windows"]] == [1.0, 1.0]
    assert trailing_rates(history["weeks"], 1, history["windows"], 4, 2) is None   # not enough history yet
    prepared = prepare(text, example(), lookback=4, min_history=2)
    assert [w["week_start"] for w in prepared["weeks"]] == ["2025-01-20"]
    assert prepared["weeks"][0]["config"]["required_sorties"] == 30


# [B-2]
def test_observable_success_matches_history():
    text = HEADER + _week("2025-01-06", 1) + _week("2025-01-13", 1) + _week("2025-01-20", 1, flown_short=1)
    prepared = prepare(text, example(), min_history=2)
    actual = prepared["weeks"][0]["actual"]
    assert actual["missed_days"] == ["Wed"] and not actual["succeeded"]
    m = run_plan(example(), 500, 1)["metrics"]
    assert 0 <= m["observable"]["flown_and_recovered"] <= m["observable"]["flown"] <= 1
    assert m["probability_success"] <= m["observable"]["flown_and_recovered"] + 1e-9


# [B-3]
def test_scoring_on_known_outcomes():
    weeks = [{"week_start": f"w{i}", "has_recovery": False, "rates": {},
              "actual": {"succeeded": i % 2 == 0, "flown": 30, "planned": 30, "missed_days": [] if i % 2 == 0 else ["Wed"]}}
             for i in range(20)]
    metrics = [{"observable": {"flown": 0.5, "flown_and_recovered": 0.5}, "weakest_day": "Wed",
                "distributions": {"sorties_flown": {"p10": 29, "p50": 30, "p90": 30}},
                "daily": {"Wed": {"share_missing_schedule": 0.4}, "Mon": {"share_missing_schedule": 0.05}}} for _ in weeks]
    r = summarize({"weeks": weeks, "skipped_for_history": [], "problems": [], "lookback": 4}, metrics)
    assert r["weeks"] == 20 and r["observed_success"] == 0.5
    assert r["brier"] == pytest.approx(0.25) and r["skill"] == pytest.approx(0.0)
    assert r["bins"][0]["agrees"] and r["riskiest_day_matched"] == 1.0
    assert r["day_risk_when_missed"] == pytest.approx(0.4)


# [B-4]
def test_synthetic_history_round_trips():
    config = example()
    text = synthetic_history(config, weeks=8, seed=3)
    history = parse_history(text)
    assert len(history["weeks"]) == 8 and history["windows"] == [8.0, 12.0, 24.0] and not history["problems"]
    for week in history["weeks"]:
        for day in week["days"].values():
            assert sum(day["flown"]) <= sum(day["planned"])
            assert day["fixed"][8.0] <= day["fixed"][12.0] <= day["fixed"][24.0] <= day["breaks"] + day["aborts"]
    prepared = prepare(text, config)
    assert len(prepared["weeks"]) == 6
    template = json.loads(web_api.backtest_template(json.dumps(config)))["csv"]
    assert template.startswith("week_start,day,pai")
    assert json.loads(web_api.backtest_prepare("not,a,history\n1,2,3", json.dumps(config), 4))["errors"]
