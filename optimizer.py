from __future__ import annotations

from dataclasses import dataclass, replace
from random import Random

from model_config import build_scenario
from pattern_generator import (
    PatternConstraints,
    capacity_points,
    generate_turn_pattern_permutations,
)
from simulation_engine import Scenario, SimulationSummary, simulate
from ttp_rules import (
    DEFAULT_TTP_POLICY,
    FLEET_FLEX_MODEL,
    SCHEDULED_SPARES_MODEL,
    TtpPolicy,
    floor_count,
    recovery_model_options,
    risk_band,
)


@dataclass(frozen=True)
class OptimizationConfig:
    policy: TtpPolicy = DEFAULT_TTP_POLICY
    pai_min: int = 1
    pai_max: int = 15
    flying_days: int | None = None
    ute_levels: tuple[float, ...] | None = None
    iterations: int = 250
    random_seed: int | None = 55
    success_threshold: float | None = None
    required_weekly_sorties: int | None = None
    planned_attrition_rate: float | None = None
    planned_attrition_count: int | None = None
    attrition_scenarios: tuple[tuple[str, float], ...] = (("Planning Attrition", 0.15),)
    event_count_models: tuple[str, ...] = ("Normal TTP",)
    fix_count_models: tuple[str, ...] = ("Probabilistic Monte Carlo",)
    max_patterns_per_requirement: int | None = None
    constraints: PatternConstraints = PatternConstraints()
    mc_rate: float = 0.735
    ground_abort_rate: float = 0.064
    break_rate: float = 0.265
    fix_8hr_rate: float = 0.496
    fix_12hr_rate: float = 0.607
    fix_24hr_rate: float = 0.803


def base_optimizer_scenario(
    use_uncommitted_aircraft_for_ga_recovery: bool = False,
    policy: TtpPolicy = DEFAULT_TTP_POLICY,
    *,
    mc_rate: float = 0.735,
    ground_abort_rate: float = 0.064,
    break_rate: float = 0.265,
    fix_8hr_rate: float = 0.496,
    fix_12hr_rate: float = 0.607,
    fix_24hr_rate: float = 0.803,
) -> Scenario:
    return build_scenario(
        schedule={},
        total_required_sorties=1,
        use_uncommitted_aircraft_for_ga_recovery=use_uncommitted_aircraft_for_ga_recovery,
        policy=policy,
        mc_rate=mc_rate,
        ground_abort_rate=ground_abort_rate,
        break_rate=break_rate,
        fix_8hr_rate=fix_8hr_rate,
        fix_12hr_rate=fix_12hr_rate,
        fix_24hr_rate=fix_24hr_rate,
    )


def optimize_turn_patterns(config: OptimizationConfig | None = None) -> list[dict[str, object]]:
    config = config or OptimizationConfig()
    template = _template_from_config(config)
    rng = Random(config.random_seed)
    rows = []
    pattern_cache: dict[tuple[int, int, PatternConstraints], list[dict[str, object]]] = {}
    for pai in range(config.pai_min, config.pai_max + 1):
        points = capacity_points(
            pai,
            flying_days=config.flying_days,
            ute_levels=config.ute_levels,
            policy=config.policy,
        )
        for point in points:
            weekly_sorties = int(point["weekly_sorties"])
            cache_key = (weekly_sorties, pai, config.constraints)
            patterns = pattern_cache.get(cache_key)
            if patterns is None:
                patterns = generate_turn_pattern_permutations(
                    weekly_sorties,
                    pai,
                    template,
                    config.constraints,
                    max_results=config.max_patterns_per_requirement,
                )
                pattern_cache[cache_key] = patterns
            for pattern_index, pattern in enumerate(patterns):
                schedule = pattern["schedule"]
                for attrition_name, attrition_rate in config.attrition_scenarios:
                    required_sorties = _required_sorties(
                        weekly_sorties,
                        config.required_weekly_sorties,
                        attrition_rate,
                        config.planned_attrition_count,
                    )
                    for event_count_model in config.event_count_models:
                        for fix_count_model in config.fix_count_models:
                            for model_name, use_uncommitted in recovery_model_options():
                                scenario = _scenario_for_pattern(
                                    template,
                                    pai,
                                    schedule,
                                    required_sorties,
                                    use_uncommitted,
                                    event_count_model,
                                    fix_count_model,
                                )
                                summary = simulate(
                                    scenario,
                                    iterations=config.iterations,
                                    seed=rng.randrange(1_000_000_000),
                                )
                                rows.append(
                                    _result_row(
                                        pai,
                                        point,
                                        pattern,
                                        model_name,
                                        event_count_model,
                                        fix_count_model,
                                        summary,
                                        _success_threshold(config),
                                        pattern_index,
                                        attrition_name,
                                        attrition_rate,
                                        config.policy,
                                    )
                                )
    return sorted(
        rows,
        key=lambda row: (
            row["pai"],
            row["weekly_sorties"],
            row["event_count_model"],
            row["fix_count_model"],
            row["model"],
            -row["composite_score"],
            row["recovery_debt"],
            row["pattern_signature"],
            row["schedule_signature"],
        ),
    )


def _template_from_config(config: OptimizationConfig) -> Scenario:
    return base_optimizer_scenario(
        False,
        config.policy,
        mc_rate=config.mc_rate,
        ground_abort_rate=config.ground_abort_rate,
        break_rate=config.break_rate,
        fix_8hr_rate=config.fix_8hr_rate,
        fix_12hr_rate=config.fix_12hr_rate,
        fix_24hr_rate=config.fix_24hr_rate,
    )


def best_by_requirement(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    best: dict[tuple[int, int, str, str, str, str, str], dict[str, object]] = {}
    for row in rows:
        key = (
            int(row["pai"]),
            int(row["weekly_sorties"]),
            str(row["capacity_label"]),
            str(row["attrition_scenario"]),
            str(row["event_count_model"]),
            str(row["fix_count_model"]),
            str(row["model"]),
        )
        current = best.get(key)
        if current is None or _rank_key(row) > _rank_key(current):
            best[key] = row
    return sorted(best.values(), key=lambda row: (row["pai"], row["weekly_sorties"], row["event_count_model"], row["fix_count_model"], row["model"]))


def best_by_family(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    best: dict[tuple[int, int, str, str, str, str, str, str], dict[str, object]] = {}
    for row in rows:
        key = (
            int(row["pai"]),
            int(row["weekly_sorties"]),
            str(row["capacity_label"]),
            str(row["attrition_scenario"]),
            str(row["event_count_model"]),
            str(row["fix_count_model"]),
            str(row["model"]),
            str(row["pattern_family"]),
        )
        current = best.get(key)
        if current is None or _rank_key(row) > _rank_key(current):
            best[key] = row
    return sorted(best.values(), key=lambda row: (row["pai"], row["weekly_sorties"], row["event_count_model"], row["fix_count_model"], row["model"], row["pattern_family"]))


def family_rollup(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    families = sorted({str(row["pattern_family"]) for row in rows})
    output = []
    for family in families:
        family_rows = [row for row in rows if row["pattern_family"] == family]
        best = max(family_rows, key=_rank_key)
        output.append(
            {
                "pattern_family": family,
                "tested": len(family_rows),
                "best_pattern": best["pattern_with_frontlines"],
                "best_name": best["pattern_name"],
                "best_peak_frontlines": best["peak_frontlines"],
                "best_commit_aircraft": best["commit_aircraft"],
                "best_success": best["success"],
                "best_score": best["composite_score"],
                "avg_success": sum(float(row["success"]) for row in family_rows) / len(family_rows),
                "avg_recovery_debt": sum(float(row["recovery_debt"]) for row in family_rows) / len(family_rows),
            }
        )
    return sorted(output, key=lambda row: (-row["best_score"], row["pattern_family"]))


def _scenario_for_pattern(
    template: Scenario,
    pai: int,
    schedule,
    required_sorties: int,
    use_uncommitted: bool,
    event_count_model: str,
    fix_count_model: str,
) -> Scenario:
    return replace(
        template,
        inventory=replace(template.inventory, paa=pai, pai=pai),
        homestation=replace(
            template.homestation,
            use_uncommitted_aircraft_for_ga_recovery=use_uncommitted,
            event_count_model=event_count_model,
            fix_count_model=fix_count_model,
        ),
        schedule=schedule,
        total_required_sorties=required_sorties,
    )


def _required_sorties(
    weekly_sorties: int,
    required_weekly_sorties: int | None,
    planned_attrition_rate: float | None,
    planned_attrition_count: int | None = None,
) -> int:
    if required_weekly_sorties is not None and required_weekly_sorties > 0:
        return required_weekly_sorties
    planned_attrition = planned_attrition_allowance(
        weekly_sorties,
        attrition_rate=planned_attrition_rate,
        attrition_count=planned_attrition_count,
    )
    return max(1, weekly_sorties - planned_attrition)


def _floor_count(value: float) -> int:
    return floor_count(value)


def planned_attrition_allowance(
    planned_sorties: int,
    *,
    attrition_rate: float | None = None,
    attrition_count: int | None = None,
) -> int:
    if attrition_count is not None:
        return max(0, attrition_count)
    if attrition_rate is None:
        return 0
    return _floor_count(planned_sorties * attrition_rate)


def _result_row(
    pai: int,
    point: dict[str, object],
    pattern: dict[str, object],
    model_name: str,
    event_count_model: str,
    fix_count_model: str,
    summary: SimulationSummary,
    success_threshold: float,
    pattern_index: int,
    attrition_name: str,
    attrition_rate: float,
    policy: TtpPolicy = DEFAULT_TTP_POLICY,
) -> dict[str, object]:
    classification = pattern["classification"]
    schedule = pattern["schedule"]
    first_go_sequence = [schedule[day].first_go for day in policy.flying_days]
    acft_required_sequence = [
        day.aircraft_required for day in summary.sample_iteration.days if day.day in policy.flying_days
    ]
    turn_sequence = [
        schedule[day].second_go + schedule[day].third_go + schedule[day].fourth_go
        for day in policy.flying_days
    ]
    pattern_with_frontlines = "-".join(
        f"{total}({first_go})"
        for total, first_go in zip(classification["daily_sequence"], first_go_sequence)
    )
    starting_mc = summary.sample_iteration.days[0].total_mc_aircraft
    recovery_debt = max(0.0, starting_mc - summary.average_next_monday_available)
    planned_requirement_met = int(point["weekly_sorties"]) >= summary.required_weekly_sorties
    total_turn_sorties = sum(turn_sequence)
    turn_ratio = total_turn_sorties / max(int(point["weekly_sorties"]), 1)
    peak_frontline_utilization = max(first_go_sequence) / max(int(point["commit_aircraft"]), 1)
    frontline_pressure = _frontline_pressure(first_go_sequence, policy)
    human_factor_score = _human_factor_score(
        list(classification["daily_sequence"]),
        first_go_sequence,
        turn_sequence,
        policy,
    )
    success = summary.probability_success if planned_requirement_met else 0.0
    sortie_success = summary.probability_meet_sorties if planned_requirement_met else 0.0
    planned_attrition_success = (
        summary.probability_within_planned_attrition if planned_requirement_met else 0.0
    )
    failure_mode = _top_count(summary.failure_mode_counts)
    if not planned_requirement_met:
        failure_mode = "Insufficient Planned Sorties"
    score = _composite_score(
        summary,
        classification,
        recovery_debt,
        success,
        sortie_success,
        planned_attrition_success,
        turn_ratio,
        peak_frontline_utilization,
        frontline_pressure,
        human_factor_score,
        policy,
    )
    return {
        "pai": pai,
        "attrition_scenario": attrition_name,
        "attrition_rate": attrition_rate,
        "event_count_model": event_count_model,
        "fix_count_model": fix_count_model,
        "capacity_label": point["label"],
        "weekly_sorties": point["weekly_sorties"],
        "ute": point["actual_ute"],
        "commit_aircraft": point["commit_aircraft"],
        "max_daily_sorties": max(classification["daily_sequence"]),
        "model": model_name,
        "pattern_index": pattern_index,
        "pattern_name": classification["pattern_name"],
        "pattern_family": classification["pattern_family"],
        "pattern_signature": classification["pattern_signature"],
        "schedule_signature": pattern["schedule_signature"],
        "pattern_with_frontlines": pattern_with_frontlines,
        "daily_sequence": classification["daily_sequence"],
        "first_go_sequence": first_go_sequence,
        "turn_sequence": turn_sequence,
        "total_turn_sorties": total_turn_sorties,
        "turn_ratio": turn_ratio,
        "aircraft_required_sequence": acft_required_sequence,
        "peak_frontlines": max(first_go_sequence),
        "frontline_backend": frontline_pressure["backend_frontlines"],
        "frontline_backend_penalty": frontline_pressure["backend_penalty"],
        "frontline_friday": frontline_pressure["friday_frontlines"],
        "frontline_friday_penalty": frontline_pressure["friday_penalty"],
        "frontline_early_preference": frontline_pressure["early_preference"],
        "human_factor_score": human_factor_score,
        "peak_frontline_utilization": peak_frontline_utilization,
        "peak_aircraft_required": max(acft_required_sequence),
        "success": success,
        "success_std_dev": summary.success_std_dev,
        "success_min": summary.success_min,
        "success_max": summary.success_max,
        "success_range": summary.success_max - summary.success_min,
        "success_p10": summary.success_p10,
        "success_p50": summary.success_p50,
        "success_p90": summary.success_p90,
        "success_ci95_low": summary.success_ci95_low,
        "success_ci95_high": summary.success_ci95_high,
        "low_confidence": summary.low_confidence,
        "confidence_warnings": "; ".join(summary.confidence_warnings) or "None",
        "full_schedule_success": summary.probability_full_schedule,
        "sortie_success": sortie_success,
        "daily_schedule_success": summary.probability_daily_schedule,
        "planned_attrition_success": planned_attrition_success,
        "aircraft_success": summary.probability_meet_aircraft_required,
        "commit_success": summary.probability_within_ttp_commit,
        "recovery_success": summary.probability_recovery,
        "backlog_success": summary.probability_backlog,
        "no_suppressed_events_success": summary.probability_no_suppressed_events,
        "avg_actual_attrition": summary.average_actual_attrition,
        "avg_actual_attrition_rate": summary.average_actual_attrition_rate,
        "planned_attrition_rate": summary.planned_attrition_rate,
        "avg_attrition_delta": summary.average_attrition_delta,
        "avg_repair_backlog": summary.average_repair_backlog,
        "suppressed_events_count": summary.suppressed_events_count,
        "validation_warnings": "; ".join(summary.validation_warnings) or "None",
        "planned_attrition": summary.planned_attrition,
        "required_sorties": summary.required_weekly_sorties,
        "sortie_margin": int(point["weekly_sorties"]) - summary.required_weekly_sorties,
        "avg_next_monday": summary.average_next_monday_available,
        "recovery_debt": recovery_debt,
        "first_failure_point": _top_count(summary.failure_counts),
        "failure_mode": failure_mode,
        "risk_band": risk_band(success, policy),
        "is_successful": success >= success_threshold,
        "smoothness_score": classification["smoothness_score"],
        "compression_score": classification["compression_score"],
        "day_to_day_delta": classification["day_to_day_delta"],
        "friday_sorties": classification["friday_sorties"],
        "friday_load_score": classification["friday_load_score"],
        "friday_penalty": classification["friday_penalty"],
        "friday_recovery_score": classification["friday_recovery_score"],
        "backend_sorties": classification["backend_sorties"],
        "backend_load_score": classification["backend_load_score"],
        "backend_penalty": classification["backend_penalty"],
        "early_week_preference": classification["early_week_preference"],
        "composite_score": score,
    }


def _composite_score(
    summary: SimulationSummary,
    classification: dict[str, object],
    recovery_debt: float,
    success: float,
    sortie_success: float,
    planned_attrition_success: float,
    turn_ratio: float,
    peak_frontline_utilization: float,
    frontline_pressure: dict[str, float],
    human_factor_score: float,
    policy: TtpPolicy = DEFAULT_TTP_POLICY,
) -> float:
    weights = policy.human_factor_weights
    smoothness = float(classification["smoothness_score"])
    compression_penalty = float(classification["compression_score"])
    delta_penalty = float(classification["day_to_day_delta"]) / 10
    friday_penalty = float(classification["friday_penalty"])
    friday_recovery = float(classification["friday_recovery_score"])
    backend_penalty = float(classification["backend_penalty"])
    early_week_preference = float(classification["early_week_preference"])
    frontline_backend_penalty = float(frontline_pressure["backend_penalty"])
    frontline_friday_penalty = float(frontline_pressure["friday_penalty"])
    frontline_early_preference = float(frontline_pressure["early_preference"])
    preferred_turn_ratio = weights.preferred_turn_ratio
    turn_balance = max(0.0, 1 - abs(turn_ratio - preferred_turn_ratio) / preferred_turn_ratio)
    excessive_turn_penalty = max(0.0, turn_ratio - weights.max_preferred_turn_ratio)
    recovery_score = max(0.0, 1 - recovery_debt / max(summary.sample_iteration.days[0].total_mc_aircraft, 1))
    return (
        success * 0.36
        + sortie_success * 0.12
        + summary.probability_within_ttp_commit * 0.14
        + summary.probability_meet_aircraft_required * 0.12
        + recovery_score * 0.08
        + smoothness * 0.08
        + friday_recovery * 0.08
        + early_week_preference * 0.08
        + frontline_early_preference * 0.08
        + human_factor_score * 0.14
        + turn_balance * 0.04
        - compression_penalty * 0.02
        - delta_penalty * 0.01
        - friday_penalty * weights.optimizer_friday_penalty
        - backend_penalty * weights.optimizer_backend_penalty
        - frontline_backend_penalty * weights.optimizer_frontline_backend_penalty
        - frontline_friday_penalty * weights.optimizer_frontline_friday_penalty
        - excessive_turn_penalty * weights.optimizer_excessive_turn_penalty
        - max(0.0, peak_frontline_utilization - 0.85) * 0.03
    )


def _frontline_pressure(
    first_go_sequence: list[int],
    policy: TtpPolicy = DEFAULT_TTP_POLICY,
) -> dict[str, float]:
    weights = policy.human_factor_weights
    total_frontlines = sum(first_go_sequence)
    if not first_go_sequence or not total_frontlines:
        return {
            "backend_frontlines": 0.0,
            "backend_penalty": 0.0,
            "friday_frontlines": 0.0,
            "friday_penalty": 0.0,
            "early_preference": 0.0,
        }

    avg_frontlines = total_frontlines / len(first_go_sequence)
    early_frontlines = sum(first_go_sequence[:2])
    backend_frontlines = sum(first_go_sequence[-2:])
    friday_frontlines = first_go_sequence[-1]
    backend_penalty = max(0.0, (backend_frontlines - early_frontlines) / total_frontlines)
    if friday_frontlines >= avg_frontlines:
        backend_penalty += weights.frontline_friday_backend_penalty
    backend_penalty = min(1.0, backend_penalty)
    friday_penalty = max(0.0, (friday_frontlines - avg_frontlines) / max(avg_frontlines, 1))
    if friday_frontlines == max(first_go_sequence) and friday_frontlines > avg_frontlines:
        friday_penalty += weights.frontline_friday_peak_penalty
    friday_penalty = min(1.0, friday_penalty)
    early_preference = max(0.0, (early_frontlines - backend_frontlines) / total_frontlines)
    return {
        "backend_frontlines": float(backend_frontlines),
        "backend_penalty": backend_penalty,
        "friday_frontlines": float(friday_frontlines),
        "friday_penalty": friday_penalty,
        "early_preference": early_preference,
    }


def _human_factor_score(
    daily_sequence: list[int],
    first_go_sequence: list[int],
    turn_sequence: list[int],
    policy: TtpPolicy = DEFAULT_TTP_POLICY,
) -> float:
    if not daily_sequence:
        return 0.0

    max_daily = max(max(daily_sequence), 1)
    total = sum(daily_sequence)
    early_total = sum(daily_sequence[:2])
    backend_total = sum(daily_sequence[-2:])
    friday_total = daily_sequence[-1]

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
    waterfall_score = non_increasing_steps / max(len(daily_sequence) - 1, 1)
    flat_score = flat_steps / max(len(daily_sequence) - 1, 1)
    front_week_score = max(0.0, (early_total - backend_total) / max(total, 1))
    friday_recovery = max(0.0, 1 - friday_total / max_daily)

    preferred_turn_days = turn_sequence[:4]
    friday_turns = turn_sequence[-1] if turn_sequence else 0
    two_turn_fit = sum(1 for turns in preferred_turn_days if turns == 2) / max(len(preferred_turn_days), 1)
    friday_turn_recovery = 1.0 if friday_turns == 0 else max(0.0, 1 - friday_turns / 3)

    first_go_non_increasing = sum(
        1
        for index in range(1, len(first_go_sequence))
        if first_go_sequence[index] <= first_go_sequence[index - 1]
    ) / max(len(first_go_sequence) - 1, 1)
    friday_frontline_recovery = max(0.0, 1 - first_go_sequence[-1] / max(max(first_go_sequence), 1))

    weights = policy.human_factor_weights
    return min(
        1.0,
        waterfall_score * weights.waterfall_score
        + flat_score * weights.flat_score
        + front_week_score * weights.front_week_score
        + friday_recovery * weights.friday_recovery_score
        + two_turn_fit * weights.two_turn_fit
        + friday_turn_recovery * weights.friday_turn_recovery
        + first_go_non_increasing * weights.first_go_non_increasing
        + friday_frontline_recovery * weights.friday_frontline_recovery,
    )


def _success_threshold(config: OptimizationConfig) -> float:
    return (
        config.policy.green_success_threshold
        if config.success_threshold is None
        else config.success_threshold
    )


def _top_count(counts: dict[str, int]) -> str:
    if not counts:
        return "None"
    key, value = max(counts.items(), key=lambda item: item[1])
    return f"{key} ({value})"


def _rank_key(row: dict[str, object]) -> tuple[float, float, float, float]:
    return (
        float(row["success"]),
        float(row["human_factor_score"]),
        -float(row["friday_penalty"]),
        -float(row["frontline_friday_penalty"]),
        -float(row["backend_penalty"]),
        -float(row["frontline_backend_penalty"]),
        float(row["early_week_preference"]),
        float(row["frontline_early_preference"]),
        float(row["friday_recovery_score"]),
        float(row["composite_score"]),
        -float(row["recovery_debt"]),
        float(row["smoothness_score"]),
    )
