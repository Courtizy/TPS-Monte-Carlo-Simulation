"""Turn-pattern search: permute recognizable weekly pattern families and test them.

generate() builds candidate weeks for one or more weekly sortie targets:
  1. every Monday-Friday split of the weekly total that fits the daily cap and
     day-to-day change limit (sampled evenly if there are very many),
  2. each week classified into a family planners recognize (Waterfall, Flat
     Turns, Recovery Valley, ...), with some families kept diagnostic-only,
  3. an even spread of weeks picked from every family, and
  4. each day's total split into goes (even, or stepped down like 6-4-2) within
     commit and per-go limits.
The browser runs every candidate on the same seed, then analyze() ranks them,
picks leaders to confirm with longer runs, and writes the requirement check.
"""
from __future__ import annotations

import math
from random import Random
from statistics import mean
from typing import Any

from tps.L2_metrics.metrics import CAUSE_WORDS
from tps.L0_inputs.rules import commit_aircraft, day_spares
from tps.L0_inputs.schemas import DayPlan, load_scenario

FAMILIES = (
    "Flat Turns", "Waterfall", "Step-Down", "Front-Loaded Push", "Balanced Push", "Recovery Valley",
    "Midweek Spike", "Multi-Spike", "Sawtooth", "Step-Up",
    "Reverse Waterfall", "Back-Loaded Push", "Compressed Surge",
)
DIAGNOSTIC = frozenset({"Reverse Waterfall", "Back-Loaded Push", "Compressed Surge"})
FAMILY_NOTES = {
    "Flat Turns": "The same sorties every day.",
    "Waterfall": "Heaviest on Monday, tapering through the week.",
    "Step-Down": "Tapers in steps, holding a level for two or more days.",
    "Front-Loaded Push": "More flying early in the week, not a steady taper.",
    "Balanced Push": "Close to even across the week.",
    "Recovery Valley": "A light day mid-week to catch up on repairs.",
    "Midweek Spike": "Peaks mid-week.",
    "Multi-Spike": "Two or more heavy days that aren't together.",
    "Sawtooth": "Alternates heavier and lighter days.",
    "Step-Up": "Builds in steps toward the end of the week.",
    "Reverse Waterfall": "Lightest Monday, heaviest Friday. Diagnostic only.",
    "Back-Loaded Push": "More flying late in the week. Diagnostic only.",
    "Compressed Surge": "Most of the week's flying crammed into a few days. Diagnostic only.",
}
SPLITS = {"even": "Even across goes", "step": "Stepped down by go"}
STEP_WEIGHTS = {1: (1,), 2: (2, 1), 3: (3, 2, 1), 4: (4, 3, 2, 1)}
GO_NAMES = ("first_go", "second_go", "third_go", "fourth_go")
ENUMERATION_LIMIT = 20_000   # list every week up to this many; beyond it, draw a sample
SAMPLE_DRAWS = 4_000


# ---------------------------------------------------------------- families
# [P-3]
def classify(totals: tuple[int, ...]) -> str:
    """Name the shape of a week's daily sortie totals (same order of checks as the original TPS)."""
    t = list(totals)
    n = len(t)
    if n < 2 or len(set(t)) == 1:
        return "Flat Turns"
    top3 = sum(sorted(t, reverse=True)[:3])
    if n >= 5 and top3 / sum(t) >= 0.75:
        return "Compressed Surge"
    pairs = list(zip(t, t[1:]))
    plateaus = any(a == b for a, b in pairs)
    if all(a >= b for a, b in pairs):
        return "Step-Down" if plateaus and len(set(t)) >= 3 else "Waterfall"
    if all(a <= b for a, b in pairs):
        return "Step-Up" if plateaus and len(set(t)) >= 3 else "Reverse Waterfall"
    signs = [1 if b > a else -1 for a, b in pairs if a != b]
    if len(signs) >= 3 and all(signs[i] != signs[i - 1] for i in range(1, len(signs))):
        return "Sawtooth"
    if any(t[i] + 2 <= min(t[i - 1], t[i + 1]) for i in range(1, n - 1)):
        return "Recovery Valley"
    if n >= 5 and t.index(max(t)) in (2, 3):
        return "Midweek Spike"
    if sum(1 for v in t if v >= mean(t) + 1) >= 2:
        return "Multi-Spike"
    if sum(t[:2]) > sum(t[-2:]) + 2:
        return "Front-Loaded Push"
    if sum(t[-2:]) > sum(t[:2]) + 2:
        return "Back-Loaded Push"
    return "Balanced Push"


# ---------------------------------------------------------------- weeks
# [P-2]
def daily_compositions(weekly: int, days: int, low: int, cap: int, max_delta: int | None,
                       rng: Random, limit: int = ENUMERATION_LIMIT) -> list[tuple[int, ...]]:
    """Every way to split the weekly total across the days (sampled evenly if too many)."""
    counts: dict[tuple[int, int, int], int] = {}

    def count(day: int, remaining: int, previous: int) -> int:
        if day == days:
            return 1 if remaining == 0 else 0
        key = (day, remaining, previous)
        if key not in counts:
            left = days - day - 1
            total = 0
            for v in range(max(low, remaining - cap * left), min(cap, remaining - low * left) + 1):
                if day and max_delta is not None and abs(v - previous) > max_delta:
                    continue
                total += count(day + 1, remaining - v, v)
            counts[key] = total
        return counts[key]

    total = count(0, weekly, -1)
    if total == 0:
        return []

    def options(day, remaining, previous):
        left = days - day - 1
        for v in range(max(low, remaining - cap * left), min(cap, remaining - low * left) + 1):
            if day and max_delta is not None and abs(v - previous) > max_delta:
                continue
            yield v

    if total <= limit:
        out: list[tuple[int, ...]] = []

        def walk(prefix, remaining, previous):
            if len(prefix) == days:
                out.append(tuple(prefix))
                return
            for v in options(len(prefix), remaining, previous):
                walk(prefix + [v], remaining - v, v)

        walk([], weekly, -1)
        return out

    # Too many to list: draw uniformly using the counts.
    seen = set()
    for _ in range(SAMPLE_DRAWS):
        week, remaining, previous = [], weekly, -1
        for day in range(days):
            weights = [(v, count(day + 1, remaining - v, v)) for v in options(day, remaining, previous)]
            pick = rng.randrange(sum(w for _, w in weights))
            for v, w in weights:
                if pick < w:
                    break
                pick -= w
            week.append(v)
            remaining -= v
            previous = v
        seen.add(tuple(week))
    return sorted(seen)


# [P-4]
def split_day(total: int, goes: int, style: str) -> tuple[int, int, int, int]:
    """Split a day's sorties into goes: evenly, or stepped down (first go largest)."""
    if total <= 0:
        return (0, 0, 0, 0)
    if style == "even":
        base, extra = divmod(total, goes)
        counts = [base + 1] * extra + [base] * (goes - extra)
    else:
        weights = STEP_WEIGHTS[goes]
        raw = [total * w / sum(weights) for w in weights]
        counts = [math.floor(x) for x in raw]
        order = sorted(range(goes), key=lambda i: (-(raw[i] - counts[i]), i))
        for i in order[: total - sum(counts)]:
            counts[i] += 1
        counts.sort(reverse=True)
    return tuple(counts + [0] * (4 - goes))


def _day_fits(split: tuple[int, ...], rules, commit: int) -> bool:
    plan = DayPlan(*split)
    if plan.first_go + day_spares(plan, rules) > commit:
        return False
    limits = (None, rules.max_second_go, rules.max_third_go, rules.max_fourth_go)
    if any(limit is not None and c > limit for c, limit in zip(split, limits)):
        return False
    return rules.max_daily_sorties is None or sum(split) <= rules.max_daily_sorties


# [P-2]
def daily_cap(scenario) -> int:
    """Most sorties one day can hold under commit, spares, go count, and per-go limits."""
    rules = scenario.rules
    commit = commit_aircraft(scenario.inventory.pai, rules)
    best = 0
    for total in range(1, commit * scenario.goes_per_day + 1):
        if any(_day_fits(split_day(total, scenario.goes_per_day, s), rules, commit) for s in SPLITS):
            best = total
    return best


# [P-1]
def week_targets(config: dict[str, Any], mode: str = "band", custom: list[int] | None = None) -> list[int]:
    """Weekly sortie totals to test: the requirement, a band around it, or a custom list."""
    scenario = load_scenario(config)
    days = len(scenario.rules.flying_days)
    cap_total = daily_cap(scenario) * days
    required = scenario.required_sorties
    if mode == "custom" and custom:
        return sorted({t for t in custom if days <= t <= cap_total})
    if mode == "requirement" or not required:
        return [min(max(required, days), cap_total)] if cap_total else []
    planned = sum(scenario.schedule[d].daily_sorties for d in scenario.rules.flying_days)
    top = min(cap_total, math.ceil(1.5 * max(required, planned)))
    if scenario.sute_ceiling:
        top = min(top, max(required, math.floor(scenario.sute_ceiling * scenario.inventory.pai * days * 1.1)))
    low = max(days, round(required * 0.75))
    high = max(min(required, cap_total), top)
    points = {min(required, cap_total), high, low}
    for k in range(1, 4):
        points.add(round(low + (high - low) * k / 4))
    return sorted(p for p in points if days <= p <= cap_total)


# ---------------------------------------------------------------- candidates
def _label(totals, splits) -> tuple[str, str]:
    detail = "-".join("x".join(str(g) for g in s if g) or "0" for s in splits)
    return "-".join(map(str, totals)), detail


def generate(config: dict[str, Any], mode: str = "band", custom: list[int] | None = None,
             budget: int = 180, split_styles: tuple[str, ...] = ("step", "even"), seed: int = 0) -> dict[str, Any]:
    """Candidate weeks for each target, spread evenly across families and go splits."""
    scenario = load_scenario(config)
    rules = scenario.rules
    days = rules.flying_days
    commit = commit_aircraft(scenario.inventory.pai, rules)
    goes = scenario.goes_per_day
    cap = daily_cap(scenario)
    targets = week_targets(config, mode, custom)
    rng = Random(seed)
    per_target = max(len(FAMILIES), budget // max(1, len(targets)))
    per_day_pai = scenario.inventory.pai * len(days)
    candidates: list[dict[str, Any]] = []
    coverage: dict[str, dict[str, int]] = {}

    current_totals = tuple(scenario.schedule[d].daily_sorties for d in days)
    candidates.append(_candidate("Your plan", current_totals, [scenario.schedule[d].goes for d in days],
                                 "current", None, days, per_day_pai, sum(current_totals), rules))

    for target in targets:
        weeks = daily_compositions(target, len(days), 1, cap, rules.max_day_to_day_delta, rng)
        by_family: dict[str, list[tuple[int, ...]]] = {}
        for week in weeks:
            by_family.setdefault(classify(week), []).append(week)
        coverage[str(target)] = {f: len(v) for f, v in by_family.items()}
        present = [f for f in FAMILIES if f in by_family]
        if not present:
            continue
        slots = max(1, per_target // (len(present) * len(split_styles)))
        for family in present:
            pool = by_family[family]
            picks = pool if len(pool) <= slots else [pool[round(i * (len(pool) - 1) / (slots - 1))] for i in range(slots)] if slots > 1 else [rng.choice(pool)]
            for week in dict.fromkeys(picks):
                for style in split_styles:
                    splits = []
                    for total in week:
                        split = split_day(total, goes, style)
                        if not _day_fits(split, rules, commit):
                            other = split_day(total, goes, "even" if style == "step" else "step")
                            split = other if _day_fits(other, rules, commit) else None
                        if split is None:
                            break
                        splits.append(split)
                    if len(splits) == len(week):
                        candidates.append(_candidate(family, week, splits, style, target, days, per_day_pai, target, rules))
    # The same week can appear from both split styles when they give identical goes; keep one.
    unique, seen = [], set()
    for c in candidates:
        key = c["detail"]
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return {"targets": targets, "daily_cap": cap, "coverage": coverage, "candidates": unique}


def _candidate(family, totals, splits, style, target, days, per_day_pai, weekly, rules=None) -> dict[str, Any]:
    name, detail = _label(totals, splits)
    spares = sum(day_spares(DayPlan(*s), rules) for s in splits if sum(s)) if rules is not None else 0
    return {
        "spares_per_week": spares,
        "label": f"{family} {name}" if family != "Your plan" else f"Your plan {name}",
        "family": family if family != "Your plan" else classify(tuple(totals)),
        "is_current": family == "Your plan",
        "diagnostic": family in DIAGNOSTIC,
        "totals": list(totals),
        "detail": detail,
        "split": style,
        "target": target,
        "weekly_sorties": weekly,
        "sute": weekly / per_day_pai,
        "per_aircraft": weekly / (per_day_pai / len(days)),
        "patch": {
            "schedule": {d: {**{GO_NAMES[i]: s[i] for i in range(4)}, "spares": None} for d, s in zip(days, splits)},
            # [P-5]
            # Judge each tested week on flying its own total; the verdict compares against the real requirement.
            **({"required_sorties": weekly} if family != "Your plan" else {}),
        },
        "kind": "pattern",
        "cost": f"{weekly} sorties a week",
    }


# ---------------------------------------------------------------- analysis
DAY_NAMES = {"Mon": "Monday", "Tue": "Tuesday", "Wed": "Wednesday", "Thu": "Thursday", "Fri": "Friday",
             "Sat": "Saturday", "Sun": "Sunday"}
SHORT_CAUSES = {
    "lost_turn_short": "no aircraft back for a turn",
    "lost_abort_uncovered": "aborts use up the spares",
    "lost_first_go_short": "too few aircraft for the first go",
}


def _failure_parts(m: dict[str, Any]) -> tuple[str | None, int | None, str | None]:
    day = m.get("weakest_day")
    goes = (m.get("goes") or {}).get("by_go") or []
    worst = min(goes, key=lambda g: g["share_flown"]) if len(goes) > 1 else None
    go = worst["go"] if worst and worst["share_flown"] < 0.999 else None
    cause = (m.get("causes") or {}).get("main_cause")
    return day, go, cause


def _fails_where(m: dict[str, Any]) -> str:
    """Sentence form, for the verdict: 'most often on Wednesday, mostly on go 2, because ...'."""
    day, go, cause = _failure_parts(m)
    parts = []
    if day:
        parts.append(f"most often on {DAY_NAMES.get(day, day)}")
    if go:
        parts.append(f"mostly on go {go}")
    text = ", ".join(parts)
    if cause:
        text += (", " if text else "") + f"because {CAUSE_WORDS[cause]}"
    if not text and m.get("recovery", {}).get("share_short", 0) > 0:
        text = "at next Monday's recovery check"
    return text or "rarely"


def _fails_short(m: dict[str, Any]) -> str:
    """Table form: 'Wed, go 2: no aircraft back for a turn'."""
    day, go, cause = _failure_parts(m)
    where = ", ".join([p for p in (day, f"go {go}" if go else None) if p])
    what = SHORT_CAUSES.get(cause, "")
    if not where and not what:
        return "Next Monday recovery" if m.get("recovery", {}).get("share_short", 0) > 0 else "Rarely fails"
    return f"{where}: {what}" if where and what else where or what


def _summary(c: dict[str, Any]) -> dict[str, Any]:
    m = c["metrics"]
    return {
        "index": c["index"], "label": c["label"], "family": c["family"], "detail": c["detail"],
        "diagnostic": c["diagnostic"], "is_current": c.get("is_current", False), "target": c["target"],
        "weekly_sorties": c["weekly_sorties"], "sute": c["sute"], "split": c["split"],
        "success": m["probability_success"], "ci95_low": m["ci95_low"], "ci95_high": m["ci95_high"],
        "iterations": m["iterations"], "fails_where": _fails_where(m), "fails_short": _fails_short(m),
        "spares_per_week": c.get("spares_per_week", 0),
        "adds_per_week": m["reported"]["mean_2407_adds_per_week"],
        "resources": c.get("spares_per_week", 0) + m["reported"]["mean_2407_adds_per_week"],
        "confirmed": c.get("confirmed", False),
    }


# [P-6]
def analyze(config: dict[str, Any], results: list[dict[str, Any]], success_target: float = 0.85,
            confirm_limit: int = 8) -> dict[str, Any]:
    """Rank tested patterns, pick leaders to confirm, and write the requirement check."""
    scenario = load_scenario(config)
    required = scenario.required_sorties
    items = [_summary(c) for c in results]
    tested = [i for i in items if not i["is_current"]]
    recommendable = [i for i in tested if not i["diagnostic"]]
    targets = sorted({i["target"] for i in tested if i["target"] is not None})

    def best(group):
        return max(group, key=lambda i: (i["success"], -i["sute"])) if group else None

    per_target = []
    for t in targets:
        group = [i for i in recommendable if i["target"] == t]
        top = best(group)
        per_target.append({"weekly_sorties": t, "sute": t / (scenario.inventory.pai * len(scenario.rules.flying_days)),
                           "best": top, "meets": bool(top and top["success"] >= success_target),
                           "patterns_tested": len([i for i in tested if i["target"] == t])})
    sustained = [p for p in per_target if p["meets"]]
    max_sustained = max(sustained, key=lambda p: p["weekly_sorties"]) if sustained else None

    focus = min(targets, key=lambda t: (abs(t - required), -t)) if targets else None
    family_rows = []
    for family in FAMILIES:
        group = [i for i in tested if i["target"] == focus and i["family"] == family]
        if group:
            top = best(group)
            family_rows.append({**top, "family_note": FAMILY_NOTES[family], "tested": len(group)})
    family_rows.sort(key=lambda r: (r["diagnostic"], -r["success"]))

    # Leaders worth confirming with a longer run: the best few per target near or above the bar.
    confirm = []
    for t in targets:
        group = sorted([i for i in recommendable if i["target"] == t], key=lambda i: -i["success"])
        for i in group[:3]:
            if i["success"] >= success_target - 0.05 and not i["confirmed"]:
                confirm.append(i["index"])
    for row in family_rows:
        if not row["diagnostic"] and not row["confirmed"] and row["index"] not in confirm:
            confirm.append(row["index"])
    current = next((i for i in items if i["is_current"]), None)
    frontier = efficient_frontier(recommendable + ([current] if current else []))

    return {
        "success_target": success_target,
        "required_sorties": required,
        "focus_target": focus,
        "per_target": per_target,
        "families": family_rows,
        "max_sustained": max_sustained,
        "current": current,
        "confirm": confirm[:confirm_limit],
        "frontier": frontier,
        "verdict": _verdict(scenario, success_target, focus, per_target, max_sustained, family_rows, current),
        "patterns_tested": len(tested),
    }


def _verdict(scenario, bar, focus, per_target, max_sustained, family_rows, current) -> list[str]:
    pai = scenario.inventory.pai
    mc = round(scenario.rates.mc_rate * 100)
    required = scenario.required_sorties
    bar_pct = round(bar * 100)
    lines = []
    row = next((p for p in per_target if p["weekly_sorties"] == focus), None)
    if row and row["best"]:
        b = row["best"]
        need = f"{focus} sorties a week" + (" (the requirement)" if focus == required else f" (closest tested to the {required} required)")
        if row["meets"]:
            lines.append(f"To fly {need} with {pai} PAI at {mc}% MC, the best pattern tested is {b['family']} {b['detail']}. "
                         f"It succeeds in {round(b['success'] * 100)}% of weeks; it fails {b['fails_where']}.")
        else:
            lines.append(f"No pattern tested flies {need} in {bar_pct}% of weeks with {pai} PAI at {mc}% MC. "
                         f"The best, {b['family']} {b['detail']}, succeeds in {round(b['success'] * 100)}%; it fails {b['fails_where']}.")
        meeting = [r for r in family_rows if not r["diagnostic"] and r["success"] >= bar]
        recommendable = [r for r in family_rows if not r["diagnostic"]]
        if recommendable:
            lines.append(f"{len(meeting)} of {len(recommendable)} pattern families tested at {focus} a week reach {bar_pct}%.")
    if max_sustained:
        gap = required - max_sustained["weekly_sorties"]
        text = (f"At the {bar_pct}% bar, this fleet sustains up to {max_sustained['weekly_sorties']} sorties a week "
                f"(SUTE {max_sustained['sute']:.2f}) with {max_sustained['best']['family']} {max_sustained['best']['detail']}")
        text += f", {gap} short of the requirement." if gap > 0 else "."
        lines.append(text)
    elif per_target:
        lines.append(f"None of the weekly targets tested reach the {bar_pct}% bar. Fly less, add aircraft or spares, or accept more risk.")
    if current:
        lines.append(f"Your current plan ({current['detail']}, {current['weekly_sorties']} a week) succeeds in "
                     f"{round(current['success'] * 100)}% of weeks.")
    return lines


# [P-7]
def efficient_frontier(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Patterns no other pattern beats on all three: more sorties, higher success, fewer resources.

    Resources are scheduled spares plus 2407 adds per week: aircraft held back or pulled in.
    """
    def dominated(a, b):   # does b beat a?
        return (b["weekly_sorties"] >= a["weekly_sorties"] and b["success"] >= a["success"] - 1e-12
                and b["resources"] <= a["resources"] + 1e-12
                and (b["weekly_sorties"] > a["weekly_sorties"] or b["success"] > a["success"] + 1e-12
                     or b["resources"] < a["resources"] - 1e-12))
    pool = [i for i in items if i]
    front = [a for a in pool if not any(dominated(a, b) for b in pool if b is not a)]
    return sorted(front, key=lambda i: (i["weekly_sorties"], i["success"]))
