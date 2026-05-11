from __future__ import annotations

from dataclasses import replace
from random import Random

import streamlit as st

from pattern_generator import (
    PatternConstraints,
    capacity_points,
    deployed_ute_calculation,
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


def _pattern_detail(schedule: dict[str, DaySchedule], policy: TtpPolicy) -> list[dict[str, object]]:
    rows = []
    for label, values in (
        ("1st Go", [schedule[day].first_go for day in policy.flying_days]),
        ("2nd Go", [schedule[day].second_go for day in policy.flying_days]),
        ("Aircraft Required", [schedule[day].aircraft_required(policy=policy) for day in policy.flying_days]),
        ("Daily Sorties", [schedule[day].daily_sorties for day in policy.flying_days]),
    ):
        row = {"Metric": label}
        row.update({day: values[index] for index, day in enumerate(policy.flying_days)})
        rows.append(row)
    return rows


def _summary_rows(summaries: dict[str, SimulationSummary]) -> list[dict[str, object]]:
    return [
        {
            "model": name,
            "success": summary.probability_success,
            "sortie_success": summary.probability_meet_sorties,
            "aircraft_success": summary.probability_meet_aircraft_required,
            "commit_success": summary.probability_within_ttp_commit,
            "recovery_success": summary.probability_recovery,
            "avg_next_monday": summary.average_next_monday_available,
            "avg_backlog": summary.average_repair_backlog,
            "failure_modes": summary.failure_mode_counts,
        }
        for name, summary in summaries.items()
    ]


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
    st.header("Deployed UTE Calculator")
    col1, col2, col3, col4 = st.columns(4)
    om_days = int(col1.number_input("Monthly O&M Days", min_value=1, value=20, step=1))
    deployment_days = int(col2.number_input("Monthly Deployment Days", min_value=1, value=30, step=1))
    deployed_aircraft = int(col3.number_input("Aircraft", min_value=1, value=11, step=1))
    expected_sorties = int(col4.number_input("Expected Monthly Sorties", min_value=0, value=120, step=1))
    deployed = deployed_ute_calculation(
        om_days=om_days,
        deployment_days=deployment_days,
        aircraft=deployed_aircraft,
        expected_sorties=expected_sorties,
    )
    metric_cols = st.columns(4)
    metric_cols[0].metric("Deployed UTE", f"{float(deployed['deployed_ute']):.2f}")
    metric_cols[1].metric("Homestation Monthly Equivalent", int(deployed["equivalent_homestation_monthly_sorties"]))
    metric_cols[2].metric("Homestation Weekly Equivalent", f"{float(deployed['equivalent_homestation_weekly_sorties']):.1f}")
    metric_cols[3].metric("Planning Band", "Inside" if deployed["within_planning_band"] else "Outside")
    st.dataframe([deployed], use_container_width=True)
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
        st.subheader("Pattern")
        st.dataframe(_pattern_detail(result["schedule"], result["policy"]), use_container_width=True, hide_index=True)
        st.subheader("Results")
        st.dataframe(_summary_rows(result["summaries"]), use_container_width=True)
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
    st.dataframe(result["capacity_rows"], use_container_width=True)

with patterns:
    st.dataframe(_display_rows(rows), use_container_width=True)

with detail:
    if rows:
        options = {
            f"{row['pai']} PAI | {row['capacity_label']} | {row['model']} | {row['pattern_with_frontlines']} | {float(row['success']):.0%}": row
            for row in rows
        }
        selected = options[st.selectbox("Selected Pattern", list(options))]
        st.write(selected)
