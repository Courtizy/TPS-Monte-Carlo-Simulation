import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from helpers import example  # noqa: E402
from tps_core.L0_inputs.schemas import ConfigError, fingerprint, load_scenario, plan_warnings, validate_config  # noqa: E402


def test_example_is_valid_and_clean():
    config = example()
    assert validate_config(config) == []
    assert plan_warnings(load_scenario(config)) == []


# [R-5]
@pytest.mark.parametrize("changes, words", [
    ({"rates": {"break_rate": 1.4}}, "rates.break_rate"),
    ({"rates": {"fix_windows": [{"hours": 8, "rate": 0.5}, {"hours": 12, "rate": 0.4}]}}, "cumulative"),
    ({"rates": {"fix_windows": [{"hours": 8, "rate": 0.5}, {"hours": 6, "rate": 0.6}]}}, "above the window"),
    ({"options": {"go_profile": {"goes_per_day": 5, "sortie_hours": 1, "turn_hours": 1}}}, "goes_per_day"),
    ({"options": {"go_profile": {"goes_per_day": 4, "sortie_hours": 4, "turn_hours": 4}}}, "more than one day"),
    ({"schedule": {"Mon": {"first_go": 4, "second_go": 2, "third_go": 1}}}, "more goes than"),
    ({"rules": {"standard_patterns": [[4, 6]]}}, "standard_patterns"),
    ({"sute": {"monthly_sorties_per_aircraft": 0, "om_days": 30}}, "sute.monthly"),
    ({"rules": {"commit_rate": None}}, "rules.commit_rate"),
    ({"rules": {"surprise": 1}}, "rules.surprise"),
    ({"inventory": {"pai": 0}}, "inventory.pai"),
    ({"schedule": {"Sat": {"first_go": 2}}}, "schedule.Sat"),
    ({"schedule": {"Mon": {"first_go": 2, "second_go": 3}}}, "no larger"),
    ({"sute": None, "required_sorties": None}, "required_sorties"),
    ({"options": {"weekend_coverage_hours": {"Sat": 10}}}, "weekend_coverage_hours"),
    ({"options": {"event_mode": "Guess"}}, "event_mode"),
    ({"options": {"repeat_rate": 0.7, "recur_rate": 0.5}}, "must not exceed 1"),
    ({"schema": "tps/0"}, "schema"),
    ({"extra": 1}, "Unknown key: extra"),
])
def test_validation_catches_problems(changes, words):
    config = example(**changes)
    for key in [k for k, v in changes.items() if v is None]:
        config.pop(key, None)
    errors = validate_config(config)
    assert any(words in e for e in errors), errors
    with pytest.raises(ConfigError):
        load_scenario(config)


# [R-4]
def test_plan_warnings_flag_rule_breaks():
    config = example(schedule={"Mon": {"first_go": 9, "second_go": 6}}, required_sorties=90)
    text = " ".join(plan_warnings(load_scenario(config)))
    for words in ("above commit", "second-go", "sorties change", "Required sorties"):
        assert words in text


def test_fingerprint_ignores_key_order():
    config = example()
    assert fingerprint(config) == fingerprint(dict(reversed(list(config.items()))))
    assert fingerprint(config) != fingerprint(example(required_sorties=37))
