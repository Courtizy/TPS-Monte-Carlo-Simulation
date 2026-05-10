from __future__ import annotations

from dataclasses import dataclass

from optimizer import OptimizationConfig
from simulation_engine import DaySchedule, Scenario
from ttp_rules import commit_aircraft


@dataclass(frozen=True)
class ValidationResult:
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def is_valid(self) -> bool:
        return not self.errors


def validate_scenario(scenario: Scenario) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    inventory = scenario.inventory
    homestation = scenario.homestation
    policy = scenario.policy

    if inventory.pai <= 0:
        errors.append("PAI must be positive.")
    if inventory.paa < inventory.pai:
        warnings.append("PAA is lower than PAI; verify possessed aircraft inputs.")

    _validate_rate("MC rate", homestation.mc_rate, errors)
    _validate_rate("Ground abort rate", homestation.ground_abort_rate, errors)
    _validate_rate("Break rate", homestation.break_rate, errors)
    _validate_rate("8-hour fix rate", homestation.fix_8hr_rate, errors)
    _validate_rate("12-hour fix rate", homestation.fix_12hr_rate, errors)
    _validate_rate("24-hour fix rate", homestation.fix_24hr_rate, errors)

    if homestation.fix_12hr_rate < homestation.fix_8hr_rate:
        warnings.append("12-hour fix rate is lower than 8-hour fix rate.")
    if homestation.fix_24hr_rate < homestation.fix_12hr_rate:
        warnings.append("24-hour fix rate is lower than 12-hour fix rate.")

    weekly_sorties = sum(
        scenario.schedule.get(day, DaySchedule()).daily_sorties
        for day in policy.flying_days
    )
    if scenario.total_required_sorties > weekly_sorties:
        warnings.append("Required sorties exceed planned sorties; success will require an intentional over-plan exception.")

    commit_limit = commit_aircraft(inventory.pai, policy)
    if commit_limit > inventory.pai:
        errors.append("Commit aircraft cannot exceed PAI.")
    if commit_limit == 0:
        warnings.append("Commit aircraft rounds to zero at this PAI and commit rate.")

    for day in policy.flying_days:
        schedule = scenario.schedule.get(day, DaySchedule())
        aircraft_required = schedule.aircraft_required(policy=policy)
        if aircraft_required > commit_limit:
            warnings.append(f"{day}: aircraft required exceeds the TTP commit cap.")
        if schedule.third_go or schedule.fourth_go:
            warnings.append(f"{day}: third/fourth go is scheduled; verify platform policy allows it.")
        if schedule.second_go > policy.max_second_go:
            warnings.append(f"{day}: second-go count exceeds policy max.")
        if schedule.third_go > policy.max_third_go:
            warnings.append(f"{day}: third-go count exceeds policy max.")
        if schedule.fourth_go > policy.max_fourth_go:
            warnings.append(f"{day}: fourth-go count exceeds policy max.")
        if schedule.spares == 0 and homestation.use_uncommitted_aircraft_for_ga_recovery is False:
            warnings.append(f"{day}: no scheduled spares under Scheduled-Spares Only recovery.")

    return ValidationResult(tuple(errors), tuple(sorted(set(warnings))))


def validate_optimizer_config(config: OptimizationConfig) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    if config.pai_min <= 0 or config.pai_max <= 0:
        errors.append("PAI sweep bounds must be positive.")
    if config.pai_min > config.pai_max:
        errors.append("PAI minimum cannot exceed PAI maximum.")
    if config.iterations < 100:
        warnings.append("Iteration count is low; confidence intervals may be too wide.")
    if config.success_threshold is not None and not 0 <= config.success_threshold <= 1:
        errors.append("Success threshold must be between 0 and 1.")

    for name, rate in config.attrition_scenarios:
        if not 0 <= rate <= 1:
            errors.append(f"{name} attrition rate must be between 0 and 1.")
        if rate > 0.25:
            warnings.append(f"{name} attrition buffer exceeds 25%.")

    return ValidationResult(tuple(errors), tuple(sorted(set(warnings))))


def _validate_rate(name: str, value: float, errors: list[str]) -> None:
    if not 0 <= value <= 1:
        errors.append(f"{name} must be between 0 and 1.")
