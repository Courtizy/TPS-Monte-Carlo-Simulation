from __future__ import annotations

import streamlit as st

from gui_controller import (
    best_pattern_options,
    build_gui_config,
    display_rows,
    pattern_detail_rows,
    run_gui_model,
    surge_rows,
)
from ttp_rules import DEFAULT_TTP_POLICY


st.set_page_config(
    page_title="Turn Pattern Sustainability Modeler",
    layout="wide",
)

st.title("Turn Pattern Sustainability Modeler")
st.caption("Monte Carlo turn-pattern planning dashboard")

with st.sidebar:
    st.header("Scenario")
    pai_mode = st.radio("PAI Mode", ["Single PAI", "PAI Sweep"], horizontal=True)
    if pai_mode == "Single PAI":
        pai = st.slider("PAI", 1, 15, 11)
        pai_min = pai
        pai_max = pai
    else:
        pai_min, pai_max = st.slider("PAI Range", 1, 15, (9, 12))

    required_sorties = st.number_input(
        "Required Weekly Sorties",
        min_value=0,
        value=24,
        help="Use 0 to let optional attrition mode calculate the requirement from planned sorties.",
    )
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
    attrition_mode = st.selectbox(
        "Attrition Mode",
        ["Requirement Based", "Low Attrition", "Planning Attrition", "High Attrition"],
    )
    attrition_lookup = {
        "Requirement Based": 0.0,
        "Low Attrition": 0.10,
        "Planning Attrition": 0.15,
        "High Attrition": 0.20,
    }
    ute_levels = tuple(
        level for level in DEFAULT_TTP_POLICY.ute_levels
        if st.checkbox(f"Include {level:.2f} UTE", value=True)
    )
    max_patterns = st.number_input("Max Patterns Per Requirement", min_value=1, value=60, step=10)

    st.header("Pattern Rules")
    max_daily_sorties = st.slider("Max Daily Sorties", 1, 12, 8)
    max_second_go = st.slider("Max Second-Go Sorties", 0, 6, 3)
    max_day_delta = st.slider("Max Day-to-Day Delta", 0, 8, 2)
    include_surge = st.checkbox("Run Surge Analysis", value=True)

    run = st.button("Run Model", type="primary")

if "gui_result" not in st.session_state:
    st.session_state.gui_result = None

if run:
    with st.spinner("Running model..."):
        config = build_gui_config(
            pai_min=int(pai_min),
            pai_max=int(pai_max),
            required_weekly_sorties=int(required_sorties) if required_sorties else None,
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
            max_day_to_day_delta=int(max_day_delta),
            ute_levels=ute_levels or DEFAULT_TTP_POLICY.ute_levels,
            attrition_scenarios=((attrition_mode, attrition_lookup[attrition_mode]),),
        )
        st.session_state.gui_result = run_gui_model(config, include_surge=include_surge)

result = st.session_state.gui_result

if result is None:
    st.info("Set the inputs in the sidebar and run the model.")
    st.stop()

if result.validation_errors:
    st.error("Input errors must be fixed before running.")
    st.write(result.validation_errors)
    st.stop()

if result.validation_warnings:
    st.warning("Assumption warnings")
    st.write(result.validation_warnings)

recommendation = result.recommendation
summary, capacity, patterns, detail, surge, validation = st.tabs(
    ["Summary", "Capacity Sweep", "Best Patterns", "Pattern Detail", "Surge", "Validation"]
)

with summary:
    st.subheader("Executive Summary")
    if recommendation is None:
        st.warning("No recommendation was available for the selected inputs.")
    else:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Assessment", recommendation.assessment)
        col2.metric("Confidence", recommendation.confidence)
        col3.metric("Feasible", "Yes" if recommendation.feasible else "No")
        col4.metric("Sustainable", "Yes" if recommendation.sustainable else "No")
        st.markdown(f"**Recommended Pattern:** `{recommendation.pattern}`")
        st.markdown(f"**Primary Limiting Factor:** {recommendation.limiting_factor}")
        st.write(recommendation.recommendation)

    if result.best_rows:
        top = result.best_rows[0]
        metrics = st.columns(5)
        metrics[0].metric("Planned Sorties", int(top["weekly_sorties"]))
        metrics[1].metric("Required Sorties", int(top["required_sorties"]))
        metrics[2].metric("Success", f"{float(top['success']):.1%}")
        metrics[3].metric("Next Mon MC", f"{float(top['avg_next_monday']):.1f}")
        metrics[4].metric("Risk", str(top["risk_band"]))

with capacity:
    st.subheader("PAI / UTE Capacity")
    st.dataframe(result.capacity_rows, use_container_width=True)

with patterns:
    st.subheader("Ranked Best Patterns")
    st.dataframe(display_rows(result.best_rows), use_container_width=True)

with detail:
    st.subheader("Pattern Detail")
    options = best_pattern_options(result.best_rows)
    if not options:
        st.warning("No pattern rows available.")
    else:
        selected_label = st.selectbox("Selected Pattern", list(options))
        selected = options[selected_label]
        st.markdown(f"**Pattern:** `{selected['pattern_with_frontlines']}`")
        st.markdown(f"**Name:** {selected['pattern_name']}")
        st.markdown(f"**Assessment:** {selected['operational_assessment']}")
        st.dataframe(pattern_detail_rows(selected), use_container_width=True, hide_index=True)

with surge:
    st.subheader("Max-Commit Surge Duration")
    rows = surge_rows(result.surge)
    if not rows:
        st.info("Surge analysis was not run or no max-commit candidate was available.")
    else:
        st.dataframe(rows, use_container_width=True)
        first_red = next((row for row in rows if row["risk"] == "Red"), None)
        if first_red:
            st.warning(f"Surge falls to Red in week {first_red['week']}.")

with validation:
    st.subheader("Run Metadata")
    st.write(
        {
            "policy": result.config.policy.policy_name,
            "policy_version": result.config.policy.policy_version,
            "iterations": result.config.iterations,
            "random_seed": result.config.random_seed,
            "event_model": result.config.event_count_models[0],
            "fix_model": result.config.fix_count_models[0],
        }
    )
    st.subheader("Assumption Warnings")
    if result.validation_warnings:
        st.write(result.validation_warnings)
    else:
        st.success("No optimizer validation warnings.")
