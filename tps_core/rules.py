"""Planning rules (a rule set) and the arithmetic that applies them.

Rule values are data supplied in each config's "rules" block. Only structural
defaults (day names, first-day fix rule) live here; commit and spare rates must
be supplied, so no unit planning value is built into the code.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil, floor

DEFAULT_FLYING_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri")
DEFAULT_RECOVERY_DAYS = ("Sat", "Sun", "Next Mon")
RISK_BANDS = ((0.85, "Green"), (0.70, "Yellow"), (0.55, "Orange"), (0.0, "Red"))


@dataclass(frozen=True)
class RuleSet:
    commit_rate: float
    spare_rate: float
    flying_days: tuple[str, ...] = DEFAULT_FLYING_DAYS
    recovery_days: tuple[str, ...] = DEFAULT_RECOVERY_DAYS
    long_fix_start_day: str = "Tue"
    max_daily_sorties: int | None = None
    max_second_go: int | None = None
    max_third_go: int | None = None
    max_fourth_go: int | None = None
    max_day_to_day_delta: int | None = None
    first_day_fix_hours: float = 8.0   # on the first flying day, longer fixes wait for the next day
    standard_patterns: tuple[tuple[int, ...], ...] | None = None  # MAJCOM standard turn patterns, if published

    @property
    def all_days(self) -> tuple[str, ...]:
        return self.flying_days + self.recovery_days


def floor_count(value: float) -> int:
    return max(0, floor(value))


def ceil_count(value: float) -> int:
    return max(0, ceil(value))


# [R-2]
def commit_aircraft(pai: int, rules: RuleSet) -> int:
    """Committed aircraft: PAI x commit rate, rounded down."""
    return floor_count(pai * rules.commit_rate)


# [R-3]
def calculated_spares(first_go: int, rules: RuleSet) -> int:
    """Scheduled spares: first go x spare rate, rounded up."""
    return ceil_count(first_go * rules.spare_rate)


def day_spares(plan, rules: RuleSet) -> int:
    return calculated_spares(plan.first_go, rules) if plan.spares is None else plan.spares


# [R-4]
def aircraft_required(plan, rules: RuleSet) -> int:
    """Front-line aircraft for a day: first go + spares."""
    return plan.first_go + day_spares(plan, rules)


# [F-3]
def can_use_long_fix(day: str, rules: RuleSet) -> bool:
    """12- and 24-hour fixes are worked from long_fix_start_day onward."""
    days = rules.all_days
    if day not in days or rules.long_fix_start_day not in days:
        return day != rules.flying_days[0]
    return days.index(day) >= days.index(rules.long_fix_start_day)


# [M-8]
def risk_band(probability: float) -> str:
    for threshold, name in RISK_BANDS:
        if probability >= threshold:
            return name
    return RISK_BANDS[-1][1]
