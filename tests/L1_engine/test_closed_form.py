"""The engine against closed-form answers. With breaks and aborts drawn independently per
sortie ("Fully Random"), no repeats, and fixes that either always or never finish, the chance a
week succeeds can be worked out by hand. Each simulated rate must sit within 4 standard errors."""
import copy
import sys
from math import sqrt
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from helpers import EXAMPLE  # noqa: E402
from tps.L4_evidence.runs import run_plan  # noqa: E402

WEEKS = 40_000


def _config(pai, schedule, break_rate, abort_rate, spare_rate=0.0, fix_rate=0.0):
    c = copy.deepcopy(EXAMPLE)
    c.pop("seasonality", None)
    c["inventory"]["pai"] = pai
    c["rates"].update(mc_rate=1.0, break_rate=break_rate, ground_abort_rate=abort_rate,
                      fix_windows=[{"hours": 8, "rate": fix_rate}])
    c["rules"].update(spare_rate=spare_rate, commit_rate=1.0)
    c["schedule"] = schedule
    c["required_sorties"] = sum(sum(day.values()) for day in schedule.values())
    c["options"].update(event_mode="Fully Random", fix_mode="Random", repeat_rate=0.0, recur_rate=0.0)
    return c


CASES = [
    # 4 jets fly 4 then turn 4 on Monday; a break is never fixed, so every one of the 8 sorties
    # must hold (the turn needs all 4 back, and so does next Monday): (1 - 0.1)^8
    ("every sortie must hold", _config(4, {"Mon": {"first_go": 4, "second_go": 4}}, 0.10, 0.0), 0.9 ** 8),
    # one jet, one sortie, 30% ground aborts, fixed within 8 hours: 1 - 0.3
    ("one abort loses the sortie", _config(1, {"Mon": {"first_go": 1}}, 0.0, 0.30, fix_rate=1.0), 0.70),
    # two sorties and one spare: the week is lost only if both slots abort: 1 - 0.3^2
    ("a spare covers one abort", _config(3, {"Mon": {"first_go": 2}}, 0.0, 0.30, spare_rate=0.5, fix_rate=1.0), 1 - 0.3 ** 2),
    ("nothing breaks", _config(6, {"Mon": {"first_go": 6, "second_go": 4}}, 0.0, 0.0), 1.0),
]


@pytest.mark.parametrize("name, config, exact", CASES, ids=[c[0] for c in CASES])
def test_engine_matches_the_closed_form(name, config, exact):
    p = run_plan(config, WEEKS, seed=7, example_weeks=0)["metrics"]["probability_success"]
    se = sqrt(exact * (1 - exact) / WEEKS)
    assert abs(p - exact) <= 4 * se + 1e-12, f"{name}: simulated {p:.4f}, exact {exact:.4f}"
