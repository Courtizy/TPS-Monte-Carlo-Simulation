from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from math import floor
from typing import Any, Protocol


MODEL_VERSION = "0.21.6"
SCHEDULED_SPARES_MODEL = "Scheduled-Spares Only"
FLEET_FLEX_MODEL = "Fleet-Flex Recovery"


class ScheduleDay(Protocol):
    first_go: int
    spares: int | None


@dataclass(frozen=True)
class HumanFactorWeights:
    waterfall_score: float = 0.20
    flat_score: float = 0.10
    front_week_score: float = 0.18
    friday_recovery_score: float = 0.16
    two_turn_fit: float = 0.12
    friday_turn_recovery: float = 0.10
    first_go_non_increasing: float = 0.08
    friday_frontline_recovery: float = 0.06
    split_first_go_non_increasing: float = 0.30
    split_friday_frontline_recovery: float = 0.25
    split_two_turn_fit: float = 0.25
    optimizer_friday_penalty: float = 0.12
    optimizer_backend_penalty: float = 0.28
    optimizer_frontline_backend_penalty: float = 0.22
    optimizer_frontline_friday_penalty: float = 0.14
    friday_peak_penalty: float = 0.15
    friday_increase_penalty: float = 0.10
    backend_day_penalty: float = 0.08
    backend_increase_penalty: float = 0.08
    frontline_friday_backend_penalty: float = 0.08
    frontline_friday_peak_penalty: float = 0.12
    preferred_turn_ratio: float = 0.30
    max_preferred_turn_ratio: float = 0.45
    optimizer_excessive_turn_penalty: float = 0.08


@dataclass(frozen=True)
class TtpPolicy:
    policy_name: str = "Default TTP Policy"
    policy_version: str = "1.0"
    commit_rate: float = 0.55
    ute_levels: tuple[float, ...] = ()
    ute_min: float = 0.40
    ute_max: float = 0.52
    ute_step: float = 0.01
    flying_days: tuple[str, ...] = ("Mon", "Tue", "Wed", "Thu", "Fri")
    recovery_days: tuple[str, ...] = ("Sat", "Sun", "Next Mon")
    spare_rate: float = 0.0
    max_daily_sorties: int = 9
    max_day_to_day_delta: int | None = 5
    max_second_go: int = 4
    max_third_go: int = 0
    max_fourth_go: int = 0
    allow_zero_days: bool = True
    long_fix_start_day: str = "Tue"
    green_success_threshold: float = 0.85
    yellow_success_threshold: float = 0.70
    orange_success_threshold: float = 0.55
    surge_label: str = "55% Commit Surge"
    high_commit_debt_rate: float = 0.10
    moderate_commit_debt_rate: float = 0.06
    human_factor_weights: HumanFactorWeights = HumanFactorWeights()

    @property
    def all_days(self) -> tuple[str, ...]:
        return self.flying_days + self.recovery_days


DEFAULT_TTP_POLICY = TtpPolicy()
WEEKDAYS = DEFAULT_TTP_POLICY.all_days
FLYING_DAYS = DEFAULT_TTP_POLICY.flying_days


def floor_count(value: float) -> int:
    return max(0, floor(value))


def commit_aircraft(pai: int, policy: TtpPolicy = DEFAULT_TTP_POLICY) -> int:
    return floor_count(pai * policy.commit_rate)


def calculated_spares(
    first_go: int,
    policy: TtpPolicy = DEFAULT_TTP_POLICY,
    spare_rate: float | None = None,
) -> int:
    rate = policy.spare_rate if spare_rate is None else spare_rate
    return floor_count(first_go * rate)


def aircraft_required(
    schedule_day: ScheduleDay,
    policy: TtpPolicy = DEFAULT_TTP_POLICY,
    spare_rate: float | None = None,
) -> int:
    spares = (
        calculated_spares(schedule_day.first_go, policy, spare_rate)
        if schedule_day.spares is None
        else schedule_day.spares
    )
    return schedule_day.first_go + spares


def within_commit(
    required_aircraft: int,
    pai: int,
    policy: TtpPolicy = DEFAULT_TTP_POLICY,
) -> bool:
    return required_aircraft <= commit_aircraft(pai, policy)


def can_use_long_fix(day: str, policy: TtpPolicy = DEFAULT_TTP_POLICY) -> bool:
    all_days = policy.all_days
    if day not in all_days or policy.long_fix_start_day not in all_days:
        return day != policy.flying_days[0]
    return all_days.index(day) >= all_days.index(policy.long_fix_start_day)


def risk_band(success: float, policy: TtpPolicy = DEFAULT_TTP_POLICY) -> str:
    if success >= policy.green_success_threshold:
        return "Green"
    if success >= policy.yellow_success_threshold:
        return "Yellow"
    if success >= policy.orange_success_threshold:
        return "Orange"
    return "Red"


def recovery_model_options() -> tuple[tuple[str, bool], ...]:
    return (
        (SCHEDULED_SPARES_MODEL, False),
        (FLEET_FLEX_MODEL, True),
    )


@dataclass(frozen=True)
class ValidationResult:
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def is_valid(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class ScenarioRunMetadata:
    scenario_name: str
    timestamp_utc: str
    model_version: str
    policy_name: str
    policy_version: str
    random_seed: int | None
    iterations: int
    recovery_model: str
    event_count_model: str
    fix_count_model: str
    input_fingerprint: str


def validate_scenario(scenario: Any) -> ValidationResult:
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
        _daily_sorties(scenario.schedule.get(day))
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
        schedule = scenario.schedule.get(day)
        aircraft_count = aircraft_required(schedule, policy) if schedule is not None else 0
        if aircraft_count > commit_limit:
            warnings.append(f"{day}: aircraft required exceeds the TTP commit cap.")
        if (
            (getattr(schedule, "third_go", 0) and policy.max_third_go == 0)
            or (getattr(schedule, "fourth_go", 0) and policy.max_fourth_go == 0)
        ):
            warnings.append(f"{day}: third/fourth go is scheduled; verify platform policy allows it.")
        if getattr(schedule, "second_go", 0) > policy.max_second_go:
            warnings.append(f"{day}: second-go count exceeds policy max.")
        if getattr(schedule, "third_go", 0) > policy.max_third_go:
            warnings.append(f"{day}: third-go count exceeds policy max.")
        if getattr(schedule, "fourth_go", 0) > policy.max_fourth_go:
            warnings.append(f"{day}: fourth-go count exceeds policy max.")
        if getattr(schedule, "spares", None) == 0 and homestation.use_uncommitted_aircraft_for_ga_recovery is False:
            warnings.append(f"{day}: no scheduled spares under Scheduled-Spares Only recovery.")

    return ValidationResult(tuple(errors), tuple(sorted(set(warnings))))


def validate_optimizer_config(config: Any) -> ValidationResult:
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


def build_run_metadata(
    scenario: Any,
    *,
    scenario_name: str,
    iterations: int,
    random_seed: int | None,
    recovery_model: str,
) -> ScenarioRunMetadata:
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return ScenarioRunMetadata(
        scenario_name=scenario_name,
        timestamp_utc=timestamp,
        model_version=MODEL_VERSION,
        policy_name=scenario.policy.policy_name,
        policy_version=scenario.policy.policy_version,
        random_seed=random_seed,
        iterations=iterations,
        recovery_model=recovery_model,
        event_count_model=scenario.homestation.event_count_model,
        fix_count_model=scenario.homestation.fix_count_model,
        input_fingerprint=_fingerprint_scenario(scenario),
    )


def _validate_rate(name: str, value: float, errors: list[str]) -> None:
    if not 0 <= value <= 1:
        errors.append(f"{name} must be between 0 and 1.")


def _daily_sorties(schedule: Any) -> int:
    if schedule is None:
        return 0
    return (
        getattr(schedule, "first_go", 0)
        + getattr(schedule, "second_go", 0)
        + getattr(schedule, "third_go", 0)
        + getattr(schedule, "fourth_go", 0)
    )


def _fingerprint_scenario(scenario: Any) -> str:
    schedule_text = "|".join(
        f"{day}:{schedule.first_go},{schedule.second_go},{schedule.third_go},{schedule.fourth_go},{schedule.spares}"
        for day, schedule in sorted(scenario.schedule.items())
    )
    raw = "|".join(
        [
            str(scenario.inventory),
            str(scenario.homestation),
            schedule_text,
            str(scenario.total_required_sorties),
            scenario.policy.policy_name,
            scenario.policy.policy_version,
        ]
    )
    return sha256(raw.encode("utf-8")).hexdigest()[:16]
