from __future__ import annotations

from dataclasses import dataclass
from random import Random
from statistics import mean
from typing import Iterable


WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "Next Mon")
FLYING_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri")


@dataclass(frozen=True)
class HomestationData:
    mc_rate: float
    ground_abort_rate: float
    break_rate: float
    fix_8hr_rate: float
    fix_12hr_rate: float
    fix_24hr_rate: float
    ttp_commit_rate: float = 0.55
    afi_spare_rate: float = 0.20
    use_uncommitted_aircraft_for_ga_recovery: bool = True


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

    def calculated_spares(self, spare_rate: float) -> int:
        return round(self.first_go * spare_rate)

    def aircraft_required(self, spare_rate: float) -> int:
        spares = self.calculated_spares(spare_rate) if self.spares is None else self.spares
        return self.first_go + spares


@dataclass(frozen=True)
class Scenario:
    inventory: AircraftInventory
    homestation: HomestationData
    schedule: dict[str, DaySchedule]
    total_required_sorties: int


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

    @property
    def total_sorties(self) -> int:
        return sum(day.sorties_flown for day in self.days if day.day in FLYING_DAYS)

    @property
    def planned_sorties(self) -> int:
        return sum(day.planned_sorties for day in self.days if day.day in FLYING_DAYS)

    @property
    def planned_attrition(self) -> int:
        return max(0, self.planned_sorties - self.required_sorties)

    @property
    def actual_attrition(self) -> int:
        return max(0, self.planned_sorties - self.total_sorties)

    @property
    def stays_within_planned_attrition(self) -> bool:
        return self.actual_attrition <= self.planned_attrition

    @property
    def meets_sortie_requirement(self) -> bool:
        return self.stays_within_planned_attrition

    @property
    def meets_all_aircraft_required(self) -> bool:
        return all(day.meets_aircraft_required for day in self.days if day.day in FLYING_DAYS)

    @property
    def stays_within_ttp_commit(self) -> bool:
        return all(day.within_ttp_commit for day in self.days if day.day in FLYING_DAYS)

    @property
    def succeeds(self) -> bool:
        return (
            self.meets_sortie_requirement
            and self.meets_all_aircraft_required
            and self.stays_within_ttp_commit
        )

    @property
    def failure_modes(self) -> list[str]:
        modes = []
        if not self.meets_sortie_requirement:
            modes.append("Sortie Shortfall")
        if not self.meets_all_aircraft_required:
            modes.append("Aircraft Availability")
        if not self.stays_within_ttp_commit:
            modes.append("TTP Commit")

        starting_mc = self.days[0].total_mc_aircraft if self.days else 0
        next_monday_available = self.days[-1].available_eod if self.days else 0
        if modes and next_monday_available < starting_mc:
            modes.append("Repair Backlog")

        return modes

    @property
    def first_failure_day(self) -> str | None:
        for day in self.days:
            if day.day in FLYING_DAYS and not day.meets_aircraft_required:
                return day.day
            if day.day in FLYING_DAYS and not day.within_ttp_commit:
                return day.day
        if not self.meets_sortie_requirement:
            return "Week"
        return None


@dataclass(frozen=True)
class SimulationSummary:
    iterations: int
    probability_success: float
    probability_meet_sorties: float
    probability_within_planned_attrition: float
    probability_meet_aircraft_required: float
    probability_within_ttp_commit: float
    planned_weekly_sorties: int
    required_weekly_sorties: int
    planned_attrition: int
    average_actual_attrition: float
    average_next_monday_available: float
    failure_counts: dict[str, int]
    failure_mode_counts: dict[str, int]
    sample_iteration: IterationResult
    sortie_totals: list[int]
    actual_attrition_values: list[int]
    next_monday_available_values: list[int]
    daily_lost_sorties: dict[str, list[int]]
    daily_available_eod: dict[str, list[int]]


def run_iteration(scenario: Scenario, rng: Random) -> IterationResult:
    weekly_sorties = sum(scenario.schedule[day].daily_sorties for day in FLYING_DAYS)
    total_code_3 = round(weekly_sorties * scenario.homestation.break_rate)
    total_ground_aborts = round(weekly_sorties * scenario.homestation.ground_abort_rate)

    code_3_by_day = _distribute_events(total_code_3, scenario, rng)
    ground_aborts_by_day = _distribute_events(total_ground_aborts, scenario, rng)

    results: list[DayResult] = []
    previous_available: int | None = None
    long_fix_queue = 0

    for day in WEEKDAYS:
        schedule = scenario.schedule.get(day, DaySchedule())
        spares = schedule.calculated_spares(scenario.homestation.afi_spare_rate) if schedule.spares is None else schedule.spares
        aircraft_required = schedule.aircraft_required(scenario.homestation.afi_spare_rate)
        total_mc = round(scenario.inventory.pai * scenario.homestation.mc_rate)
        mc_for_flying = total_mc if previous_available is None else previous_available

        code_3 = code_3_by_day.get(day, 0)
        ground_abort = ground_aborts_by_day.get(day, 0)
        ga_plus_code_3 = code_3 + ground_abort

        fixed_8hr, remaining = _sequential_fix_count(
            ga_plus_code_3, scenario.homestation.fix_8hr_rate, rng
        )

        if day == "Mon":
            fixed_12hr = 0
            fixed_24hr = 0
            long_fix_queue += remaining
        else:
            long_fix_candidates = long_fix_queue + remaining
            fixed_12hr, remaining_after_12hr = _sequential_fix_count(
                long_fix_candidates, scenario.homestation.fix_12hr_rate, rng
            )
            fixed_24hr, _remaining_after_24hr = _sequential_fix_count(
                remaining_after_12hr, scenario.homestation.fix_24hr_rate, rng
            )
            long_fix_queue = 0

        total_fixes = fixed_8hr + fixed_12hr + fixed_24hr
        available_eod = max(0, mc_for_flying - ga_plus_code_3 + total_fixes)
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

        commit_limit = round(scenario.inventory.pai * scenario.homestation.ttp_commit_rate)
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

    return IterationResult(results, required_sorties=scenario.total_required_sorties)


def simulate(
    scenario: Scenario,
    iterations: int = 10_000,
    seed: int | None = None,
) -> SimulationSummary:
    rng = Random(seed)
    iteration_results = [run_iteration(scenario, rng) for _ in range(iterations)]
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
        probability_success=_probability(result.succeeds for result in iteration_results),
        probability_meet_sorties=_probability(
            result.meets_sortie_requirement for result in iteration_results
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
        planned_weekly_sorties=iteration_results[0].planned_sorties,
        required_weekly_sorties=scenario.total_required_sorties,
        planned_attrition=iteration_results[0].planned_attrition,
        average_actual_attrition=mean(
            result.actual_attrition for result in iteration_results
        ),
        average_next_monday_available=mean(
            result.days[-1].available_eod for result in iteration_results
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
                next(day_result.lost_sorties for day_result in result.days if day_result.day == day)
                for result in iteration_results
            ]
            for day in FLYING_DAYS
        },
        daily_available_eod={
            day: [
                next(
                    day_result.available_eod
                    for day_result in result.days
                    if day_result.day == day
                )
                for result in iteration_results
            ]
            for day in WEEKDAYS
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


def _distribute_events(total_events: int, scenario: Scenario, rng: Random) -> dict[str, int]:
    events = {day: 0 for day in FLYING_DAYS}
    if total_events <= 0:
        return events

    capacity_by_day = {
        day: scenario.schedule[day].first_go
        for day in FLYING_DAYS
        if scenario.schedule[day].first_go > 0
    }

    remaining_capacity = sum(capacity_by_day.values())
    if total_events > remaining_capacity:
        raise ValueError(
            "Weekly GA/Code 3 events exceed total first-go aircraft capacity. "
            "Reduce rates or increase front-line aircraft."
        )

    for _ in range(total_events):
        available_days = [
            day for day, capacity in capacity_by_day.items() if events[day] < capacity
        ]
        selected_day = rng.choice(available_days)
        events[selected_day] += 1

    return events


def _sequential_fix_count(events: int, fix_rate: float, rng: Random) -> tuple[int, int]:
    fixed = sum(1 for _ in range(events) if rng.random() < fix_rate)
    return fixed, events - fixed


def _probability(values: Iterable[bool]) -> float:
    values = list(values)
    if not values:
        return 0.0
    return sum(values) / len(values)
