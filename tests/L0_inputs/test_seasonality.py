"""Seasonality: each month's conditions applied to the same weekly pattern."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from helpers import ROOT, example  # noqa: E402
from tps.L0_inputs.schemas import load_scenario, validate_config  # noqa: E402
from tps.L0_inputs.seasonality import MONTHS, month_config, season_view  # noqa: E402
from tps.L4_evidence.backtest import monthly_profile, synthetic_history  # noqa: E402


# [R-7]
def test_season_months_change_what_they_say():
    base = example()
    base["seasonality"] = {"months": {"Jul": {"break_scale": 1.5, "fix_scale": 0.8}, "Jan": {"ground_abort_rate": 0.09},
                                      "Nov": {"holiday": True}, "Sep": {"surge": True}}}
    assert validate_config(base) == []
    b = load_scenario(base)
    jul = load_scenario(month_config(base, "Jul"))
    assert jul.rates.break_rate == min(1.0, b.rates.break_rate * 1.5)
    assert all(a[1] < c[1] for a, c in zip(jul.rates.fix_windows, b.rates.fix_windows))
    assert load_scenario(month_config(base, "Jan")).rates.ground_abort_rate == 0.09
    nov = load_scenario(month_config(base, "Nov"))
    assert len(nov.rules.flying_days) == len(b.rules.flying_days) - 1 and dict(nov.options.weekend_coverage_hours) == {"Sat": 0, "Sun": 0}
    assert nov.required_sorties < b.required_sorties
    sep = load_scenario(month_config(base, "Sep"))
    assert sum(p.daily_sorties for p in sep.schedule.values()) > sum(p.daily_sorties for p in b.schedule.values())
    assert load_scenario(month_config(base, "Apr")).rates == b.rates           # months left out use the base week
    view = season_view(base, runs=200, seed=3)
    assert [m["month"] for m in view] == list(MONTHS) and "holiday" in view[10]["flags"]
    profile = monthly_profile(synthetic_history(example(), weeks=20, seed=2))
    assert profile["months"] and all(0 <= m["break_rate"] <= 1 for m in profile["months"].values())
    with_profile = example(); with_profile["seasonality"] = profile
    assert validate_config(with_profile) == []
    assert validate_config(example(seasonality={"months": {"Smarch": {}}}))


def test_public_configs_carry_a_valid_synthetic_profile():
    for path in sorted((ROOT / "configs" / "public").glob("*.json")):
        config = json.loads(path.read_text())
        assert validate_config(config) == [] and "Synthetic" in config["seasonality"]["source"]
