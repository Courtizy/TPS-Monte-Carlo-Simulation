"""Fix candidates and the sustainable-plan search.

build_levers() turns a finished run into a short list of changes a planner can
make, each with its cost, so a sweep can rank them by how much they help.
sustainable_candidates() lists same-every-day patterns (first go x turns) that
fit the rules, so a sweep can find the most sorties that still meet a target.
Both return sweep variants: {"label", "patch", "kind", "cost", ...}.
"""
from __future__ import annotations

from typing import Any

from tps_core.L0_inputs.rules import aircraft_required, commit_aircraft, day_spares
from tps_core.L0_inputs.schemas import DayPlan, load_scenario


# [L-1]
def build_levers(config: dict[str, Any], metrics: dict[str, Any]) -> list[dict[str, Any]]:
    scenario = load_scenario(config)
    rules = scenario.rules
    commit = commit_aircraft(scenario.inventory.pai, rules)
    days = rules.flying_days
    weakest = metrics.get("weakest_day")
    variants = [{"label": "As planned", "patch": {}, "kind": "baseline", "group": "baseline", "cost": "None"}]

    def over_commit(plan: DayPlan, extra: int) -> bool:
        return aircraft_required(plan, rules) + extra > commit

    target = max((aircraft_required(scenario.schedule[d], rules) for d in days), default=0)
    fixed_target = scenario.minimum_monday_aircraft is not None

    def raises_target(changed: list[DayPlan]) -> str:
        if fixed_target or not any(aircraft_required(p, rules) + 1 > target for p in changed):
            return ""
        return "; raises next Monday's recovery target by 1"

    if weakest:
        plan = scenario.schedule[weakest]
        if plan.first_go:
            variants.append({
                "label": f"One more spare on {weakest}",
                "group": "maintenance",
                "patch": {"schedule": {weakest: {"spares": day_spares(plan, rules) + 1}}},
                "kind": "lever",
                "cost": f"1 more aircraft on the {weakest} front line" + (" (above commit)" if over_commit(plan, 1) else "")
                + raises_target([plan]),
            })
        goes = [g for g in plan.goes if g]
        if len(goes) > 1:
            fewer = list(plan.goes)
            fewer[len(goes) - 1] -= 1   # drop one sortie from the day's last go
            names = ("first_go", "second_go", "third_go", "fourth_go")
            variants.append({
                "label": f"One fewer sortie on {weakest}'s last go",
                "group": "scheduling",
                "patch": {"schedule": {weakest: {names[i]: fewer[i] for i in range(4) if fewer[i] != plan.goes[i]}}},
                "kind": "lever",
                "cost": "1 fewer sortie planned" + (
                    " (below the weekly requirement)"
                    if sum(p.daily_sorties for p in scenario.schedule.values()) - 1 < scenario.required_sorties else ""),
            })
    flying_plans = {d: scenario.schedule[d] for d in days if scenario.schedule[d].first_go}
    if flying_plans:
        above = any(over_commit(p, 1) for p in flying_plans.values())
        variants.append({
            "label": "One more spare every day",
            "group": "maintenance",
            "patch": {"schedule": {d: {"spares": day_spares(p, rules) + 1} for d, p in flying_plans.items()}},
            "kind": "lever",
            "cost": "1 more aircraft on each day's front line" + (" (above commit on some days)" if above else "")
            + raises_target(list(flying_plans.values())),
        })
    if not scenario.options.allow_2407_adds:
        variants.append({
            "label": "Allow 2407 adds",
            "group": "maintenance",
            "patch": {"options": {"allow_2407_adds": True}},
            "kind": "lever",
            "cost": "Unplanned aircraft each need approval and count against commit afterward",
        })
    if weakest:
        variants.extend(_moves(scenario, metrics, weakest, commit))
    weekend = dict(scenario.options.weekend_coverage_hours)
    if weekend.get("Sat", 24) == 0 and weekend.get("Sun", 24) == 0:
        variants.append({
            "label": "One 8-hour repair shift each weekend day",
            "group": "maintenance",
            "patch": {"options": {"weekend_coverage_hours": {"Sat": 8, "Sun": 8}}},
            "kind": "lever",
            "cost": "Two weekend shifts",
        })
    if weekend.get("Sat", 24) < 24 or weekend.get("Sun", 24) < 24:
        variants.append({
            "label": "Weekend repairs around the clock",
            "group": "maintenance",
            "patch": {"options": {"weekend_coverage_hours": {"Sat": 24, "Sun": 24}}},
            "kind": "lever",
            "cost": "Full weekend manning",
        })
    return variants


def _pattern_fits(pattern: tuple[int, ...], rules, commit: int) -> bool:
    plan = DayPlan(*pattern)
    if aircraft_required(plan, rules) > commit:
        return False
    limits = (None, rules.max_second_go, rules.max_third_go, rules.max_fourth_go)
    if any(limit is not None and count > limit for count, limit in zip(pattern, limits)):
        return False
    return rules.max_daily_sorties is None or sum(pattern) <= rules.max_daily_sorties


def _shapes(goes: int, commit: int) -> list[tuple[int, ...]]:
    """Patterns to try when no standard patterns are published.

    Two goes: every first go and turn count. More goes: step-down shapes
    (the same number each go, or 1, 2, or 3 fewer each go), which keeps the
    search small while covering how multi-go days are usually built.
    """
    shapes = set()
    for first in range(1, commit + 1):
        if goes == 1:
            shapes.add((first,))
        elif goes == 2:
            shapes.update((first, turn) for turn in range(first + 1))
        else:
            for step in range(4):
                pattern = tuple(max(first - step * k, 0) for k in range(goes))
                shapes.add(pattern)
                shapes.add(pattern[:-1] + (0,))   # also try leaving the last go empty
    return sorted(shapes)


def pattern_label(pattern: tuple[int, ...]) -> str:
    flown = [str(g) for g in pattern if g]
    return "-".join(flown) + " every day"


def sustainable_candidates(config: dict[str, Any], max_candidates: int = 60) -> list[dict[str, Any]]:
    """Same-every-day patterns that fit the rules, most sorties first.

    Uses the rule set's standard turn patterns when it has them.
    """
    scenario = load_scenario(config)
    rules = scenario.rules
    commit = commit_aircraft(scenario.inventory.pai, rules)
    days = rules.flying_days
    goes = scenario.goes_per_day
    if rules.standard_patterns:
        pool = [tuple(p) + (0,) * (4 - len(p)) for p in rules.standard_patterns if len(p) <= goes]
    else:
        pool = [p + (0,) * (4 - len(p)) for p in _shapes(goes, commit)]
    names = ("first_go", "second_go", "third_go", "fourth_go")
    candidates = []
    per_day = scenario.inventory.pai * len(days)
    for pattern in dict.fromkeys(pool):
        if not _pattern_fits(pattern, rules, commit):
            continue
        weekly = sum(pattern) * len(days)
        candidates.append({
            "label": pattern_label(pattern),
            "patch": {"schedule": {d: {**{names[i]: pattern[i] for i in range(4)}, "spares": None} for d in days}},
            "kind": "candidate",
            "pattern": [g for g in pattern if g],
            "weekly_sorties": weekly,
            "sute": weekly / per_day,
            "standard": bool(rules.standard_patterns),
            "cost": f"{weekly} sorties a week",
        })
    candidates.sort(key=lambda c: (-c["weekly_sorties"], -c["pattern"][0]))
    return candidates[:max_candidates]


GO_NAMES = ("first_go", "second_go", "third_go", "fourth_go")


def _fits(goes: list[int], rules, commit: int) -> bool:
    if any(goes[i + 1] > goes[i] for i in range(3)):
        return False
    plan = DayPlan(*goes)
    if aircraft_required(plan, rules) > commit:
        return False
    limits = (None, rules.max_second_go, rules.max_third_go, rules.max_fourth_go)
    if any(limit is not None and c > limit for c, limit in zip(goes, limits)):
        return False
    return rules.max_daily_sorties is None or sum(goes) <= rules.max_daily_sorties


# [L-2]
def _moves(scenario, metrics, weakest: str, commit: int, how_many: int = 2) -> list[dict[str, Any]]:
    """Move one sortie off the weakest day's last go onto the steadiest days: same weekly flying."""
    rules = scenario.rules
    source = scenario.schedule[weakest]
    flown = [g for g in source.goes if g]
    if not flown:
        return []
    from_go = len(flown) - 1
    src = list(source.goes)
    src[from_go] -= 1
    if not _fits(src, rules, commit) and sum(src) > 0:
        return []
    daily = metrics.get("daily", {})
    others = [d for d in rules.flying_days if d != weakest and scenario.schedule[d].daily_sorties]
    others.sort(key=lambda d: (daily.get(d, {}).get("share_missing_schedule", 1),
                               -(daily.get(d, {}).get("ready_p10", 0) - daily.get(d, {}).get("aircraft_needed", 0))))
    moves = []
    max_go = scenario.goes_per_day
    for day in others:
        dst_plan = scenario.schedule[day]
        for go in [from_go] + [g for g in range(max_go - 1, -1, -1) if g != from_go]:
            dst = list(dst_plan.goes)
            dst[go] += 1
            if go < max_go and _fits(dst, rules, commit):
                moves.append({
                    "label": f"Move one sortie from {weakest} go {from_go + 1} to {day} go {go + 1}",
                    "group": "scheduling",
                    "patch": {"schedule": {
                        weakest: {GO_NAMES[i]: src[i] for i in range(4) if src[i] != source.goes[i]},
                        day: {GO_NAMES[i]: dst[i] for i in range(4) if dst[i] != dst_plan.goes[i]},
                    }},
                    "kind": "lever",
                    "cost": f"Same weekly sorties; {weakest} flies {sum(src)}, {day} flies {sum(dst)}",
                })
                break
        if len(moves) >= how_many:
            break
    return moves
