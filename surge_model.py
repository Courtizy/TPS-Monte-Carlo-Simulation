from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from random import Random
from statistics import mean

from simulation_engine import (
    DayResult,
    DaySchedule,
    IterationResult,
    Scenario,
)
from turn_pattern_modeler import (
    _distribute_events,
    _apply_repair_capacity,
    _sequential_fix_count,
    _weekly_event_count,
)
from ttp_rules import can_use_long_fix, commit_aircraft, floor_count, risk_band


@dataclass(frozen=True)
class SurgeWeekSummary:
    week: int
    probability_success: float
    probability_commit_capacity: float
    average_ending_mc: float
    average_next_monday_mc: float
    average_repair_backlog: float
    average_surge_debt: float
    risk_band: str


@dataclass(frozen=True)
class SurgeSummary:
    weeks: list[SurgeWeekSummary]
    threshold_week: int | None
    max_surge_weeks: int
    iterations: int


def simulate_surge_duration(
    scenario: Scenario,
    max_surge_weeks: int = 6,
    iterations: int = 500,
    seed: int | None = None,
    success_threshold: float | None = None,
    weekly_event_rate_growth: float = 0.12,
    weekly_fix_rate_decay: float = 0.08,
    high_commit_debt_rate: float | None = None,
    moderate_commit_debt_rate: float | None = None,
) -> SurgeSummary:
    policy = scenario.policy
    success_threshold = policy.green_success_threshold if success_threshold is None else success_threshold
    high_commit_debt_rate = (
        policy.high_commit_debt_rate if high_commit_debt_rate is None else high_commit_debt_rate
    )
    moderate_commit_debt_rate = (
        policy.moderate_commit_debt_rate
        if moderate_commit_debt_rate is None
        else moderate_commit_debt_rate
    )
    rng = Random(seed)
    week_successes = [[] for _ in range(max_surge_weeks)]
    week_commit = [[] for _ in range(max_surge_weeks)]
    week_ending_mc = [[] for _ in range(max_surge_weeks)]
    week_next_monday = [[] for _ in range(max_surge_weeks)]
    week_backlog = [[] for _ in range(max_surge_weeks)]
    week_surge_debt = [[] for _ in range(max_surge_weeks)]

    for _ in range(iterations):
        starting_mc = floor_count(scenario.inventory.pai * scenario.homestation.mc_rate)
        available = starting_mc
        repair_backlog = 0
        surge_debt = 0
        for week_index in range(max_surge_weeks):
            week_start_available = max(0, available - surge_debt)
            result, available, repair_backlog = _run_surge_week(
                scenario,
                rng,
                initial_available=week_start_available,
                repair_backlog=repair_backlog,
                week_index=week_index,
                weekly_event_rate_growth=weekly_event_rate_growth,
                weekly_fix_rate_decay=weekly_fix_rate_decay,
            )
            week_successes[week_index].append(result.succeeds)
            week_commit[week_index].append(
                result.stays_within_ttp_commit
                and result.days[0].mc_aircraft_for_flying >= result.days[0].commit_limit
            )
            week_ending_mc[week_index].append(result.days[-1].available_eod)
            week_next_monday[week_index].append(available)
            week_backlog[week_index].append(repair_backlog)
            week_surge_debt[week_index].append(surge_debt)
            surge_debt += _weekly_surge_debt(
                scenario,
                result,
                high_commit_debt_rate=high_commit_debt_rate,
                moderate_commit_debt_rate=moderate_commit_debt_rate,
            )

    weeks = []
    threshold_week = None
    for week_index in range(max_surge_weeks):
        probability_success = _probability(week_successes[week_index])
        if threshold_week is None and probability_success < success_threshold:
            threshold_week = week_index + 1
        weeks.append(
            SurgeWeekSummary(
                week=week_index + 1,
                probability_success=probability_success,
                probability_commit_capacity=_probability(week_commit[week_index]),
                average_ending_mc=mean(week_ending_mc[week_index]),
                average_next_monday_mc=mean(week_next_monday[week_index]),
                average_repair_backlog=mean(week_backlog[week_index]),
                average_surge_debt=mean(week_surge_debt[week_index]),
                risk_band=risk_band(probability_success, policy),
            )
        )

    return SurgeSummary(
        weeks=weeks,
        threshold_week=threshold_week,
        max_surge_weeks=max_surge_weeks,
        iterations=iterations,
    )


def _run_surge_week(
    scenario: Scenario,
    rng: Random,
    initial_available: int,
    repair_backlog: int,
    week_index: int,
    weekly_event_rate_growth: float,
    weekly_fix_rate_decay: float,
) -> tuple[IterationResult, int, int]:
    weekly_sorties = sum(
        scenario.schedule.get(day, DaySchedule()).daily_sorties for day in scenario.policy.flying_days
    )
    event_multiplier = 1 + weekly_event_rate_growth * week_index
    fix_multiplier = max(0.0, 1 - weekly_fix_rate_decay * week_index)
    total_code_3 = _weekly_event_count(
        weekly_sorties,
        min(1.0, scenario.homestation.break_rate * event_multiplier),
        scenario.homestation.event_count_model,
        rng,
    )
    total_ground_aborts = _weekly_event_count(
        weekly_sorties,
        min(1.0, scenario.homestation.ground_abort_rate * event_multiplier),
        scenario.homestation.event_count_model,
        rng,
    )
    code_3_distribution = _distribute_events(total_code_3, scenario, rng)
    ground_abort_distribution = _distribute_events(total_ground_aborts, scenario, rng)
    code_3_by_day = code_3_distribution.events
    ground_aborts_by_day = ground_abort_distribution.events
    suppressed_events_count = (
        code_3_distribution.suppressed_events + ground_abort_distribution.suppressed_events
    )
    validation_warnings = code_3_distribution.warnings + ground_abort_distribution.warnings

    results: list[DayResult] = []
    previous_available: int | None = initial_available
    long_fix_queue = repair_backlog
    recently_fixed_pool = 0

    for day in scenario.policy.all_days:
        schedule = scenario.schedule.get(day, DaySchedule())
        spares = schedule.calculated_spares(policy=scenario.policy) if schedule.spares is None else schedule.spares
        aircraft_required = schedule.aircraft_required(policy=scenario.policy)
        total_mc = floor_count(scenario.inventory.pai * scenario.homestation.mc_rate)
        mc_for_flying = previous_available if previous_available is not None else total_mc

        code_3 = code_3_by_day.get(day, 0)
        if recently_fixed_pool > 0 and scenario.homestation.repeat_recur_multiplier > 1 and day in scenario.policy.flying_days:
            repeat_recur_rate = min(
                1.0,
                scenario.homestation.break_rate
                * (scenario.homestation.repeat_recur_multiplier - 1),
            )
            repeat_recur_events = _weekly_event_count(
                recently_fixed_pool,
                repeat_recur_rate,
                scenario.homestation.event_count_model,
                rng,
            )
            repeat_capacity = max(0, schedule.first_go - code_3)
            if repeat_recur_events > repeat_capacity:
                suppressed_events_count += repeat_recur_events - repeat_capacity
                validation_warnings.append(
                    f"{day}: repeat-recur events exceeded daily front-line capacity"
                )
                repeat_recur_events = repeat_capacity
            code_3 += repeat_recur_events
        ground_abort = ground_aborts_by_day.get(day, 0)
        ga_plus_code_3 = code_3 + ground_abort
        open_events_before_repairs = ga_plus_code_3 + long_fix_queue

        fixed_8hr, remaining = _sequential_fix_count(
            ga_plus_code_3,
            scenario.homestation.fix_8hr_rate * fix_multiplier,
            scenario.homestation.fix_count_model,
            rng,
        )
        if not can_use_long_fix(day, scenario.policy):
            fixed_12hr = 0
            fixed_24hr = 0
            long_fix_queue += remaining
        else:
            long_fix_candidates = long_fix_queue + remaining
            fixed_12hr, remaining_after_12hr = _sequential_fix_count(
                long_fix_candidates,
                scenario.homestation.fix_12hr_rate * fix_multiplier,
                scenario.homestation.fix_count_model,
                rng,
            )
            fixed_24hr, remaining_after_24hr = _sequential_fix_count(
                remaining_after_12hr,
                scenario.homestation.fix_24hr_rate * fix_multiplier,
                scenario.homestation.fix_count_model,
                rng,
            )
            long_fix_queue = remaining_after_24hr

        fixed_8hr, fixed_12hr, fixed_24hr, deferred_repairs = _apply_repair_capacity(
            day,
            fixed_8hr,
            fixed_12hr,
            fixed_24hr,
            scenario,
        )
        long_fix_queue += deferred_repairs
        total_fixes = fixed_8hr + fixed_12hr + fixed_24hr
        if total_fixes > open_events_before_repairs:
            validation_warnings.append(f"{day}: fixes exceeded open events")
        unclamped_available_eod = mc_for_flying - ga_plus_code_3 + total_fixes
        if unclamped_available_eod > scenario.inventory.pai:
            validation_warnings.append(f"{day}: EOD aircraft exceeded PAI and was clamped")
        if unclamped_available_eod < 0:
            validation_warnings.append(f"{day}: EOD aircraft went negative and was clamped")
        available_eod = min(scenario.inventory.pai, max(0, unclamped_available_eod))
        scheduled_spares_available = min(spares, max(0, mc_for_flying - schedule.first_go))
        uncommitted_aircraft_available = (
            max(0, mc_for_flying - aircraft_required)
            if scenario.homestation.use_uncommitted_aircraft_for_ga_recovery
            else 0
        )
        covered_ground_abort = min(ground_abort, scheduled_spares_available + uncommitted_aircraft_available)
        lost_sorties = max(0, ground_abort - covered_ground_abort)
        sorties_flown = max(0, schedule.daily_sorties - lost_sorties)
        commit_limit = commit_aircraft(scenario.inventory.pai, scenario.policy)

        results.append(
            DayResult(
                day=day,
                first_go=schedule.first_go,
                second_go=schedule.second_go,
                third_go=schedule.third_go,
                fourth_go=schedule.fourth_go,
                spares=spares,
                aircraft_required=aircraft_required,
                planned_sorties=schedule.daily_sorties,
                sorties_flown=sorties_flown,
                pai=scenario.inventory.pai,
                total_mc_aircraft=total_mc,
                mc_aircraft_for_flying=mc_for_flying,
                code_3=code_3,
                ground_abort=ground_abort,
                covered_ground_abort=covered_ground_abort,
                lost_sorties=lost_sorties,
                ga_plus_code_3=ga_plus_code_3,
                fixed_8hr=fixed_8hr,
                fixed_12hr=fixed_12hr,
                fixed_24hr=fixed_24hr,
                available_eod=available_eod,
                commit_limit=commit_limit,
                meets_aircraft_required=mc_for_flying >= aircraft_required,
                within_ttp_commit=aircraft_required <= commit_limit,
            )
        )
        previous_available = available_eod
        recently_fixed_pool = total_fixes

    return (
        IterationResult(
            results,
            scenario.total_required_sorties,
            repair_backlog=long_fix_queue,
            backlog_threshold=scenario.homestation.backlog_threshold,
            minimum_required_monday_aircraft=scenario.homestation.minimum_required_monday_aircraft,
            suppressed_events_count=suppressed_events_count,
            validation_warnings=validation_warnings,
        ),
        results[-1].available_eod,
        long_fix_queue,
    )


def _weekly_surge_debt(
    scenario: Scenario,
    result: IterationResult,
    high_commit_debt_rate: float,
    moderate_commit_debt_rate: float,
) -> int:
    flying_days = [day for day in result.days if day.day in scenario.policy.flying_days]
    if not flying_days:
        return 0
    commit_limit = max(flying_days[0].commit_limit, 1)
    average_commit_utilization = mean(day.aircraft_required / commit_limit for day in flying_days)
    if average_commit_utilization >= 0.95:
        return max(1, _ceil_count(scenario.inventory.pai * high_commit_debt_rate))
    if average_commit_utilization >= 0.85:
        return max(1, _ceil_count(scenario.inventory.pai * moderate_commit_debt_rate))
    return 0


def _probability(values: list[bool]) -> float:
    return sum(values) / len(values) if values else 0.0


def _ceil_count(value: float) -> int:
    return max(0, ceil(value))
