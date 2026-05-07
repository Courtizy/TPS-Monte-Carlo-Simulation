from __future__ import annotations

from collections import Counter
from dataclasses import replace
from html import escape
from pathlib import Path

from example_run import build_model_scenarios, get_turn_pattern_inputs
from turn_pattern_modeler import FLYING_DAYS, DaySchedule, Scenario, SimulationSummary, compare_turn_patterns, simulate


OUTPUT_DIR = Path("analysis_output")
REPORT_PATH = OUTPUT_DIR / "report.html"
TARGET_UTE_RATE = 0.40
ACCEPTABLE_UTE_MAX = 0.52
FLEET_SWEEP_MIN = 1
FLEET_SWEEP_MAX = 15
FLEET_SWEEP_ITERATIONS = 1_000
SUSTAINABLE_SUCCESS_THRESHOLD = 0.90
SENSITIVITY_ITERATIONS = 2_500
SENSITIVITY_SWING = 0.10
SENSITIVITY_PARAMETERS = (
    ("mc_rate", "MC Rate"),
    ("ground_abort_rate", "Ground Abort Rate"),
    ("break_rate", "Break Rate"),
    ("fix_8hr_rate", "8 Hr Fix Rate"),
    ("fix_12hr_rate", "12 Hr Fix Rate"),
    ("fix_24hr_rate", "24 Hr Fix Rate"),
    ("ttp_commit_rate", "TTP Commit Rate"),
    ("afi_spare_rate", "AFI Spare Rate"),
)


def main() -> None:
    turn_pattern_inputs = get_turn_pattern_inputs()
    strict_scenarios = build_model_scenarios(
        turn_pattern_inputs,
        use_uncommitted_aircraft_for_ga_recovery=False,
    )
    non_strict_scenarios = build_model_scenarios(
        turn_pattern_inputs,
        use_uncommitted_aircraft_for_ga_recovery=True,
    )

    strict = compare_turn_patterns(strict_scenarios, iterations=10_000, seed=7)
    non_strict = compare_turn_patterns(non_strict_scenarios, iterations=10_000, seed=7)
    strict_sensitivity = run_sensitivity(strict_scenarios, seed=71)
    non_strict_sensitivity = run_sensitivity(non_strict_scenarios, seed=72)
    fleet_rows = build_fleet_ute_sweep(next(iter(strict_scenarios.values())))

    OUTPUT_DIR.mkdir(exist_ok=True)
    REPORT_PATH.write_text(
        build_report(strict, non_strict, strict_sensitivity, non_strict_sensitivity, fleet_rows),
        encoding="utf-8",
    )
    print(f"Wrote analysis report to {REPORT_PATH}")


def build_report(
    strict: dict[str, SimulationSummary],
    non_strict: dict[str, SimulationSummary],
    strict_sensitivity: list[dict[str, object]],
    non_strict_sensitivity: list[dict[str, object]],
    fleet_rows: list[dict[str, object]],
) -> str:
    best_strict_name, best_strict = _best_summary(strict)
    best_non_strict_name, best_non_strict = _best_summary(non_strict)
    sections = [
        "<h1>Turn Pattern Sustainability Analysis</h1>",
        '<div class="note"><p>This report compares strict and non-strict ground-abort recovery models. Strict only uses scheduled spares. Non-strict also allows uncommitted MC aircraft to recover ground aborts.</p></div>',
        _recommendation_block(best_strict_name, best_strict, best_non_strict_name, best_non_strict, strict_sensitivity, non_strict_sensitivity),
        "<h2>UTE Planning Reference</h2>",
        _ute_reference(best_strict),
        "<h2>Fleet UTE Action Table</h2>",
        _fleet_decision_summary(fleet_rows),
        _fleet_action_table(fleet_rows),
        "<h2>Named Pattern Comparison</h2>",
        _paired_pattern_table(strict, non_strict),
        _success_chart(strict, non_strict),
        "<h2>Why Patterns Fail</h2>",
        _failure_mode_chart(strict, "Strict Failure Modes"),
        _failure_mode_chart(non_strict, "Non-Strict Failure Modes"),
        "<h2>Sensitivity Drivers</h2>",
        "<h3>Strict</h3>",
        _sensitivity_table(strict_sensitivity),
        "<h3>Non-Strict</h3>",
        _sensitivity_table(non_strict_sensitivity),
        "<h2>Diagnostics</h2>",
        _summary_table(strict, "Strict Full Summary"),
        _summary_table(non_strict, "Non-Strict Full Summary"),
        _fleet_detail_table(fleet_rows),
        "<h2>Methodology</h2>",
        _methodology_box(),
    ]
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Turn Pattern Sustainability Analysis</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #172026; background: #f7f8fa; }}
h1, h2, h3 {{ margin-bottom: 8px; }}
p {{ max-width: 980px; line-height: 1.45; }}
.note, .recommendation, .methodology {{ background: white; border-left: 5px solid #3a8f78; padding: 14px 18px; margin: 12px 0 24px; max-width: 1040px; }}
.recommendation {{ border-left-color: #4d6f91; }}
.ute-band {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; max-width: 1040px; margin: 12px 0 26px; }}
.ute-box {{ background: white; border: 1px solid #d8dde3; padding: 12px; }}
.ute-box strong {{ display: block; font-size: 22px; margin-top: 4px; }}
table {{ border-collapse: collapse; background: white; margin: 12px 0 24px; min-width: 820px; }}
th, td {{ border: 1px solid #d8dde3; padding: 8px 10px; text-align: right; }}
th:first-child, td:first-child {{ text-align: left; }}
th {{ background: #e8edf3; }}
.green {{ background: #e1f2e8; }}
.yellow {{ background: #fff2cc; }}
.red {{ background: #f8d9d9; }}
.chart {{ background: white; border: 1px solid #d8dde3; margin: 12px 0 28px; padding: 12px; width: fit-content; }}
.caption {{ color: #52606d; font-size: 14px; }}
</style>
</head>
<body>
{''.join(sections)}
</body>
</html>
"""


def _recommendation_block(
    best_strict_name: str,
    best_strict: SimulationSummary,
    best_non_strict_name: str,
    best_non_strict: SimulationSummary,
    strict_sensitivity: list[dict[str, object]],
    non_strict_sensitivity: list[dict[str, object]],
) -> str:
    return (
        '<div class="recommendation">'
        "<h2>Executive Recommendation</h2>"
        f"<p><b>Strict best:</b> {escape(best_strict_name)} at {best_strict.probability_success:.2%}. <b>Read:</b> {escape(_why_pattern(best_strict))}</p>"
        f"<p><b>Non-strict best:</b> {escape(best_non_strict_name)} at {best_non_strict.probability_success:.2%}. <b>Read:</b> {escape(_why_pattern(best_non_strict))}</p>"
        f"<p><b>Top strict sensitivity:</b> {escape(_driver_text(strict_sensitivity[0] if strict_sensitivity else None))}. <b>Top non-strict sensitivity:</b> {escape(_driver_text(non_strict_sensitivity[0] if non_strict_sensitivity else None))}.</p>"
        "<p><b>Planning interpretation:</b> use strict results for sustainability without pulling extra aircraft into the schedule. Use non-strict results to understand rescue capacity and operational nuance.</p>"
        "</div>"
    )


def _ute_reference(summary: SimulationSummary) -> str:
    pai = summary.sample_iteration.days[0].pai
    target_sorties = round(pai * len(FLYING_DAYS) * TARGET_UTE_RATE)
    required_ute = summary.required_weekly_sorties / (pai * len(FLYING_DAYS))
    planned_ute = summary.planned_weekly_sorties / (pai * len(FLYING_DAYS))
    commit_limit = summary.sample_iteration.days[0].commit_limit
    max_commit_ute = commit_limit / pai
    return (
        '<div class="ute-band">'
        + _ute_box("PAI", str(pai), "Aircraft used in the UTE denominator.")
        + _ute_box("0.4 UTE Sorties", str(target_sorties), "Weekly sorties at 0.4 UTE.")
        + _ute_box("Required UTE", f"{required_ute:.2f}", f"{summary.required_weekly_sorties} required sorties.")
        + _ute_box("Planned UTE", f"{planned_ute:.2f}", f"{summary.planned_weekly_sorties} planned sorties.")
        + _ute_box("Max Commit Reference", f"{max_commit_ute:.2f}", f"{commit_limit} aircraft/day under the TTP commit rule.")
        + "</div>"
    )


def _ute_box(title: str, value: str, note: str) -> str:
    return f'<div class="ute-box"><span>{escape(title)}</span><strong>{escape(value)}</strong><p>{escape(note)}</p></div>'


def _paired_pattern_table(strict: dict[str, SimulationSummary], non_strict: dict[str, SimulationSummary]) -> str:
    rows = []
    for name in strict:
        strict_summary = strict[name]
        non_summary = non_strict[name]
        rows.append(
            "<tr>"
            f"<td>{escape(name)}</td>"
            f'<td class="{_threshold_class(strict_summary.probability_success)}">{strict_summary.probability_success:.2%}</td>'
            f'<td class="{_threshold_class(non_summary.probability_success)}">{non_summary.probability_success:.2%}</td>'
            f"<td>{strict_summary.planned_weekly_sorties}</td>"
            f"<td>{strict_summary.required_weekly_sorties}</td>"
            f"<td>{_weekly_ute(strict_summary):.2f}</td>"
            f"<td>{strict_summary.planned_attrition}</td>"
            f"<td>{strict_summary.average_actual_attrition:.2f}</td>"
            f"<td>{non_summary.average_actual_attrition:.2f}</td>"
            f"<td>{strict_summary.average_next_monday_available:.1f}</td>"
            f"<td>{non_summary.average_next_monday_available:.1f}</td>"
            f"<td>{escape(_top_failure_mode(strict_summary))}</td>"
            f"<td>{escape(_top_failure_mode(non_summary))}</td>"
            "</tr>"
        )
    return (
        "<table><tr><th>Pattern</th><th>Strict Success</th><th>Non-Strict Success</th><th>Planned</th><th>Required</th><th>UTE</th><th>Planned Attrition</th><th>Strict Avg Attrition</th><th>Non-Strict Avg Attrition</th><th>Strict Next Mon</th><th>Non-Strict Next Mon</th><th>Strict Top Failure</th><th>Non-Strict Top Failure</th></tr>"
        + "".join(rows)
        + "</table>"
    )


def build_fleet_ute_sweep(template: Scenario) -> list[dict[str, object]]:
    rows = []
    planned_attrition_allowance = max(0, sum(template.schedule[day].daily_sorties for day in FLYING_DAYS) - template.total_required_sorties)
    for pai in range(FLEET_SWEEP_MIN, FLEET_SWEEP_MAX + 1):
        commit_limit = max(1, round(pai * template.homestation.ttp_commit_rate))
        target_sorties = int(pai * len(FLYING_DAYS) * TARGET_UTE_RATE)
        acceptable_sorties = max(target_sorties, int(pai * len(FLYING_DAYS) * ACCEPTABLE_UTE_MAX))
        max_commit_sorties = max(acceptable_sorties, commit_limit * len(FLYING_DAYS))
        best_band_strict = _find_best_sustainable_pattern(template, pai, target_sorties, acceptable_sorties, commit_limit, planned_attrition_allowance, False, 50_000 + pai * 100)
        best_band_non_strict = _find_best_sustainable_pattern(template, pai, target_sorties, acceptable_sorties, commit_limit, planned_attrition_allowance, True, 60_000 + pai * 100)
        best_strict = _find_best_sustainable_pattern(template, pai, target_sorties, max_commit_sorties, commit_limit, planned_attrition_allowance, False, 70_000 + pai * 100)
        best_non_strict = _find_best_sustainable_pattern(template, pai, target_sorties, max_commit_sorties, commit_limit, planned_attrition_allowance, True, 80_000 + pai * 100)
        rows.append({
            "pai": pai,
            "target_sorties": target_sorties,
            "acceptable_sorties": acceptable_sorties,
            "required_sorties": template.total_required_sorties,
            "commit_limit": commit_limit,
            "commit_percent": commit_limit / pai,
            "best_band_strict": best_band_strict,
            "best_band_non_strict": best_band_non_strict,
            "best_strict": best_strict,
            "best_non_strict": best_non_strict,
        })
    return rows


def _find_best_sustainable_pattern(template: Scenario, pai: int, min_sorties: int, max_sorties: int, commit_limit: int, planned_attrition_allowance: int, use_uncommitted_aircraft_for_ga_recovery: bool, seed: int) -> dict[str, object]:
    best_row: dict[str, object] | None = None
    best_success_row: dict[str, object] | None = None
    for offset, sorties in enumerate(range(min_sorties, max_sorties + 1)):
        schedule = _balanced_schedule(sorties, commit_limit)
        summary = _evaluate_fleet_pattern(template, pai, schedule, planned_attrition_allowance, use_uncommitted_aircraft_for_ga_recovery, seed + offset)
        row = {"sorties": sorties, "ute": _ute_for_sorties(sorties, pai), "pattern": _schedule_label(schedule), "success": summary.probability_success}
        if best_success_row is None or row["success"] > best_success_row["success"]:
            best_success_row = row
        if row["success"] >= SUSTAINABLE_SUCCESS_THRESHOLD:
            best_row = row
    return best_row or best_success_row or {"sorties": 0, "ute": 0.0, "pattern": "No pattern", "success": 0.0}


def _evaluate_fleet_pattern(template: Scenario, pai: int, schedule: dict[str, DaySchedule], planned_attrition_allowance: int, use_uncommitted_aircraft_for_ga_recovery: bool, seed: int) -> SimulationSummary:
    planned_sorties = sum(schedule[day].daily_sorties for day in FLYING_DAYS)
    scenario = replace(
        template,
        inventory=replace(template.inventory, paa=pai, pai=pai),
        homestation=replace(template.homestation, use_uncommitted_aircraft_for_ga_recovery=use_uncommitted_aircraft_for_ga_recovery),
        schedule=schedule,
        total_required_sorties=max(1, planned_sorties - planned_attrition_allowance),
    )
    return simulate(scenario, iterations=FLEET_SWEEP_ITERATIONS, seed=seed)


def _fleet_decision_summary(rows: list[dict[str, object]]) -> str:
    return (
        '<div class="ute-band">'
        + _ute_box("Strict In Band", _minimum_pai_text(_minimum_pai_for(rows, "best_band_strict")), "Meets requirement inside the acceptable UTE band using strict sustainability.")
        + _ute_box("Non-Strict In Band", _minimum_pai_text(_minimum_pai_for(rows, "best_band_non_strict")), "Meets requirement inside the acceptable UTE band using non-strict recovery.")
        + _ute_box("Strict To Max", _minimum_pai_text(_minimum_pai_for(rows, "best_strict")), "Meets requirement up to the max-commit reference using strict sustainability.")
        + _ute_box("Non-Strict To Max", _minimum_pai_text(_minimum_pai_for(rows, "best_non_strict")), "Most permissive planning view.")
        + "</div>"
    )


def _fleet_action_table(rows: list[dict[str, object]]) -> str:
    body = []
    for row in rows:
        action = _fleet_action(row)
        body.append(
            "<tr>"
            f"<td>{row['pai']}</td><td>{row['target_sorties']}</td><td>{row['acceptable_sorties']}</td><td>{row['required_sorties']}</td>"
            f"<td>{action['sorties']}</td><td>{action['ute']:.2f}</td>"
            f'<td class="{_threshold_class(action["success"])}">{action["success"]:.0%}</td>'
            f"<td>{action['margin']:+d}</td><td>{escape(action['model'])}</td><td>{escape(action['recommendation'])}</td><td>{escape(action['risk'])}</td>"
            "</tr>"
        )
    return "<table><tr><th>PAI</th><th>0.4 Sorties</th><th>0.52 Sorties</th><th>Required</th><th>Recommended Sorties</th><th>UTE</th><th>Success</th><th>Margin</th><th>Model Basis</th><th>Recommendation</th><th>Risk</th></tr>" + "".join(body) + "</table>"


def _fleet_detail_table(rows: list[dict[str, object]]) -> str:
    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<td>{row['pai']}</td><td>{row['commit_limit']}</td><td>{row['commit_percent']:.0%}</td>"
            f"<td>{escape(str(row['best_band_strict']['pattern']))}</td><td>{row['best_band_strict']['success']:.0%}</td>"
            f"<td>{escape(str(row['best_band_non_strict']['pattern']))}</td><td>{row['best_band_non_strict']['success']:.0%}</td>"
            f"<td>{escape(str(row['best_strict']['pattern']))}</td><td>{row['best_strict']['success']:.0%}</td>"
            f"<td>{escape(str(row['best_non_strict']['pattern']))}</td><td>{row['best_non_strict']['success']:.0%}</td>"
            "</tr>"
        )
    return "<table><tr><th>PAI</th><th>Commit Acft</th><th>Commit %</th><th>Best Strict Band Pattern</th><th>Success</th><th>Best Non-Strict Band Pattern</th><th>Success</th><th>Best Strict To Max Pattern</th><th>Success</th><th>Best Non-Strict To Max Pattern</th><th>Success</th></tr>" + "".join(body) + "</table>"


def _fleet_action(row: dict[str, object]) -> dict[str, object]:
    required = int(row["required_sorties"])
    options = [
        ("Strict, in UTE band", row["best_band_strict"], "Plan in acceptable UTE band using strict sustainability."),
        ("Non-strict, in UTE band", row["best_band_non_strict"], "Plan in acceptable UTE band, but depends on uncommitted MC aircraft recovery."),
        ("Strict, to max commit", row["best_strict"], "Requirement may require operating above the acceptable UTE band."),
        ("Non-strict, to max commit", row["best_non_strict"], "Requirement may require above-band UTE and non-strict recovery."),
    ]
    for model, candidate, recommendation in options:
        if candidate["success"] >= SUSTAINABLE_SUCCESS_THRESHOLD and candidate["sorties"] >= required:
            return {"sorties": candidate["sorties"], "ute": candidate["ute"], "success": candidate["success"], "margin": candidate["sorties"] - required, "model": model, "recommendation": recommendation, "risk": _fleet_risk_note(candidate, required)}
    model, candidate, _recommendation = max(options, key=lambda option: (option[1]["success"], option[1]["sorties"]))
    return {"sorties": candidate["sorties"], "ute": candidate["ute"], "success": candidate["success"], "margin": candidate["sorties"] - required, "model": model, "recommendation": "Does not meet the current requirement at the sustainability threshold.", "risk": _fleet_risk_note(candidate, required)}


def _fleet_risk_note(candidate: dict[str, object], required: int) -> str:
    if candidate["sorties"] < required:
        return "Insufficient weekly sortie capacity."
    if candidate["success"] < SUSTAINABLE_SUCCESS_THRESHOLD:
        return "Below success threshold."
    if candidate["ute"] > ACCEPTABLE_UTE_MAX:
        return "Above acceptable UTE band."
    return "Inside acceptable UTE band."


def _minimum_pai_for(rows: list[dict[str, object]], key: str) -> dict[str, object] | None:
    for row in rows:
        candidate = row[key]
        if candidate["sorties"] >= row["required_sorties"] and candidate["success"] >= SUSTAINABLE_SUCCESS_THRESHOLD:
            return {"pai": row["pai"], "sorties": candidate["sorties"], "ute": candidate["ute"], "success": candidate["success"]}
    return None


def _minimum_pai_text(row: dict[str, object] | None) -> str:
    if row is None:
        return "None"
    return f"{row['pai']} PAI, {row['sorties']} sorties, {row['ute']:.2f} UTE, {row['success']:.0%}"


def _balanced_schedule(weekly_sorties: int, commit_limit: int) -> dict[str, DaySchedule]:
    daily_totals = _balanced_daily_totals(weekly_sorties)
    return {day: DaySchedule(first_go=min(total, commit_limit), second_go=max(0, total - min(total, commit_limit))) for day, total in zip(FLYING_DAYS, daily_totals)}


def _balanced_daily_totals(weekly_sorties: int) -> list[int]:
    base = weekly_sorties // len(FLYING_DAYS)
    extra = weekly_sorties % len(FLYING_DAYS)
    return [base + (1 if index < extra else 0) for index in range(len(FLYING_DAYS))]


def _schedule_label(schedule: dict[str, DaySchedule]) -> str:
    return "-".join(f"{schedule[day].daily_sorties}({schedule[day].first_go})" for day in FLYING_DAYS)


def _ute_for_sorties(sorties: int, pai: int) -> float:
    return sorties / (pai * len(FLYING_DAYS)) if pai else 0.0


def run_sensitivity(scenarios: dict[str, Scenario], seed: int) -> list[dict[str, object]]:
    rows = []
    for scenario_index, (pattern_name, scenario) in enumerate(scenarios.items()):
        baseline = simulate(scenario, iterations=SENSITIVITY_ITERATIONS, seed=seed + scenario_index * 1000)
        for parameter_index, (field_name, label) in enumerate(SENSITIVITY_PARAMETERS):
            low = simulate(_perturb_scenario(scenario, field_name, 1 - SENSITIVITY_SWING), iterations=SENSITIVITY_ITERATIONS, seed=seed + scenario_index * 1000 + parameter_index * 20 + 1)
            high = simulate(_perturb_scenario(scenario, field_name, 1 + SENSITIVITY_SWING), iterations=SENSITIVITY_ITERATIONS, seed=seed + scenario_index * 1000 + parameter_index * 20 + 2)
            low_delta = low.probability_success - baseline.probability_success
            high_delta = high.probability_success - baseline.probability_success
            rows.append({"pattern": pattern_name, "parameter": label, "baseline": baseline.probability_success, "low": low.probability_success, "high": high.probability_success, "low_delta": low_delta, "high_delta": high_delta, "swing": max(abs(low_delta), abs(high_delta))})
    return sorted(rows, key=lambda row: row["swing"], reverse=True)


def _perturb_scenario(scenario: Scenario, field_name: str, multiplier: float) -> Scenario:
    current_value = getattr(scenario.homestation, field_name)
    new_value = min(1.0, max(0.0, current_value * multiplier))
    return replace(scenario, homestation=replace(scenario.homestation, **{field_name: new_value}))


def _sensitivity_table(rows: list[dict[str, object]]) -> str:
    body = []
    for row in rows[:12]:
        body.append(f"<tr><td>{escape(str(row['pattern']))}</td><td>{escape(str(row['parameter']))}</td><td>{row['baseline']:.2%}</td><td>{row['low']:.2%}</td><td>{row['high']:.2%}</td><td>{row['low_delta']:+.2%}</td><td>{row['high_delta']:+.2%}</td></tr>")
    return "<table><tr><th>Pattern</th><th>Input</th><th>Baseline</th><th>-10%</th><th>+10%</th><th>-10% Delta</th><th>+10% Delta</th></tr>" + "".join(body) + "</table>"


def _summary_table(summaries: dict[str, SimulationSummary], title: str) -> str:
    rows = []
    for name, summary in sorted(summaries.items(), key=lambda item: item[1].probability_success, reverse=True):
        rows.append(
            f"<tr><td>{escape(name)}</td><td class='{_threshold_class(summary.probability_success)}'>{summary.probability_success:.2%}</td><td>{summary.probability_meet_sorties:.2%}</td><td>{summary.probability_meet_aircraft_required:.2%}</td><td>{summary.probability_within_ttp_commit:.2%}</td><td>{_weekly_ute(summary):.2f}</td><td>{summary.planned_weekly_sorties}</td><td>{summary.required_weekly_sorties}</td><td>{summary.planned_attrition}</td><td>{summary.average_actual_attrition:.2f}</td><td>{summary.average_next_monday_available:.1f}</td><td>{escape(_top_failure_mode(summary))}</td></tr>"
        )
    return f"<h3>{escape(title)}</h3><table><tr><th>Pattern</th><th>Success</th><th>Sorties</th><th>Aircraft</th><th>Commit</th><th>UTE</th><th>Planned</th><th>Required</th><th>Planned Attrition</th><th>Avg Attrition</th><th>Avg Next Mon</th><th>Top Failure</th></tr>{''.join(rows)}</table>"


def _success_chart(strict: dict[str, SimulationSummary], non_strict: dict[str, SimulationSummary]) -> str:
    labels = []
    values = []
    for name in strict:
        labels.extend([f"{name} Strict", f"{name} Non-Strict"])
        values.extend([strict[name].probability_success * 100, non_strict[name].probability_success * 100])
    return _bar_chart(labels, values, "Overall Success Probability", "%")


def _failure_mode_chart(summaries: dict[str, SimulationSummary], title: str) -> str:
    counts: Counter[str] = Counter()
    for summary in summaries.values():
        counts.update(summary.failure_mode_counts)
    labels = list(counts.keys()) or ["No Failures"]
    values = [counts[label] for label in labels] or [0]
    return _bar_chart(labels, values, title, "iterations")


def _bar_chart(labels: list[str], values: list[float], title: str, unit: str) -> str:
    width = 980
    height = 360
    margin_left = 56
    margin_bottom = 120
    margin_top = 42
    plot_width = width - margin_left - 24
    plot_height = height - margin_top - margin_bottom
    max_value = max(max(values), 1) if values else 1
    bar_gap = 8
    bar_width = max(12, (plot_width - bar_gap * (len(values) - 1)) / max(len(values), 1))
    bars = []
    for index, value in enumerate(values):
        x = margin_left + index * (bar_width + bar_gap)
        bar_height = (value / max_value) * plot_height if max_value else 0
        y = margin_top + plot_height - bar_height
        label = escape(labels[index])
        value_label = f"{value:.1f}" if isinstance(value, float) and value % 1 else f"{int(value)}"
        bars.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" height="{bar_height:.1f}" fill="#4d6f91"></rect><text x="{x + bar_width / 2:.1f}" y="{y - 5:.1f}" text-anchor="middle" font-size="11">{value_label}</text><text transform="translate({x + bar_width / 2:.1f},{height - margin_bottom + 18}) rotate(55)" text-anchor="start" font-size="11">{label}</text>')
    return f'<div class="chart"><svg width="{width}" height="{height}" role="img" aria-label="{escape(title)}"><text x="{width / 2:.1f}" y="22" text-anchor="middle" font-size="16" font-weight="700">{escape(title)}</text><text x="8" y="{margin_top + plot_height / 2:.1f}" transform="rotate(-90 8,{margin_top + plot_height / 2:.1f})" text-anchor="middle" font-size="12">{escape(unit)}</text><line x1="{margin_left}" y1="{margin_top + plot_height}" x2="{width - 16}" y2="{margin_top + plot_height}" stroke="#6f7a85"></line><line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{margin_top + plot_height}" stroke="#6f7a85"></line>{''.join(bars)}</svg></div>'


def _methodology_box() -> str:
    return '<div class="methodology"><p><b>Simulation setup:</b> named-pattern comparisons use 10,000 Monte Carlo iterations. Sensitivity analysis uses 2,500 iterations per input swing. Fleet sweep uses 1,000 iterations per candidate.</p><p><b>Strict model:</b> only scheduled spares can recover ground aborts. <b>Non-strict model:</b> scheduled spares plus uncommitted MC aircraft can recover ground aborts.</p><p><b>Current limitations:</b> this is a day-level model. It does not yet include crews, fuels, weapons, phase inspections, parts, or maintenance shift capacity.</p></div>'


def _best_summary(summaries: dict[str, SimulationSummary]) -> tuple[str, SimulationSummary]:
    return max(summaries.items(), key=lambda item: item[1].probability_success)


def _weekly_ute(summary: SimulationSummary) -> float:
    pai = summary.sample_iteration.days[0].pai if summary.sample_iteration.days else 0
    return summary.planned_weekly_sorties / (pai * len(FLYING_DAYS)) if pai else 0.0


def _top_failure_mode(summary: SimulationSummary) -> str:
    if not summary.failure_mode_counts:
        return "No Failures"
    mode, count = max(summary.failure_mode_counts.items(), key=lambda item: item[1])
    return f"{mode} ({count})"


def _threshold_class(probability: float) -> str:
    if probability >= 0.90:
        return "green"
    if probability >= 0.70:
        return "yellow"
    return "red"


def _why_pattern(summary: SimulationSummary) -> str:
    if summary.probability_success >= 0.90:
        return "Actual attrition usually stays inside the planned attrition allowance, so the pattern meets the required weekly sorties."
    top_mode = _top_failure_mode(summary)
    if "Sortie Shortfall" in top_mode:
        return "The pattern fails primarily because actual sortie attrition exceeds the planned attrition allowance."
    if "Aircraft Availability" in top_mode:
        return "The pattern fails primarily because available MC aircraft fall below the committed daily requirement."
    if "TTP Commit" in top_mode:
        return "The pattern fails primarily because committed aircraft exceed the TTP commit limit."
    if "Repair Backlog" in top_mode:
        return "The pattern fails primarily because aircraft do not recover fast enough by the end of the week."
    return "The pattern has mixed failure behavior and should be reviewed against the detailed distributions."


def _driver_text(row: dict[str, object] | None) -> str:
    if not row:
        return "No sensitivity driver"
    return f"{row['pattern']} / {row['parameter']} (max swing {row['swing']:.2%})"


if __name__ == "__main__":
    main()
