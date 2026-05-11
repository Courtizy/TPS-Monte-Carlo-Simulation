from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from input_validation import validate_optimizer_config
from model_config import build_scenario
from optimizer import OptimizationConfig, best_by_requirement, optimize_turn_patterns
from pattern_generator import PatternConstraints, capacity_points
from recommendation_engine import add_recommendations, best_recommendation
from simulation_engine import DaySchedule
from surge_model import SurgeSummary, simulate_surge_duration
from ttp_rules import DEFAULT_TTP_POLICY, TtpPolicy, commit_aircraft


@dataclass(frozen=True)
class GuiRunResult:
    config: OptimizationConfig
    rows: list[dict[str, object]]
    best_rows: list[dict[str, object]]
    recommendation: Any
    validation_errors: tuple[str, ...]
    validation_warnings: tuple[str, ...]
    capacity_rows: list[dict[str, object]]
    surge: SurgeSummary | None


def build_gui_config(
    *,
    pai_min: int,
    pai_max: int,
    required_weekly_sorties: int | None,
    iterations: int,
    random_seed: int,
    mc_rate: float,
    ground_abort_rate: float,
    break_rate: float,
    fix_8hr_rate: float,
    fix_12hr_rate: float,
    fix_24hr_rate: float,
    event_count_model: str,
    fix_count_model: str,
    max_patterns: int,
    max_daily_sorties: int,
    max_second_go: int,
    max_day_to_day_delta: int,
    ute_levels: tuple[float, ...] = (),
    attrition_scenarios: tuple[tuple[str, float], ...] = (("Requirement Based", 0.0),),
    policy: TtpPolicy = DEFAULT_TTP_POLICY,
) -> OptimizationConfig:
    explicit_ute_levels = ute_levels or None
    tuned_policy = replace(
        policy,
        ute_levels=ute_levels,
        max_daily_sorties=max_daily_sorties,
        max_second_go=max_second_go,
        max_day_to_day_delta=max_day_to_day_delta,
    )
    return OptimizationConfig(
        policy=tuned_policy,
        pai_min=pai_min,
        pai_max=pai_max,
        iterations=iterations,
        random_seed=random_seed,
        required_weekly_sorties=required_weekly_sorties if required_weekly_sorties else None,
        attrition_scenarios=attrition_scenarios,
        event_count_models=(event_count_model,),
        fix_count_models=(fix_count_model,),
        ute_levels=explicit_ute_levels,
        max_patterns_per_requirement=max_patterns,
        constraints=PatternConstraints.from_policy(tuned_policy),
        mc_rate=mc_rate,
        ground_abort_rate=ground_abort_rate,
        break_rate=break_rate,
        fix_8hr_rate=fix_8hr_rate,
        fix_12hr_rate=fix_12hr_rate,
        fix_24hr_rate=fix_24hr_rate,
    )


def run_gui_model(config: OptimizationConfig, *, include_surge: bool = True) -> GuiRunResult:
    validation = validate_optimizer_config(config)
    if validation.errors:
        return GuiRunResult(
            config=config,
            rows=[],
            best_rows=[],
            recommendation=None,
            validation_errors=validation.errors,
            validation_warnings=validation.warnings,
            capacity_rows=_capacity_rows(config),
            surge=None,
        )

    rows = add_recommendations(optimize_turn_patterns(config), config.policy)
    best_rows = add_recommendations(best_by_requirement(rows), config.policy)
    recommendation = best_recommendation(best_rows, config.policy)
    surge = _run_gui_surge(config, best_rows) if include_surge and best_rows else None
    return GuiRunResult(
        config=config,
        rows=rows,
        best_rows=best_rows,
        recommendation=recommendation,
        validation_errors=validation.errors,
        validation_warnings=validation.warnings,
        capacity_rows=_capacity_rows(config),
        surge=surge,
    )


def pattern_detail_rows(row: dict[str, object]) -> list[dict[str, object]]:
    days = list(DEFAULT_TTP_POLICY.flying_days)
    daily = list(row.get("daily_sequence", []))
    first_go = list(row.get("first_go_sequence", []))
    turns = list(row.get("turn_sequence", []))
    aircraft_required = list(row.get("aircraft_required_sequence", []))
    return [
        _detail_row("1st Go", days, first_go),
        _detail_row("Turn Sorties", days, turns),
        _detail_row("Aircraft Required", days, aircraft_required),
        _detail_row("Daily Sorties", days, daily),
    ]


def best_pattern_options(rows: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    options = {}
    for row in rows:
        label = (
            f"{row['pai']} PAI | {row['capacity_label']} | {row['model']} | "
            f"{row['pattern_with_frontlines']} | {float(row['success']):.0%}"
        )
        options[label] = row
    return options


def display_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    fields = [
        "pai",
        "attrition_scenario",
        "capacity_label",
        "weekly_sorties",
        "required_sorties",
        "model",
        "pattern_with_frontlines",
        "operational_assessment",
        "limiting_factor",
        "recommendation_confidence",
        "success",
        "avg_next_monday",
        "recovery_debt",
        "risk_band",
    ]
    return [{field: row.get(field) for field in fields} for row in rows]


def surge_rows(surge: SurgeSummary | None) -> list[dict[str, object]]:
    if surge is None:
        return []
    return [
        {
            "week": week.week,
            "success": week.probability_success,
            "commit_capacity": week.probability_commit_capacity,
            "ending_mc": week.average_ending_mc,
            "next_monday_mc": week.average_next_monday_mc,
            "repair_backlog": week.average_repair_backlog,
            "surge_debt": week.average_surge_debt,
            "risk": week.risk_band,
        }
        for week in surge.weeks
    ]


def _capacity_rows(config: OptimizationConfig) -> list[dict[str, object]]:
    return [
        point
        for pai in range(config.pai_min, config.pai_max + 1)
        for point in capacity_points(
            pai,
            flying_days=config.flying_days,
            ute_levels=config.ute_levels,
            policy=config.policy,
        )
    ]


def _run_gui_surge(config: OptimizationConfig, best_rows: list[dict[str, object]]) -> SurgeSummary | None:
    surge_candidates = [
        row for row in best_rows
        if row["capacity_label"] == config.policy.surge_label and row["model"] == "Fleet-Flex Recovery"
    ]
    if not surge_candidates:
        return None
    surge_row = max(surge_candidates, key=lambda row: (float(row["success"]), int(row["weekly_sorties"])))
    pai = int(surge_row["pai"])
    commit_count = commit_aircraft(pai, config.policy)
    if commit_count <= 0:
        return None
    schedule = {day: DaySchedule(first_go=commit_count) for day in config.policy.flying_days}
    scenario = build_scenario(
        schedule=schedule,
        total_required_sorties=max(1, int(surge_row["required_sorties"])),
        use_uncommitted_aircraft_for_ga_recovery=True,
        pai=pai,
        event_count_model=str(surge_row["event_count_model"]),
        fix_count_model=str(surge_row["fix_count_model"]),
        policy=config.policy,
        mc_rate=config.mc_rate,
        ground_abort_rate=config.ground_abort_rate,
        break_rate=config.break_rate,
        fix_8hr_rate=config.fix_8hr_rate,
        fix_12hr_rate=config.fix_12hr_rate,
        fix_24hr_rate=config.fix_24hr_rate,
    )
    return simulate_surge_duration(
        scenario,
        max_surge_weeks=6,
        iterations=max(50, min(config.iterations, 500)),
        seed=config.random_seed,
    )


def _detail_row(label: str, days: list[str], values: list[int]) -> dict[str, object]:
    row: dict[str, object] = {"Metric": label}
    for index, day in enumerate(days):
        row[day] = values[index] if index < len(values) else 0
    return row
