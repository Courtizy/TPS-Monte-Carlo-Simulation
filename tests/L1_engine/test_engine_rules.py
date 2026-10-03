"""Pins rules confirmed in ASSUMPTIONS.md on the tps_core engine."""
import math
import sys
from pathlib import Path
from random import Random

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from helpers import example  # noqa: E402
from tps_core.L1_engine.engine import coverage_by_day, ready_time, run_week  # noqa: E402
from tps_core.L0_inputs.schemas import DEFAULT_GO_TIMES, Options, load_scenario  # noqa: E402

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "Next Mon")
FULL = coverage_by_day(DAYS, Options(weekend_coverage_hours=(("Sat", 24), ("Sun", 24))))


def next_go(ready_at):
    for index, day in enumerate(DAYS):
        for number, (launch, _) in enumerate(DEFAULT_GO_TIMES[:2], 1):
            if ready_at <= 24 * index + launch:
                return day, number


# [F-2] [T-1]
@pytest.mark.parametrize("event_hour, hours, expected", [
    (26, 8, ("Tue", 2)), (26, 12, ("Wed", 1)), (26, 24, ("Wed", 2)),
    (36, 8, ("Wed", 1)), (36, 12, ("Wed", 1)), (36, 24, ("Thu", 1)),
])
def test_return_timing_table(event_hour, hours, expected):
    assert next_go(ready_time(event_hour, hours, FULL)) == expected


# [F-4]
def test_weekend_clock():
    sat8 = coverage_by_day(DAYS, Options(weekend_coverage_hours=(("Sat", 8), ("Sun", 0))))
    none = coverage_by_day(DAYS, Options(weekend_coverage_hours=(("Sat", 0), ("Sun", 0))))
    assert ready_time(98, 24, sat8) <= 168          # Friday 24-hr fix ready Monday
    assert 168 < ready_time(98, 24, none) <= 178    # no duty: ready for Monday's turn


def _scenario(schedule, **rates):
    base = {"mc_rate": 1.0, "break_rate": 0.0, "ground_abort_rate": 0.0,
            "fix_8hr_rate": 0.0, "fix_12hr_rate": 0.0, "fix_24hr_rate": 0.0}
    base.update(rates)
    return example(inventory={"pai": 8}, rates=base, rules={"spare_rate": 0.0},
                   schedule=schedule, options={"event_mode": "Spreadsheet", "fix_mode": "Expected",
                                               "repeat_rate": 0.0, "recur_rate": 0.0})


# [E-4]
def test_break_costs_the_turn_and_8hr_fix_saves_it():
    lost = run_week(load_scenario(_scenario({"Mon": {"first_go": 4, "second_go": 4}}, break_rate=1.0)), Random(0))[0][0]
    saved = run_week(load_scenario(_scenario({"Mon": {"first_go": 4, "second_go": 4}}, break_rate=1.0,
                                             fix_8hr_rate=1.0, fix_12hr_rate=1.0, fix_24hr_rate=1.0)), Random(0))[0][0]
    assert (lost["sorties_flown"], lost["lost_sorties"]) == (4, 4)
    assert (saved["sorties_flown"], saved["lost_sorties"]) == (8, 0)


# [F-3]
def test_first_day_long_fix_ready_wednesday():
    config = _scenario({"Mon": {"first_go": 1}}, break_rate=1.0, fix_12hr_rate=1.0, fix_24hr_rate=1.0)
    rows = {r["day"]: r for r in run_week(load_scenario(config), Random(0))[0]}
    assert rows["Tue"]["mc_aircraft_for_flying"] == 7 and rows["Wed"]["mc_aircraft_for_flying"] == 8


# [S-3]
def test_2407_adds_cover_losses_and_count_against_commit():
    config = _scenario({"Mon": {"first_go": 4, "second_go": 4}}, break_rate=1.0)
    config["options"]["allow_2407_adds"] = True
    monday = run_week(load_scenario(config), Random(0))[0][0]
    assert monday["adds_2407"] == 4 and monday["lost_sorties"] == 0
    assert monday["actual_exceeds_commit"] and monday["within_ttp_commit"]


# [E-1] [E-2]
def test_fixed_count_places_exact_breaks():
    config = example(inventory={"pai": 40}, rates={"mc_rate": 1.0, "fix_8hr_rate": 1.0, "fix_12hr_rate": 1.0,
                                                   "fix_24hr_rate": 1.0}, options={"repeat_rate": 0.0, "recur_rate": 0.0})
    rows, _ = run_week(load_scenario(config), Random(3))
    assert sum(r["code_3"] for r in rows) == math.ceil(39 * 0.25)
