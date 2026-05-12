from __future__ import annotations

from dataclasses import replace
from random import Random

import streamlit as st

from pattern_generator import (
    PatternConstraints,
    capacity_points,
    generate_turn_pattern_permutations,
)
from ttp_rules import (
    DEFAULT_TTP_POLICY,
    MODEL_VERSION,
    TtpPolicy,
    recovery_model_options,
    risk_band,
    validate_scenario,
)
from simulation import AircraftInventory, DaySchedule, HomestationData, Scenario, SimulationSummary, simulate


st.set_page_config(page_title="Turn Pattern Sustainability Modeler", layout="wide")


@st.cache_data(show_spinner=False)
def run_best_fit(
    *,
    pai_min: int,
    pai_max: int,
    required_sorties: int | None,
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
    max_day_delta: int,
    include_surge: bool,
    ute_min: float,
    ute_max: float,
) -> dict[str, object]:
    policy = replace(
        DEFAULT_TTP_POLICY,
        max_daily_sorties=max_daily_sorties,
        max_second_go=max_second_go,
        max_day_to_day_delta=max_day_delta,
        ute_min=ute_min,
        ute_max=ute_max,
    )
    constraints = PatternConstraints.from_policy(policy)
    rng = Random(random_seed)
    rows: list[dict[str, object]] = []
    capacity_rows = [
        {"pai": pai, **point}
        for pai in range(pai_min, pai_max + 1)
        for point in capacity_points(pai, policy=policy)
    ]

    for pai in range(pai_min, pai_max + 1):
        template = _scenario(
            pai=pai,
            schedule={},
            required_sorties=1,
            use_uncommitted_aircraft_for_ga_recovery=True,
            policy=policy,
            mc_rate=mc_rate,
            ground_abort_rate=ground_abort_rate,
            break_rate=break_rate,
            fix_8hr_rate=fix_8hr_rate,
            fix_12hr_rate=fix_12hr_rate,
            fix_24hr_rate=fix_24hr_rate,
            event_count_model=event_count_model,
            fix_count_model=fix_count_model,
        )
        for point in capacity_points(pai, policy=policy):
            if point["label"] == policy.surge_label and not include_surge:
                continue
            patterns = generate_turn_pattern_permutations(
                int(point["weekly_sorties"]),
                pai,
                template,
                constraints,
                max_results=max_patterns,
            )
            for model_name, use_uncommitted in recovery_model_options():
                best_row = None
                for index, pattern in enumerate(patterns):
                    weekly_sorties = int(point["weekly_sorties"])
                    target = required_sorties if required_sorties and required_sorties > 0 else weekly_sorties
                    scenario = _scenario(
                        pai=pai,
                        schedule=pattern["schedule"],
                        required_sorties=target,
                        use_uncommitted_aircraft_for_ga_recovery=use_uncommitted,
                        policy=policy,
                        mc_rate=mc_rate,
                        ground_abort_rate=ground_abort_rate,
                        break_rate=break_rate,
                        fix_8hr_rate=fix_8hr_rate,
                        fix_12hr_rate=fix_12hr_rate,
                        fix_24hr_rate=fix_24hr_rate,
                        event_count_model=event_count_model,
                        fix_count_model=fix_count_model,
                    )
                    summary = simulate(scenario, iterations=iterations, seed=rng.randrange(1_000_000_000))
                    row = _result_row(
                        pai=pai,
                        point=point,
                        pattern=pattern,
                        model_name=model_name,
                        summary=summary,
                        policy=policy,
                        pattern_index=index,
                    )
                    if best_row is None or _rank(row) > _rank(best_row):
                        best_row = row
                if best_row is not None:
                    rows.append(best_row)

    return {
        "policy": policy,
        "capacity_rows": capacity_rows,
        "rows": sorted(rows, key=lambda row: (row["pai"], row["weekly_sorties"], row["model"])),
    }


@st.cache_data(show_spinner=False)
def run_manual_pattern(
    *,
    pai: int,
    required_sorties: int,
    first_go: tuple[int, ...],
    second_go: tuple[int, ...],
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
    max_daily_sorties: int,
    max_second_go: int,
    ute_min: float,
    ute_max: float,
) -> dict[str, object]:
    policy = replace(
        DEFAULT_TTP_POLICY,
        max_daily_sorties=max_daily_sorties,
        max_second_go=max_second_go,
        ute_min=ute_min,
        ute_max=ute_max,
    )
    schedule = {
        day: DaySchedule(first_go=first_go[index], second_go=second_go[index])
        for index, day in enumerate(policy.flying_days)
    }
    summaries = {}
    warnings = []
    for model_name, use_uncommitted in recovery_model_options():
        scenario = _scenario(
            pai=pai,
            schedule=schedule,
            required_sorties=required_sorties,
            use_uncommitted_aircraft_for_ga_recovery=use_uncommitted,
            policy=policy,
            mc_rate=mc_rate,
            ground_abort_rate=ground_abort_rate,
            break_rate=break_rate,
            fix_8hr_rate=fix_8hr_rate,
            fix_12hr_rate=fix_12hr_rate,
            fix_24hr_rate=fix_24hr_rate,
            event_count_model=event_count_model,
            fix_count_model=fix_count_model,
        )
        validation = validate_scenario(scenario)
        warnings.extend(validation.warnings)
        summaries[model_name] = simulate(scenario, iterations=iterations, seed=random_seed + len(summaries))
    return {
        "policy": policy,
        "schedule": schedule,
        "summaries": summaries,
        "warnings": tuple(sorted(set(warnings))),
    }


def _scenario(
    *,
    pai: int,
    schedule: dict[str, DaySchedule],
    required_sorties: int,
    use_uncommitted_aircraft_for_ga_recovery: bool,
    policy: TtpPolicy,
    mc_rate: float,
    ground_abort_rate: float,
    break_rate: float,
    fix_8hr_rate: float,
    fix_12hr_rate: float,
    fix_24hr_rate: float,
    event_count_model: str,
    fix_count_model: str,
) -> Scenario:
    return Scenario(
        inventory=AircraftInventory(paa=pai, pai=pai),
        homestation=HomestationData(
            mc_rate=mc_rate,
            ground_abort_rate=ground_abort_rate,
            break_rate=break_rate,
            fix_8hr_rate=fix_8hr_rate,
            fix_12hr_rate=fix_12hr_rate,
            fix_24hr_rate=fix_24hr_rate,
            ttp_commit_rate=policy.commit_rate,
            spare_rate=policy.spare_rate,
            use_uncommitted_aircraft_for_ga_recovery=use_uncommitted_aircraft_for_ga_recovery,
            event_count_model=event_count_model,
            fix_count_model=fix_count_model,
        ),
        schedule=schedule,
        total_required_sorties=required_sorties,
        policy=policy,
    )


def _result_row(
    *,
    pai: int,
    point: dict[str, object],
    pattern: dict[str, object],
    model_name: str,
    summary: SimulationSummary,
    policy: TtpPolicy,
    pattern_index: int,
) -> dict[str, object]:
    schedule = pattern["schedule"]
    classification = pattern["classification"]
    first_go = [schedule[day].first_go for day in policy.flying_days]
    turns = [schedule[day].second_go for day in policy.flying_days]
    pattern_with_frontlines = "-".join(
        f"{total}({front})" for total, front in zip(classification["daily_sequence"], first_go)
    )
    starting_mc = summary.sample_iteration.days[0].total_mc_aircraft
    recovery_debt = max(0.0, starting_mc - summary.average_next_monday_available)
    return {
        "pai": pai,
        "capacity_label": point["label"],
        "weekly_sorties": point["weekly_sorties"],
        "ute": point["actual_ute"],
        "avg_sorties_per_aircraft": int(point["weekly_sorties"]) / pai if pai else 0,
        "commit_aircraft": point["commit_aircraft"],
        "model": model_name,
        "pattern_index": pattern_index,
        "pattern_name": classification["pattern_name"],
        "pattern_family": classification["pattern_family"],
        "pattern_with_frontlines": pattern_with_frontlines,
        "daily_sequence": classification["daily_sequence"],
        "first_go_sequence": first_go,
        "turn_sequence": turns,
        "required_sorties": summary.required_weekly_sorties,
        "success": summary.probability_success,
        "sortie_success": summary.probability_meet_sorties,
        "aircraft_success": summary.probability_meet_aircraft_required,
        "commit_success": summary.probability_within_ttp_commit,
        "recovery_success": summary.probability_recovery,
        "backlog_success": summary.probability_backlog,
        "success_std_dev": summary.success_std_dev,
        "success_min": summary.success_min,
        "success_max": summary.success_max,
        "avg_next_monday": summary.average_next_monday_available,
        "recovery_debt": recovery_debt,
        "failure_mode": _top_count(summary.failure_mode_counts),
        "risk_band": risk_band(summary.probability_success, policy),
        "score": _score(summary, classification, recovery_debt),
    }


def _score(summary: SimulationSummary, classification: dict[str, object], recovery_debt: float) -> float:
    return (
        summary.probability_success * 0.45
        + summary.probability_meet_sorties * 0.18
        + summary.probability_meet_aircraft_required * 0.12
        + summary.probability_within_ttp_commit * 0.12
        + summary.probability_recovery * 0.08
        + float(classification["smoothness_score"]) * 0.05
        - recovery_debt * 0.02
        - float(classification["backend_penalty"]) * 0.08
        - float(classification["friday_penalty"]) * 0.06
    )


def _rank(row: dict[str, object]) -> tuple[float, float, float, float]:
    return (
        float(row["score"]),
        float(row["success"]),
        float(row["avg_next_monday"]),
        -float(row["recovery_debt"]),
    )


def _top_count(counts: dict[str, int]) -> str:
    if not counts:
        return "None"
    key, value = max(counts.items(), key=lambda item: item[1])
    return f"{key} ({value})"


def _excel_iteration_table(summary: SimulationSummary) -> list[dict[str, object]]:
    days = summary.sample_iteration.days
    row_specs = (
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
    rows = []
    for label, attr in row_specs:
        row = {"Metric": label}
        row.update({day.day: str(getattr(day, attr)) for day in days})
        rows.append(row)
    for label, attr in (
        ("Meets Acft Req", "meets_aircraft_required"),
        ("Within TTP Commit", "within_ttp_commit"),
    ):
        row = {"Metric": label}
        row.update({day.day: "Yes" if getattr(day, attr) else "No" for day in days})
        rows.append(row)
    return rows


def _summary_rows(summaries: dict[str, SimulationSummary]) -> list[dict[str, object]]:
    return [
        {
            "Model": name,
            "Iterations": f"{summary.iterations:,}",
            "Overall Success": _pct(summary.probability_success),
            "Sortie Target Met": _pct(summary.probability_meet_sorties),
            "Daily Schedule Met": _pct(summary.probability_daily_schedule),
            "Aircraft Available": _pct(summary.probability_meet_aircraft_required),
            "Within Commit": _pct(summary.probability_within_ttp_commit),
            "Next-Monday Recovery": _pct(summary.probability_recovery),
            "Avg Next-Monday MC": f"{summary.average_next_monday_available:.1f}",
            "Avg Backlog": f"{summary.average_repair_backlog:.1f}",
            "Primary Failure": _primary_failure(summary),
        }
        for name, summary in summaries.items()
    ]


def _manual_interpretation_rows(summaries: dict[str, SimulationSummary]) -> list[dict[str, object]]:
    return [
        {
            "Model": name,
            "Assessment": _manual_assessment(summary),
            "Interpretation": _manual_interpretation(name, summary),
            "Failure Detail": _failure_detail(summary),
        }
        for name, summary in summaries.items()
    ]


def _pct(value: float) -> str:
    return f"{value:.1%}"


def _primary_failure(summary: SimulationSummary) -> str:
    if not summary.failure_mode_counts:
        return "None"
    failure, count = max(summary.failure_mode_counts.items(), key=lambda item: item[1])
    return f"{failure} in {count:,} of {summary.iterations:,} iterations"


def _failure_detail(summary: SimulationSummary) -> str:
    if not summary.failure_mode_counts:
        return "No modeled failures across the run."
    return "; ".join(
        f"{failure}: {count:,}/{summary.iterations:,} ({count / summary.iterations:.1%})"
        for failure, count in sorted(summary.failure_mode_counts.items())
    )


def _manual_assessment(summary: SimulationSummary) -> str:
    if summary.probability_success >= 0.85:
        return "Sustainable"
    if summary.probability_meet_sorties >= 0.85 and summary.probability_recovery >= 0.70:
        return "Executable with risk"
    if summary.probability_meet_sorties >= 0.85:
        return "Sorties feasible, not operationally sustainable"
    return "Not recommended"


def _manual_interpretation(model_name: str, summary: SimulationSummary) -> str:
    if summary.probability_success >= 0.85:
        return (
            f"{model_name} made the full operational success standard in "
            f"{summary.probability_success:.1%} of {summary.iterations:,} iterations."
        )
    if summary.probability_meet_sorties >= 0.85 and summary.probability_success < 0.85:
        return (
            "The sortie target is usually met, but another dimension is failing. "
            "Review daily schedule, aircraft availability, commit compliance, and recovery."
        )
    return (
        "The pattern does not reliably meet the modeled requirement under this recovery assumption. "
        "The failure detail column shows the dominant reason."
    )


def _display_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "PAI": row["pai"],
            "Capacity Point": row["capacity_label"],
            "Planned Sorties": row["weekly_sorties"],
            "Required Sorties": row["required_sorties"],
            "UTE": f"{float(row['ute']):.2f}",
            "Avg Sorties / Aircraft": f"{float(row['avg_sorties_per_aircraft']):.1f}",
            "Recovery Model": row["model"],
            "Pattern Total(Frontline)": row["pattern_with_frontlines"],
            "Pattern Family": row["pattern_name"],
            "Overall Success": _pct(float(row["success"])),
            "Sortie Target Met": _pct(float(row["sortie_success"])),
            "Avg Next-Monday MC": f"{float(row['avg_next_monday']):.1f}",
            "Recovery Debt": f"{float(row['recovery_debt']):.1f}",
            "Risk": row["risk_band"],
        }
        for row in rows
    ]


def _is_recommendable(row: dict[str, object], policy: TtpPolicy = DEFAULT_TTP_POLICY) -> bool:
    return (
        int(row["weekly_sorties"]) >= int(row["required_sorties"])
        and float(row["success"]) >= policy.yellow_success_threshold
        and float(row["recovery_success"]) >= policy.yellow_success_threshold
        and float(row["backlog_success"]) >= policy.yellow_success_threshold
    )


def _recommendable_rows(
    rows: list[dict[str, object]],
    policy: TtpPolicy = DEFAULT_TTP_POLICY,
) -> list[dict[str, object]]:
    return [row for row in rows if _is_recommendable(row, policy)]


def _pai_values(rows: list[dict[str, object]]) -> list[int]:
    return sorted({int(row["pai"]) for row in rows})


def _rows_for_pai(rows: list[dict[str, object]], pai: int) -> list[dict[str, object]]:
    return [row for row in rows if int(row["pai"]) == pai]


def _top_pattern_rows(rows: list[dict[str, object]], limit: int = 5) -> list[dict[str, object]]:
    return sorted(rows, key=_rank, reverse=True)[:limit]


def _best_by_ute_rows(
    rows: list[dict[str, object]],
    policy: TtpPolicy,
) -> list[dict[str, object]]:
    output = []
    for pai in _pai_values(rows):
        pai_rows = _recommendable_rows(_rows_for_pai(rows, pai), policy)
        capacity_labels = sorted(
            {str(row["capacity_label"]) for row in pai_rows},
            key=lambda label: (
                "Surge" in label,
                float(label.split()[-1]) if label.startswith("UTE ") else 99.0,
            ),
        )
        for label in capacity_labels:
            matching = [row for row in pai_rows if row["capacity_label"] == label]
            if matching:
                output.append(max(matching, key=_rank))
    return output


def _operating_envelope_rows(rows: list[dict[str, object]], policy: TtpPolicy) -> list[dict[str, str]]:
    output = []
    for pai in _pai_values(rows):
        pai_rows = _rows_for_pai(rows, pai)
        viable = _recommendable_rows(pai_rows, policy)
        if viable:
            min_ute = min(float(row["ute"]) for row in viable)
            max_ute = max(float(row["ute"]) for row in viable)
            max_sorties = max(int(row["weekly_sorties"]) for row in viable)
            best = max(viable, key=_rank)
            status = str(best["risk_band"])
        else:
            min_ute = max_ute = None
            max_sorties = 0
            best = max(pai_rows, key=_rank) if pai_rows else None
            status = f"No sustainable pattern; best failed risk {best['risk_band']}" if best else "No valid patterns"
        output.append(
            {
                "PAI": str(pai),
                "Sustainable UTE Min": f"{min_ute:.2f}" if min_ute is not None else "None",
                "Sustainable UTE Max": f"{max_ute:.2f}" if max_ute is not None else "None",
                "Max Sustainable Sorties": str(max_sorties) if max_sorties else "None",
                "Status": status,
            }
        )
    return output


def _failure_readout_rows(rows: list[dict[str, object]]) -> list[dict[str, str]]:
    counts: dict[str, int] = {}
    for row in rows:
        if _is_recommendable(row):
            continue
        failure = str(row["failure_mode"])
        counts[failure] = counts.get(failure, 0) + 1
    if not counts:
        return [{"Failure Mode": "None", "Patterns": "0", "Share": "0.0%"}]
    total = sum(counts.values())
    return [
        {
            "Failure Mode": failure,
            "Patterns": str(count),
            "Share": _pct(count / total),
        }
        for failure, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)
    ]


def _recovery_delta_rows(summaries: dict[str, SimulationSummary]) -> list[dict[str, str]]:
    rows = []
    names = list(summaries)
    baseline = summaries[names[0]] if names else None
    for name, summary in summaries.items():
        delta = "Baseline"
        if baseline is not None and summary is not baseline:
            delta = f"{summary.probability_success - baseline.probability_success:+.1%}"
        rows.append(
            {
                "Recovery Model": name,
                "Overall Success": _pct(summary.probability_success),
                "Delta vs Strict": delta,
                "Sortie Target Met": _pct(summary.probability_meet_sorties),
                "Aircraft Available": _pct(summary.probability_meet_aircraft_required),
                "Next-Monday Recovery": _pct(summary.probability_recovery),
                "Avg Next-Monday MC": f"{summary.average_next_monday_available:.1f}",
                "Avg Backlog": f"{summary.average_repair_backlog:.1f}",
                "Primary Failure": _primary_failure(summary),
            }
        )
    return rows


def _decision_guidance(pai: int, rows: list[dict[str, object]], policy: TtpPolicy) -> str:
    viable = _recommendable_rows(rows, policy)
    if viable:
        best = max(viable, key=_rank)
        return (
            f"{pai} PAI has recommendable patterns under the current assumptions. "
            f"The strongest option plans {best['weekly_sorties']} sorties at {float(best['ute']):.2f} UTE "
            f"with {best['pattern_with_frontlines']} and {best['risk_band']} risk."
        )
    if not rows:
        return f"{pai} PAI did not generate valid patterns under the current constraints."
    best_failed = max(rows, key=_rank)
    return (
        f"{pai} PAI has no sustainable pattern under the current assumptions. "
        f"The best failed candidate is {best_failed['pattern_with_frontlines']} at "
        f"{best_failed['capacity_label']}, failing primarily from {best_failed['failure_mode']}."
    )


def _capacity_display_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "PAI": row.get("pai", ""),
            "Capacity Point": row["label"],
            "Target UTE": f"{float(row['target_ute']):.2f}",
            "Weekly Sorties": row["weekly_sorties"],
            "Actual UTE": f"{float(row['actual_ute']):.2f}",
            "Avg Sorties / Aircraft": f"{int(row['weekly_sorties']) / int(row['pai']):.1f}" if row.get("pai") else "",
            "Commit Aircraft": row["commit_aircraft"],
        }
        for row in rows
    ]


def _detail_rows(row: dict[str, object]) -> list[dict[str, str]]:
    return [
        {"Metric": "PAI", "Value": str(row["pai"])},
        {"Metric": "Capacity Point", "Value": str(row["capacity_label"])},
        {"Metric": "Planned Sorties", "Value": str(row["weekly_sorties"])},
        {"Metric": "Required Sorties", "Value": str(row["required_sorties"])},
        {"Metric": "UTE", "Value": f"{float(row['ute']):.2f}"},
        {"Metric": "Avg Sorties / Aircraft", "Value": f"{float(row['avg_sorties_per_aircraft']):.1f}"},
        {"Metric": "Commit Aircraft", "Value": str(row["commit_aircraft"])},
        {"Metric": "Recovery Model", "Value": str(row["model"])},
        {"Metric": "Pattern Total(Frontline)", "Value": str(row["pattern_with_frontlines"])},
        {"Metric": "1st Go Sequence", "Value": "-".join(str(value) for value in row["first_go_sequence"])},
        {"Metric": "2nd Go Sequence", "Value": "-".join(str(value) for value in row["turn_sequence"])},
        {"Metric": "Pattern Family", "Value": str(row["pattern_name"])},
        {"Metric": "Overall Success", "Value": _pct(float(row["success"]))},
        {"Metric": "Sortie Target Met", "Value": _pct(float(row["sortie_success"]))},
        {"Metric": "Aircraft Available", "Value": _pct(float(row["aircraft_success"]))},
        {"Metric": "Commit Compliance", "Value": _pct(float(row["commit_success"]))},
        {"Metric": "Next-Monday Recovery", "Value": _pct(float(row["recovery_success"]))},
        {"Metric": "Backlog Success", "Value": _pct(float(row["backlog_success"]))},
        {"Metric": "Avg Next-Monday MC", "Value": f"{float(row['avg_next_monday']):.1f}"},
        {"Metric": "Recovery Debt", "Value": f"{float(row['recovery_debt']):.1f}"},
        {"Metric": "Primary Failure", "Value": str(row["failure_mode"])},
        {"Metric": "Risk", "Value": str(row["risk_band"])},
    ]


def _dsute_calculation(
    *,
    om_days: int,
    possessed_aircraft: int,
    base_sorties: int,
    ute_min: float,
    ute_max: float,
    include_operating_location_sorties: bool = False,
    operating_location_sorties: int = 0,
) -> dict[str, float | int | bool]:
    included_operating_location_sorties = (
        operating_location_sorties if include_operating_location_sorties else 0
    )
    modeled_sorties = base_sorties + included_operating_location_sorties
    possessed_aircraft_days = possessed_aircraft * om_days
    dsute = modeled_sorties / possessed_aircraft_days if possessed_aircraft_days > 0 else 0
    return {
        "om_days": om_days,
        "possessed_aircraft": possessed_aircraft,
        "base_sorties": base_sorties,
        "include_operating_location_sorties": include_operating_location_sorties,
        "operating_location_sorties_included": included_operating_location_sorties,
        "modeled_sorties": modeled_sorties,
        "possessed_aircraft_days": possessed_aircraft_days,
        "dsute": dsute,
        "sorties_per_day": modeled_sorties / om_days if om_days > 0 else 0,
        "sorties_per_aircraft": modeled_sorties / possessed_aircraft if possessed_aircraft > 0 else 0,
        "within_planning_band": ute_min <= dsute <= ute_max,
        "below_planning_band": dsute < ute_min,
        "above_planning_band": dsute > ute_max,
    }


def _show_about_page() -> None:
    st.header("About / Model Logic")
    st.caption("A plain-language guide to what the model is doing and how to read it.")

    st.subheader("Purpose")
    st.write(
        "This app tests whether a weekly turn pattern is likely to meet a required sortie target "
        "while staying within commit limits, aircraft availability, recovery, and repair-backlog constraints."
    )

    st.subheader("How The Model Flows")
    flow_steps = [
        ("1. User Inputs", "PAI, sortie requirement, maintenance rates, UTE range, and model options."),
        ("2. Policy Layer", "Applies commit rate, go limits, recovery rules, risk bands, and rounding rules."),
        ("3. Capacity Sweep", "Calculates weekly sortie capacity for each PAI and UTE point."),
        ("4. Pattern Generator", "Builds realistic first-go and second-go turn-pattern candidates."),
        ("5. Monte Carlo Engine", "Runs ground aborts, Code 3s, fixes, daily MC carry-forward, and weekend recovery."),
        ("6. Success Scoring", "Checks sorties, daily schedule, aircraft availability, commit compliance, recovery, and backlog."),
        ("7. App Outputs", "Shows recommendations, sustainable patterns, diagnostics, and recovery-model comparisons."),
    ]
    for title, body in flow_steps:
        st.markdown(f"**{title}**")
        st.write(body)

    with st.expander("Inputs And Policy Rules", expanded=True):
        st.markdown(
            """
            - **PAI**: possessed aircraft used by the scenario.
            - **UTE planning range**: sortie output band used to generate candidate weekly sortie counts.
            - **Required weekly sorties**: the sortie target the pattern must meet.
            - **Commit rate**: maximum aircraft committed to the flying schedule.
            - **Max daily sorties / second-go limit**: controls which patterns are considered realistic.
            - **Maintenance rates**: MC rate, ground-abort rate, break rate, and 8/12/24-hour fix rates.
            """
        )

    with st.expander("What Counts As Success"):
        st.markdown(
            """
            Overall success is stricter than sortie success. A run must meet the required weekly sorties,
            make the daily schedule, have enough aircraft available, stay within commit limits, recover
            by next Monday, avoid unacceptable backlog, and avoid suppressed events.

            A pattern that meets the sortie target but leaves the fleet unrecovered is treated as risky
            or unsustainable rather than a clean success.
            """
        )

    with st.expander("Recovery Models"):
        st.markdown(
            """
            - **Scheduled-Spares Only**: ground aborts can only be absorbed by scheduled spares.
            - **Fleet-Flex Recovery**: uncommitted MC aircraft can also absorb a ground abort if available.

            Comparing both models helps separate strict scheduling sustainability from practical fleet-flex
            execution.
            """
        )

    with st.expander("DSUTE Calculator"):
        st.markdown(
            """
            DSUTE is calculated on the sortie side only:

            `DSUTE = scheduled or required sorties / (possessed aircraft x O&M days)`

            Flying hours, average sortie duration, and deployed or operating-location hours are not used.
            Deployed or operating-location sorties are only included if intentionally toggled into the requirement.
            """
        )

    with st.expander("How To Read The Tabs"):
        st.markdown(
            """
            - **Summary**: decision brief by PAI, operating envelope, viable options, and failure readout.
            - **Capacity Sweep**: sortie math across the selected UTE range and max-commit capacity point.
            - **Best Patterns**: sustainable/recommendable candidates only, including best pattern by UTE.
            - **Diagnostics**: all tested best candidates, including failed patterns.
            - **Pattern Detail**: selected pattern details and recovery-model comparison.
            - **Manual Turn Pattern**: test a specific first-go / second-go schedule.
            """
        )

    st.subheader("Version")
    st.write(f"Current model version: {MODEL_VERSION}")


st.title("Turn Pattern Sustainability Modeler")
st.caption("Monte Carlo turn-pattern planning dashboard")

with st.sidebar:
    st.header("Scenario")
    st.caption(f"Version: {MODEL_VERSION}")
    page = st.radio(
        "Page",
        ["Optimization Dashboard", "Manual Turn Pattern", "DSUTE Calculator", "About / Model Logic"],
    )
    if page != "About / Model Logic":
        ute_min, ute_max = st.slider(
            "UTE Planning Range",
            min_value=0.00,
            max_value=0.80,
            value=(DEFAULT_TTP_POLICY.ute_min, DEFAULT_TTP_POLICY.ute_max),
            step=0.01,
        )

    if page not in ("DSUTE Calculator", "About / Model Logic"):
        pai_mode = st.radio("PAI Mode", ["Single PAI", "PAI Sweep"], horizontal=True)
        if pai_mode == "Single PAI":
            pai = st.slider("PAI", 1, 15, 11)
            pai_min = pai_max = pai
        else:
            pai_min, pai_max = st.slider("PAI Range", 1, 15, (9, 12))

        required_sorties = st.number_input("Required Weekly Sorties", min_value=0, value=24)
        iterations = st.number_input("Iterations", min_value=50, value=500, step=50)
        random_seed = st.number_input("Random Seed", min_value=0, value=42, step=1)

        st.header("Maintenance Rates")
        mc_rate = st.number_input("MC Rate", min_value=0.0, max_value=1.0, value=0.735, step=0.005)
        ground_abort_rate = st.number_input("Ground Abort Rate", min_value=0.0, max_value=1.0, value=0.064, step=0.005)
        break_rate = st.number_input("Break / Code 3 Rate", min_value=0.0, max_value=1.0, value=0.265, step=0.005)
        fix_8hr_rate = st.number_input("8-Hour Fix Rate", min_value=0.0, max_value=1.0, value=0.496, step=0.005)
        fix_12hr_rate = st.number_input("12-Hour Fix Rate", min_value=0.0, max_value=1.0, value=0.607, step=0.005)
        fix_24hr_rate = st.number_input("24-Hour Fix Rate", min_value=0.0, max_value=1.0, value=0.803, step=0.005)

        st.header("Model Options")
        event_count_model = st.selectbox("Event Count Model", ["Normal TTP", "Probabilistic Monte Carlo"])
        fix_count_model = st.selectbox("Fix Count Model", ["Normal TTP", "Probabilistic Monte Carlo"])
        max_daily_sorties = st.slider("Max Daily Sorties", 1, 12, 7)
        max_second_go = st.slider("Max Second-Go Sorties", 0, 6, 2)

        if page == "Optimization Dashboard":
            max_patterns = st.number_input("Max Patterns Per UTE Point", min_value=1, value=30, step=10)
            max_day_delta = st.slider("Max Day-to-Day Delta", 0, 8, 2)
            include_surge = st.checkbox("Include max-commit surge in optimization", value=False)
        else:
            max_patterns = 40
            max_day_delta = DEFAULT_TTP_POLICY.max_day_to_day_delta or 0
            include_surge = False

if page == "About / Model Logic":
    _show_about_page()
    st.stop()

if page == "DSUTE Calculator":
    st.header("DSUTE Calculator")
    st.caption(
        "DSUTE is calculated on the sortie side only: scheduled or required sorties / "
        "(possessed aircraft x operating and maintenance days)."
    )
    col1, col2, col3 = st.columns(3)
    om_days = int(col1.number_input("O&M Days", min_value=1, value=7, step=1))
    possessed_aircraft = int(col2.number_input("Possessed Aircraft", min_value=1, value=11, step=1))
    base_sorties = int(col3.number_input("Scheduled / Required Sorties", min_value=0, value=31, step=1))
    include_operating_location_sorties = st.checkbox(
        "Include deployed / operating-location sorties in the requirement",
        value=False,
    )
    operating_location_sorties = 0
    if include_operating_location_sorties:
        operating_location_sorties = int(
            st.number_input("Deployed / Operating-Location Sorties to Include", min_value=0, value=0, step=1)
        )
    deployed = _dsute_calculation(
        om_days=om_days,
        possessed_aircraft=possessed_aircraft,
        base_sorties=base_sorties,
        ute_min=float(ute_min),
        ute_max=float(ute_max),
        include_operating_location_sorties=include_operating_location_sorties,
        operating_location_sorties=operating_location_sorties,
    )
    metric_cols = st.columns(5)
    metric_cols[0].metric("DSUTE", f"{float(deployed['dsute']):.2f}")
    metric_cols[1].metric("Possessed Aircraft Days", int(deployed["possessed_aircraft_days"]))
    metric_cols[2].metric("Sorties / O&M Day", f"{float(deployed['sorties_per_day']):.1f}")
    metric_cols[3].metric("Avg Sorties / Aircraft", f"{float(deployed['sorties_per_aircraft']):.1f}")
    metric_cols[4].metric("Planning Band", "Inside" if deployed["within_planning_band"] else "Outside")
    if deployed["above_planning_band"]:
        st.warning(f"This DSUTE is above the {float(ute_min):.2f}-{float(ute_max):.2f} planning band.")
    elif deployed["below_planning_band"]:
        st.info(f"This DSUTE is below the {float(ute_min):.2f}-{float(ute_max):.2f} planning band.")
    else:
        st.success(f"This DSUTE is inside the {float(ute_min):.2f}-{float(ute_max):.2f} planning band.")
    st.write(
        f"Interpretation: {float(deployed['dsute']):.2f} DSUTE means this location is generating "
        f"about {float(deployed['dsute']):.2f} sorties per possessed aircraft per O&M day."
    )
    st.stop()

if page == "Manual Turn Pattern":
    st.header("Manual Turn Pattern")
    days = list(DEFAULT_TTP_POLICY.flying_days)
    default_first = [5, 4, 4, 3, 2]
    default_second = [2, 2, 2, 2, 0]
    cols = st.columns(len(days))
    first_go = []
    second_go = []
    for index, day in enumerate(days):
        with cols[index]:
            st.markdown(f"**{day}**")
            first_go.append(int(st.number_input(f"{day} 1st Go", min_value=0, max_value=15, value=default_first[index])))
            second_go.append(int(st.number_input(f"{day} 2nd Go", min_value=0, max_value=15, value=default_second[index])))
    planned = sum(first_go) + sum(second_go)
    st.metric("Manual Planned Sorties", planned)

    if st.button("Run Manual Pattern", type="primary"):
        st.session_state["manual_result"] = run_manual_pattern(
            pai=int(pai_max),
            required_sorties=int(required_sorties) if required_sorties else planned,
            first_go=tuple(first_go),
            second_go=tuple(second_go),
            iterations=int(iterations),
            random_seed=int(random_seed),
            mc_rate=float(mc_rate),
            ground_abort_rate=float(ground_abort_rate),
            break_rate=float(break_rate),
            fix_8hr_rate=float(fix_8hr_rate),
            fix_12hr_rate=float(fix_12hr_rate),
            fix_24hr_rate=float(fix_24hr_rate),
            event_count_model=event_count_model,
            fix_count_model=fix_count_model,
            max_daily_sorties=int(max_daily_sorties),
            max_second_go=int(max_second_go),
            ute_min=float(ute_min),
            ute_max=float(ute_max),
        )

    result = st.session_state.get("manual_result")
    if result:
        if result["warnings"]:
            st.warning(result["warnings"])

        st.subheader("Results")
        st.dataframe(_summary_rows(result["summaries"]), width="stretch", hide_index=True)

        st.subheader("Interpretation")
        st.dataframe(_manual_interpretation_rows(result["summaries"]), width="stretch", hide_index=True)

        st.subheader("Sample Iteration Table")
        selected_model = st.selectbox("Sample Iteration Model", list(result["summaries"]))
        st.dataframe(
            _excel_iteration_table(result["summaries"][selected_model]),
            width="stretch",
            hide_index=True,
        )
        st.caption(
            "Overall success is stricter than sortie success. A run can meet the weekly sortie target "
            "but still fail if the daily schedule is missed, aircraft are unavailable, commit limits are "
            "exceeded, next-Monday recovery fails, backlog remains open, or events are suppressed."
        )
    else:
        st.info("Enter the manual pattern and run it.")
    st.stop()

st.header("Optimization Dashboard")
st.caption(
    f"Planning optimization searches every UTE target from {float(ute_min):.2f} through {float(ute_max):.2f}. "
    "Max-commit surge is shown in the capacity table and can be included as an optional stress case."
)
if pai_max > pai_min and int(iterations) * int(max_patterns) * (pai_max - pai_min + 1) > 120_000:
    st.warning(
        "This sweep is large for Streamlit Cloud. For faster visual checks, lower iterations or max patterns; "
        "increase them for final planning runs."
    )

if st.button("Run Model", type="primary"):
    st.session_state["best_fit_result"] = run_best_fit(
        pai_min=int(pai_min),
        pai_max=int(pai_max),
        required_sorties=int(required_sorties) if required_sorties else None,
        iterations=int(iterations),
        random_seed=int(random_seed),
        mc_rate=float(mc_rate),
        ground_abort_rate=float(ground_abort_rate),
        break_rate=float(break_rate),
        fix_8hr_rate=float(fix_8hr_rate),
        fix_12hr_rate=float(fix_12hr_rate),
        fix_24hr_rate=float(fix_24hr_rate),
        event_count_model=event_count_model,
        fix_count_model=fix_count_model,
        max_patterns=int(max_patterns),
        max_daily_sorties=int(max_daily_sorties),
        max_second_go=int(max_second_go),
        max_day_delta=int(max_day_delta),
        include_surge=bool(include_surge),
        ute_min=float(ute_min),
        ute_max=float(ute_max),
    )

result = st.session_state.get("best_fit_result")
if not result:
    st.info("Set inputs in the sidebar and run the model.")
    st.stop()
    raise SystemExit

summary, capacity, patterns, diagnostics, detail = st.tabs(
    ["Summary", "Capacity Sweep", "Best Patterns", "Diagnostics", "Pattern Detail"]
)
rows = result["rows"]
policy = result["policy"]

with summary:
    if not rows:
        st.warning("No valid patterns were generated for these inputs.")
    else:
        st.subheader("Operating Envelope")
        st.dataframe(_operating_envelope_rows(rows, policy), width="stretch", hide_index=True)

        for pai_value in _pai_values(rows):
            pai_rows = _rows_for_pai(rows, pai_value)
            viable = _recommendable_rows(pai_rows, policy)
            recommended = max(viable, key=_rank) if viable else max(pai_rows, key=_rank)
            label = "Recommendation" if viable else "Best Failed Candidate"

            with st.expander(f"{pai_value} PAI Decision Brief", expanded=(pai_value == _pai_values(rows)[0])):
                col1, col2, col3, col4 = st.columns(4)
                col1.metric(label, recommended["pattern_with_frontlines"])
                col2.metric("Success", f"{float(recommended['success']):.1%}")
                col3.metric("Next Mon MC", f"{float(recommended['avg_next_monday']):.1f}")
                col4.metric("Risk", recommended["risk_band"])
                st.write(_decision_guidance(pai_value, pai_rows, policy))

                st.markdown("**Viable Options**")
                if viable:
                    st.dataframe(_display_rows(_top_pattern_rows(viable)), width="stretch", hide_index=True)
                else:
                    st.info("No Green/Yellow sustainable options met the current requirement and recovery rules.")

                st.markdown("**Failure Readout**")
                st.dataframe(_failure_readout_rows(pai_rows), width="stretch", hide_index=True)

with capacity:
    st.dataframe(_capacity_display_rows(result["capacity_rows"]), width="stretch", hide_index=True)

with patterns:
    recommendable = _recommendable_rows(rows, policy)
    if recommendable:
        st.subheader("Best Sustainable Pattern by UTE")
        best_by_ute = _best_by_ute_rows(rows, policy)
        st.dataframe(_display_rows(best_by_ute), width="stretch", hide_index=True)
        st.subheader("All Sustainable Pattern Candidates")
        st.dataframe(_display_rows(recommendable), width="stretch", hide_index=True)
    else:
        st.warning("No sustainable best patterns were found under the current assumptions.")

with diagnostics:
    st.caption("All tested best candidates, including patterns rejected from the Best Patterns tab.")
    st.dataframe(_display_rows(rows), width="stretch", hide_index=True)

with detail:
    if rows:
        options = {
            f"{row['pai']} PAI | {row['capacity_label']} | {row['model']} | {row['pattern_with_frontlines']} | {float(row['success']):.0%}": row
            for row in rows
        }
        selected = options[st.selectbox("Selected Pattern", list(options))]
        st.dataframe(_detail_rows(selected), width="stretch", hide_index=True)

        st.subheader("Recovery Model Comparison")
        st.caption("Reruns the selected pattern under both recovery assumptions using the current sidebar inputs.")
        if st.button("Compare Recovery Models for Selected Pattern"):
            comparison = run_manual_pattern(
                pai=int(selected["pai"]),
                required_sorties=int(selected["required_sorties"]),
                first_go=tuple(int(value) for value in selected["first_go_sequence"]),
                second_go=tuple(int(value) for value in selected["turn_sequence"]),
                iterations=int(iterations),
                random_seed=int(random_seed),
                mc_rate=float(mc_rate),
                ground_abort_rate=float(ground_abort_rate),
                break_rate=float(break_rate),
                fix_8hr_rate=float(fix_8hr_rate),
                fix_12hr_rate=float(fix_12hr_rate),
                fix_24hr_rate=float(fix_24hr_rate),
                event_count_model=event_count_model,
                fix_count_model=fix_count_model,
                max_daily_sorties=int(max_daily_sorties),
                max_second_go=int(max_second_go),
                ute_min=float(ute_min),
                ute_max=float(ute_max),
            )
            st.session_state["detail_recovery_comparison"] = comparison

        comparison = st.session_state.get("detail_recovery_comparison")
        if comparison:
            st.dataframe(_recovery_delta_rows(comparison["summaries"]), width="stretch", hide_index=True)
