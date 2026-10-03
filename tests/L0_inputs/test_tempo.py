"""Deployed tempo from any figures, and both home requirements."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from helpers import example  # noqa: E402
from tps_core import web_api  # noqa: E402
from tps_core.L4_evidence.runs import run_plan  # noqa: E402
from tps_core.L0_inputs.schemas import validate_config  # noqa: E402
from tps_core.L0_inputs.tempo import home_requirements, solve_tempo  # noqa: E402


# [M-9]
@pytest.mark.parametrize("figures, sute, aircraft, days", [
    ({"possessed_aircraft_days": 77, "sorties_per_om_day": 4.4, "avg_sorties_per_aircraft": 2.8}, 0.4, 11, 7),
    ({"possessed_aircraft": 11, "om_days": 7, "sorties": 31}, 31 / 77, 11, 7),
    ({"monthly_sorties_per_aircraft": 12, "om_days": 30}, 0.4, None, 30),
    ({"possessed_aircraft_days": 77, "sorties": 31}, 31 / 77, None, None),
    ({"sorties_per_om_day": 4.4, "possessed_aircraft": 11}, 0.4, 11, None),
    ({"sute": 0.45}, 0.45, None, None),
])
def test_tempo_from_any_figures(figures, sute, aircraft, days):
    t = solve_tempo(figures)
    assert t["sute"] == pytest.approx(sute, rel=1e-9)
    assert t["per_aircraft_week"] == pytest.approx(sute * 7, rel=1e-9)
    if aircraft:
        assert t["possessed_aircraft"] == pytest.approx(aircraft, rel=1e-9)
    if days:
        assert t["om_days"] == pytest.approx(days, rel=1e-9)


def test_figures_that_cannot_pin_down_a_sute_are_rejected():
    assert solve_tempo({"possessed_aircraft_days": 77, "sorties_per_om_day": 4.4})["sute"] is None
    config = example()
    config["sute"] = {"possessed_aircraft_days": 77, "sorties_per_om_day": 4.4}   # replace, don't merge
    errors = validate_config(config)
    assert any("don't pin down a SUTE" in e for e in errors)


def test_rounded_figures_that_disagree_are_fit_and_flagged():
    t = solve_tempo({"possessed_aircraft": 11, "om_days": 7, "sorties": 31, "avg_sorties_per_aircraft": 2.5})
    assert t["mismatch"] > 0.03 and 0.36 < t["sute"] < 0.41


# [M-7]
def test_both_home_requirements():
    assert home_requirements(0.4, 11, 5) == {"match_sute": 22, "match_per_aircraft": 31}   # 0.4 x 7 x 11 = 30.8
    report = {"possessed_aircraft_days": 77, "sorties_per_om_day": 4.4, "avg_sorties_per_aircraft": 2.8}
    config = example(inventory={"pai": 11}, rules={"max_day_to_day_delta": None})
    config["sute"] = dict(report)   # replace the example's tempo figures, don't merge
    config["schedule"] = {d: {"first_go": f, "second_go": 2} for d, f in zip(("Mon", "Tue", "Wed", "Thu", "Fri"), (4, 4, 4, 3, 3))}
    by_sute = run_plan(config, 300, 1)
    config["sute"]["requirement_basis"] = "per_aircraft"
    by_aircraft = run_plan(config, 300, 1)
    assert by_sute["required_sorties"] == 22 and by_aircraft["required_sorties"] == 31
    pa = by_sute["metrics"]["sute"]["per_aircraft"]
    assert pa["planned"] == pytest.approx(28 / 11) and pa["deployed"] == pytest.approx(2.8)
    assert by_sute["tempo"]["sorties"] == pytest.approx(30.8)


def test_web_api_tempo():
    t = json.loads(web_api.tempo(json.dumps({"possessed_aircraft": 11, "om_days": 7, "sorties": 31}), 11, 5))
    assert t["requirements"] == {"match_sute": 23, "match_per_aircraft": 31}
