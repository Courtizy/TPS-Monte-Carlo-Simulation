"""If the step 4 go engine (L1_engine) is in the repo, tps_core must match it exactly."""
import json
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
legacy = pytest.importorskip("L1_engine")
L0 = pytest.importorskip("L0_inputs")

from tps_core import engine  # noqa: E402
from tps_core.schemas import load_scenario  # noqa: E402


def test_matches_step4_engine():
    legacy_config = L0.template_go_config()
    scenario = L0.scenario_from_config(legacy_config)
    if scenario.policy.commit_rate != 0.55:
        pytest.skip("Parity check assumes the example's commit rate matches ttp_rules")
    old = legacy.compile_go_plan(scenario, L0.go_options_from_config(legacy_config))
    new = engine.compile_plan(load_scenario(json.loads((ROOT / "examples" / "synthetic_week.json").read_text())))
    a, b = random.Random(99), random.Random(99)
    added = {"lost_first_go_short", "lost_turn_short", "lost_abort_uncovered",   # new in tps_core 0.2
             "planned_by_go", "flown_by_go"}                                     # new in tps_core 0.3
    for _ in range(500):
        (old_days, old_week), (new_days, new_week) = legacy.run_compiled_week(old, a), engine.run_compiled_week(new, b)
        assert old_week == new_week
        assert old_days == [{k: v for k, v in day.items() if k not in added} for day in new_days]
