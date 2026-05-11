from __future__ import annotations

from math import ceil, floor
from dataclasses import dataclass, field
from random import Random
from statistics import mean, median, pstdev
from typing import Iterable

from ttp_rules import (
    DEFAULT_TTP_POLICY,
    FLYING_DAYS,
    WEEKDAYS,
    TtpPolicy,
    aircraft_required as policy_aircraft_required,
    calculated_spares as policy_calculated_spares,
    can_use_long_fix,
    commit_aircraft,
    floor_count,
)


@dataclass(frozen=True)
class HomestationData:
    mc_rate: float
    ground_abort_rate: float
    break_rate: float
    fix_8hr_rate: float
    fix_12hr_rate: float
    fix_24hr_rate: float
    ttp_commit_rate: float = DEFAULT_TTP_POLICY.commit_rate
    afi_spare_rate: float = DEFAULT_TTP_POLICY.spare_rate
    use_uncommitted_aircraft_for_ga_recovery: bool = True
    event_count_model: str = "Normal TTP"
    fix_count_model: str = "Probabilistic Monte Carlo"
    minimum_required_monday_aircraft: int | None = None
    backlog_threshold: int = 0
    max_daily_repair_throughput: int | None = None
    weekend_repair_capacity_factor: float = 1.0
    repeat_recur_multiplier: float = 1.0
    fatigue_break_multiplier: float = 1.0
    fatigue_fix_degradation: float = 1.0


@dataclass(frozen=True)
class AircraftInventory:
    paa: int
    pai: int


@dataclass(frozen=True)
class DaySchedule:
    first_go: int = 0
    second_go: int = 0
    third_go: int = 0
    fourth_go: int = 0
    spares: int | None = None

    @property
    def daily_sorties(self) -> int:
        return self.first_go + self.second_go + self.third_go + self.fourth_go

    def calculated_spares(
        self,
        spare_rate: float | None = None,
        policy: TtpPolicy = DEFAULT_TTP_POLICY,
    ) -> int:
        return policy_calculated_spares(self.first_go, policy, spare_rate)

    def aircraft_required(
        self,
        spare_rate: float | None = None,
        policy: TtpPolicy = DEFAULT_TTP_POLICY,
    ) -> int:
        return policy_aircraft_required(self, policy, spare_rate)


@dataclass(frozen=True)
class Scenario:
    inventory: AircraftInventory
    homestation: HomestationData
    schedule: dict[str, DaySchedule]
    total_required_sorties: int
    policy: TtpPolicy = DEFAULT_TTP_POLICY


@dataclass(frozen=True)
class EventDistribution:
    events: dict[str, int]
    suppressed_events: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DayResult:
    day: str
    first_go: int
    second_go: int
    third_go: int
    fourth_go: int
    spares: int
    aircraft_required: int
    planned_sorties: int
    sorties_flown: int
    pai: int
    total_mc_aircraft: int
    mc_aircraft_for_flying: int
    code_3: int
    ground_abort: int
    covered_ground_abort: int
    lost_sorties: int
    ga_plus_code_3: int
    fixed_8hr: int
    fixed_12hr: int
    fixed_24hr: int
    available_eod: int
    commit_limit: int
    meets_aircraft_required: bool
    within_ttp_commit: bool


@dataclass(frozen=True)
class IterationResult:
    days: list[DayResult]
    required_sorties: int
    repair_backlog: int = 0
    backlog_threshold: int = 0
    minimum_required_monday_aircraft: int | None = None
    suppressed_events_count: int = 0
    validation_warnings: list[str] = field(default_factory=list)
    deferred_maintenance_debt: int = 0
    flying_days: tuple[str, ...] = FLYING_DAYS

    @property
    def total_sorties(self) -> int:
        return sum(day.sorties_flown for day in self.days if day.day in self.flying_days)

    @property
    def planned_sorties(self) -> int:
        return sum(day.planned_sorties for day in self.days if day.day in self.flying_days)

    @property
    def planned_attrition(self) -> int:
        return max(0, self.planned_sorties - self.required_sorties)

    @property
    def actual_attrition(self) -> int:
        return max(0, self.planned_sorties - self.total_sorties)

    @property
    def actual_attrition_rate(self) -> float:
        return self.actual_attrition / self.planned_sorties if self.planned_sorties else 0.0

    @property
    def planned_attrition_rate(self) -> float:
        return self.planned_attrition / self.planned_sorties if self.planned_sorties else 0.0

    @property
    def attrition_delta(self) -> float:
        return self.actual_attrition_rate - self.planned_attrition_rate

    @property
    def full_schedule_success(self) -> bool:
        return self.total_sorties >= self.planned_sorties

    @property
    def stays_within_planned_attrition(self) -> bool:
        return self.actual_attrition <= self.planned_attrition

    @property
    def meets_sortie_requirement(self) -> bool:
        return self.total_sorties >= self.required_sorties

    @property
    def daily_schedule_success(self) -> bool:
        return all(
            day.sorties_flown >= day.planned_sorties
            for day in self.days
            if day.day in self.flying_days
        )

    @property
    def failed_days(self) -> list[DayResult]:
        return [
            day for day in self.days
            if day.day in self.flying_days and day.sorties_flown < day.planned_sorties
        ]

    @property
    def daily_sortie_misses(self) -> dict[str, int]:
        return {
            day.day: day.planned_sorties - day.sorties_flown
            for day in self.failed_days
        }

    @property
    def worst_failed_day(self) -> str | None:
        if not self.failed_days:
            return None
        day = max(self.failed_days, key=lambda item: item.planned_sorties - item.sorties_flown)
        return day.day

    @property
    def failed_day_count(self) -> int:
        return len(self.failed_days)

    @property
    def meets_all_aircraft_required(self) -> bool:
        return all(day.meets_aircraft_required for day in self.days if day.day in self.flying_days)

    @property
    def stays_within_ttp_commit(self) -> bool:
        return all(day.within_ttp_commit for day in self.days if day.day in self.flying_days)

    @property
    def recovery_success(self) -> bool:
        if not self.days:
            return False
        threshold = max(
            (day.aircraft_required for day in self.days if day.day in self.flying_days),
            default=0,
        )
        if self.minimum_required_monday_aircraft is not None:
            threshold = self.minimum_required_monday_aircraft
        return self.days[-1].available_eod >= threshold

    @property
    def backlog_success(self) -> bool:
        return self.repair_backlog <= self.backlog_threshold

    @property
    def has_suppressed_events(self) -> bool:
        return self.suppressed_events_count > 0

    @property
    def succeeds(self) -> bool:
        return (
            self.meets_sortie_requirement
            and self.daily_schedule_success
            and self.meets_all_aircraft_required
            and self.stays_within_ttp_commit
            and self.recovery_success
            and self.backlog_success
            and not self.has_suppressed_events
        )

    @property
    def failure_modes(self) -> list[str]:
        modes = []
        if not self.full_schedule_success:
            modes.append("Full Schedule Not Flown")
        if not self.meets_sortie_requirement:
            modes.append("Sortie Shortfall")
        if not self.daily_schedule_success:
            modes.append("Daily Schedule Miss")
        if not self.meets_all_aircraft_required:
            modes.append("Aircraft Availability")
        if not self.stays_within_ttp_commit:
            modes.append("TTP Commit")
        if not self.recovery_success:
            modes.append("Recovery")
        if not self.backlog_success:
            modes.append("Repair Backlog")
        if self.has_suppressed_events:
            modes.append("Event Suppression")

        starting_mc = self.days[0].total_mc_aircraft if self.days else 0
        next_monday_available = self.days[-1].available_eod if self.days else 0
        if modes and next_monday_available < starting_mc and "Repair Backlog" not in modes:
            modes.append("Repair Backlog")

        return modes

    @property
    def first_failure_day(self) -> str | None:
        for day in self.days:
            if day.day in self.flying_days and not day.meets_aircraft_required:
                return day.day
            if day.day in self.flying_days and not day.within_ttp_commit:
                return day.day
            if day.day in self.flying_days and day.sorties_flown < day.planned_sorties:
                return day.day
        if not self.meets_sortie_requirement:
            return "Week"
        if not self.recovery_success:
            return "Next Mon"
        return None


@dataclass(frozen=True)
class SimulationSummary:
    iterations: int
    probability_success: float
    success_std_dev: float
    success_min: float
    success_max: float
    success_p10: float
    success_p50: float
    success_p90: float
    success_ci95_low: float
    success_ci95_high: float
    low_confidence: bool
    confidence_warnings: list[str]
    probability_full_schedule: float
    probability_meet_sorties: float
    probability_daily_schedule: float
    probability_within_planned_attrition: float
    probability_meet_aircraft_required: float
    probability_within_ttp_commit: float
    probability_recovery: float
    probability_backlog: float
    probability_no_suppressed_events: float
    planned_weekly_sorties: int
    required_weekly_sorties: int
    planned_attrition: int
    average_actual_attrition: float
    average_actual_attrition_rate: float
    planned_attrition_rate: float
    average_attrition_delta: float
    average_next_monday_available: float
    average_repair_backlog: float
    suppressed_events_count: int
    validation_warnings: list[str]
    daily_sortie_misses: dict[str, list[int]]
    failed_day_counts: list[int]
    worst_failed_day_counts: dict[str, int]
    failure_counts: dict[str, int]
    failure_mode_counts: dict[str, int]
    sample_iteration: IterationResult
    sortie_totals: list[int]
    actual_attrition_values: list[int]
    next_monday_available_values: list[int]
    daily_lost_sorties: dict[str, list[int]]
    daily_available_eod: dict[str, list[int]]


def run_iteration(scenario: Scenario, rng: Random) -> IterationResult:
    validation_warnings: list[str] = []
    policy = scenario.policy
    weekly_sorties = sum(
        scenario.schedule.get(day, DaySchedule()).daily_sorties for day in policy.flying_days
    )
    total_code_3 = _weekly_event_count(
        weekly_sorties,
        min(1.0, scenario.homestation.break_rate * scenario.homestation.fatigue_break_multiplier),
        scenario.homestation.event_count_model,
        rng,
    )
    total_ground_aborts = _weekly_event_count(
        weekly_sorties,
        scenario.homestation.ground_abort_rate,
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
    validation_warnings.extend(code_3_distribution.warnings)
    validation_warnings.extend(ground_abort_distribution.warnings)

    results: list[DayResult] = []
    previous_available: int | None = None
    long_fix_queue = 0
    recently_fixed_pool = 0

    for day in policy.all_days:
        schedule = scenario.schedule.get(day, DaySchedule())
        spares = schedule.calculated_spares(policy=policy) if schedule.spares is None else schedule.spares
        aircraft_required = schedule.aircraft_required(policy=policy)
        total_mc = floor_count(scenario.inventory.pai * scenario.homestation.mc_rate)
        mc_for_flying = total_mc if previous_available is None else previous_available

        code_3 = code_3_by_day.get(day, 0)
        if recently_fixed_pool > 0 and scenario.homestation.repeat_recur_multiplier > 1 and day in policy.flying_days:
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
            scenario.homestation.fix_8hr_rate * scenario.homestation.fatigue_fix_degradation,
            scenario.homestation.fix_count_model,
            rng,
        )

        if not can_use_long_fix(day, policy):
            fixed_12hr = 0
            fixed_24hr = 0
            long_fix_queue += remaining
        else:
            long_fix_candidates = long_fix_queue + remaining
            fixed_12hr, remaining_after_12hr = _sequential_fix_count(
                long_fix_candidates,
                scenario.homestation.fix_12hr_rate * scenario.homestation.fatigue_fix_degradation,
                scenario.homestation.fix_count_model,
                rng,
            )
            fixed_24hr, remaining_after_24hr = _sequential_fix_count(
                remaining_after_12hr,
                scenario.homestation.fix_24hr_rate * scenario.homestation.fatigue_fix_degradation,
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
        ga_recovery_aircraft = scheduled_spares_available + uncommitted_aircraft_available
        covered_ground_abort = min(ground_abort, ga_recovery_aircraft)
        lost_sorties = max(0, ground_abort - covered_ground_abort)
        sorties_flown = max(0, schedule.daily_sorties - lost_sorties)

        commit_limit = commit_aircraft(scenario.inventory.pai, policy)
        if aircraft_required > commit_limit:
            validation_warnings.append(f"{day}: front-line aircraft exceeded TTP commit cap")
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

    return IterationResult(
        results,
        required_sorties=scenario.total_required_sorties,
        repair_backlog=long_fix_queue,
        backlog_threshold=scenario.homestation.backlog_threshold,
        minimum_required_monday_aircraft=scenario.homestation.minimum_required_monday_aircraft,
        suppressed_events_count=suppressed_events_count,
        validation_warnings=validation_warnings,
        flying_days=policy.flying_days,
    )


def simulate(
    scenario: Scenario,
    iterations: int = 10_000,
    seed: int | None = None,
) -> SimulationSummary:
    rng = Random(seed)
    iteration_results = [run_iteration(scenario, rng) for _ in range(iterations)]
    policy = scenario.policy
    day_maps = [
        {day_result.day: day_result for day_result in result.days}
        for result in iteration_results
    ]
    success_values = [1.0 if result.succeeds else 0.0 for result in iteration_results]
    success_mean = mean(success_values)
    success_std_dev = pstdev(success_values) if len(success_values) > 1 else 0.0
    ci_half_width = 1.96 * (success_std_dev / (len(success_values) ** 0.5)) if success_values else 0.0
    validation_warnings = sorted({
        warning for result in iteration_results for warning in result.validation_warnings
    })
    suppressed_events_count = sum(result.suppressed_events_count for result in iteration_results)
    confidence_warnings = _confidence_warnings(
        iterations=iterations,
        success_std_dev=success_std_dev,
        ci_half_width=ci_half_width,
        suppressed_events_count=suppressed_events_count,
        average_backlog=mean(result.repair_backlog for result in iteration_results),
    )
    failure_counts: dict[str, int] = {}
    failure_mode_counts: dict[str, int] = {}

    for result in iteration_results:
        failure_day = result.first_failure_day
        if failure_day:
            failure_counts[failure_day] = failure_counts.get(failure_day, 0) + 1
        if not result.succeeds:
            for mode in result.failure_modes:
                failure_mode_counts[mode] = failure_mode_counts.get(mode, 0) + 1

    return SimulationSummary(
        iterations=iterations,
        probability_success=success_mean,
        success_std_dev=success_std_dev,
        success_min=min(success_values),
        success_max=max(success_values),
        success_p10=_percentile(success_values, 10),
        success_p50=median(success_values),
        success_p90=_percentile(success_values, 90),
        success_ci95_low=max(0.0, success_mean - ci_half_width),
        success_ci95_high=min(1.0, success_mean + ci_half_width),
        low_confidence=bool(confidence_warnings),
        confidence_warnings=confidence_warnings,
        probability_full_schedule=_probability(
            result.full_schedule_success for result in iteration_results
        ),
        probability_meet_sorties=_probability(
            result.meets_sortie_requirement for result in iteration_results
        ),
        probability_daily_schedule=_probability(
            result.daily_schedule_success for result in iteration_results
        ),
        probability_within_planned_attrition=_probability(
            result.stays_within_planned_attrition for result in iteration_results
        ),
        probability_meet_aircraft_required=_probability(
            result.meets_all_aircraft_required for result in iteration_results
        ),
        probability_within_ttp_commit=_probability(
            result.stays_within_ttp_commit for result in iteration_results
        ),
        probability_recovery=_probability(
            result.recovery_success for result in iteration_results
        ),
        probability_backlog=_probability(
            result.backlog_success for result in iteration_results
        ),
        probability_no_suppressed_events=_probability(
            not result.has_suppressed_events for result in iteration_results
        ),
        planned_weekly_sorties=iteration_results[0].planned_sorties,
        required_weekly_sorties=scenario.total_required_sorties,
        planned_attrition=iteration_results[0].planned_attrition,
        average_actual_attrition=mean(
            result.actual_attrition for result in iteration_results
        ),
        average_actual_attrition_rate=mean(
            result.actual_attrition_rate for result in iteration_results
        ),
        planned_attrition_rate=iteration_results[0].planned_attrition_rate,
        average_attrition_delta=mean(
            result.attrition_delta for result in iteration_results
        ),
        average_next_monday_available=mean(
            result.days[-1].available_eod for result in iteration_results
        ),
        average_repair_backlog=mean(
            result.repair_backlog for result in iteration_results
        ),
        suppressed_events_count=suppressed_events_count,
        validation_warnings=validation_warnings,
        daily_sortie_misses={
            day: [
                result.daily_sortie_misses.get(day, 0)
            for result in iteration_results
            ]
            for day in policy.flying_days
        },
        failed_day_counts=[result.failed_day_count for result in iteration_results],
        worst_failed_day_counts=_counts(
            result.worst_failed_day for result in iteration_results if result.worst_failed_day
        ),
        failure_counts=failure_counts,
        failure_mode_counts=failure_mode_counts,
        sample_iteration=iteration_results[0],
        sortie_totals=[result.total_sorties for result in iteration_results],
        actual_attrition_values=[
            result.actual_attrition for result in iteration_results
        ],
        next_monday_available_values=[
            result.days[-1].available_eod for result in iteration_results
        ],
        daily_lost_sorties={
            day: [
                day_map[day].lost_sorties
            for day_map in day_maps
            ]
            for day in policy.flying_days
        },
        daily_available_eod={
            day: [
                day_map[day].available_eod
                for day_map in day_maps
            ]
            for day in policy.all_days
        },
    )


def compare_turn_patterns(
    scenarios: dict[str, Scenario],
    iterations: int = 10_000,
    seed: int | None = None,
) -> dict[str, SimulationSummary]:
    rng = Random(seed)
    return {
        name: simulate(scenario, iterations=iterations, seed=rng.randrange(1_000_000_000))
        for name, scenario in scenarios.items()
    }


def _distribute_events(total_events: int, scenario: Scenario, rng: Random) -> EventDistribution:
    events = {day: 0 for day in scenario.policy.flying_days}
    if total_events <= 0:
        return EventDistribution(events)

    capacity_by_day = {
        day: scenario.schedule.get(day, DaySchedule()).first_go
        for day in scenario.policy.flying_days
        if scenario.schedule.get(day, DaySchedule()).first_go > 0
    }

    remaining_capacity = sum(capacity_by_day.values())
    suppressed_events = 0
    warnings: list[str] = []
    if total_events > remaining_capacity:
        suppressed_events = total_events - remaining_capacity
        total_events = remaining_capacity
        warnings.append(
            "Event redistribution capacity exhausted; overflow events were suppressed "
            "and this iteration is flagged statistically constrained."
        )

    for _ in range(total_events):
        available_days = [
            day for day, capacity in capacity_by_day.items() if events[day] < capacity
        ]
        selected_day = rng.choice(available_days)
        events[selected_day] += 1

    return EventDistribution(events, suppressed_events=suppressed_events, warnings=warnings)


def _weekly_event_count(
    weekly_sorties: int,
    event_rate: float,
    event_count_model: str,
    rng: Random,
) -> int:
    if event_count_model == "Probabilistic Monte Carlo":
        return sum(1 for _ in range(weekly_sorties) if rng.random() < event_rate)
    return _ceil_count(weekly_sorties * event_rate)


def _sequential_fix_count(
    events: int,
    fix_rate: float,
    fix_count_model: str,
    rng: Random,
) -> tuple[int, int]:
    fix_rate = max(0.0, min(1.0, fix_rate))
    if fix_count_model == "Normal TTP":
        fixed = round(events * fix_rate)
    else:
        fixed = sum(1 for _ in range(events) if rng.random() < fix_rate)
    fixed = min(events, max(0, fixed))
    return fixed, max(0, events - fixed)


def _apply_repair_capacity(
    day: str,
    fixed_8hr: int,
    fixed_12hr: int,
    fixed_24hr: int,
    scenario: Scenario,
) -> tuple[int, int, int, int]:
    if scenario.homestation.max_daily_repair_throughput is None:
        return fixed_8hr, fixed_12hr, fixed_24hr, 0
    capacity = scenario.homestation.max_daily_repair_throughput
    if day in ("Sat", "Sun"):
        capacity = floor_count(capacity * scenario.homestation.weekend_repair_capacity_factor)
    capacity = max(0, capacity)
    total_fixes = fixed_8hr + fixed_12hr + fixed_24hr
    if total_fixes <= capacity:
        return fixed_8hr, fixed_12hr, fixed_24hr, 0

    overflow = total_fixes - capacity
    reduce_24 = min(fixed_24hr, overflow)
    fixed_24hr -= reduce_24
    overflow -= reduce_24
    reduce_12 = min(fixed_12hr, overflow)
    fixed_12hr -= reduce_12
    overflow -= reduce_12
    reduce_8 = min(fixed_8hr, overflow)
    fixed_8hr -= reduce_8
    deferred = reduce_24 + reduce_12 + reduce_8
    return fixed_8hr, fixed_12hr, fixed_24hr, deferred


def _probability(values: Iterable[bool]) -> float:
    values = list(values)
    if not values:
        return 0.0
    return sum(values) / len(values)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * percentile / 100
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = index - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _counts(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def _confidence_warnings(
    iterations: int,
    success_std_dev: float,
    ci_half_width: float,
    suppressed_events_count: int,
    average_backlog: float,
) -> list[str]:
    warnings = []
    if iterations < 100:
        warnings.append("Low iteration count; convergence may be poor")
    if success_std_dev > 0.30:
        warnings.append("High success variance")
    if ci_half_width > 0.10:
        warnings.append("Wide 95% confidence interval")
    if suppressed_events_count > 0:
        warnings.append("Event suppression occurred; result is statistically constrained")
    if average_backlog > 0:
        warnings.append("Repair backlog remains open")
    return warnings


def _ceil_count(value: float) -> int:
    return max(0, ceil(value))
