"""Preset scenarios for the public Results page [R-6].

Each public unit config is run under three scenarios and two recovery models:

  baseline        the week as configured
  surge           one more sortie on every go each day, where commit and the go limits allow
  short_staffed   no weekend repair hours, and every fix window's rate cut by 15%

  spares          losses are covered by scheduled spares only (no 2407 adds)
  flex            fleet flex: idle MC aircraft can also cover losses (2407 adds allowed)

These are synthetic what-ifs on synthetic units, there to show the method.
"""
from __future__ import annotations

import copy
from typing import Any

from tps.L0_inputs.rules import aircraft_required, commit_aircraft
from tps.L0_inputs.schemas import DayPlan, load_scenario

GO_NAMES = ("first_go", "second_go", "third_go", "fourth_go")
SCENARIOS = {
    "baseline": ("Baseline week", "The week as configured."),
    "surge": ("Surge week", "One more sortie on every go each day, where commit and the go limits allow."),
    "short_staffed": ("Short-staffed recovery", "No weekend repair hours, and every fix rate 15% lower."),
}
RECOVERY = {
    "spares": ("Scheduled spares", "Losses are covered by scheduled spares only."),
    "flex": ("Fleet flex", "Idle mission-capable aircraft can also cover losses (2407 adds)."),
}


def _fits(goes: list[int], rules, commit: int) -> bool:
    if any(goes[i + 1] > goes[i] for i in range(3)):
        return False
    if aircraft_required(DayPlan(*goes), rules) > commit:
        return False
    limits = (None, rules.max_second_go, rules.max_third_go, rules.max_fourth_go)
    if any(limit is not None and c > limit for c, limit in zip(goes, limits)):
        return False
    return rules.max_daily_sorties is None or sum(goes) <= rules.max_daily_sorties


def scenario_config(base: dict[str, Any], scenario: str, recovery: str) -> dict[str, Any]:
    config = copy.deepcopy(base)
    sc = load_scenario(base)
    if scenario == "surge":
        commit = commit_aircraft(sc.inventory.pai, sc.rules)
        for day in sc.rules.flying_days:
            plan = sc.schedule[day]
            goes = list(plan.goes)
            for g in range(sc.goes_per_day):
                if goes[g] == 0 and g > 0:
                    continue
                trial = goes[:]
                trial[g] += 1
                if _fits(trial, sc.rules, commit):
                    goes = trial
            config["schedule"][day].update({GO_NAMES[i]: goes[i] for i in range(4) if goes[i] or GO_NAMES[i] in config["schedule"][day]})
    elif scenario == "short_staffed":
        config.setdefault("options", {})["weekend_coverage_hours"] = {"Sat": 0, "Sun": 0}
        rates = config["rates"]
        if "fix_windows" in rates:
            rates["fix_windows"] = [{"hours": w["hours"], "rate": round(w["rate"] * 0.85, 6)} for w in rates["fix_windows"]]
        else:
            for key in ("fix_8hr_rate", "fix_12hr_rate", "fix_24hr_rate"):
                if key in rates:
                    rates[key] = round(rates[key] * 0.85, 6)
    elif scenario != "baseline":
        raise ValueError(f"unknown scenario {scenario}")
    if recovery not in RECOVERY:
        raise ValueError(f"unknown recovery model {recovery}")
    config.setdefault("options", {})["allow_2407_adds"] = recovery == "flex"
    config["name"] = f"{base.get('name', 'Unit')}: {SCENARIOS[scenario][0]}, {RECOVERY[recovery][0].lower()}"
    return config
