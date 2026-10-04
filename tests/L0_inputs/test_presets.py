"""Public presets: each unit under baseline, surge, and short-staffed conditions, two recovery models."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from helpers import ROOT, example  # noqa: E402
from tps.L0_inputs.presets import RECOVERY, SCENARIOS, scenario_config  # noqa: E402
from tps.L0_inputs.schemas import load_scenario, plan_warnings, validate_config  # noqa: E402


# [R-6]
def test_presets_are_valid_and_change_what_they_say():
    for path in sorted((ROOT / "configs" / "public").glob("*.json")):
        base = json.loads(path.read_text())
        before = load_scenario(base)
        for scenario in SCENARIOS:
            for recovery in RECOVERY:
                config = scenario_config(base, scenario, recovery)
                assert validate_config(config) == [], (path.name, scenario, recovery)
                sc = load_scenario(config)
                assert sc.options.allow_2407_adds == (recovery == "flex")
                planned = sum(p.daily_sorties for p in sc.schedule.values())
                if scenario == "surge":
                    assert planned > sum(p.daily_sorties for p in before.schedule.values())
                    assert not [w for w in plan_warnings(sc) if "above commit" in w]
                if scenario == "short_staffed":
                    assert dict(sc.options.weekend_coverage_hours) == {"Sat": 0, "Sun": 0}
                    assert all(a[1] < b[1] or b[1] == 0 for a, b in zip(sc.rates.fix_windows, before.rates.fix_windows))
    assert scenario_config(example(), "baseline", "spares")["schedule"] == example()["schedule"]
