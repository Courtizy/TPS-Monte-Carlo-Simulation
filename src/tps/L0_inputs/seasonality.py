"""Seasonality: the same weekly pattern under each month's conditions [R-7].

A config may carry a `seasonality` block with one entry per month (any months left out use the
base week). Each entry can set:

  mc_rate, break_rate, ground_abort_rate     that month's rates (for example, from history)
  break_scale, abort_scale, mc_scale         or multipliers on the base rates
  fix_windows                                that month's cumulative fix rates
  fix_scale                                  or a multiplier on every fix rate (heat slows fixes)
  holiday                                    a holiday week: one fewer flying day, no weekend repairs
  surge                                      an exercise or fiscal-year-end push: the surge week

The weekly engine is unchanged: each month is simply a config, run like any other.
"""
from __future__ import annotations

import copy
from typing import Any

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
MONTH_KEYS = {"mc_rate", "break_rate", "ground_abort_rate", "break_scale", "abort_scale", "mc_scale",
              "fix_windows", "fix_scale", "holiday", "surge", "note"}


def validate_seasonality(block: Any) -> list[str]:
    if block is None:
        return []
    if not isinstance(block, dict) or set(block) - {"months", "source"} or not isinstance(block.get("months", {}), dict):
        return ["seasonality must be {\"months\": {\"Jan\": {...}, ...}} with an optional \"source\""]
    errors = []
    for month, entry in block["months"].items():
        if month not in MONTHS:
            errors.append(f"seasonality.months.{month}: use Jan to Dec")
            continue
        if not isinstance(entry, dict) or set(entry) - MONTH_KEYS:
            errors.append(f"seasonality.months.{month} may hold {', '.join(sorted(MONTH_KEYS))}")
            continue
        for key in ("mc_rate", "break_rate", "ground_abort_rate"):
            if key in entry and not (isinstance(entry[key], (int, float)) and 0 <= entry[key] <= 1):
                errors.append(f"seasonality.months.{month}.{key} must be between 0 and 1")
        for key in ("break_scale", "abort_scale", "mc_scale", "fix_scale"):
            if key in entry and not (isinstance(entry[key], (int, float)) and 0 < entry[key] <= 5):
                errors.append(f"seasonality.months.{month}.{key} must be a positive multiplier")
    return errors


def _windows(rates: dict[str, Any]) -> list[dict[str, float]]:
    if "fix_windows" in rates:
        return [dict(w) for w in rates["fix_windows"]]
    return [{"hours": h, "rate": rates[k]} for k, h in (("fix_8hr_rate", 8), ("fix_12hr_rate", 12), ("fix_24hr_rate", 24)) if k in rates]


def month_config(base: dict[str, Any], month: str) -> dict[str, Any]:
    """The base week under one month's conditions."""
    from tps.L0_inputs.presets import scenario_config
    entry = ((base.get("seasonality") or {}).get("months") or {}).get(month, {})
    config = copy.deepcopy(base)
    config.pop("seasonality", None)
    rates = config["rates"]
    for key, scale in (("mc_rate", "mc_scale"), ("break_rate", "break_scale"), ("ground_abort_rate", "abort_scale")):
        if key in entry:
            rates[key] = float(entry[key])
        elif scale in entry:
            rates[key] = min(1.0, rates[key] * float(entry[scale]))
    if "fix_windows" in entry or "fix_scale" in entry:
        windows = entry.get("fix_windows") or _windows(rates)
        scale = float(entry.get("fix_scale", 1.0))
        for key in ("fix_8hr_rate", "fix_12hr_rate", "fix_24hr_rate"):
            rates.pop(key, None)
        floor, fixed = 0.0, []
        for w in windows:
            floor = max(floor, min(1.0, float(w["rate"]) * scale))
            fixed.append({"hours": w["hours"], "rate": round(floor, 6)})
        rates["fix_windows"] = fixed
    if entry.get("surge"):
        allow = config.get("options", {}).get("allow_2407_adds", False)
        config = scenario_config(config, "surge", "flex" if allow else "spares")
    if entry.get("holiday"):
        # A holiday week drops its last flying day from the week, so a requirement worked out from
        # SUTE shrinks with it; an entered requirement shrinks in proportion.
        rules = config.setdefault("rules", {})
        days = list(rules.get("flying_days", ("Mon", "Tue", "Wed", "Thu", "Fri")))
        if len(days) > 1:
            off = days.pop()
            rules["flying_days"] = days
            config["schedule"].pop(off, None)
            if "required_sorties" in config:
                config["required_sorties"] = round(config["required_sorties"] * len(days) / (len(days) + 1))
        config.setdefault("options", {})["weekend_coverage_hours"] = {"Sat": 0, "Sun": 0}
    config["name"] = f"{base.get('name', 'Plan')}: {month}"
    return config


def has_seasonality(config: dict[str, Any]) -> bool:
    return bool(((config.get("seasonality") or {}).get("months")))


def season_view(base: dict[str, Any], runs: int = 1000, seed: int = 20261004) -> list[dict[str, Any]]:
    """Each month's result for the same weekly pattern [R-7]."""
    from tps.L4_evidence.runs import run_plan
    out = []
    for month in MONTHS:
        entry = ((base.get("seasonality") or {}).get("months") or {}).get(month, {})
        m = run_plan(month_config(base, month), runs, seed, example_weeks=0)["metrics"]
        out.append({"month": month, "success": m["probability_success"], "ci95": [m["ci95_low"], m["ci95_high"]],
                    "weakest_day": m.get("weakest_day"), "main_cause": m["causes"].get("main_cause"),
                    "flags": [f for f in ("holiday", "surge") if entry.get(f)], "note": entry.get("note", "")})
    return out
