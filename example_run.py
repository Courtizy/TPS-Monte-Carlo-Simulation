from model_config import build_scenario
from optimizer import FLEET_FLEX_MODEL, SCHEDULED_SPARES_MODEL
from simulation_engine import DaySchedule, Scenario, SimulationSummary, compare_turn_patterns


SAMPLE_ROWS = (
    ("1st Go", "first_go"),
    ("2nd Go", "second_go"),
    ("3rd Go", "third_go"),
    ("4th Go", "fourth_go"),
    ("Spares", "spares"),
    ("Acft Req'd", "aircraft_required"),
    ("Daily Sorties", "planned_sorties"),
    ("Sorties Flown", "sorties_flown"),
    ("PAI", "pai"),
    ("Total MC Acft", "total_mc_aircraft"),
    ("MC Acft for Flying", "mc_aircraft_for_flying"),
    ("Code 3", "code_3"),
    ("GA", "ground_abort"),
    ("GA Covered", "covered_ground_abort"),
    ("Sortie Loss", "lost_sorties"),
    ("GA+Code 3", "ga_plus_code_3"),
    ("8 Hr Fix", "fixed_8hr"),
    ("12 Hr Fix", "fixed_12hr"),
    ("24 Hr Fix", "fixed_24hr"),
    ("Available EOD", "available_eod"),
    ("Commit Limit", "commit_limit"),
)


def print_sample_iteration_table(summary: SimulationSummary) -> None:
    days = summary.sample_iteration.days
    label_width = 20
    col_width = 9
    table_width = label_width + (col_width * len(days))

    print("-" * table_width)
    print(f"{'':<{label_width}}" + "".join(f"{day.day:>{col_width}}" for day in days))
    print("-" * table_width)

    for label, attr in SAMPLE_ROWS:
        values = "".join(f"{getattr(day, attr):>{col_width}}" for day in days)
        print(f"{label:<{label_width}}{values}")

    print("-" * table_width)
    print(
        f"{'Meets Acft Req':<{label_width}}"
        + "".join(_format_bool(day.meets_aircraft_required, col_width) for day in days)
    )
    print(
        f"{'Within TTP Commit':<{label_width}}"
        + "".join(_format_bool(day.within_ttp_commit, col_width) for day in days)
    )
    print("-" * table_width)


def _format_bool(value: bool, width: int) -> str:
    return f"{'Yes' if value else 'No':>{width}}"


def print_summary(name: str, summary: SimulationSummary) -> None:
    print("=" * 72)
    print(name)
    print("=" * 72)
    print(f"Iterations: {summary.iterations:,}")
    print(f"Planned weekly sorties: {summary.planned_weekly_sorties}")
    print(f"Required weekly sorties: {summary.required_weekly_sorties}")
    print(f"Planned attrition allowance: {summary.planned_attrition}")
    print(f"Average actual attrition: {summary.average_actual_attrition:.2f}")
    print(f"Probability of overall success: {summary.probability_success:.2%}")
    print(f"Success standard deviation: {summary.success_std_dev:.2%}")
    print(
        "Success p10/p50/p90: "
        f"{summary.success_p10:.0%}/{summary.success_p50:.0%}/{summary.success_p90:.0%}"
    )
    print(
        "Probability full planned schedule is flown: "
        f"{summary.probability_full_schedule:.2%}"
    )
    print(f"Probability sorties requirement is met: {summary.probability_meet_sorties:.2%}")
    print(f"Probability daily schedule is met: {summary.probability_daily_schedule:.2%}")
    print(
        "Probability actual attrition stays within plan: "
        f"{summary.probability_within_planned_attrition:.2%}"
    )
    print(
        "Probability aircraft required are available: "
        f"{summary.probability_meet_aircraft_required:.2%}"
    )
    print(f"Probability TTP commit stays within limit: {summary.probability_within_ttp_commit:.2%}")
    print(f"Probability next-Monday recovery succeeds: {summary.probability_recovery:.2%}")
    print(f"Probability repair backlog stays within threshold: {summary.probability_backlog:.2%}")
    print(f"Suppressed events: {summary.suppressed_events_count}")
    if summary.low_confidence:
        print(f"Confidence warnings: {summary.confidence_warnings}")
    print(f"Average next Monday available aircraft: {summary.average_next_monday_available:.1f}")
    print(f"Failure counts: {summary.failure_counts}")
    print(f"Failure mode counts: {summary.failure_mode_counts}")
    print()
    print("Sample iteration:")
    print_sample_iteration_table(summary)
    print()


def print_comparison_table(title: str, summaries: dict[str, SimulationSummary]) -> None:
    print(title)
    print()
    print(
        f"{'Pattern':<34} {'Success':>9} {'Sorties':>9} "
        f"{'Pln Attr':>9} {'Avg Attr':>9} {'Aircraft':>9} {'Commit':>9} {'Next Mon':>9}"
    )
    print("-" * 104)
    for name, summary in sorted(
        summaries.items(),
        key=lambda item: item[1].probability_success,
        reverse=True,
    ):
        print(
            f"{name:<34} "
            f"{summary.probability_success:>8.2%} "
            f"{summary.probability_meet_sorties:>8.2%} "
            f"{summary.planned_attrition:>9} "
            f"{summary.average_actual_attrition:>9.2f} "
            f"{summary.probability_meet_aircraft_required:>8.2%} "
            f"{summary.probability_within_ttp_commit:>8.2%} "
            f"{summary.average_next_monday_available:>9.1f}"
        )
    print()


def get_turn_pattern_inputs() -> dict[str, dict[str, object]]:
    return {
        "Pattern A - Flat 4s": {
            "schedule": {
                "Mon": DaySchedule(first_go=4, second_go=0),
                "Tue": DaySchedule(first_go=4, second_go=2),
                "Wed": DaySchedule(first_go=4, second_go=2),
                "Thu": DaySchedule(first_go=4, second_go=2),
                "Fri": DaySchedule(first_go=4, second_go=0),
            },
            "total_required_sorties": 24,
        },
        "Pattern B - 5/day Waterfall": {
            "schedule": {
                "Mon": DaySchedule(first_go=5, second_go=2),
                "Tue": DaySchedule(first_go=4, second_go=2),
                "Wed": DaySchedule(first_go=3, second_go=2),
                "Thu": DaySchedule(first_go=3, second_go=2),
                "Fri": DaySchedule(first_go=3, second_go=0),
            },
            "total_required_sorties": 24,
        },
        "Pattern C - 5/day Two-Hump Waterfall": {
            "schedule": {
                "Mon": DaySchedule(first_go=5, second_go=2),
                "Tue": DaySchedule(first_go=3, second_go=2),
                "Wed": DaySchedule(first_go=4, second_go=2),
                "Thu": DaySchedule(first_go=3, second_go=2),
                "Fri": DaySchedule(first_go=3, second_go=0),
            },
            "total_required_sorties": 24,
        },
    }


def build_model_scenarios(
    turn_pattern_inputs: dict[str, dict[str, object]],
    use_uncommitted_aircraft_for_ga_recovery: bool,
) -> dict[str, Scenario]:
    return {
        name: build_scenario(
            schedule=inputs["schedule"],
            total_required_sorties=inputs["total_required_sorties"],
            use_uncommitted_aircraft_for_ga_recovery=use_uncommitted_aircraft_for_ga_recovery,
        )
        for name, inputs in turn_pattern_inputs.items()
    }


def main() -> None:
    turn_pattern_inputs = get_turn_pattern_inputs()

    strict_turn_patterns = build_model_scenarios(
        turn_pattern_inputs,
        use_uncommitted_aircraft_for_ga_recovery=False,
    )
    non_strict_turn_patterns = build_model_scenarios(
        turn_pattern_inputs,
        use_uncommitted_aircraft_for_ga_recovery=True,
    )

    strict_summaries = compare_turn_patterns(strict_turn_patterns, iterations=10_000, seed=7)
    non_strict_summaries = compare_turn_patterns(
        non_strict_turn_patterns, iterations=10_000, seed=7
    )

    print_comparison_table(
        f"{SCHEDULED_SPARES_MODEL}: only scheduled spares cover ground aborts",
        strict_summaries,
    )
    print_comparison_table(
        f"{FLEET_FLEX_MODEL}: uncommitted MC aircraft can cover ground aborts",
        non_strict_summaries,
    )
    print()

    for model_name, summaries in (
        (SCHEDULED_SPARES_MODEL, strict_summaries),
        (FLEET_FLEX_MODEL, non_strict_summaries),
    ):
        for name, summary in summaries.items():
            print_summary(f"{model_name} - {name}", summary)


if __name__ == "__main__":
    main()
