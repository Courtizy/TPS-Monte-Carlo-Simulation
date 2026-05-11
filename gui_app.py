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
    FLEET_FLEX_MODEL,
    MODEL_VERSION,
    SCHEDULED_SPARES_MODEL,
    TtpPolicy,
    commit_aircraft,
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
) -> dict[str, object]:
    policy = replace(
        DEFAULT_TTP_POLICY,
        max_daily_sorties=max_daily_sorties,
        max_second_go=max_second_go,
        max_day_to_day_delta=max_day_delta,
    )
    constraints = PatternConstraints.from_policy(policy)
    rng = Random(random_seed)
    rows: list[dict[str, object]] = []
    capacity_rows = [
        point
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
) -> dict[str, object]:
    policy = replace(DEFAULT_TTP_POLICY, max_daily_sorties=max_daily_sorties, max_second_go=max_second_go)
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
            afi_spare_rate=policy.spare_rate,
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
    fields = [
        "pai",
        "capacity_label",
        "weekly_sorties",
        "required_sorties",
        "model",
        "pattern_with_frontlines",
        "pattern_name",
        "success",
        "sortie_success",
        "avg_next_monday",
        "recovery_debt",
        "risk_band",
    ]
    return [{field: row.get(field) for field in fields} for row in rows]


def _dsute_calculation(
    *,
    om_days: int,
    offutt_possessed_aircraft: int,
    offutt_sorties: int,
    include_ol_sorties: bool = False,
    ol_sorties: int = 0,
) -> dict[str, float | int | bool]:
    included_ol_sorties = ol_sorties if include_ol_sorties else 0
    modeled_sorties = offutt_sorties + included_ol_sorties
    possessed_aircraft_days = offutt_possessed_aircraft * om_days
    dsute = modeled_sorties / possessed_aircraft_days if possessed_aircraft_days > 0 else 0
    return {
        "om_days": om_days,
         "offutt_possessed_aircraft": offutt_possessed_aircraft,
        "offutt_sorties": offutt_sorties,
        "include_ol_sorties": include_ol_sorties,
        "ol_sorties_included": included_ol_sorties,ies,
        "modeled_sorties": modeled_sorties,
        "possessed_aircraft_days": possessed_aircraft_days,
        "dsute": dsute,
        "sorties_per_day": modeled_sorties / om_days if om_days > 0 else 0,
        "sorties_per_aircraft": modeled_sorties / offutt_possessed_aircraft if offutt_possessed_aircraft > 0 else 0,
        "within_planning_band": DEFAULT_TTP_POLICY.ute_min <= dsute <= DEFAULT_TTP_POLICY.ute_max,
        "below_planning_band": dsute < DEFAULT_TTP_POLICY.ute_min,
        "above_planning_band": dsute > DEFAULT_TTP_POLICY.ute_max,
    }


st.title("Turn Pattern Sustainability Modeler")
st.caption("Monte Carlo turn-pattern planning dashboard")

with st.sidebar:
    st.header("Scenario")
    st.caption(f"Version: {MODEL_VERSION}")
    page = st.radio(
        "Page",
        ["Optimization Dashboard", "Manual Turn Pattern", "Deployed UTE Calculator"],
    )
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
    max_patterns = st.number_input("Max Patterns Per UTE Point", min_value=1, value=60, step=10)
    max_daily_sorties = st.slider("Max Daily Sorties", 1, 12, 8)
    max_second_go = st.slider("Max Second-Go Sorties", 0, 6, 3)
    max_day_delta = st.slider("Max Day-to-Day Delta", 0, 8, 2)

if page == "Deployed UTE Calculator":
    st.header("DSUTE Calculator")
    st.caption("DSUTE is calculated on the sortie side only: Deployed Sorties / (Deployed Possessed aircraft x O&M days)."
    col1, col2, col3 = st.columns(3)
    om_days = int(col1.number_input("O&M Days", min_value=1, value=7, step=1))
    offutt_aircraft = int(col2.number_input("Offutt Possessed Aircraft", min_value=1, value=11, step=1))
    offutt_sorties = int(col3.number_input("Offutt Sorties", min_value=0, value=31, step=1))
    include_ol_sorties = st.checkbox("Include downrange / OL sorties in Offutt requirement", value=False)
    ol_sorties = 0
    if include_ol_sorties:
        ol_sorties = int(st.number_input("Downrange / OL Sorties to Include", min_value=0, value=0, step=1))
    deployed = _dsute_calculation(
        om_days=om_days,
       offutt_possessed_aircraft=offutt_aircraft,
        offutt_sorties=offutt_sorties,
        include_ol_sorties=include_ol_sorties,
        ol_sorties=ol_sorties,
    )
    metric_cols = st.columns(4)
    metric_cols[0].metric("DSUTE", f"{float(deployed['dsute']):.2f}")
    metric_cols[1].metric("Possessed Aircraft Days", int(deployed["possessed_aircraft_days"]))
    metric_cols[2].metric("Sorties / O&M Day", f"{float(deployed['sorties_per_day']):.1f}")
    metric_cols[3].metric("Planning Band", "Inside" if deployed["within_planning_band"] else "Outside")
    if deployed["above_planning_band"]:
        st.warning("This DSUTE is above the 0.40-0.52 homestation planning band.")
    elif deployed["below_planning_band"]:
        st.info("This DSUTE is below the 0.40-0.52 homestation planning band.")
    else:
        st.success("This DSUTE is inside the 0.40-0.52 homestation planning band.")
    st.write(
        f"Interpretation: {float(deployed['dsute']):.2f} DSUTE means deployed is generating "
        f"about {float(deployed['dsute']):.2f} sorties per possessed aircraft per O&M day."
    )
    st.dataframe([deployed], width="stretch")
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
        result = run_manual_pattern(
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
        )
        if result["warnings"]:
            st.warning(result["warnings"])
        st.subheader("Results")
        st.dataframe(_summary_rows(result["summaries"]), width="stretch")
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
st.caption("UTE search always uses every target from 0.40 through 0.52, plus the separate max-commit surge case.")

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
    )

result = st.session_state.get("best_fit_result")
if not result:
    st.info("Set inputs in the sidebar and run the model.")
    st.stop()
    raise SystemExit

summary, capacity, patterns, detail = st.tabs(["Summary", "Capacity Sweep", "Best Patterns", "Pattern Detail"])
rows = result["rows"]

with summary:
    if not rows:
        st.warning("No valid patterns were generated for these inputs.")
    else:
        best = max(rows, key=_rank)
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Best Pattern", best["pattern_with_frontlines"])
        col2.metric("Success", f"{float(best['success']):.1%}")
        col3.metric("Next Mon MC", f"{float(best['avg_next_monday']):.1f}")
        col4.metric("Risk", best["risk_band"])
        st.write(f"Primary failure mode: {best['failure_mode']}")

with capacity:
    st.dataframe(result["capacity_rows"], width="stretch")

with patterns:
    st.dataframe(_display_rows(rows), width="stretch")

with detail:
    if rows:
        options = {
            f"{row['pai']} PAI | {row['capacity_label']} | {row['model']} | {row['pattern_with_frontlines']} | {float(row['success']):.0%}": row
            for row in rows
        }
        selected = options[st.selectbox("Selected Pattern", list(options))]
        st.write(selected)
