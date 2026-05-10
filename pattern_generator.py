from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from statistics import mean, pstdev

from simulation_engine import DaySchedule, Scenario
from ttp_rules import DEFAULT_TTP_POLICY, TtpPolicy, commit_aircraft, floor_count


@dataclass(frozen=True)
class PatternConstraints:
    flying_days: int = len(DEFAULT_TTP_POLICY.flying_days)
    max_daily_sorties: int = DEFAULT_TTP_POLICY.max_daily_sorties
    max_day_to_day_delta: int | None = DEFAULT_TTP_POLICY.max_day_to_day_delta
    max_second_go: int = DEFAULT_TTP_POLICY.max_second_go
    max_third_go: int = DEFAULT_TTP_POLICY.max_third_go
    max_fourth_go: int = DEFAULT_TTP_POLICY.max_fourth_go
    allow_zero_days: bool = DEFAULT_TTP_POLICY.allow_zero_days

    @classmethod
    def from_policy(cls, policy: TtpPolicy) -> "PatternConstraints":
        return cls(
            flying_days=len(policy.flying_days),
            max_daily_sorties=policy.max_daily_sorties,
            max_day_to_day_delta=policy.max_day_to_day_delta,
            max_second_go=policy.max_second_go,
            max_third_go=policy.max_third_go,
            max_fourth_go=policy.max_fourth_go,
            allow_zero_days=policy.allow_zero_days,
        )


def capacity_points(
    pai: int,
    commit_rate: float | None = None,
    flying_days: int | None = None,
    ute_levels: tuple[float, ...] | None = None,
    policy: TtpPolicy = DEFAULT_TTP_POLICY,
) -> list[dict[str, float | int | str]]:
    commit_rate = policy.commit_rate if commit_rate is None else commit_rate
    flying_days = len(policy.flying_days) if flying_days is None else flying_days
    ute_levels = policy.ute_levels if ute_levels is None else ute_levels
    points: list[dict[str, float | int | str]] = []
    seen: set[tuple[int, str]] = set()
    for ute in ute_levels:
        weekly_sorties = floor_count(pai * flying_days * ute)
        actual_ute = weekly_sorties / (pai * flying_days) if pai else 0
        key = (weekly_sorties, f"UTE {ute:.2f}")
        if key not in seen:
            points.append(
                {
                    "label": f"UTE {ute:.2f}",
                    "target_ute": ute,
                    "weekly_sorties": weekly_sorties,
                    "actual_ute": actual_ute,
                    "commit_aircraft": floor_count(pai * commit_rate),
                }
            )
            seen.add(key)

    commit_aircraft_count = floor_count(pai * commit_rate)
    max_commit_weekly_sorties = commit_aircraft_count * flying_days
    max_commit_ute = max_commit_weekly_sorties / (pai * flying_days) if pai else 0
    points.append(
        {
            "label": policy.surge_label,
            "target_ute": max_commit_ute,
            "weekly_sorties": max_commit_weekly_sorties,
            "actual_ute": max_commit_ute,
            "commit_aircraft": commit_aircraft_count,
        }
    )
    return points


def generate_turn_pattern_permutations(
    weekly_sorties: int,
    pai: int,
    scenario: Scenario,
    constraints: PatternConstraints | None = None,
    max_results: int | None = None,
) -> list[dict[str, object]]:
    policy = scenario.policy
    constraints = constraints or PatternConstraints.from_policy(policy)
    commit_aircraft_count = max(1, commit_aircraft(pai, policy))
    daily_cap = min(constraints.max_daily_sorties, commit_aircraft_count + constraints.max_second_go)
    patterns = []

    total_patterns = sorted(
        _daily_total_patterns(weekly_sorties, constraints.flying_days, daily_cap, constraints),
        key=lambda totals: _classification_sort_key(classify_turn_pattern(list(totals), commit_aircraft=commit_aircraft_count, policy=policy)),
    )

    for totals in total_patterns:
        classification = classify_turn_pattern(list(totals), commit_aircraft=commit_aircraft_count, policy=policy)
        schedule_options = sorted(
            _schedule_options_from_daily_totals(totals, commit_aircraft_count, constraints, policy),
            key=lambda schedule: _schedule_pressure_sort_key(schedule, policy),
        )
        if max_results is not None:
            schedule_options = schedule_options[: max(4, min(12, max_results // 10))]
        for schedule in schedule_options:
            if any(day.aircraft_required(policy=policy) > commit_aircraft_count for day in schedule.values()):
                continue
            schedule_signature = _schedule_signature(schedule, policy)
            patterns.append(
                {
                    "daily_totals": list(totals),
                    "schedule": schedule,
                    "classification": classification,
                    "signature": f"{classification['pattern_signature']}|{schedule_signature}",
                    "schedule_signature": schedule_signature,
                }
            )
            if max_results is not None and len(patterns) >= max_results:
                return sorted(patterns, key=_pattern_sort_key)

    return sorted(patterns, key=_pattern_sort_key)


def _classification_sort_key(classification: dict[str, object]) -> tuple[object, ...]:
    return (
        -_human_factor_shape_score(classification["daily_sequence"]),
        classification["compression_score"],
        classification["friday_penalty"],
        classification["backend_penalty"],
        -classification["early_week_preference"],
        -classification["smoothness_score"],
        classification["friday_sorties"],
        classification["pattern_signature"],
    )


def _pattern_sort_key(item: dict[str, object]) -> tuple[object, ...]:
    return (
        -_human_factor_shape_score(item["classification"]["daily_sequence"]),
        item["classification"]["compression_score"],
        item["classification"]["friday_penalty"],
        item["classification"]["backend_penalty"],
        -item["classification"]["early_week_preference"],
        -item["classification"]["smoothness_score"],
        _peak_frontlines(item["schedule"]),
        item["classification"]["friday_sorties"],
        item["signature"],
    )


def _schedule_pressure_sort_key(
    schedule: dict[str, DaySchedule],
    policy: TtpPolicy = DEFAULT_TTP_POLICY,
) -> tuple[object, ...]:
    first_go_sequence = [schedule[day].first_go for day in policy.flying_days]
    turn_sequence = [schedule[day].second_go for day in policy.flying_days]
    total_frontlines = sum(first_go_sequence)
    early_frontlines = sum(first_go_sequence[:2])
    backend_frontlines = sum(first_go_sequence[-2:])
    friday_frontlines = first_go_sequence[-1] if first_go_sequence else 0
    deltas = [
        abs(first_go_sequence[index] - first_go_sequence[index - 1])
        for index in range(1, len(first_go_sequence))
    ]
    return (
        -_human_factor_split_score(first_go_sequence, turn_sequence),
        max(0, backend_frontlines - early_frontlines),
        friday_frontlines,
        max(first_go_sequence, default=0),
        sum(deltas),
        total_frontlines,
        _schedule_signature(schedule),
    )


def _human_factor_shape_score(
    daily_sequence: list[int],
    policy: TtpPolicy = DEFAULT_TTP_POLICY,
) -> float:
    if not daily_sequence:
        return 0.0
    total = sum(daily_sequence)
    max_daily = max(max(daily_sequence), 1)
    non_increasing_steps = sum(
        1
        for index in range(1, len(daily_sequence))
        if daily_sequence[index] <= daily_sequence[index - 1]
    )
    flat_steps = sum(
        1
        for index in range(1, len(daily_sequence))
        if daily_sequence[index] == daily_sequence[index - 1]
    )
    front_week_score = max(0.0, (sum(daily_sequence[:2]) - sum(daily_sequence[-2:])) / max(total, 1))
    friday_recovery = max(0.0, 1 - daily_sequence[-1] / max_daily)
    weights = policy.human_factor_weights
    return min(
        1.0,
        non_increasing_steps / max(len(daily_sequence) - 1, 1) * 0.42
        + flat_steps / max(len(daily_sequence) - 1, 1) * 0.18
        + front_week_score * 0.24
        + friday_recovery * weights.friday_recovery_score,
    )


def _human_factor_split_score(
    first_go_sequence: list[int],
    turn_sequence: list[int],
    policy: TtpPolicy = DEFAULT_TTP_POLICY,
) -> float:
    if not first_go_sequence:
        return 0.0
    first_go_non_increasing = sum(
        1
        for index in range(1, len(first_go_sequence))
        if first_go_sequence[index] <= first_go_sequence[index - 1]
    ) / max(len(first_go_sequence) - 1, 1)
    friday_frontline_recovery = max(0.0, 1 - first_go_sequence[-1] / max(max(first_go_sequence), 1))
    two_turn_fit = sum(1 for turns in turn_sequence[:4] if turns == 2) / max(len(turn_sequence[:4]), 1)
    friday_turn_recovery = 1.0 if turn_sequence[-1] == 0 else max(0.0, 1 - turn_sequence[-1] / 3)
    weights = policy.human_factor_weights
    return min(
        1.0,
        first_go_non_increasing * weights.split_first_go_non_increasing
        + friday_frontline_recovery * weights.split_friday_frontline_recovery
        + two_turn_fit * weights.split_two_turn_fit
        + friday_turn_recovery * weights.friday_turn_recovery,
    )


def classify_turn_pattern(
    pattern: list[int],
    commit_aircraft: int | None = None,
    policy: TtpPolicy = DEFAULT_TTP_POLICY,
) -> dict[str, object]:
    total = sum(pattern)
    avg = mean(pattern) if pattern else 0
    std_dev = pstdev(pattern) if len(pattern) > 1 else 0
    deltas = [pattern[index] - pattern[index - 1] for index in range(1, len(pattern))]
    abs_delta = sum(abs(delta) for delta in deltas)
    max_delta = max((abs(delta) for delta in deltas), default=0)
    peak_sorties = max(pattern) if pattern else 0
    peak_index = pattern.index(peak_sorties) if pattern else 0
    spike_count = sum(1 for value in pattern if value >= avg + 1 and value == peak_sorties)
    valley_count = _valley_count(pattern)
    front_load_score = sum(pattern[:3]) / total if total else 0
    back_load_score = sum(pattern[-3:]) / total if total else 0
    smoothness_score = max(0.0, 1 - (abs_delta / max(total, 1)))
    compression_score = sum(sorted(pattern, reverse=True)[:2]) / total if total else 0
    friday_sorties = pattern[-1] if pattern else 0
    friday_load_score = friday_sorties / max(avg, 1)
    friday_penalty = max(0.0, friday_load_score - 1.0)
    weights = policy.human_factor_weights
    if pattern and friday_sorties == peak_sorties and friday_sorties > avg:
        friday_penalty += weights.friday_peak_penalty
    if len(pattern) >= 2 and friday_sorties > pattern[-2]:
        friday_penalty += weights.friday_increase_penalty
    friday_penalty = min(1.0, friday_penalty)
    friday_recovery_score = max(0.0, 1 - friday_load_score)
    early_week_sorties = sum(pattern[:2])
    backend_sorties = sum(pattern[-2:])
    backend_load_score = backend_sorties / max(total, 1)
    backend_penalty = max(0.0, (backend_sorties - early_week_sorties) / max(total, 1))
    if len(pattern) >= 5 and pattern[4] >= avg:
        backend_penalty += weights.backend_day_penalty
    if len(pattern) >= 5 and pattern[3] + pattern[4] > pattern[0] + pattern[1] + 1:
        backend_penalty += weights.backend_increase_penalty
    backend_penalty = min(1.0, backend_penalty)
    early_week_preference = max(0.0, (early_week_sorties - backend_sorties) / max(total, 1))

    family = _pattern_family(pattern, std_dev, front_load_score, back_load_score, compression_score, valley_count)
    modifiers = _pattern_modifiers(pattern, avg, commit_aircraft, family, policy)
    pattern_name = " ".join(modifiers + [family]).strip()

    return {
        "pattern_name": pattern_name,
        "pattern_family": family,
        "pattern_signature": "-".join(str(value) for value in pattern),
        "daily_sequence": pattern,
        "total_sorties": total,
        "peak_day": policy.flying_days[peak_index] if peak_index < len(policy.flying_days) else str(peak_index + 1),
        "peak_sorties": peak_sorties,
        "standard_deviation": std_dev,
        "day_to_day_delta": max_delta,
        "spike_count": spike_count,
        "valley_count": valley_count,
        "front_load_score": front_load_score,
        "back_load_score": back_load_score,
        "smoothness_score": smoothness_score,
        "compression_score": compression_score,
        "friday_sorties": friday_sorties,
        "friday_load_score": friday_load_score,
        "friday_penalty": friday_penalty,
        "friday_recovery_score": friday_recovery_score,
        "backend_sorties": backend_sorties,
        "backend_load_score": backend_load_score,
        "backend_penalty": backend_penalty,
        "early_week_preference": early_week_preference,
    }


def _schedule_options_from_daily_totals(
    totals: tuple[int, ...],
    commit_aircraft: int,
    constraints: PatternConstraints,
    policy: TtpPolicy = DEFAULT_TTP_POLICY,
) -> list[dict[str, DaySchedule]]:
    day_options = [_day_schedule_options(total, commit_aircraft, constraints) for total in totals]
    if any(not options for options in day_options):
        return []
    return [
        dict(zip(policy.flying_days, option_set))
        for option_set in product(*day_options)
    ]


def _day_schedule_options(
    total: int,
    commit_aircraft: int,
    constraints: PatternConstraints,
) -> list[DaySchedule]:
    if total == 0:
        return [DaySchedule()]

    options = []
    min_first_go = max(1, total - constraints.max_second_go)
    max_first_go = min(total, commit_aircraft)
    for first_go in range(min_first_go, max_first_go + 1):
        second_go = total - first_go
        if second_go > constraints.max_second_go:
            continue
        if second_go > first_go:
            continue
        options.append(DaySchedule(first_go=first_go, second_go=second_go))
    return sorted(
        options,
        key=lambda schedule: (
            schedule.first_go,
            -schedule.second_go,
        ),
    )


def _daily_total_patterns(
    weekly_sorties: int,
    flying_days: int,
    daily_cap: int,
    constraints: PatternConstraints,
) -> list[tuple[int, ...]]:
    patterns: list[tuple[int, ...]] = []

    def build(prefix: tuple[int, ...], remaining_sorties: int) -> None:
        days_left = flying_days - len(prefix)
        if days_left == 0:
            if remaining_sorties == 0:
                patterns.append(prefix)
            return

        min_daily = 0 if constraints.allow_zero_days else 1
        min_remaining_after_today = min_daily * (days_left - 1)
        max_remaining_after_today = daily_cap * (days_left - 1)
        low = max(min_daily, remaining_sorties - max_remaining_after_today)
        high = min(daily_cap, remaining_sorties - min_remaining_after_today)

        for total in range(low, high + 1):
            if prefix and constraints.max_day_to_day_delta is not None:
                if abs(total - prefix[-1]) > constraints.max_day_to_day_delta:
                    continue
            build(prefix + (total,), remaining_sorties - total)

    build((), weekly_sorties)
    return patterns


def _schedule_signature(
    schedule: dict[str, DaySchedule],
    policy: TtpPolicy = DEFAULT_TTP_POLICY,
) -> str:
    return "-".join(
        f"{schedule[day].first_go}/{schedule[day].second_go}/{schedule[day].third_go}/{schedule[day].fourth_go}"
        for day in policy.flying_days
    )


def _peak_frontlines(schedule: dict[str, DaySchedule]) -> int:
    return max(
        (day_schedule.first_go for day_schedule in schedule.values()),
        default=0,
    )


def _pattern_family(
    pattern: list[int],
    std_dev: float,
    front_load_score: float,
    back_load_score: float,
    compression_score: float,
    valley_count: int,
) -> str:
    if std_dev <= 0.75:
        return "Flat Turns"
    if compression_score >= 0.70:
        return "Compressed Surge"
    if _is_monotonic(pattern, descending=True):
        return "Waterfall"
    if _is_monotonic(pattern, descending=False):
        return "Reverse Waterfall"
    if _has_steps(pattern, descending=True):
        return "Step-Down"
    if _has_steps(pattern, descending=False):
        return "Step-Up"
    if _is_sawtooth(pattern):
        return "Sawtooth"
    if valley_count:
        return "Recovery Valley"
    if pattern.index(max(pattern)) in (2, 3):
        return "Midweek Spike"
    if sum(1 for value in pattern if value >= mean(pattern) + 1) >= 2:
        return "Multi-Spike"
    if front_load_score >= 0.62:
        return "Front-Loaded Push"
    if back_load_score >= 0.62:
        return "Back-Loaded Push"
    return "Balanced Push"


def _pattern_modifiers(
    pattern: list[int],
    avg: float,
    commit_aircraft: int | None,
    family: str,
    policy: TtpPolicy = DEFAULT_TTP_POLICY,
) -> list[str]:
    modifiers = []
    if avg >= 7:
        modifiers.append("Heavy")
    elif avg >= 5:
        modifiers.append("Moderate")
    elif avg > 0:
        modifiers.append("Light")
    if family not in ("Front-Loaded Push", "Waterfall", "Step-Down") and sum(pattern[:2]) > sum(pattern[-2:]) + 2:
        modifiers.append("Front-Loaded")
    if family not in ("Back-Loaded Push", "Reverse Waterfall", "Step-Up") and sum(pattern[-2:]) > sum(pattern[:2]) + 2:
        modifiers.append("Back-Loaded")
    if _valley_count(pattern):
        modifiers.append("with Recovery Valley")
    if pattern and pattern[-1] <= max(1, floor_count(avg * policy.commit_rate)):
        modifiers.append("with Friday Recovery")
    return modifiers


def _is_monotonic(pattern: list[int], descending: bool) -> bool:
    pairs = zip(pattern, pattern[1:])
    if descending:
        return all(left >= right for left, right in pairs) and any(left > right for left, right in zip(pattern, pattern[1:]))
    return all(left <= right for left, right in pairs) and any(left < right for left, right in zip(pattern, pattern[1:]))


def _has_steps(pattern: list[int], descending: bool) -> bool:
    if len(set(pattern)) < 3:
        return False
    return _is_monotonic(pattern, descending=descending) and any(pattern[index] == pattern[index - 1] for index in range(1, len(pattern)))


def _is_sawtooth(pattern: list[int]) -> bool:
    deltas = [pattern[index] - pattern[index - 1] for index in range(1, len(pattern))]
    signs = [1 if delta > 0 else -1 if delta < 0 else 0 for delta in deltas]
    signs = [sign for sign in signs if sign]
    return len(signs) >= 3 and all(signs[index] != signs[index - 1] for index in range(1, len(signs)))


def _valley_count(pattern: list[int]) -> int:
    return sum(
        1
        for index in range(1, len(pattern) - 1)
        if pattern[index] + 2 <= min(pattern[index - 1], pattern[index + 1])
    )
