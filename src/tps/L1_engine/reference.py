"""Go-level simulation engine (readable reference).

The straightforward version of the model: easiest to read and review against
MODEL_LOGIC.md, whose rule IDs (like [F-3]) appear as comments below.
tps.engine must match it exactly for the same seed.

Model hours [T-1]: day i of rules.all_days spans [24*i, 24*(i+1)); hour 0 of
each day is the first-go launch.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, fields
from random import Random
from typing import Any

from tps.L0_inputs.rules import aircraft_required, can_use_long_fix, commit_aircraft, day_spares, floor_count
from tps.L0_inputs.schemas import MAX_GOES, DayPlan, Options, Scenario, window_key

GOLDEN = 0.6180339887498949  # even-spread sequence for "Expected" draws
NEVER = math.inf

GO_EXTRA_COLUMNS = (
    "adds_2407",
    "spares_used",
    "actual_front_line",
    "actual_exceeds_commit",
    "repeat_recur_events",
    "new_beyond_24hr",
)


# ---------------------------------------------------------------- clock
# [F-4]
def coverage_by_day(all_days: tuple[str, ...], options: Options) -> list[float]:
    """Fix-clock hours available each day (24 unless a weekend coverage is set)."""
    weekend = dict(options.weekend_coverage_hours)
    return [float(weekend.get(day, 24)) for day in all_days]


def ready_time(start: float, hours: float, coverage: list[float]) -> float:
    """Hour a fix finishes, pausing outside each day's covered hours.

    Coverage on a day runs from that day's hour 0. After the last modeled day
    the clock runs continuously.
    """
    t, remaining = start, hours
    while remaining > 1e-9:
        index = int(t // 24)
        if index >= len(coverage):
            return t + remaining
        window_end = 24 * index + coverage[index]
        if t < window_end:
            work = min(remaining, window_end - t)
            t += work
            remaining -= work
            if remaining <= 1e-9:
                break
        t = 24.0 * (index + 1)
    return t


# ---------------------------------------------------------------- draws
# [F-5]
class _Draws:
    """Uniform draws: random, or an even-spread fixed sequence for 'Expected'."""

    def __init__(self, rng: Random, expected: bool, offset: float) -> None:
        self.rng, self.expected, self.k, self.offset = rng, expected, 0, offset

    def next(self) -> float:
        if not self.expected:
            return self.rng.random()
        self.k += 1
        return (self.offset + self.k * GOLDEN) % 1.0


def _event_count(slots: int, rate: float) -> int:
    return min(slots, max(0, math.ceil(round(slots * rate, 9))))


# [E-2]
def _place_events(slots: int, rate: float, mode: str, rng: Random, offset: float) -> set[int]:
    """Which planned sorties (by chronological index) get an event."""
    if slots <= 0 or rate <= 0:
        return set()
    if mode == "Fully Random":
        return {k for k in range(slots) if rng.random() < rate}
    count = _event_count(slots, rate)
    if mode == "Spreadsheet":
        return {min(slots - 1, math.floor((j + offset) * slots / count)) for j in range(count)}
    return set(rng.sample(range(slots), count))


# ---------------------------------------------------------------- engine
@dataclass
class _Jet:
    id: int
    ready_at: float = 0.0
    latent_start: float | None = None  # repeat/recur window for a re-break
    latent_end: float | None = None


def run_week(
    scenario: Scenario,
    rng: Random,
    log: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Simulate one week. Returns (day rows, week values).

    Pass a list as log to record every event of the week in order [X-1]. Recording
    happens after the random draws it describes, so it never changes results.
    """

    def record(kind: str, **event: Any) -> None:
        if log is not None:
            log.append({"kind": kind, **event})

    options = scenario.options
    policy = scenario.rules
    home = scenario.rates
    all_days = policy.all_days
    flying = set(policy.flying_days)
    coverage = coverage_by_day(all_days, options)
    last = len(all_days) - 1

    # Cumulative fix rates, never falling from one window to the next.
    windows, floor = [], 0.0
    for hours, rate in home.fix_windows:
        floor = max(floor, min(1.0, rate))
        windows.append((hours, floor))
    expected = options.fix_mode == "Expected"
    fix_draws = _Draws(rng, expected, 0.0)
    latent_draws = _Draws(rng, expected, 0.5)

    # Planned sorties in time order: (day index, go index).
    # [E-1]
    slots: list[tuple[int, int]] = []
    for index, day in enumerate(all_days):
        if day not in flying:
            continue
        plan = scenario.schedule.get(day, DayPlan())
        for go, count in enumerate((plan.first_go, plan.second_go, plan.third_go, plan.fourth_go)):
            slots.extend([(index, go)] * count)
    break_slots = _place_events(len(slots), home.break_rate, options.event_mode, rng, 0.5)
    abort_slots = _place_events(len(slots), home.ground_abort_rate, options.event_mode, rng, 0.75)

    # [R-1]
    start_mc = floor_count(scenario.inventory.pai * home.mc_rate)
    fleet = [_Jet(i) for i in range(start_mc)]
    commit_limit = commit_aircraft(scenario.inventory.pai, policy)
    returns: list[tuple[float, int]] = []  # (ready_at, bucket hours)
    rows: list[dict[str, Any]] = []
    slot_index = 0

    # [F-1] [F-2] [F-3] [F-6]
    def send_to_fix(jet: _Jet, event_time: float, day_index: int, reason: str = "") -> bool:
        """Start a fix. Returns True if the aircraft is down beyond 24 hr."""
        draw = fix_draws.next()
        fixed_within = [hours for hours, rate in windows if draw < rate]
        if not fixed_within:   # not fixed within the longest window: down for the week
            jet.ready_at, jet.latent_start, jet.latent_end = NEVER, None, None
            record("fix", t=event_time, tail=jet.id, reason=reason, window=None, clock_start=event_time,
                   ready=None, beyond=True, follow_up=None)
            return True
        hours = fixed_within[0]
        start = event_time
        if hours > policy.first_day_fix_hours and not can_use_long_fix(all_days[day_index], policy):
            later = [j for j in range(day_index + 1, len(all_days)) if can_use_long_fix(all_days[j], policy)]
            start = 24.0 * (later[0] if later else len(all_days))
        jet.ready_at = ready_time(start, hours, coverage)
        returns.append((jet.ready_at, hours))
        latent = latent_draws.next()
        if latent < options.repeat_rate:
            jet.latent_start, jet.latent_end = jet.ready_at, jet.ready_at + options.repeat_window_hours
        elif latent < options.repeat_rate + options.recur_rate:
            jet.latent_start, jet.latent_end = jet.ready_at, jet.ready_at + options.recur_window_hours
        else:
            jet.latent_start = jet.latent_end = None
        follow_up = ("repeat" if latent < options.repeat_rate
                     else "recur" if latent < options.repeat_rate + options.recur_rate else None)
        record("fix", t=event_time, tail=jet.id, reason=reason, window=hours, clock_start=start,
               ready=jet.ready_at, beyond=False, follow_up=follow_up)
        return False

    for index, day in enumerate(all_days):
        day_start = 24.0 * index
        plan = scenario.schedule.get(day, DayPlan()) if day in flying else DayPlan()
        spares = day_spares(plan, policy)
        required = aircraft_required(plan, policy) if day in flying else 0
        ready_at_start = [jet for jet in fleet if jet.ready_at <= day_start]
        counts = dict.fromkeys(
            ("sorties_flown", "code_3", "ground_abort", "covered_ground_abort", "lost_sorties",
             "spares_used", "repeat_recur_events", "new_beyond_24hr",
             "lost_first_go_short", "lost_turn_short", "lost_abort_uncovered"),
            0,
        )
        front: list[_Jet] = []
        flown_by_go = [0] * MAX_GOES
        if day in flying:
            record("day", t=day_start, day=day, ready=len(ready_at_start), needed=required,
                   first_go=plan.first_go, lineup=[j.id for j in ready_at_start[:plan.first_go]],
                   spares=[j.id for j in ready_at_start[plan.first_go:required]],
                   down=[{"tail": j.id, "ready": None if j.ready_at == NEVER else j.ready_at}
                         for j in fleet if j.ready_at > day_start])
        added: set[int] = set()

        if day in flying and plan.daily_sorties > 0:
            front = ready_at_start[:required]
            lineup = front[: plan.first_go]
            lineup_ids = {jet.id for jet in lineup}
            front_ids = {jet.id for jet in front}
            flown_today: set[int] = set()

            for go, needed in enumerate((plan.first_go, plan.second_go, plan.third_go, plan.fourth_go)):
                if needed == 0:
                    continue
                launch = day_start + options.go_times[go][0]
                land = day_start + options.go_times[go][1]
                record("go", t=launch, day=day, go=go + 1, needed=needed)
                # [S-2]
                spare_ok = options.spares_cover_goes is None or (go + 1) in options.spares_cover_goes

                # [T-3]
                def ready(jet: _Jet) -> bool:
                    return jet.ready_at <= launch

                if go == 0:
                    primary = list(lineup)
                else:
                    primary = [j for j in fleet if j.id in flown_today and ready(j)]
                primary_ids = {j.id for j in primary}
                backups = [
                    j for j in front
                    if j.id not in flown_today and j.id not in primary_ids and ready(j)
                    and (j.id in lineup_ids or spare_ok)
                ]
                adds = (
                    [j for j in fleet if j.id not in front_ids and ready(j)]
                    if options.allow_2407_adds else []
                )
                # [S-1]
                queue = [(j, "primary") for j in primary] + [(j, "backup") for j in backups] + [
                    (j, "2407") for j in adds
                ]
                cursor = 0

                def take() -> tuple[_Jet, str] | None:
                    nonlocal cursor
                    while cursor < len(queue):
                        jet, tier = queue[cursor]
                        cursor += 1
                        if ready(jet):
                            return jet, tier
                    return None

                for _ in range(needed):
                    slot = slot_index
                    slot_index += 1
                    pick = take()
                    # [E-5] [M-5]
                    if pick is None:
                        # No aircraft left for this sortie: the fleet was short at the
                        # first go, or nothing came back in time for a later go.
                        counts["lost_sorties"] += 1
                        if go > 0:
                            cause = "lost_turn_short"
                        elif len(lineup) < plan.first_go:
                            cause = "lost_first_go_short"   # the day started short
                        else:
                            cause = "lost_abort_uncovered"  # earlier aborts used the spares
                        counts[cause] += 1
                        record("lost", t=launch, day=day, go=go + 1, slot=slot, cause=cause)
                        continue
                    # [E-3]
                    if slot in abort_slots:
                        counts["ground_abort"] += 1
                        record("abort", t=launch, day=day, go=go + 1, slot=slot, tail=pick[0].id)
                        if send_to_fix(pick[0], launch, index, "abort"):
                            counts["new_beyond_24hr"] += 1
                        pick = take()
                        if pick is None:
                            counts["lost_sorties"] += 1
                            counts["lost_abort_uncovered"] += 1
                            record("lost", t=launch, day=day, go=go + 1, slot=slot, cause="lost_abort_uncovered")
                            continue
                        counts["covered_ground_abort"] += 1
                    jet, tier = pick
                    role = ("2407" if tier == "2407" else "planned" if tier == "primary"
                            else "lineup" if jet.id in lineup_ids else "spare")
                    record("launch", t=launch, land=land, day=day, go=go + 1, slot=slot, tail=jet.id, role=role)
                    counts["sorties_flown"] += 1
                    flown_by_go[go] += 1
                    flown_today.add(jet.id)
                    if tier == "backup" and jet.id not in lineup_ids:
                        counts["spares_used"] += 1
                    # [S-3]
                    if tier == "2407" and jet.id not in added:
                        added.add(jet.id)
                        front_ids.add(jet.id)
                    rebreak = False
                    if jet.latent_start is not None:
                        if jet.latent_start <= launch <= jet.latent_end:
                            rebreak = True
                            counts["repeat_recur_events"] += 1
                        if rebreak or launch > jet.latent_end:
                            jet.latent_start = jet.latent_end = None
                    # [E-4]
                    if slot in break_slots or rebreak:
                        counts["code_3"] += 1
                        record("break", t=land, day=day, go=go + 1, tail=jet.id, rebreak=rebreak)
                        if send_to_fix(jet, land, index, "repeat or recur" if rebreak else "break"):
                            counts["new_beyond_24hr"] += 1

        horizon = day_start if index == last else day_start + 24.0
        available = sum(1 for jet in fleet if jet.ready_at <= horizon)
        actual_front = len(front) + len(added)
        rows.append({
            "day": day,
            "first_go": plan.first_go,
            "second_go": plan.second_go,
            "third_go": plan.third_go,
            "fourth_go": plan.fourth_go,
            "spares": spares if day in flying else 0,
            "aircraft_required": required,
            "planned_sorties": plan.daily_sorties,
            "planned_by_go": list(plan.goes),
            "flown_by_go": flown_by_go,
            "sorties_flown": counts["sorties_flown"],
            "pai": scenario.inventory.pai,
            "total_mc_aircraft": start_mc,
            "mc_aircraft_for_flying": len(ready_at_start),
            "code_3": counts["code_3"],
            "ground_abort": counts["ground_abort"],
            "covered_ground_abort": counts["covered_ground_abort"],
            "lost_sorties": counts["lost_sorties"],
            "lost_first_go_short": counts["lost_first_go_short"],
            "lost_turn_short": counts["lost_turn_short"],
            "lost_abort_uncovered": counts["lost_abort_uncovered"],
            "ga_plus_code_3": counts["code_3"] + counts["ground_abort"],
            **{window_key(hours): 0 for hours, _ in windows},
            "available_eod": available,
            "commit_limit": commit_limit,
            "meets_aircraft_required": len(ready_at_start) >= required,
            "within_ttp_commit": required <= commit_limit,
            "adds_2407": len(added),
            "spares_used": counts["spares_used"],
            "actual_front_line": actual_front,
            "actual_exceeds_commit": actual_front > commit_limit,
            "repeat_recur_events": counts["repeat_recur_events"],
            "new_beyond_24hr": counts["new_beyond_24hr"],
        })

    # Fixes completed in each day's window (24i, 24(i+1)], up to next Monday's start.
    for ready_at, hours in returns:
        day_index = math.ceil(ready_at / 24) - 1
        if 0 <= day_index < last:
            rows[day_index][window_key(hours)] += 1

    backlog = start_mc - rows[last]["available_eod"]
    week = {
        "required_sorties": scenario.required_sorties,
        # [M-3]
        "repair_backlog": backlog,
        "backlog_threshold": scenario.backlog_threshold,
        "minimum_required_monday_aircraft": scenario.minimum_monday_aircraft,
        "suppressed_events_count": 0,
    }
    return rows, week
