from __future__ import annotations

from io import BytesIO
from dataclasses import replace
from pathlib import Path
from random import Random

import streamlit as st

try:
    from PIL import Image
except ImportError:  # Streamlit installs Pillow, but keep local checks graceful.
    Image = None

from pattern_generator import (
    PatternConstraints,
    capacity_points,
    generate_turn_pattern_permutations,
)
from ttp_rules import (
    DEFAULT_TTP_POLICY,
    MODEL_VERSION,
    TtpPolicy,
    commit_aircraft,
    recovery_model_options,
    risk_band,
    validate_scenario,
)
from simulation import AircraftInventory, DaySchedule, HomestationData, Scenario, SimulationSummary, simulate


ASSET_DIR = Path(__file__).parent / "assets"
LOGO_LOCKUP_PATH = ASSET_DIR / "logo_option_6a_lockup.png"
LOGO_ICON_PATH = ASSET_DIR / "logo_option_6a_clean_white_red_icon.png"
SIDEBAR_LOGO_PATH = ASSET_DIR / "logo_option_6a_clean_white_red_lockup.png"
MODEL_LOGIC_PATH = Path(__file__).parent / "MODEL_LOGIC.md"


LOGO_FALLBACK_SVG = """
<svg viewBox="0 0 780 190" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Turn Pattern Sustainability Monte Carlo Model logo">
  <rect width="780" height="190" fill="white"/>
  <g fill="none" stroke-linecap="round" stroke-linejoin="round">
    <path d="M35 90 C65 20 145 20 190 88 C235 156 315 156 350 90 C315 24 235 24 190 92 C145 160 65 160 35 90"
          stroke="#08284a" stroke-width="13"/>
    <path d="M190 92 C235 24 315 24 350 90" stroke="#168f92" stroke-width="13"/>
    <path d="M215 70 C255 36 300 34 335 64" stroke="#168f92" stroke-width="5"/>
    <path d="M318 35 L358 52 L318 68 L329 53 Z" fill="#08284a" stroke="#08284a" stroke-width="3"/>
  </g>
  <g>
    <circle cx="70" cy="92" r="5" fill="#168f92"/>
    <circle cx="100" cy="92" r="5" fill="#168f92"/>
    <circle cx="130" cy="92" r="5" fill="#88939d"/>
    <circle cx="160" cy="92" r="5" fill="#88939d"/>
    <circle cx="260" cy="92" r="5" fill="#e0a047"/>
    <circle cx="290" cy="92" r="5" fill="#e0a047"/>
    <circle cx="320" cy="92" r="5" fill="#d9821f"/>
    <circle cx="350" cy="92" r="5" fill="#d9821f"/>
  </g>
  <text x="190" y="158" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="28" font-weight="700" fill="#168f92">TPS-MCM</text>
  <line x1="390" y1="25" x2="390" y2="165" stroke="#c4c9ce" stroke-width="2"/>
  <text x="420" y="70" font-family="Arial, Helvetica, sans-serif" font-size="42" font-weight="800" letter-spacing="4" fill="#08284a">TURN PATTERN</text>
  <text x="420" y="122" font-family="Arial, Helvetica, sans-serif" font-size="42" font-weight="800" letter-spacing="4" fill="#08284a">SUSTAINABILITY</text>
  <line x1="420" y1="154" x2="455" y2="154" stroke="#168f92" stroke-width="3"/>
  <text x="470" y="162" font-family="Arial, Helvetica, sans-serif" font-size="20" font-weight="600" letter-spacing="5" fill="#168f92">MONTE CARLO MODEL</text>
  <line x1="705" y1="154" x2="745" y2="154" stroke="#d9821f" stroke-width="3"/>
</svg>
"""


def _logo_bytes(path: Path) -> bytes | None:
    if path.exists():
        return path.read_bytes()
    return None


def _display_logo(path: Path, *, width: int = 260) -> None:
    if path.exists() and path.suffix.lower() == ".svg":
        svg = path.read_text(encoding="utf-8")
        st.markdown(f'<div style="max-width: {width}px;">{svg}</div>', unsafe_allow_html=True)
        return
    logo_bytes = _logo_bytes(path)
    if logo_bytes is not None:
        st.image(logo_bytes, width=width)
        return
    st.markdown("### TPS-MCM")


def _page_icon() -> object | None:
    icon_bytes = _logo_bytes(LOGO_ICON_PATH)
    if icon_bytes is None:
        return None
    if Image is None:
        return None
    return Image.open(BytesIO(icon_bytes))


def _model_logic_markdown() -> str:
    if MODEL_LOGIC_PATH.exists():
        return MODEL_LOGIC_PATH.read_text(encoding="utf-8")
    return "MODEL_LOGIC.md was not found in the app folder."


_page_config = {"page_title": "Turn Pattern Sustainability Monte Carlo Model", "layout": "wide"}
_icon = _page_icon()
if _icon is not None:
    _page_config["page_icon"] = _icon
st.set_page_config(**_page_config)


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
    max_third_go: int,
    max_fourth_go: int,
    max_day_delta: int,
    include_surge: bool,
    ute_min: float,
    ute_max: float,
    spare_rate: float,
) -> dict[str, object]:
    policy = replace(
        DEFAULT_TTP_POLICY,
        max_daily_sorties=max_daily_sorties,
        max_second_go=max_second_go,
        max_third_go=max_third_go,
        max_fourth_go=max_fourth_go,
        max_day_to_day_delta=max_day_delta,
        ute_min=ute_min,
        ute_max=ute_max,
        spare_rate=spare_rate,
    )
    constraints = PatternConstraints.from_policy(policy)
    rng = Random(random_seed)
    rows: list[dict[str, object]] = []
    family_coverage_rows: list[dict[str, object]] = []
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
            family_names = sorted({
                str(pattern["classification"]["pattern_family"])
                for pattern in patterns
            })
            family_coverage_rows.append(
                {
                    "PAI": pai,
                    "Capacity Point": point["label"],
                    "Weekly Sorties": point["weekly_sorties"],
                    "Patterns Tested": len(patterns),
                    "Families Tested": len(family_names),
                    "Pattern Families": ", ".join(family_names),
                }
            )
            for model_name, use_uncommitted in recovery_model_options():
                best_rows_by_family: dict[str, dict[str, object]] = {}
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
                    family = str(row["pattern_family"])
                    current_best = best_rows_by_family.get(family)
                    if current_best is None or _rank(row) > _rank(current_best):
                        best_rows_by_family[family] = row
                rows.extend(best_rows_by_family.values())

    return {
        "policy": policy,
        "capacity_rows": capacity_rows,
        "family_coverage_rows": family_coverage_rows,
        "rows": sorted(rows, key=lambda row: (row["pai"], row["weekly_sorties"], row["model"])),
    }


@st.cache_data(show_spinner=False)
def run_manual_pattern(
    *,
    pai: int,
    required_sorties: int,
    first_go: tuple[int, ...],
    second_go: tuple[int, ...],
    third_go: tuple[int, ...],
    fourth_go: tuple[int, ...],
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
    max_third_go: int,
    max_fourth_go: int,
    ute_min: float,
    ute_max: float,
    spare_rate: float,
) -> dict[str, object]:
    policy = replace(
        DEFAULT_TTP_POLICY,
        max_daily_sorties=max_daily_sorties,
        max_second_go=max_second_go,
        max_third_go=max_third_go,
        max_fourth_go=max_fourth_go,
        ute_min=ute_min,
        ute_max=ute_max,
        spare_rate=spare_rate,
    )
    schedule = {
        day: DaySchedule(
            first_go=first_go[index],
            second_go=second_go[index],
            third_go=third_go[index],
            fourth_go=fourth_go[index],
        )
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


@st.cache_data(show_spinner=False)
def run_surge_weeks(
    *,
    pai_min: int,
    pai_max: int,
    surge_weeks: int,
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
    ute_min: float,
    ute_max: float,
    spare_rate: float,
) -> list[dict[str, object]]:
    policy = replace(DEFAULT_TTP_POLICY, ute_min=ute_min, ute_max=ute_max, spare_rate=spare_rate)
    rng = Random(random_seed)
    rows = []
    for pai in range(pai_min, pai_max + 1):
        committed = commit_aircraft(pai, policy)
        schedule = {
            day: DaySchedule(first_go=committed)
            for day in policy.flying_days
        }
        required_sorties = committed * len(policy.flying_days)
        for week in range(1, surge_weeks + 1):
            fatigue_break_multiplier = 1.0 + (0.10 * (week - 1))
            fatigue_fix_degradation = max(0.60, 1.0 - (0.08 * (week - 1)))
            for model_name, use_uncommitted in recovery_model_options():
                scenario = Scenario(
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
                        use_uncommitted_aircraft_for_ga_recovery=use_uncommitted,
                        event_count_model=event_count_model,
                        fix_count_model=fix_count_model,
                        fatigue_break_multiplier=fatigue_break_multiplier,
                        fatigue_fix_degradation=fatigue_fix_degradation,
                    ),
                    schedule=schedule,
                    total_required_sorties=required_sorties,
                    policy=policy,
                )
                summary = simulate(scenario, iterations=iterations, seed=rng.randrange(1_000_000_000))
                rows.append(
                    {
                        "PAI": pai,
                        "Week": week,
                        "Recovery Model": model_name,
                        "Commit Aircraft": committed,
                        "Planned Sorties": required_sorties,
                        "Max-Commit UTE": required_sorties / (pai * len(policy.flying_days)) if pai else 0,
                        "Break Stress": fatigue_break_multiplier,
                        "Fix Effectiveness": fatigue_fix_degradation,
                        "Overall Success": summary.probability_success,
                        "Sortie Target Met": summary.probability_meet_sorties,
                        "Next-Monday Recovery": summary.probability_recovery,
                        "Avg Next-Monday MC": summary.average_next_monday_available,
                        "Avg Backlog": summary.average_repair_backlog,
                        "Risk": risk_band(summary.probability_success, policy),
                        "Primary Failure": _primary_failure(summary),
                    }
                )
    return rows


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
    third_go = [schedule[day].third_go for day in policy.flying_days]
    fourth_go = [schedule[day].fourth_go for day in policy.flying_days]
    turn_pattern = _turn_pattern_display(first_go, turns, third_go, fourth_go)
    starting_mc = summary.sample_iteration.days[0].total_mc_aircraft
    recovery_debt = max(0.0, starting_mc - summary.average_next_monday_available)
    shape_flags = _operational_shape_flags(classification, first_go, policy, str(point["label"]))
    return {
        "pai": pai,
        "capacity_label": point["label"],
        "weekly_sorties": point["weekly_sorties"],
        "ute": point["actual_ute"],
        "avg_sorties_per_aircraft": int(point["weekly_sorties"]) / pai if pai else 0,
        "commit_aircraft": point["commit_aircraft"],
        "spare_rate": policy.spare_rate,
        "model": model_name,
        "pattern_index": pattern_index,
        "pattern_name": classification["pattern_name"],
        "pattern_family": classification["pattern_family"],
        "diagnostic_only": bool(classification.get("diagnostic_only", False)),
        "pattern_with_frontlines": turn_pattern,
        "daily_sequence": classification["daily_sequence"],
        "first_go_sequence": first_go,
        "turn_sequence": turns,
        "third_go_sequence": third_go,
        "fourth_go_sequence": fourth_go,
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
        "operational_shape_success": not shape_flags,
        "recommendation_flags": "; ".join(shape_flags) if shape_flags else "Pass",
        "risk_band": risk_band(summary.probability_success, policy),
        "score": _score(summary, classification, recovery_debt),
    }


def _turn_pattern_display(
    first_go: list[int],
    second_go: list[int],
    third_go: list[int] | None = None,
    fourth_go: list[int] | None = None,
) -> str:
    third_go = third_go or [0] * len(first_go)
    fourth_go = fourth_go or [0] * len(first_go)
    use_third = any(third_go)
    use_fourth = any(fourth_go)
    days = []
    for first, second, third, fourth in zip(first_go, second_go, third_go, fourth_go):
        if use_fourth:
            days.append(f"{first}x{second}x{third}x{fourth}")
        elif use_third:
            days.append(f"{first}x{second}x{third}")
        else:
            days.append(f"{first}x{second}")
    return "-".join(days)


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


def _operational_shape_flags(
    classification: dict[str, object],
    first_go: list[int],
    policy: TtpPolicy,
    capacity_label: str,
) -> list[str]:
    flags: list[str] = []
    sequence = [int(value) for value in classification["daily_sequence"]]
    is_flat_turn = str(classification.get("pattern_family", "")) == "Flat Turns"
    if capacity_label == policy.surge_label:
        flags.append("Max-commit surge is stress-only")
    if bool(classification.get("diagnostic_only", False)):
        flags.append("Diagnostic-only pattern family")
    if not is_flat_turn and float(classification["backend_penalty"]) > 0.20:
        flags.append("Back-loaded Thu/Fri pressure")
    if not is_flat_turn and float(classification["friday_penalty"]) > 0.20:
        flags.append("Friday recovery preference not met")
    if float(classification["compression_score"]) >= 0.70:
        flags.append("Compressed sortie concentration")
    if float(classification["smoothness_score"]) < 0.55:
        flags.append("Large day-to-day sortie swings")
    if not is_flat_turn and len(sequence) >= 5 and sequence[-1] > sequence[-2]:
        flags.append("Friday increases from Thursday")
    if not is_flat_turn and first_go and sum(first_go[-2:]) > sum(first_go[:2]) + 1:
        flags.append("Back-loaded first-go demand")
    if not is_flat_turn and first_go and first_go[-1] == max(first_go) and first_go[-1] > 0:
        flags.append("Friday is peak first-go day")
    return flags


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
            "Avg Sorties / Aircraft": f"{_avg_sorties_per_aircraft(row):.1f}",
            "Spare Rate": f"{float(row.get('spare_rate', 0)):.0%}",
            "Recovery Model": row["model"],
            "Turn Pattern": row["pattern_with_frontlines"],
            "Pattern Family": row["pattern_name"],
            "Overall Success": _pct(float(row["success"])),
            "Sortie Target Met": _pct(float(row["sortie_success"])),
            "Avg Next-Monday MC": f"{float(row['avg_next_monday']):.1f}",
            "Recovery Debt": f"{float(row['recovery_debt']):.1f}",
            "Recommendation Screen": row.get("recommendation_flags", "Pass"),
            "Risk": row["risk_band"],
        }
        for row in rows
    ]


def _avg_sorties_per_aircraft(row: dict[str, object]) -> float:
    if "avg_sorties_per_aircraft" in row:
        return float(row["avg_sorties_per_aircraft"])
    pai = int(row.get("pai", 0))
    return int(row.get("weekly_sorties", 0)) / pai if pai else 0.0


def _is_recommendable(row: dict[str, object], policy: TtpPolicy = DEFAULT_TTP_POLICY) -> bool:
    return (
        int(row["weekly_sorties"]) >= int(row["required_sorties"])
        and float(row["success"]) >= policy.yellow_success_threshold
        and float(row["recovery_success"]) >= policy.yellow_success_threshold
        and float(row["backlog_success"]) >= policy.yellow_success_threshold
        and bool(row.get("operational_shape_success", True))
    )


def _recommendable_rows(
    rows: list[dict[str, object]],
    policy: TtpPolicy = DEFAULT_TTP_POLICY,
) -> list[dict[str, object]]:
    return [row for row in rows if _is_recommendable(row, policy)]


def _recommendation_blocker(row: dict[str, object]) -> str:
    flags = str(row.get("recommendation_flags", "Pass"))
    if flags and flags != "Pass":
        return flags
    failure = str(row["failure_mode"])
    return "Passed recommendation screen" if failure == "None" else failure


def _recommendation_status(row: dict[str, object], policy: TtpPolicy) -> str:
    return "Recommendable" if _is_recommendable(row, policy) else "Not recommended"


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
            status = f"No sustainable pattern; closest non-recommended risk {best['risk_band']}" if best else "No valid patterns"
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
        failure = _recommendation_blocker(row)
        counts[failure] = counts.get(failure, 0) + 1
    if not counts:
        return [{"Not-Recommended Reason": "None", "Patterns": "0", "Share": "0.0%"}]
    total = sum(counts.values())
    return [
        {
            "Not-Recommended Reason": failure,
            "Patterns": str(count),
            "Share": _pct(count / total),
        }
        for failure, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)
    ]


def _summary_decision_rows(rows: list[dict[str, object]], policy: TtpPolicy) -> list[dict[str, object]]:
    output = []
    for pai in _pai_values(rows):
        pai_rows = _rows_for_pai(rows, pai)
        viable = _recommendable_rows(pai_rows, policy)
        selected = max(viable, key=_rank) if viable else max(pai_rows, key=_rank)
        output.append(
            {
                "PAI": pai,
                "Status": "Recommendable" if viable else "Closest Non-Recommended",
                "Turn Pattern": selected["pattern_with_frontlines"],
                "Planned": selected["weekly_sorties"],
                "Required": selected["required_sorties"],
                "UTE": f"{float(selected['ute']):.2f}",
                "Success": _pct(float(selected["success"])),
                "Recovery": _pct(float(selected["recovery_success"])),
                "Backlog": _pct(float(selected["backlog_success"])),
                "Risk": selected["risk_band"],
                "Limiter": _recommendation_blocker(selected),
            }
        )
    return output


def _capacity_interpretation_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    output = []
    pai_values = sorted({int(row["pai"]) for row in rows if row.get("pai")})
    for pai in pai_values:
        pai_rows = [row for row in rows if int(row.get("pai", 0)) == pai]
        normal_rows = [row for row in pai_rows if "55%" not in str(row["label"])]
        surge_rows = [row for row in pai_rows if "55%" in str(row["label"])]
        min_normal = min((int(row["weekly_sorties"]) for row in normal_rows), default=0)
        max_normal = max((int(row["weekly_sorties"]) for row in normal_rows), default=0)
        min_ute = min((float(row["actual_ute"]) for row in normal_rows), default=0.0)
        max_ute = max((float(row["actual_ute"]) for row in normal_rows), default=0.0)
        surge = max(surge_rows, key=lambda row: int(row["weekly_sorties"])) if surge_rows else None
        output.append(
            {
                "PAI": pai,
                "Normal UTE Band": f"{min_ute:.2f}-{max_ute:.2f}",
                "Normal Sortie Band": f"{min_normal}-{max_normal}",
                "Max-Commit Sorties": surge["weekly_sorties"] if surge else "Not included",
                "Max-Commit UTE": f"{float(surge['actual_ute']):.2f}" if surge else "Not included",
                "Interpretation": (
                    "Use the normal band for weekly planning; treat max-commit as surge-only."
                    if surge else
                    "Use this range for weekly planning."
                ),
            }
        )
    return output


def _pattern_family_rows(rows: list[dict[str, object]], policy: TtpPolicy) -> list[dict[str, object]]:
    output = []
    families = sorted({str(row["pattern_family"]) for row in rows})
    for family in families:
        family_rows = [row for row in rows if str(row["pattern_family"]) == family]
        viable = _recommendable_rows(family_rows, policy)
        best_pool = viable or family_rows
        best = max(best_pool, key=_rank)
        avg_success = sum(float(row["success"]) for row in family_rows) / len(family_rows)
        avg_debt = sum(float(row["recovery_debt"]) for row in family_rows) / len(family_rows)
        output.append(
            {
                "Pattern Family": family,
                "Tested": len(family_rows),
                "Sustainable": len(viable),
                "Best Success": _pct(float(best["success"])),
                "Average Success": _pct(avg_success),
                "Average Recovery Debt": f"{avg_debt:.1f}",
                "Representative Pattern": best["pattern_with_frontlines"],
                "Recommendation Status": "Recommendable" if viable else "No recommendable pattern in family",
                "Limiter / Screen": _recommendation_blocker(best),
            }
        )
    return sorted(output, key=lambda row: (int(row["Sustainable"]), row["Best Success"]), reverse=True)


def _diagnostic_pai_rows(rows: list[dict[str, object]], policy: TtpPolicy) -> list[dict[str, object]]:
    output = []
    for pai in _pai_values(rows):
        pai_rows = _rows_for_pai(rows, pai)
        viable = _recommendable_rows(pai_rows, policy)
        rejected = len(pai_rows) - len(viable)
        near_miss_pool = [row for row in pai_rows if not _is_recommendable(row, policy)]
        near_miss = max(near_miss_pool, key=_rank) if near_miss_pool else None
        output.append(
            {
                "PAI": pai,
                "Candidates Tested": len(pai_rows),
                "Sustainable": len(viable),
                "Rejected": rejected,
                "Sustainable Share": _pct(len(viable) / len(pai_rows)) if pai_rows else "0.0%",
                "Closest Non-Recommended Pattern": near_miss["pattern_with_frontlines"] if near_miss else "None",
                "Why It Was Not Recommended": _recommendation_blocker(near_miss) if near_miss else "None",
            }
        )
    return output


def _failure_mode_rows(rows: list[dict[str, object]], policy: TtpPolicy) -> list[dict[str, object]]:
    counts: dict[str, int] = {}
    for row in rows:
        if _is_recommendable(row, policy):
            continue
        failure = _recommendation_blocker(row)
        counts[failure] = counts.get(failure, 0) + 1
    total = sum(counts.values())
    return [
        {"Not-Recommended Reason": failure, "Patterns": count, "Share": _pct(count / total) if total else "0.0%"}
        for failure, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)
    ]


def _detail_probability_rows(row: dict[str, object]) -> list[dict[str, object]]:
    return [
        {"Metric": "Overall Success", "Probability": float(row["success"])},
        {"Metric": "Sortie Target Met", "Probability": float(row["sortie_success"])},
        {"Metric": "Aircraft Available", "Probability": float(row["aircraft_success"])},
        {"Metric": "Commit Compliance", "Probability": float(row["commit_success"])},
        {"Metric": "Next-Monday Recovery", "Probability": float(row["recovery_success"])},
        {"Metric": "Backlog Success", "Probability": float(row["backlog_success"])},
    ]


def _detail_daily_sortie_rows(row: dict[str, object], policy: TtpPolicy) -> list[dict[str, object]]:
    output = []
    first_go = list(row["first_go_sequence"])
    second_go = list(row["turn_sequence"])
    third_go = list(row.get("third_go_sequence", [0] * len(first_go)))
    fourth_go = list(row.get("fourth_go_sequence", [0] * len(first_go)))
    for index, day in enumerate(policy.flying_days):
        output.append(
            {
                "Day": day,
                "1st Go": int(first_go[index]),
                "2nd Go": int(second_go[index]),
                "3rd Go": int(third_go[index]),
                "4th Go": int(fourth_go[index]),
                "Daily Sorties": int(first_go[index] + second_go[index] + third_go[index] + fourth_go[index]),
            }
        )
    return output


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


def _surge_display_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "PAI": row["PAI"],
            "Week": row["Week"],
            "Recovery Model": row["Recovery Model"],
            "Commit Aircraft": row["Commit Aircraft"],
            "Planned Sorties": row["Planned Sorties"],
            "Max-Commit UTE": f"{float(row['Max-Commit UTE']):.2f}",
            "Break Stress": f"{float(row['Break Stress']):.2f}x",
            "Fix Effectiveness": f"{float(row['Fix Effectiveness']):.2f}x",
            "Overall Success": _pct(float(row["Overall Success"])),
            "Sortie Target Met": _pct(float(row["Sortie Target Met"])),
            "Next-Monday Recovery": _pct(float(row["Next-Monday Recovery"])),
            "Avg Next-Monday MC": f"{float(row['Avg Next-Monday MC']):.1f}",
            "Avg Backlog": f"{float(row['Avg Backlog']):.1f}",
            "Risk": row["Risk"],
            "Primary Failure": row["Primary Failure"],
        }
        for row in rows
    ]


def _surge_is_sustainable(row: dict[str, object], policy: TtpPolicy) -> bool:
    return (
        float(row["Overall Success"]) >= policy.yellow_success_threshold
        and float(row["Next-Monday Recovery"]) >= policy.yellow_success_threshold
        and float(row["Avg Backlog"]) <= 0.5
        and str(row["Risk"]) in ("Green", "Yellow")
    )


def _surge_grouped_rows(rows: list[dict[str, object]]) -> list[tuple[int, str, list[dict[str, object]]]]:
    groups: list[tuple[int, str, list[dict[str, object]]]] = []
    keys = sorted({(int(row["PAI"]), str(row["Recovery Model"])) for row in rows})
    for pai, model in keys:
        matching = [
            row for row in rows
            if int(row["PAI"]) == pai and str(row["Recovery Model"]) == model
        ]
        groups.append((pai, model, sorted(matching, key=lambda row: int(row["Week"]))))
    return groups


def _surge_summary_rows(rows: list[dict[str, object]], policy: TtpPolicy) -> list[dict[str, object]]:
    output = []
    for pai, model, group in _surge_grouped_rows(rows):
        sustained_through = 0
        first_failed: dict[str, object] | None = None
        for row in group:
            if first_failed is None and _surge_is_sustainable(row, policy):
                sustained_through = int(row["Week"])
            elif first_failed is None:
                first_failed = row
        week_1 = group[0] if group else {}
        final_week = group[-1] if group else {}
        peak_backlog = max(float(row["Avg Backlog"]) for row in group) if group else 0.0
        lowest_recovery = min(float(row["Next-Monday Recovery"]) for row in group) if group else 0.0
        if first_failed is None:
            first_failed_week = "None in window"
            limiter = "No hard failure"
            interpretation = (
                "Modeled as sustainable through the selected surge window. Treat this as a stress posture, "
                "not a normal planning rate."
            )
        elif sustained_through == 0:
            first_failed_week = str(first_failed["Week"])
            limiter = str(first_failed["Primary Failure"])
            interpretation = (
                "Max surge is not sustainable even in week 1 under this recovery model. "
                "Use the failure readout to see whether sorties, recovery, or backlog is driving the miss."
            )
        else:
            first_failed_week = str(first_failed["Week"])
            limiter = str(first_failed["Primary Failure"])
            interpretation = (
                f"Surge is modeled as usable through week {sustained_through}; "
                f"risk becomes unacceptable in week {first_failed_week}."
            )
        output.append(
            {
                "PAI": pai,
                "Recovery Model": model,
                "Sustained Through Week": sustained_through,
                "First Failed Week": first_failed_week,
                "Week 1 Success": _pct(float(week_1.get("Overall Success", 0.0))),
                "Final Week Success": _pct(float(final_week.get("Overall Success", 0.0))),
                "Lowest Next-Monday Recovery": _pct(lowest_recovery),
                "Peak Avg Backlog": f"{peak_backlog:.1f}",
                "Primary Limiter": limiter,
                "Interpretation": interpretation,
            }
        )
    return output


def _surge_failure_rows(rows: list[dict[str, object]], policy: TtpPolicy) -> list[dict[str, object]]:
    output = []
    for pai, model, group in _surge_grouped_rows(rows):
        first_failed = next(
            (row for row in group if not _surge_is_sustainable(row, policy)),
            None,
        )
        if first_failed is None:
            watch_row = min(
                group,
                key=lambda row: (
                    float(row["Overall Success"]),
                    float(row["Next-Monday Recovery"]),
                    -float(row["Avg Backlog"]),
                ),
            )
            output.append(
                {
                    "PAI": pai,
                    "Recovery Model": model,
                    "Status": "Passes selected window",
                    "Week": watch_row["Week"],
                    "Failure Signal": "Weakest modeled week",
                    "Primary Failure": "None",
                    "Next-Monday Recovery": _pct(float(watch_row["Next-Monday Recovery"])),
                    "Avg Backlog": f"{float(watch_row['Avg Backlog']):.1f}",
                    "Explanation": "No hard failure in the selected window; this row shows the weakest week to monitor.",
                }
            )
        else:
            output.append(
                {
                    "PAI": pai,
                    "Recovery Model": model,
                    "Status": "Fails sustainability screen",
                    "Week": first_failed["Week"],
                    "Failure Signal": first_failed["Risk"],
                    "Primary Failure": first_failed["Primary Failure"],
                    "Next-Monday Recovery": _pct(float(first_failed["Next-Monday Recovery"])),
                    "Avg Backlog": f"{float(first_failed['Avg Backlog']):.1f}",
                    "Explanation": (
                        "This is the first week where success, recovery, or backlog no longer meets the surge screen."
                    ),
                }
            )
    return output


def _surge_chart_rows(rows: list[dict[str, object]], metric: str) -> list[dict[str, object]]:
    return [
        {
            "Week": int(row["Week"]),
            "Series": f"{row['PAI']} PAI / {row['Recovery Model']}",
            metric: float(row[metric]),
        }
        for row in rows
    ]


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
        f"The closest non-recommended candidate is {best_failed['pattern_with_frontlines']} at "
        f"{best_failed['capacity_label']}, failing primarily from {_recommendation_blocker(best_failed)}."
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
        {"Metric": "Avg Sorties / Aircraft", "Value": f"{_avg_sorties_per_aircraft(row):.1f}"},
        {"Metric": "Commit Aircraft", "Value": str(row["commit_aircraft"])},
        {"Metric": "Scheduled Spare Rate", "Value": f"{row.get('spare_rate', 0):.0%}"},
        {"Metric": "Recovery Model", "Value": str(row["model"])},
        {"Metric": "Turn Pattern", "Value": str(row["pattern_with_frontlines"])},
        {"Metric": "1st Go Sequence", "Value": "-".join(str(value) for value in row["first_go_sequence"])},
        {"Metric": "2nd Go Sequence", "Value": "-".join(str(value) for value in row["turn_sequence"])},
        {"Metric": "3rd Go Sequence", "Value": "-".join(str(value) for value in row.get("third_go_sequence", [0, 0, 0, 0, 0]))},
        {"Metric": "4th Go Sequence", "Value": "-".join(str(value) for value in row.get("fourth_go_sequence", [0, 0, 0, 0, 0]))},
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
        {"Metric": "Recommendation Screen", "Value": str(row.get("recommendation_flags", "Pass"))},
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


def _planning_band_from_dsute(
    dsute: float,
    upper_spread: float,
    floor_value: float,
    ceiling_value: float,
) -> dict[str, float]:
    lower = max(floor_value, dsute)
    upper = min(ceiling_value, dsute + upper_spread)
    if upper < lower:
        upper = lower
    return {
        "lower": lower,
        "upper": upper,
        "spread": upper - lower,
    }


def _show_about_page() -> None:
    st.header("About")
    st.caption("A quick guide to what the app does, how to use it, and how to interpret the results.")

    st.subheader("Turn Pattern Sustainability Monte Carlo Model")
    st.markdown(
        """
        The Turn Pattern Sustainability Monte Carlo Model is a planning tool that helps evaluate whether a weekly
        aircraft schedule is executable, supportable, and sustainable.

        Instead of only asking whether the required sorties can be scheduled, the model estimates the probability
        that a proposed turn pattern can survive maintenance uncertainty, aircraft availability limits, ground
        aborts, and repair timelines.
        """
    )

    st.info(
        "Core question: Can this weekly turn pattern meet the sortie requirement without overcommitting the fleet "
        "or creating unacceptable recovery risk for next week?"
    )

    st.subheader("What the App Does")
    st.markdown(
        """
        This application uses Monte Carlo simulation to test weekly turn patterns against user-defined planning
        assumptions, including:

        - possessed aircraft and mission-capable rate,
        - required sorties and UTE planning range,
        - break rates and ground-abort rates,
        - scheduled-spare assumptions,
        - 8-hour, 12-hour, and 24-hour repair outcomes,
        - commit limits and next-week recovery expectations.

        The model runs the same schedule many times under different maintenance outcomes. It then reports how often
        the plan succeeds, where it fails, and whether the fleet recovers enough for follow-on execution.
        """
    )

    st.subheader("What the Results Mean")
    st.markdown(
        """
        The app does **not** provide a single right answer. It provides a probability-based risk assessment.

        A turn pattern may generate the required sorties but still be risky if it depends on excessive aircraft
        commit, weak spare coverage, unrealistic repair recovery, or leaves too much maintenance backlog heading
        into the next week.
        """
    )
    st.dataframe(
        [
            {"Output": "Overall Success Probability", "Meaning": "How often the full plan succeeds across all modeled constraints."},
            {"Output": "Sortie Target Met", "Meaning": "How often the required weekly sorties are achieved."},
            {"Output": "Aircraft Availability", "Meaning": "Whether enough mission-capable aircraft are available each day."},
            {"Output": "Commit Compliance", "Meaning": "Whether the plan stays within the modeled commit limit."},
            {"Output": "Next-Monday Recovery", "Meaning": "Whether the fleet recovers enough to begin the next week."},
            {"Output": "Backlog Risk", "Meaning": "Whether unresolved maintenance accumulates during execution."},
        ],
        width="stretch",
        hide_index=True,
    )

    st.subheader("Important Limitations")
    st.markdown(
        """
        This model is a decision-support tool, not a replacement for maintenance production judgment, aircraft
        status review, or tail-by-tail scheduling.

        It does not predict exactly which aircraft will break or when. It estimates the likelihood that a schedule
        can survive under the assumptions provided by the user. The quality of the output depends on the quality of
        the inputs, especially break rates, abort rates, repair timelines, MC aircraft, and sortie requirements.
        """
    )

    with st.expander("Model Logic", expanded=False):
        st.markdown(_model_logic_markdown())

    st.subheader("Version")
    st.write(f"Current model version: {MODEL_VERSION}")


st.title("Turn Pattern Sustainability Monte Carlo Model")
st.caption("Monte Carlo turn-pattern planning dashboard")

with st.sidebar:
    _display_logo(SIDEBAR_LOGO_PATH, width=260)
    st.divider()
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
        use_spares = st.checkbox("Use scheduled spares", value=False)
        spare_rate = 0.20 if use_spares else 0.0
        st.caption(f"Scheduled spare rate: {spare_rate:.0%}")
        max_daily_sorties = st.slider("Max Daily Sorties", 1, 12, 7)
        go_waves = st.slider("# of GOs", 1, 4, 2)
        max_second_go = st.slider("Max Second-Go Sorties", 0, 6, 2) if go_waves >= 2 else 0
        max_third_go = st.slider("Max Third-Go Sorties", 0, 6, 0 if go_waves < 3 else 2) if go_waves >= 3 else 0
        max_fourth_go = st.slider("Max Fourth-Go Sorties", 0, 6, 0 if go_waves < 4 else 2) if go_waves >= 4 else 0

        if page == "Optimization Dashboard":
            max_patterns = st.number_input("Max Patterns Per UTE Point", min_value=1, value=30, step=10)
            max_day_delta = st.slider("Max Day-to-Day Delta", 0, 8, 2)
            include_surge = st.checkbox("Include max-commit surge in optimization", value=False)
            surge_weeks = st.slider("Max Surge Weeks", 1, 5, 5)
        else:
            max_patterns = 40
            max_day_delta = DEFAULT_TTP_POLICY.max_day_to_day_delta or 0
            include_surge = False
            surge_weeks = 5

if page == "About / Model Logic":
    _show_about_page()
    st.stop()

if page == "DSUTE Calculator":
    st.header("DSUTE Calculator")
    st.caption(
        "DSUTE is calculated on the sortie side only: scheduled or required sorties / "
        "(possessed aircraft x O&M days)."
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
    st.subheader("Suggested Model UTE Band")
    st.caption(
        "Use this to translate the observed DSUTE into a planning range for the model. "
        "The lower bound starts at the calculated DSUTE; the upper bound adds a planning buffer."
    )
    band_cols = st.columns(3)
    band_floor = float(band_cols[0].number_input("Minimum Allowed UTE", min_value=0.0, max_value=1.0, value=0.0, step=0.01))
    band_ceiling = float(band_cols[1].number_input("Maximum Allowed UTE", min_value=0.0, max_value=1.0, value=0.52, step=0.01))
    upper_spread = float(band_cols[2].number_input("Upper Planning Spread", min_value=0.0, max_value=1.0, value=0.12, step=0.01))
    suggested_band = _planning_band_from_dsute(
        float(deployed["dsute"]),
        upper_spread=upper_spread,
        floor_value=band_floor,
        ceiling_value=band_ceiling,
    )
    band_metric_cols = st.columns(3)
    band_metric_cols[0].metric("Suggested UTE Lower", f"{suggested_band['lower']:.2f}")
    band_metric_cols[1].metric("Suggested UTE Upper", f"{suggested_band['upper']:.2f}")
    band_metric_cols[2].metric("Band Width", f"{suggested_band['spread']:.2f}")
    st.info(
        f"Recommended sidebar setting: set UTE Planning Range to "
        f"{suggested_band['lower']:.2f}-{suggested_band['upper']:.2f} if you want the model "
        "to evaluate patterns near the observed deployed or operating-location sortie tempo."
    )
    st.stop()

if page == "Manual Turn Pattern":
    st.header("Manual Turn Pattern")
    days = list(DEFAULT_TTP_POLICY.flying_days)
    default_first = [5, 4, 4, 3, 2]
    default_second = [2, 2, 2, 2, 0]
    default_empty_go = [0, 0, 0, 0, 0]
    cols = st.columns(len(days))
    first_go = []
    second_go = []
    third_go = []
    fourth_go = []
    for index, day in enumerate(days):
        with cols[index]:
            st.markdown(f"**{day}**")
            first_go.append(int(st.number_input(f"{day} 1st Go", min_value=0, max_value=15, value=default_first[index])))
            if go_waves >= 2:
                second_go.append(int(st.number_input(f"{day} 2nd Go", min_value=0, max_value=15, value=default_second[index])))
            else:
                second_go.append(0)
            if go_waves >= 3:
                third_go.append(int(st.number_input(f"{day} 3rd Go", min_value=0, max_value=15, value=default_empty_go[index])))
            else:
                third_go.append(0)
            if go_waves >= 4:
                fourth_go.append(int(st.number_input(f"{day} 4th Go", min_value=0, max_value=15, value=default_empty_go[index])))
            else:
                fourth_go.append(0)
    planned = sum(first_go) + sum(second_go) + sum(third_go) + sum(fourth_go)
    st.metric("Manual Planned Sorties", planned)

    if st.button("Run Manual Pattern", type="primary"):
        st.session_state["manual_result"] = run_manual_pattern(
            pai=int(pai_max),
            required_sorties=int(required_sorties) if required_sorties else planned,
            first_go=tuple(first_go),
            second_go=tuple(second_go),
            third_go=tuple(third_go),
            fourth_go=tuple(fourth_go),
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
            max_third_go=int(max_third_go),
            max_fourth_go=int(max_fourth_go),
            ute_min=float(ute_min),
            ute_max=float(ute_max),
            spare_rate=float(spare_rate),
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
        max_third_go=int(max_third_go),
        max_fourth_go=int(max_fourth_go),
        max_day_delta=int(max_day_delta),
        include_surge=bool(include_surge),
        ute_min=float(ute_min),
        ute_max=float(ute_max),
        spare_rate=float(spare_rate),
    )
    st.session_state["surge_result"] = run_surge_weeks(
        pai_min=int(pai_min),
        pai_max=int(pai_max),
        surge_weeks=int(surge_weeks),
        iterations=int(iterations),
        random_seed=int(random_seed) + 55_000,
        mc_rate=float(mc_rate),
        ground_abort_rate=float(ground_abort_rate),
        break_rate=float(break_rate),
        fix_8hr_rate=float(fix_8hr_rate),
        fix_12hr_rate=float(fix_12hr_rate),
        fix_24hr_rate=float(fix_24hr_rate),
        event_count_model=event_count_model,
        fix_count_model=fix_count_model,
        ute_min=float(ute_min),
        ute_max=float(ute_max),
        spare_rate=float(spare_rate),
    )

result = st.session_state.get("best_fit_result")
if not result:
    st.info("Set inputs in the sidebar and run the model.")
    st.stop()
    raise SystemExit

summary, capacity, patterns, surge, diagnostics, detail = st.tabs(
    ["Summary", "Capacity Sweep", "Best Patterns", "Max Surge Weeks", "Diagnostics", "Pattern Detail"]
)
rows = result["rows"]
policy = result["policy"]
surge_rows = st.session_state.get("surge_result", [])

with summary:
    if not rows:
        st.warning("No valid patterns were generated for these inputs.")
    else:
        for pai_value in _pai_values(rows):
            pai_rows = _rows_for_pai(rows, pai_value)
            viable = _recommendable_rows(pai_rows, policy)
            recommended = max(viable, key=_rank) if viable else max(pai_rows, key=_rank)
            label = "Recommendation" if viable else "Closest Non-Recommended"

            with st.expander(f"{pai_value} PAI Decision Brief", expanded=(pai_value == _pai_values(rows)[0])):
                col1, col2, col3, col4 = st.columns(4)
                col1.metric(label, recommended["pattern_with_frontlines"])
                col2.metric("Success", f"{float(recommended['success']):.1%}")
                col3.metric("Next Mon MC", f"{float(recommended['avg_next_monday']):.1f}")
                col4.metric("Risk", recommended["risk_band"])
                if not viable:
                    st.info(
                        "This row is shown because no recommendable pattern passed the current screen for this PAI. "
                        "Treat it as the closest modeled alternative to troubleshoot, not as an execution recommendation."
                    )
                st.write(_decision_guidance(pai_value, pai_rows, policy))

                st.markdown("**Recommendable Options**")
                if viable:
                    st.dataframe(_display_rows(_top_pattern_rows(viable)), width="stretch", hide_index=True)
                else:
                    st.info("No Green/Yellow recommendable options met the current requirement and recovery rules.")

                st.markdown("**Why Candidates Were Not Recommended**")
                st.dataframe(_failure_readout_rows(pai_rows), width="stretch", hide_index=True)

with capacity:
    st.subheader("Capacity Readout")
    st.caption(
        "This is pure capacity math before Monte Carlo sustainability. Use it to see the normal planning band "
        "and keep max-commit separate from routine sustainment."
    )
    st.dataframe(_capacity_interpretation_rows(result["capacity_rows"]), width="stretch", hide_index=True)
    st.subheader("Detailed Capacity Table")
    st.dataframe(_capacity_display_rows(result["capacity_rows"]), width="stretch", hide_index=True)

with patterns:
    recommendable = _recommendable_rows(rows, policy)
    coverage_rows = result.get("family_coverage_rows", [])
    if coverage_rows:
        st.subheader("Pattern Family Coverage")
        st.caption(
            "This confirms which generated pattern families were included in the candidate set before Monte Carlo ranking."
        )
        st.dataframe(coverage_rows, width="stretch", hide_index=True)
    if recommendable:
        st.subheader("Pattern Family Comparison")
        st.caption(
            "This groups candidates by pattern family. If a family has no recommendable option, the representative "
            "pattern is the strongest near-miss from that family and is shown only for context."
        )
        st.dataframe(_pattern_family_rows(rows, policy), width="stretch", hide_index=True)

        st.subheader("Top Recommendable Pattern by UTE")
        st.caption("One top-scoring pattern per PAI and UTE point after the recommendation screen.")
        best_by_ute = _best_by_ute_rows(rows, policy)
        st.dataframe(_display_rows(best_by_ute), width="stretch", hide_index=True)

        st.subheader("All Recommendable Pattern Candidates")
        st.caption("These patterns passed the success, recovery, backlog, commit, and operational-shape screens.")
        st.dataframe(_display_rows(recommendable), width="stretch", hide_index=True)
    else:
        st.warning("No recommendable patterns were found under the current assumptions.")
        st.subheader("Pattern Family Near-Miss Readout")
        st.caption("These are representative near-miss candidates by family; they are not recommended for execution.")
        st.dataframe(_pattern_family_rows(rows, policy), width="stretch", hide_index=True)

with surge:
    st.info(
        "Read this tab as a stress test, not a normal weekly plan. Week 1 asks whether max commit is executable now; "
        "later weeks show whether recovery, backlog, or maintenance stress makes that posture unsustainable."
    )
    if surge_rows:
        st.subheader("Surge Sustainability Summary")
        st.caption(
            "Sustained Through Week is the last consecutive week that met the surge screen: overall success, "
            "next-Monday recovery, and backlog control."
        )
        st.dataframe(_surge_summary_rows(surge_rows, policy), width="stretch", hide_index=True)

        st.subheader("Visual Trend")
        success_chart, recovery_chart = st.columns(2)
        with success_chart:
            st.caption("Overall success should stay above the Yellow threshold to remain usable.")
            st.line_chart(
                _surge_chart_rows(surge_rows, "Overall Success"),
                x="Week",
                y="Overall Success",
                color="Series",
            )
        with recovery_chart:
            st.caption("Next-Monday recovery shows whether the fleet can reset for another week.")
            st.line_chart(
                _surge_chart_rows(surge_rows, "Next-Monday Recovery"),
                x="Week",
                y="Next-Monday Recovery",
                color="Series",
            )

        st.subheader("Why It Fails or Passes")
        st.caption(
            "This isolates the first unacceptable week for each PAI and recovery model. If no week fails, "
            "the weakest modeled week is shown as a watch item."
        )
        st.dataframe(_surge_failure_rows(surge_rows, policy), width="stretch", hide_index=True)

        st.subheader("Week-by-Week Detail")
        st.caption(
            "Max surge uses true max-commit front-line scheduling: committed aircraft x flying days. "
            "Weeks 2-5 apply increasing break stress and reduced fix effectiveness."
        )
        st.dataframe(_surge_display_rows(surge_rows), width="stretch", hide_index=True)
    else:
        st.info("Run the model to calculate max-commit surge weeks.")

with diagnostics:
    st.caption("All tested family-level candidates, including patterns rejected from the Best Patterns tab.")
    st.info(
        "Closest Non-Recommended Pattern is the strongest near-miss candidate for that PAI. "
        "It is shown for troubleshooting and planning context, not as a recommendation. "
        "Use the reason column to see whether it missed because of sortie success, recovery, backlog, "
        "or the operational-shape screen."
    )
    st.subheader("Candidate Pass/Reject Summary")
    st.dataframe(_diagnostic_pai_rows(rows, policy), width="stretch", hide_index=True)

    failures = _failure_mode_rows(rows, policy)
    if failures:
        st.subheader("Not-Recommended Reason Readout")
        st.caption("This shows why candidates were screened out. High counts indicate the active limiting factor.")
        st.dataframe(failures, width="stretch", hide_index=True)
    else:
        st.success("No rejected candidates under the current recommendation screen.")

    st.subheader("All Candidate Details")
    st.caption("This includes recommendable and non-recommended candidates. Use Recommendation Screen before treating a row as viable.")
    st.dataframe(_display_rows(rows), width="stretch", hide_index=True)

with detail:
    if rows:
        options = {
            (
                f"{_recommendation_status(row, policy)} | {row['pai']} PAI | {row['capacity_label']} | "
                f"{row['model']} | {row['pattern_with_frontlines']} | {float(row['success']):.0%}"
            ): row
            for row in rows
        }
        selected = options[st.selectbox("Selected Pattern", list(options))]
        st.subheader("Selected Pattern Diagnostic")
        diag_col, schedule_col = st.columns(2)
        with diag_col:
            st.caption("Component probabilities show which success dimension is carrying or limiting the pattern.")
            st.dataframe(
                [
                    {"Metric": row["Metric"], "Probability": _pct(float(row["Probability"]))}
                    for row in _detail_probability_rows(selected)
                ],
                width="stretch",
                hide_index=True,
            )
        with schedule_col:
            st.caption("Daily sortie shape shows how much pressure is being placed on each day.")
            st.bar_chart(_detail_daily_sortie_rows(selected, policy), x="Day", y="Daily Sorties")

        st.subheader("Selected Pattern Metrics")
        st.dataframe(_detail_rows(selected), width="stretch", hide_index=True)

        st.subheader("Recovery Model Comparison")
        st.caption("Reruns the selected pattern under both recovery assumptions using the current sidebar inputs.")
        if st.button("Compare Recovery Models for Selected Pattern"):
            comparison = run_manual_pattern(
                pai=int(selected["pai"]),
                required_sorties=int(selected["required_sorties"]),
                first_go=tuple(int(value) for value in selected["first_go_sequence"]),
                second_go=tuple(int(value) for value in selected["turn_sequence"]),
                third_go=tuple(int(value) for value in selected.get("third_go_sequence", [0, 0, 0, 0, 0])),
                fourth_go=tuple(int(value) for value in selected.get("fourth_go_sequence", [0, 0, 0, 0, 0])),
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
                max_third_go=int(max_third_go),
                max_fourth_go=int(max_fourth_go),
                ute_min=float(ute_min),
                ute_max=float(ute_max),
                spare_rate=float(spare_rate),
            )
            st.session_state["detail_recovery_comparison"] = comparison

        comparison = st.session_state.get("detail_recovery_comparison")
        if comparison:
            st.dataframe(_recovery_delta_rows(comparison["summaries"]), width="stretch", hide_index=True)
