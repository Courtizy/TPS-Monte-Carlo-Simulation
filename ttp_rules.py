from __future__ import annotations

from dataclasses import dataclass
from math import floor
from typing import Protocol


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
    ute_levels: tuple[float, ...] = (0.40, 0.45, 0.50, 0.52)
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
