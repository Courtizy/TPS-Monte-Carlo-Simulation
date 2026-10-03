"""Break-even margins: how far each input can slip before the plan drops below the bar [M-12].

For one input at a time, holding everything else as entered, search for the value
where the chance of success crosses the success bar. Every trial uses the same seed,
so the search moves smoothly instead of jumping with luck. If the plan is above the
bar today, the answer is how far the input can get worse; if it is below, how much
the input alone would have to improve, or that it can't get there alone.
"""
from __future__ import annotations

import copy
from typing import Any

from tps_core.L4_evidence.runs import run_plan

INPUTS = {
    "break_rate": {"label": "Break rate", "worse": "up", "range": (0.0, 0.8)},
    "ground_abort_rate": {"label": "Ground abort rate", "worse": "up", "range": (0.0, 0.5)},
    "mc_rate": {"label": "Mission capable rate", "worse": "down", "range": (0.2, 1.0)},
    "fix_speed": {"label": "Fix rates", "worse": "down", "range": (0.2, None)},   # share of today's fix rates
}


def _windows(rates: dict[str, Any]) -> list[dict[str, float]]:
    if "fix_windows" in rates:
        return [dict(w) for w in rates["fix_windows"]]
    pairs = (("fix_8hr_rate", 8), ("fix_12hr_rate", 12), ("fix_24hr_rate", 24))
    return [{"hours": h, "rate": rates[k]} for k, h in pairs if k in rates]


def _with_value(config: dict[str, Any], name: str, value: float) -> dict[str, Any]:
    c = copy.deepcopy(config)
    if name == "fix_speed":
        windows = _windows(c["rates"])
        for key in ("fix_8hr_rate", "fix_12hr_rate", "fix_24hr_rate"):
            c["rates"].pop(key, None)
        c["rates"]["fix_windows"] = [{"hours": w["hours"], "rate": min(1.0, w["rate"] * value)} for w in windows]
    else:
        c["rates"][name] = value
    return c


def current_value(config: dict[str, Any], name: str) -> float:
    return 1.0 if name == "fix_speed" else float(config["rates"][name])


def break_even(config: dict[str, Any], name: str, seed: int, iterations: int = 2000,
               bar: float = 0.85, steps: int = 9) -> dict[str, Any]:
    """Where success crosses the bar for one input, searched by halving the interval each step."""
    spec = INPUTS[name]
    low, high = spec["range"]
    if name == "fix_speed":
        top = max((w["rate"] for w in _windows(config["rates"])), default=1.0)
        high = 1.0 / top if top > 0 else 1.0   # beyond this every window is already at 100%
    points: list[list[float]] = []

    def success(x: float) -> float:
        p = run_plan(_with_value(config, name, x), iterations, seed, example_weeks=0)["metrics"]["probability_success"]
        points.append([x, p])
        return p

    x0 = current_value(config, name)
    p0 = success(x0)
    worse_end = high if spec["worse"] == "up" else low
    better_end = low if spec["worse"] == "up" else high
    if p0 >= bar:
        end, status_if_never = worse_end, "holds_across_range"
    else:
        end, status_if_never = better_end, "cannot_reach"
    p_end = success(end)
    if (p0 >= bar) == (p_end >= bar):
        status, value = status_if_never, None
    else:
        a, b = x0, end              # success(a) on one side of the bar, success(b) on the other
        for _ in range(steps):
            mid = (a + b) / 2
            if (success(mid) >= bar) == (p0 >= bar):
                a = mid
            else:
                b = mid
        value = (a + b) / 2
        status = "holds_until" if p0 >= bar else "reaches_at"
    from tps_core.L0_inputs.schemas import load_scenario
    scenario = load_scenario(config)
    weekly = sum(scenario.schedule[d].daily_sorties for d in scenario.rules.flying_days)
    return {
        "weekly_sorties": weekly, "event_mode": scenario.options.event_mode,
        "input": name, "label": spec["label"], "worse": spec["worse"], "current": x0, "success_now": p0,
        "bar": bar, "status": status, "value": value, "range": [low, high],
        "points": sorted(points), "iterations": iterations, "seed": seed,
    }


def describe(result: dict[str, Any]) -> str:
    """One sentence a planner or leader can read."""
    import math
    name, status, value, now = result["input"], result["status"], result["value"], result["current"]
    bar = round(result["bar"] * 100)
    fmt = (lambda v: f"{v * 100:.0f}% of today's") if name == "fix_speed" else (lambda v: f"{v * 100:.1f}%")
    now_text = "" if name == "fix_speed" else f" ({now * 100:.1f}% today)"
    label = result["label"].lower()
    verb_s = "" if name == "fix_speed" else "s"   # "fix rates fall", "break rate falls"
    counts = ""
    # With a set number of breaks or aborts a week, the margin is really a count.
    if value is not None and name in ("break_rate", "ground_abort_rate") and result["event_mode"] != "Fully Random":
        noun = "breaks" if name == "break_rate" else "aborts"
        n_now = math.ceil(round(now * result["weekly_sorties"], 9))
        n_edge = math.ceil(round(value * result["weekly_sorties"], 9))
        if status == "holds_until" and n_edge > n_now:
            counts = f" In counts: {n_edge - 1} {noun} a week holds; {n_edge} doesn't (about {n_now} today)."
        elif status == "reaches_at" and n_edge < n_now:
            counts = f" In counts: {n_edge} {noun} a week or fewer (about {n_now} today)."
    if status == "holds_until":
        direction = f"rise{verb_s} past" if result["worse"] == "up" else f"fall{verb_s} below"
        return f"Holds at {bar}% until the {label} {direction} {fmt(value)}{now_text}.{counts}"
    if status == "reaches_at":
        direction = f"fall{verb_s} to" if result["worse"] == "up" else f"rise{verb_s} to"
        return f"Reaches {bar}% if the {label} {direction} {fmt(value)}{now_text}.{counts}"
    if status == "holds_across_range":
        return f"Holds at {bar}% across the whole range tested for the {label}."
    return f"The {label} alone can't bring the plan to {bar}%."
