"""Go profiles, fix windows, the first-day rule, per-go results, and SUTE (model 0.3)."""
import sys
from pathlib import Path
from random import Random

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from helpers import ROOT, example  # noqa: E402
from tps.L1_engine.engine import run_week  # noqa: E402
from tps.L3_levers.levers import sustainable_candidates  # noqa: E402
from tps.L4_evidence.runs import run_plan  # noqa: E402
from tps.L0_inputs.schemas import load_scenario, plan_warnings, profile_go_times, required_from_sute  # noqa: E402

import json  # noqa: E402

THREE_GO = json.loads((ROOT / "configs" / "public" / "synthetic_3go.json").read_text())


# [T-2]
def test_profile_go_times():
    assert profile_go_times(3, 1.5, 3) == ((0, 1.5), (4.5, 6.0), (9.0, 10.5))
    assert profile_go_times(2, 2, 8) == ((0, 2), (10, 12))


def _one_jet(windows, goes=(1, 1, 0, 0), profile=(3, 1.5, 3.0), first_day_hours=8):
    """One aircraft, every sortie breaks; returns Monday's and Tuesday's rows."""
    config = example(
        inventory={"pai": 1},
        rates={"mc_rate": 1.0, "break_rate": 1.0, "ground_abort_rate": 0.0,
               "fix_windows": [{"hours": h, "rate": v} for h, v in windows]},
        rules={"spare_rate": 0.0, "first_day_fix_hours": first_day_hours, "max_second_go": None},
        schedule={"Mon": dict(zip(("first_go", "second_go", "third_go", "fourth_go"), goes))},
        required_sorties=0,
        options={"event_mode": "Spreadsheet", "fix_mode": "Expected", "repeat_rate": 0.0, "recur_rate": 0.0,
                 "go_profile": dict(zip(("goes_per_day", "sortie_hours", "turn_hours"), profile))},
    )
    rows, _ = run_week(load_scenario(config), Random(0))
    return rows[0], rows[1]


# [F-1]
def test_a_2_hour_fix_makes_a_3_hour_turn():
    monday, _ = _one_jet([(2, 1.0)])
    assert monday["flown_by_go"][:2] == [1, 1] and monday["lost_sorties"] == 0


# [T-3]
def test_a_4_hour_fix_misses_a_3_hour_turn_but_makes_the_third_go():
    monday, _ = _one_jet([(4, 1.0)], goes=(1, 1, 1, 0))
    assert monday["flown_by_go"][:3] == [1, 0, 1]
    assert monday["lost_turn_short"] == 1


# [F-3]
def test_first_day_threshold_is_configurable():
    # A 12-hour Monday fix waits for Tuesday when the threshold is 8, not when it is 12.
    _, tue_waits = _one_jet([(12, 1.0)], goes=(1, 0, 0, 0), first_day_hours=8)
    _, tue_ready = _one_jet([(12, 1.0)], goes=(1, 0, 0, 0), first_day_hours=12)
    assert tue_waits["mc_aircraft_for_flying"] == 0
    assert tue_ready["mc_aircraft_for_flying"] == 1


# [M-6]
def test_per_go_counts_and_turn_success():
    m = run_plan(THREE_GO, 1500, 7)["metrics"]
    goes = m["goes"]
    assert [g["go"] for g in goes["by_go"]] == [1, 2, 3]
    assert goes["by_go"][0]["planned"] == 6 * 5 * 1500
    later = goes["by_go"][1:]
    assert goes["turn_success_rate"] == pytest.approx(sum(g["flown"] for g in later) / sum(g["planned"] for g in later))


# [M-7]
def test_sute_math_and_derived_requirement():
    assert required_from_sute(example()) == 36          # 12 / 30 x 18 PAI x 5 days
    assert required_from_sute(THREE_GO) == 48           # 12 / 30 x 24 PAI x 5 days
    record = run_plan(example(), 1000, 3)
    sute = record["metrics"]["sute"]
    assert record["required_sorties"] == 36 and record["required_from_sute"]
    assert sute["target"] == pytest.approx(0.4) and sute["ceiling"] == 0.52
    assert sute["planned"] == pytest.approx(39 / 90)
    assert 0 <= sute["share_weeks_meeting_target"] <= 1


def test_surge_ceiling_warning():
    config = example(schedule={d: {"first_go": 7, "second_go": 3} for d in ("Mon", "Tue", "Wed", "Thu", "Fri")},  # 50 / 90 = 0.56
                     rules={"max_day_to_day_delta": None})
    assert any("surge ceiling" in w for w in plan_warnings(load_scenario(config)))


def test_search_uses_the_units_goes_and_standard_patterns():
    labels = [c["label"] for c in sustainable_candidates(THREE_GO)]
    assert labels and all(len(l.split()[0].split("-")) <= 3 for l in labels)
    assert any(len(l.split()[0].split("-")) == 3 for l in labels)
    config = json.loads(json.dumps(THREE_GO))
    config["rules"]["standard_patterns"] = [[6, 4, 2], [5, 5], [12, 10, 8]]
    labels = [c["label"] for c in sustainable_candidates(config)]
    assert labels == ["6-4-2 every day", "5-5 every day"]   # 12-10-8 is above commit
    two_go = [c["label"] for c in sustainable_candidates(example())]
    assert all(len(l.split()[0].split("-")) <= 2 for l in two_go)
