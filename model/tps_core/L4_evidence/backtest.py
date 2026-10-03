"""Backtesting: check the model's predictions against what actually happened [B-1 to B-4].

A unit's history file has one row per flying day. For each past week the model is
given only what was known before it (the planned schedule, and rates measured over
the weeks before), predicts the week, and is scored against the outcome:

  calibration      weeks rated 80 to 90% should succeed 80 to 90% of the time
  accuracy score   Brier score, and skill against always guessing the overall rate
  sorties          actual sorties flown should land in the predicted middle 80% about 80% of the time
  days             days that actually missed should be the ones rated riskier

The history file is read in the browser and never leaves the device.
"""
from __future__ import annotations

import copy
import csv
import io
import math
import re
from random import Random
from statistics import mean
from typing import Any

from tps_core.L2_metrics.metrics import wilson_interval
from tps_core.L0_inputs.rules import aircraft_required, day_spares
from tps_core.L0_inputs.schemas import DayPlan, load_scenario

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
WEEK_COLUMNS = ("week_start", "pai", "mc_at_start", "next_monday_mc", "required_sorties")
DAY_COLUMNS = ("day", "planned_go1", "planned_go2", "planned_go3", "planned_go4", "spares",
               "flown_go1", "flown_go2", "flown_go3", "flown_go4", "breaks", "aborts")
FIXED = re.compile(r"^fixed_(\d+(?:\.\d+)?)h$")
BINS = (0.0, 0.5, 0.7, 0.85, 0.95, 1.0000001)


# ---------------------------------------------------------------- reading the file
def _num(text: str | None) -> float | None:
    text = (text or "").strip()
    if text == "":
        return None
    return float(text)


def parse_history(text: str) -> dict[str, Any]:
    """Weeks from a history file. One row per flying day; week columns may be on the first row only. [B-1]"""
    reader = csv.DictReader(io.StringIO(text.strip().lstrip("\ufeff")))
    if not reader.fieldnames:
        raise ValueError("The file is empty.")
    fields = {f.strip().lower(): f for f in reader.fieldnames}
    missing = [c for c in ("week_start", "day", "planned_go1", "flown_go1", "breaks", "aborts") if c not in fields]
    if missing:
        raise ValueError(f"The file is missing columns: {', '.join(missing)}. Download the template to see the layout.")
    windows = sorted(float(m.group(1)) for f in fields if (m := FIXED.match(f)))
    weeks: dict[str, dict[str, Any]] = {}
    problems: list[str] = []
    for line, raw in enumerate(reader, start=2):
        row = {k: raw.get(fields[k]) for k in fields}
        start = (row.get("week_start") or "").strip()
        day = (row.get("day") or "").strip()[:3].title()
        if not start or day not in DAYS:
            problems.append(f"Row {line}: needs a week_start and a day (Mon to Fri).")
            continue
        try:
            week = weeks.setdefault(start, {"week_start": start, "days": {}})
            for col in WEEK_COLUMNS[1:]:
                value = _num(row.get(col))
                if value is not None and week.get(col) is None:
                    week[col] = value
            week["days"][day] = {
                "planned": [int(_num(row.get(f"planned_go{g}")) or 0) for g in range(1, 5)],
                "spares": None if _num(row.get("spares")) is None else int(_num(row.get("spares"))),
                "flown": [int(_num(row.get(f"flown_go{g}")) or 0) for g in range(1, 5)],
                "breaks": int(_num(row.get("breaks")) or 0),
                "aborts": int(_num(row.get("aborts")) or 0),
                "fixed": {h: int(_num(row.get(f"fixed_{h:g}h")) or 0) for h in windows},
            }
        except ValueError:
            problems.append(f"Row {line}: a number couldn't be read.")
    ordered = [weeks[k] for k in sorted(weeks)]
    for week in ordered:
        if not week.get("pai"):
            problems.append(f"Week {week['week_start']}: needs pai.")
    return {"weeks": [w for w in ordered if w.get("pai")], "windows": windows, "problems": problems[:20]}


# ---------------------------------------------------------------- rates known beforehand
def trailing_rates(weeks: list[dict], index: int, windows: list[float], lookback: int, min_history: int) -> dict | None:
    """Rates from the weeks before this one only: never the week being predicted. [B-1]"""
    prior = weeks[max(0, index - lookback):index]
    if len(prior) < min_history:
        return None
    planned = sum(sum(d["planned"]) for w in prior for d in w["days"].values())
    if planned <= 0:
        return None
    breaks = sum(d["breaks"] for w in prior for d in w["days"].values())
    aborts = sum(d["aborts"] for w in prior for d in w["days"].values())
    events = breaks + aborts
    mc = [w["mc_at_start"] / w["pai"] for w in prior if w.get("mc_at_start") is not None]
    rates = {"break_rate": min(1.0, breaks / planned), "ground_abort_rate": min(1.0, aborts / planned),
             "mc_rate": min(1.0, mean(mc)) if mc else None}
    if windows and events:
        floor, fixes = 0.0, []
        for h in windows:
            share = sum(d["fixed"].get(h, 0) for w in prior for d in w["days"].values()) / events
            floor = max(floor, min(1.0, share))     # cumulative: never falls
            fixes.append({"hours": h, "rate": round(floor, 6)})
        rates["fix_windows"] = fixes
    return rates


def week_config(base: dict[str, Any], week: dict[str, Any], rates: dict[str, Any]) -> dict[str, Any]:
    config = copy.deepcopy(base)
    config["name"] = f"Week of {week['week_start']}"
    config["inventory"] = {**config.get("inventory", {}), "pai": int(week["pai"])}
    config["rates"]["break_rate"] = rates["break_rate"]
    config["rates"]["ground_abort_rate"] = rates["ground_abort_rate"]
    if rates.get("mc_rate") is not None:
        config["rates"]["mc_rate"] = rates["mc_rate"]
    if rates.get("fix_windows"):
        for key in ("fix_8hr_rate", "fix_12hr_rate", "fix_24hr_rate"):
            config["rates"].pop(key, None)
        config["rates"]["fix_windows"] = rates["fix_windows"]
    names = ("first_go", "second_go", "third_go", "fourth_go")
    schedule = {}
    for day in config.get("rules", {}).get("flying_days", DAYS[:5]):
        d = week["days"].get(day)
        plan = {n: (d["planned"][i] if d else 0) for i, n in enumerate(names)}
        if d and d["spares"] is not None:
            plan["spares"] = d["spares"]
        schedule[day] = plan
    config["schedule"] = schedule
    goes_used = max([sum(1 for g in p.values() if isinstance(g, int) and g > 0) for p in schedule.values()] + [1])
    profile = config.get("options", {}).get("go_profile")
    if profile and profile.get("goes_per_day", 4) < goes_used:
        profile["goes_per_day"] = goes_used
    if week.get("required_sorties") is not None:
        config["required_sorties"] = int(week["required_sorties"])
    return config


def actual_outcome(week: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """What happened, judged the way the model's observable prediction is. [B-2]"""
    scenario = load_scenario(config)
    flying = [d for d in scenario.rules.flying_days if d in week["days"]]
    missed_days = [d for d in flying if sum(week["days"][d]["flown"]) < sum(week["days"][d]["planned"])]
    flown = sum(sum(week["days"][d]["flown"]) for d in flying)
    planned = sum(sum(week["days"][d]["planned"]) for d in flying)
    flown_ok = not missed_days and flown >= scenario.required_sorties
    target = max((aircraft_required(scenario.schedule[d], scenario.rules) for d in flying), default=0)
    if scenario.minimum_monday_aircraft is not None:
        target = scenario.minimum_monday_aircraft
    recovered = None if week.get("next_monday_mc") is None else week["next_monday_mc"] >= target
    return {"flown": flown, "planned": planned, "missed_days": missed_days, "flown_ok": flown_ok,
            "recovered": recovered, "recovery_target": target,
            "succeeded": flown_ok and (recovered is not False)}


def prepare(text: str, base: dict[str, Any], lookback: int = 4, min_history: int = 2) -> dict[str, Any]:
    """Every week that has enough history before it, ready to predict."""
    history = parse_history(text)
    weeks, out, skipped = history["weeks"], [], []
    for i, week in enumerate(weeks):
        rates = trailing_rates(weeks, i, history["windows"], lookback, min_history)
        if rates is None:
            skipped.append(week["week_start"])
            continue
        config = week_config(base, week, rates)
        try:
            load_scenario(config)
        except Exception as error:   # a week the model can't take as entered
            history["problems"].append(f"Week {week['week_start']}: {error}")
            continue
        out.append({"week_start": week["week_start"], "config": config, "rates": rates,
                    "actual": actual_outcome(week, config),
                    "has_recovery": week.get("next_monday_mc") is not None})
    return {"weeks": out, "skipped_for_history": skipped, "problems": history["problems"],
            "windows": history["windows"], "lookback": lookback}


# ---------------------------------------------------------------- scoring
def summarize(prepared: dict[str, Any], metrics: list[dict[str, Any]]) -> dict[str, Any]:
    """Calibration, accuracy, sorties coverage, and day-level agreement. [B-3]"""
    rows = []
    for week, m in zip(prepared["weeks"], metrics):
        p = m["observable"]["flown_and_recovered"] if week["has_recovery"] else m["observable"]["flown"]
        dist = m["distributions"]["sorties_flown"]
        a = week["actual"]
        rows.append({
            "week_start": week["week_start"], "predicted": p, "succeeded": a["succeeded"],
            "flown": a["flown"], "planned": a["planned"], "sorties_p10": dist["p10"], "sorties_p50": dist["p50"],
            "sorties_p90": dist["p90"], "missed_days": a["missed_days"], "weakest_day": m.get("weakest_day"),
            "day_risk": {d: m["daily"][d]["share_missing_schedule"] for d in m["daily"] if d in DAYS[:5]},
            "rates": week["rates"],
        })
    n = len(rows)
    if not n:
        return {"weeks": 0, "rows": [], "sentences": ["No week had enough history before it to predict."]}
    y = [1.0 if r["succeeded"] else 0.0 for r in rows]
    p = [r["predicted"] for r in rows]
    base_rate = mean(y)
    brier = mean((pi - yi) ** 2 for pi, yi in zip(p, y))
    naive = mean((base_rate - yi) ** 2 for yi in y)
    skill = None if naive == 0 else 1 - brier / naive

    bins = []
    for lo, hi in zip(BINS, BINS[1:]):
        group = [r for r in rows if lo <= r["predicted"] < hi]
        if not group:
            continue
        wins = sum(r["succeeded"] for r in group)
        low, high = wilson_interval(wins, len(group))
        predicted = mean(r["predicted"] for r in group)
        bins.append({"from": lo, "to": min(hi, 1.0), "weeks": len(group), "predicted": predicted,
                     "observed": wins / len(group), "observed_low": low, "observed_high": high,
                     "agrees": low - 1e-9 <= predicted <= high + 1e-9})

    inside = [r["sorties_p10"] <= r["flown"] <= r["sorties_p90"] for r in rows]
    bias = mean(r["sorties_p50"] - r["flown"] for r in rows)
    day_pairs = [(r["day_risk"].get(d, 0.0), d in r["missed_days"]) for r in rows for d in r["day_risk"]]
    missed = [risk for risk, m in day_pairs if m]
    held = [risk for risk, m in day_pairs if not m]
    failed_weeks = [r for r in rows if r["missed_days"]]
    first_day_match = (mean(1.0 if r["weakest_day"] == r["missed_days"][0] else 0.0 for r in failed_weeks)
                       if failed_weeks else None)

    report = {
        "weeks": n, "skipped_for_history": len(prepared["skipped_for_history"]), "lookback": prepared["lookback"],
        "observed_success": base_rate, "mean_predicted": mean(p),
        "brier": brier, "brier_naive": naive, "skill": skill,
        "bins": bins, "bins_agreeing": sum(b["agrees"] for b in bins),
        "sorties_inside_range": mean(inside), "sorties_bias": bias,
        "day_risk_when_missed": mean(missed) if missed else None,
        "day_risk_when_held": mean(held) if held else None,
        "riskiest_day_matched": first_day_match, "failed_weeks": len(failed_weeks),
        "rows": rows, "problems": prepared["problems"],
    }
    report["sentences"] = _sentences(report)
    return report


def _sentences(r: dict[str, Any]) -> list[str]:
    pct = lambda v: f"{v * 100:.0f}%"  # noqa: E731
    out = [f"Across {r['weeks']} past weeks the model predicted {pct(r['mean_predicted'])} success on average; "
           f"{pct(r['observed_success'])} of those weeks actually succeeded."]
    if r["bins"]:
        out.append(f"In {r['bins_agreeing']} of {len(r['bins'])} prediction bands, the share of weeks that succeeded "
                   "is within chance of what the model predicted.")
    if r["skill"] is not None:
        verdict = ("better than" if r["skill"] > 0.05 else "about the same as" if r["skill"] > -0.05 else "worse than")
        out.append(f"Accuracy score (Brier) {r['brier']:.3f}: {verdict} always guessing the overall rate "
                   f"({r['brier_naive']:.3f}), a skill of {r['skill']:+.2f}.")
    out.append(f"Actual sorties landed inside the predicted middle-80% range in {pct(r['sorties_inside_range'])} of weeks "
               f"(at least 80% expected; most weeks fly everything planned, the top of the range, so higher is normal). "
               f"The typical prediction was {abs(r['sorties_bias']):.1f} sorties {'high' if r['sorties_bias'] > 0 else 'low'} on average.")
    if r["day_risk_when_missed"] is not None and r["day_risk_when_held"] is not None:
        out.append(f"Days that actually missed their plan had been rated {pct(r['day_risk_when_missed'])} risk on average, "
                   f"against {pct(r['day_risk_when_held'])} for days that held.")
    if r["riskiest_day_matched"] is not None:
        out.append(f"In weeks that missed a day, the first miss fell on the model's riskiest day "
                   f"{pct(r['riskiest_day_matched'])} of the time.")
    return out


# ---------------------------------------------------------------- template and synthetic history
def columns(windows: list[float]) -> list[str]:
    return list(WEEK_COLUMNS[:1]) + ["day"] + list(WEEK_COLUMNS[1:]) + list(DAY_COLUMNS[1:]) + [f"fixed_{h:g}h" for h in windows]


def synthetic_history(base: dict[str, Any], weeks: int = 60, seed: int = 7, start: str = "2025-01-06") -> str:
    """A history file made by the model itself, with rates and schedules that drift week to week. [B-4]

    If the model is right about how weeks unfold, it should score well on its own history,
    which makes this a check of the backtest itself and a worked example of the file layout.
    """
    from datetime import date, timedelta
    from tps_core.L1_engine import reference
    rng = Random(seed)
    scenario0 = load_scenario(base)
    windows = [h for h, _ in scenario0.rates.fix_windows]
    names = ("first_go", "second_go", "third_go", "fourth_go")
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(columns(windows))
    monday = date.fromisoformat(start)
    for w in range(weeks):
        config = copy.deepcopy(base)
        for key, spread in (("break_rate", 0.35), ("ground_abort_rate", 0.5)):
            config["rates"][key] = max(0.0, config["rates"][key] * rng.uniform(1 - spread, 1 + spread))
        config["rates"]["mc_rate"] = min(0.98, max(0.4, config["rates"]["mc_rate"] + rng.uniform(-0.08, 0.06)))
        for day, plan in config["schedule"].items():
            first = max(1, plan.get("first_go", 0) + rng.choice((-1, 0, 0, 1)))
            plan["first_go"] = first
            for i in range(1, 4):
                if plan.get(names[i]):
                    plan[names[i]] = max(0, min(first if i == 1 else plan[names[i - 1]], plan[names[i]] + rng.choice((-1, 0, 0, 1))))
        try:
            scenario = load_scenario(config)
        except Exception:
            scenario = scenario0
            config = copy.deepcopy(base)
        log: list[dict] = []
        days, week = reference.run_week(scenario, Random(rng.randrange(10**9)), log)
        start_mc = week["repair_backlog"] + days[-1]["available_eod"]
        fixed_by_day = {d: {h: 0 for h in windows} for d in DAYS}
        for e in log:
            if e["kind"] == "fix" and not e["beyond"] and e["reason"] in ("break", "abort", "repeat or recur"):
                day = scenario.rules.all_days[min(int(e["t"] // 24), len(scenario.rules.all_days) - 1)]
                for h in windows:
                    if e["window"] <= h and day in fixed_by_day:
                        fixed_by_day[day][h] += 1
        for d in days:
            if d["day"] not in scenario.rules.flying_days:
                continue
            plan = scenario.schedule[d["day"]]
            first_row = d["day"] == scenario.rules.flying_days[0]
            writer.writerow(
                [monday.isoformat(), d["day"],
                 scenario.inventory.pai if first_row else "", start_mc if first_row else "",
                 days[-1]["available_eod"] if first_row else "", scenario.required_sorties if first_row else ""]
                + list(d["planned_by_go"]) + [day_spares(plan, scenario.rules)] + list(d["flown_by_go"])
                + [d["code_3"], d["ground_abort"]] + [fixed_by_day[d["day"]][h] for h in windows])
        monday += timedelta(days=7)
    return out.getvalue()


def template(base: dict[str, Any]) -> str:
    """A two-week example of the layout, filled with synthetic numbers."""
    return synthetic_history(base, weeks=2, seed=1)
