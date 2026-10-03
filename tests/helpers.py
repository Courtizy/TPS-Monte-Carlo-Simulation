import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = json.loads((ROOT / "examples" / "plans" / "synthetic_week.json").read_text())


def example(**changes):
    """A deep copy of the example config with top-level blocks updated."""
    config = copy.deepcopy(EXAMPLE)
    for key, value in changes.items():
        if isinstance(value, dict) and isinstance(config.get(key), dict):
            config[key].update(value)
        else:
            config[key] = value
    rates = config.get("rates", {})
    if any(k in rates for k in ("fix_8hr_rate", "fix_12hr_rate", "fix_24hr_rate")):
        rates.pop("fix_windows", None)   # tests that set the three legacy fix rates use that format
    return config
