"""Direct tests for rules in MODEL_LOGIC.md that were only covered indirectly before."""
import sys
from pathlib import Path
from random import Random

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from helpers import example  # noqa: E402
from tps.L1_engine.engine import _Draws, run_week  # noqa: E402
from tps.L0_inputs.rules import RuleSet, aircraft_required, calculated_spares, commit_aircraft, day_spares, risk_band  # noqa: E402
from tps.L4_evidence.runs import run_plan  # noqa: E402
from tps.L0_inputs.schemas import DayPlan, load_scenario  # noqa: E402

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri")


def _week(schedule, *, pai=8, breaks=0.0, aborts=0.0, fixes=((8, 0.0),), spares_cover=None, **options):
    config = example(
        inventory={"pai": pai},
        rates={"mc_rate": 1.0, "break_rate": breaks, "ground_abort_rate": aborts,
               "fix_windows": [{"hours": h, "rate": r} for h, r in fixes]},
        rules={"spare_rate": 0.0, "max_second_go": None, "max_daily_sorties": None, "max_day_to_day_delta": None},
        schedule=schedule, required_sorties=0,
        options={"event_mode": "Spreadsheet", "fix_mode": "Expected", "repeat_rate": 0.0, "recur_rate": 0.0,
                 "spares_cover_goes": spares_cover, **options},
    )
    return run_week(load_scenario(config), Random(0))


# [R-2] [R-3] [R-4]
def test_commit_spares_and_front_line_math():
    rules = RuleSet(commit_rate=0.55, spare_rate=0.20)
    assert commit_aircraft(18, rules) == 9            # floor(9.9)
    assert calculated_spares(6, rules) == 2           # ceil(1.2)
    assert calculated_spares(5, rules) == 1           # ceil(1.0)
    assert day_spares(DayPlan(6, 3, spares=0), rules) == 0
    assert aircraft_required(DayPlan(6, 3), rules) == 8


# [E-2]
def test_fully_random_breaks_match_the_rate():
    config = example(inventory={"pai": 40}, rates={"mc_rate": 1.0, "fix_windows": [{"hours": 8, "rate": 1.0}]},
                     options={"event_mode": "Fully Random", "repeat_rate": 0.0, "recur_rate": 0.0})
    scenario = load_scenario(config)
    rng = Random(4)
    breaks = flown = 0
    for _ in range(600):
        for day in run_week(scenario, rng)[0]:
            breaks += day["code_3"]
            flown += day["sorties_flown"]
    assert breaks / flown == pytest.approx(0.25, abs=0.01)


# [E-3] [S-1]
def test_a_spare_replaces_an_abort():
    # Two sorties, one abort (on the second), one spare: the spare flies it.
    with_spare, _ = _week({"Mon": {"first_go": 2, "spares": 1}}, pai=3, aborts=0.5)
    without, _ = _week({"Mon": {"first_go": 2, "spares": 0}}, pai=2, aborts=0.5)
    assert (with_spare[0]["sorties_flown"], with_spare[0]["covered_ground_abort"], with_spare[0]["spares_used"]) == (2, 1, 1)
    assert (without[0]["sorties_flown"], without[0]["lost_sorties"]) == (1, 1)


# [E-5]
def test_events_on_lost_sorties_do_not_happen():
    # One aircraft, two planned first-go sorties, every sortie planned to break: only the flown one breaks.
    monday = _week({"Mon": {"first_go": 2}}, pai=1, breaks=1.0)[0][0]
    assert monday["sorties_flown"] == 1 and monday["lost_sorties"] == 1 and monday["code_3"] == 1


# [S-2]
def test_spares_limited_to_the_first_go():
    schedule = {"Mon": {"first_go": 4, "second_go": 4, "spares": 2}}
    any_go = _week(schedule, pai=6, breaks=1.0)[0][0]
    first_only = _week(schedule, pai=6, breaks=1.0, spares_cover=[1])[0][0]
    assert any_go["flown_by_go"][1] == 2 and first_only["flown_by_go"][1] == 0


# [F-5]
def test_expected_draws_match_the_rates():
    draws = _Draws(Random(0), expected=True, offset=0.0)
    values = [draws.next() for _ in range(2000)]
    for rate in (0.25, 0.45, 0.8):
        assert sum(v < rate for v in values) / 2000 == pytest.approx(rate, abs=0.005)


# [F-6]
def test_repeat_rebreaks_a_fixed_aircraft():
    # One aircraft flying once a day; Wednesday's sortie breaks and is fixed in 8 hours.
    schedule = {d: {"first_go": 1} for d in DAYS}
    no_repeat = _week(schedule, pai=1, breaks=0.2, fixes=((8, 1.0),))[0]
    repeat = _week(schedule, pai=1, breaks=0.2, fixes=((8, 1.0),), repeat_rate=1.0)[0]
    assert sum(d["repeat_recur_events"] for d in no_repeat) == 0
    assert sum(d["repeat_recur_events"] for d in repeat) >= 1
    assert sum(d["code_3"] for d in repeat) > sum(d["code_3"] for d in no_repeat)


# [M-1] [M-3]
def test_backlog_is_reported_not_pass_fail_by_default():
    reported = run_plan(example(), 400, 2)["metrics"]
    assert reported["components"]["backlog_within_limit"] == 1.0
    assert reported["distributions"]["repair_backlog"]["mean"] > 0
    strict = run_plan(example(success={"minimum_monday_aircraft": None, "backlog_threshold": 0}), 400, 2)["metrics"]
    assert strict["components"]["backlog_within_limit"] < 1.0
    assert strict["probability_success"] <= reported["probability_success"]


# [M-8]
def test_risk_bands():
    assert [risk_band(p) for p in (0.90, 0.85, 0.75, 0.60, 0.40)] == ["Green", "Green", "Yellow", "Orange", "Red"]
