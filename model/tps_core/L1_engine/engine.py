"""Go-level simulation engine (fast path).

Ported unchanged in logic from the verified step 4 engine. The week's plan is
compiled once per run; the inner loop works on plain lists and makes random
draws in exactly the same order as tps_core.reference, so a seed gives
identical results. tests_core/test_engine_equivalence.py enforces that.

Model hours: day i of rules.all_days spans [24*i, 24*(i+1)); hour 0 of each day
is the first-go launch. An aircraft can fly a go if ready_at <= launch.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, fields
from random import Random
from typing import Any

from tps_core.L0_inputs.rules import aircraft_required, can_use_long_fix, commit_aircraft, day_spares, floor_count
from tps_core.L0_inputs.schemas import MAX_GOES, DayPlan, Options, Scenario, window_key

GOLDEN = 0.6180339887498949  # even-spread sequence for "Expected" draws
NEVER = math.inf

GO_EXTRA_COLUMNS = (
    "adds_2407",
    "spares_used",
    "actual_front_line",
    "actual_exceeds_commit",
    "repeat_recur_events",
    "new_beyond_24hr",
    "lost_first_go_short",
    "lost_turn_short",
    "lost_abort_uncovered",
    "planned_by_go",
    "flown_by_go",
)


# ---------------------------------------------------------------- clock
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
# The week's plan (days, goes, times, events placed by fixed rules, fix-clock
# results) does not change between iterations, so it is compiled once per run.
# The inner loop then works on plain lists of numbers. Random draws happen in
# exactly the same order as the original per-iteration version, so a given
# seed produces identical trials.


@dataclass(frozen=True)
class _Go:
    index: int            # 0-based go number
    needed: int
    launch: float
    land: float
    spare_ok: bool
    is_first: bool


@dataclass(frozen=True)
class _Day:
    index: int
    flying: bool
    active: bool          # flying day with at least one planned sortie
    start: float
    horizon: float        # when end-of-day availability is counted
    first_go: int
    required: int
    goes: tuple[_Go, ...]
    long_start: float | None  # start of 12/24-hr fixes if not allowed today
    static: dict[str, Any]    # row fields that never change between iterations


@dataclass
class _Plan:
    days: tuple[_Day, ...]
    slot_count: int
    event_mode: str
    break_rate: float
    abort_rate: float
    sheet_breaks: frozenset[int] | None
    sheet_aborts: frozenset[int] | None
    windows: tuple[tuple[float, float], ...]  # cumulative (hours, rate), rates non-decreasing
    first_day_fix_hours: float
    fixed_zero: dict[str, int]                # zero counter for each window, copied into rows
    expected: bool
    repeat_rate: float
    repeat_or_recur: float
    repeat_window: float
    recur_window: float
    allow_2407: bool
    start_mc: int
    last: int
    coverage: list[float]
    week: dict[str, Any]
    ready_cache: dict[tuple[float, int], float]


def compile_plan(scenario: Scenario) -> _Plan:
    """Precompute everything about the week that does not depend on random draws."""
    options = scenario.options
    policy = scenario.rules
    home = scenario.rates
    all_days = policy.all_days
    flying = set(policy.flying_days)
    last = len(all_days) - 1
    start_mc = floor_count(scenario.inventory.pai * home.mc_rate)
    commit_limit = commit_aircraft(scenario.inventory.pai, policy)
    allowed = [can_use_long_fix(day, policy) for day in all_days]

    days = []
    slot_count = 0
    for index, day in enumerate(all_days):
        is_flying = day in flying
        plan = scenario.schedule.get(day, DayPlan()) if is_flying else DayPlan()
        spares = day_spares(plan, policy)
        required = aircraft_required(plan, policy) if is_flying else 0
        active = is_flying and plan.daily_sorties > 0
        start = 24.0 * index
        goes = []
        if active:
            for go, needed in enumerate((plan.first_go, plan.second_go, plan.third_go, plan.fourth_go)):
                if needed:
                    goes.append(_Go(
                        index=go,
                        needed=needed,
                        launch=start + options.go_times[go][0],
                        land=start + options.go_times[go][1],
                        spare_ok=options.spares_cover_goes is None or (go + 1) in options.spares_cover_goes,
                        is_first=go == 0,
                    ))
                    slot_count += needed
        long_start = None
        if not allowed[index]:
            later = [j for j in range(index + 1, len(all_days)) if allowed[j]]
            long_start = 24.0 * (later[0] if later else len(all_days))
        days.append(_Day(
            index=index,
            flying=is_flying,
            active=active,
            start=start,
            horizon=start if index == last else start + 24.0,
            first_go=plan.first_go,
            required=required,
            goes=tuple(goes),
            long_start=long_start,
            static={
                "day": day,
                "first_go": plan.first_go,
                "second_go": plan.second_go,
                "third_go": plan.third_go,
                "fourth_go": plan.fourth_go,
                "spares": spares if is_flying else 0,
                "aircraft_required": required,
                "planned_sorties": plan.daily_sorties,
                "planned_by_go": list(plan.goes),
                "pai": scenario.inventory.pai,
                "total_mc_aircraft": start_mc,
                "commit_limit": commit_limit,
                "within_ttp_commit": required <= commit_limit,
            },
        ))

    windows, floor = [], 0.0
    for hours, rate in home.fix_windows:
        floor = max(floor, min(1.0, rate))   # cumulative rates never fall
        windows.append((hours, floor))
    sheet = options.event_mode == "Spreadsheet"
    return _Plan(
        days=tuple(days),
        slot_count=slot_count,
        event_mode=options.event_mode,
        break_rate=home.break_rate,
        abort_rate=home.ground_abort_rate,
        # Spreadsheet placement uses no random draws, so it is fixed for the run.
        sheet_breaks=frozenset(_place_events(slot_count, home.break_rate, options.event_mode, None, 0.5)) if sheet else None,
        sheet_aborts=frozenset(_place_events(slot_count, home.ground_abort_rate, options.event_mode, None, 0.75)) if sheet else None,
        windows=tuple(windows),
        first_day_fix_hours=policy.first_day_fix_hours,
        fixed_zero={window_key(hours): 0 for hours, _ in windows},
        expected=options.fix_mode == "Expected",
        repeat_rate=options.repeat_rate,
        repeat_or_recur=options.repeat_rate + options.recur_rate,
        repeat_window=options.repeat_window_hours,
        recur_window=options.recur_window_hours,
        allow_2407=options.allow_2407_adds,
        start_mc=start_mc,
        last=last,
        coverage=coverage_by_day(all_days, options),
        week={
            "required_sorties": scenario.required_sorties,
            "backlog_threshold": scenario.backlog_threshold,
            "minimum_required_monday_aircraft": scenario.minimum_monday_aircraft,
            "suppressed_events_count": 0,
        },
        ready_cache={},
    )


# [A-3]
def run_compiled_week(plan: _Plan, rng: Random) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Simulate one week from a compiled plan. Returns (day rows, week values)."""
    if plan.sheet_breaks is not None:
        break_slots, abort_slots = plan.sheet_breaks, plan.sheet_aborts
    else:
        break_slots = _place_events(plan.slot_count, plan.break_rate, plan.event_mode, rng, 0.5)
        abort_slots = _place_events(plan.slot_count, plan.abort_rate, plan.event_mode, rng, 0.75)

    n = plan.start_mc
    ids = range(n)
    ready = [0.0] * n                       # hour each aircraft is next ready
    latent_start: list[float | None] = [None] * n  # repeat/recur window
    latent_end: list[float] = [0.0] * n
    returns: list[tuple[float, int]] = []   # (ready_at, fix hours)
    windows = plan.windows
    first_day_hours = plan.first_day_fix_hours
    expected = plan.expected
    rand = rng.random
    cache = plan.ready_cache
    coverage = plan.coverage
    fix_k = latent_k = 0

    def send_to_fix(jet: int, event_time: float, day: _Day) -> bool:
        """Start a fix. Returns True if the aircraft is down beyond 24 hr."""
        nonlocal fix_k, latent_k
        if expected:
            fix_k += 1
            draw = (0.0 + fix_k * GOLDEN) % 1.0
        else:
            draw = rand()
        for hours, rate in windows:
            if draw < rate:
                break
        else:
            ready[jet] = NEVER   # not fixed within the longest window: down for the week
            latent_start[jet] = None
            return True
        start = event_time if hours <= first_day_hours or day.long_start is None else day.long_start
        key = (start, hours)
        done = cache.get(key)
        if done is None:
            done = cache[key] = ready_time(start, hours, coverage)
        ready[jet] = done
        returns.append((done, hours))
        if expected:
            latent_k += 1
            latent = (0.5 + latent_k * GOLDEN) % 1.0
        else:
            latent = rand()
        if latent < plan.repeat_rate:
            latent_start[jet], latent_end[jet] = done, done + plan.repeat_window
        elif latent < plan.repeat_or_recur:
            latent_start[jet], latent_end[jet] = done, done + plan.recur_window
        else:
            latent_start[jet] = None
        return False

    rows: list[dict[str, Any]] = []
    slot = 0
    for day in plan.days:
        day_start = day.start
        ready_at_start = [j for j in ids if ready[j] <= day_start]
        flown_count = code_3 = aborts = covered = lost = 0
        lost_first = lost_turn = lost_abort = 0
        flown_by_go = [0] * MAX_GOES
        spares_used = rebreaks = beyond = 0
        front_size = 0
        added = 0

        if day.active:
            front = ready_at_start[: day.required]
            front_size = len(front)
            lineup = front[: day.first_go]
            lineup_set = set(lineup)
            front_set = set(front)
            flown: set[int] = set()

            for go in day.goes:
                launch = go.launch
                if go.is_first:
                    primary = lineup
                else:
                    primary = sorted(j for j in flown if ready[j] <= launch)
                primary_set = set(primary)
                backups = [
                    j for j in front
                    if j not in flown and j not in primary_set and ready[j] <= launch
                    and (go.spare_ok or j in lineup_set)
                ]
                adds = [j for j in ids if j not in front_set and ready[j] <= launch] if plan.allow_2407 else []
                adds_set = set(adds)
                # Candidates never overlap and only picked aircraft change state
                # during a go, so a plain iterator matches a re-checked queue.
                queue = iter(primary + backups + adds)

                for _ in range(go.needed):
                    this_slot = slot
                    slot += 1
                    jet = next(queue, None)
                    if jet is None:
                        lost += 1
                        if not go.is_first:
                            lost_turn += 1
                        elif len(lineup) < day.first_go:
                            lost_first += 1   # the day started short
                        else:
                            lost_abort += 1   # earlier aborts used the spares
                        continue
                    if this_slot in abort_slots:
                        aborts += 1
                        if send_to_fix(jet, launch, day):
                            beyond += 1
                        jet = next(queue, None)
                        if jet is None:
                            lost += 1
                            lost_abort += 1
                            continue
                        covered += 1
                    flown_count += 1
                    flown_by_go[go.index] += 1
                    flown.add(jet)
                    if jet not in lineup_set and jet not in primary_set and jet not in adds_set:
                        spares_used += 1
                    elif jet in adds_set and jet not in front_set:
                        front_set.add(jet)
                        added += 1
                    rebreak = False
                    window_start = latent_start[jet]
                    if window_start is not None:
                        if window_start <= launch <= latent_end[jet]:
                            rebreak = True
                            rebreaks += 1
                        if rebreak or launch > latent_end[jet]:
                            latent_start[jet] = None
                    if this_slot in break_slots or rebreak:
                        code_3 += 1
                        if send_to_fix(jet, go.land, day):
                            beyond += 1

        horizon = day.horizon
        actual_front = front_size + added
        row = dict(day.static)
        row.update(plan.fixed_zero)
        row.update(
            sorties_flown=flown_count,
            mc_aircraft_for_flying=len(ready_at_start),
            code_3=code_3,
            ground_abort=aborts,
            covered_ground_abort=covered,
            lost_sorties=lost,
            lost_first_go_short=lost_first,
            lost_turn_short=lost_turn,
            lost_abort_uncovered=lost_abort,
            flown_by_go=flown_by_go,
            ga_plus_code_3=code_3 + aborts,
            available_eod=len([r for r in ready if r <= horizon]),
            meets_aircraft_required=len(ready_at_start) >= day.required,
            adds_2407=added,
            spares_used=spares_used,
            actual_front_line=actual_front,
            actual_exceeds_commit=actual_front > day.static["commit_limit"],
            repeat_recur_events=rebreaks,
            new_beyond_24hr=beyond,
        )
        rows.append(row)

    # Fixes completed in each day's window (24i, 24(i+1)], up to next Monday's start.
    last = plan.last
    for ready_at, hours in returns:
        day_index = math.ceil(ready_at / 24) - 1
        if 0 <= day_index < last:
            rows[day_index][window_key(hours)] += 1

    week = dict(plan.week)
    week["repair_backlog"] = plan.start_mc - rows[last]["available_eod"]
    return rows, week


def run_week(scenario: Scenario, rng: Random) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Simulate one week. For many weeks, compile_plan() once and call run_compiled_week()."""
    return run_compiled_week(compile_plan(scenario), rng)
