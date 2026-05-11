from __future__ import annotations

from collections import Counter
from dataclasses import replace
from pathlib import Path

from optimizer import (
    FLEET_FLEX_MODEL,
    OptimizationConfig,
    SCHEDULED_SPARES_MODEL,
    base_optimizer_scenario,
    best_by_family,
    best_by_requirement,
    family_rollup,
    optimize_turn_patterns,
)
from input_validation import validate_optimizer_config
from pattern_generator import PatternConstraints, capacity_points, planning_ute_levels
from recommendation_engine import add_recommendations
from report_utils import bar_chart, cards, probability_class, table, write_report
from surge_model import simulate_surge_duration
from ttp_rules import DEFAULT_TTP_POLICY, floor_count, risk_band


REPORT_PATH = Path("analysis_output/report.html")
REPORT_POLICY = DEFAULT_TTP_POLICY
SUCCESS_THRESHOLD = REPORT_POLICY.green_success_threshold
REPORT_ITERATIONS = 25
SURGE_ITERATIONS = 120
MAX_SURGE_WEEKS = 6
ATTRITION_SCENARIOS = (
    ("Requirement Based", 0.0),
    ("Low Attrition", 0.10),
    ("Planning Attrition", 0.15),
    ("High Attrition", 0.20),
)


def main() -> None:
    config = OptimizationConfig(
        policy=REPORT_POLICY,
        iterations=REPORT_ITERATIONS,
        success_threshold=SUCCESS_THRESHOLD,
        required_weekly_sorties=None,
        planned_attrition_rate=None,
        attrition_scenarios=ATTRITION_SCENARIOS,
        event_count_models=("Normal TTP", "Probabilistic Monte Carlo"),
        fix_count_models=("Normal TTP", "Probabilistic Monte Carlo"),
        max_patterns_per_requirement=80,
        constraints=PatternConstraints.from_policy(
            replace(REPORT_POLICY, max_daily_sorties=8, max_day_to_day_delta=2, max_second_go=3)
        ),
    )
    rows = add_recommendations(optimize_turn_patterns(config), config.policy)
    best_rows = add_recommendations(best_by_requirement(rows), config.policy)
    family_rows = add_recommendations(best_by_family(rows), config.policy)
    surge = _run_surge(best_rows)
    write_report(
        REPORT_PATH,
        "Turn Pattern Optimization Report",
        build_report(rows, best_rows, family_rows, surge, config),
    )


def build_report(
    rows: list[dict[str, object]],
    best_rows: list[dict[str, object]],
    family_rows: list[dict[str, object]],
    surge,
    config: OptimizationConfig,
) -> list[str]:
    planning_rows = _planning_rows(rows)
    planning_best_rows = _planning_rows(best_rows)
    planning_family_rows = _planning_rows(family_rows)
    default_attrition = "Planning Attrition"
    default_event_count_model = "Normal TTP"
    default_fix_count_model = "Normal TTP"
    default_planning_rows = [
        row
        for row in planning_rows
        if row["attrition_scenario"] == default_attrition
        and row["event_count_model"] == default_event_count_model
        and row["fix_count_model"] == default_fix_count_model
    ]
    if not default_planning_rows:
        default_planning_rows = planning_rows
    successful = [
        row
        for row in planning_rows
        if row["success"] >= config.success_threshold and row["sortie_margin"] >= 0
    ]
    best_overall = max(
        default_planning_rows,
        key=lambda row: (
            row["success"],
            row["sortie_margin"] >= 0,
            row["composite_score"],
            -row["recovery_debt"],
        ),
    )
    highest_output = max(
        (
            row
            for row in default_planning_rows
            if row["risk_band"] in ("Green", "Yellow") and row["sortie_margin"] >= 0
        ),
        key=lambda row: (row["weekly_sorties"], row["success"]),
        default=best_overall,
    )
    min_pai = min((row["pai"] for row in successful), default="None")

    return [
        "<h1>Turn Pattern Optimization Report</h1>",
        '<div class="recommendation"><h2>Decision Flow</h2>'
        "<p>This report starts with PAI/UTE capacity, then tests generated Monday-Friday "
        "turn-pattern permutations inside the 0.40-0.52 UTE planning band. Weekly planned "
        "sorties scale with PAI and UTE; required sortie success is based on actual sorties "
        "flown versus the required weekly target. Attrition buffers are optional planning "
        "assumptions and are reported separately. Max-commit is held separate for surge duration only.</p></div>",
        _filters(config),
        _assumption_quality(config),
        _best_fit_callout(),
        cards(
            [
                ("Planning Runs Tested", f"{len(planning_rows):,}", "0.40-0.52 UTE only, both event-count methods."),
                ("Successful Runs", f"{len(successful):,}", f">= {config.success_threshold:.0%} success."),
                ("Attrition Modes", str(len(config.attrition_scenarios)), "Requirement-based plus optional 10%, 15%, and 20% planning buffers."),
                ("Event Count Methods", str(len(config.event_count_models)), "Normal TTP and probabilistic Monte Carlo."),
                ("Fix Count Methods", str(len(config.fix_count_models)), "Normal TTP and probabilistic Monte Carlo."),
                ("Best Planning Pattern", str(best_overall["pattern_signature"]), str(best_overall["pattern_name"])),
                ("Highest Green/Yellow Output", f"{highest_output['weekly_sorties']} sorties", f"{highest_output['pai']} PAI, {highest_output['ute']:.2f} UTE."),
            ]
        ),
        _collapsible_section("Capacity Sweep by PAI", _capacity_table(config)),
        _collapsible_section(
            "Primary Ranked Output",
            "<p>One best-fit planning pattern is shown for each PAI, UTE point, and model type. Max-commit surge rows are intentionally excluded here. Success is shown as the average Monte Carlo success rate, with standard deviation and observed iteration range to show volatility.</p>",
            '<div class="note"><strong>Thu/Fri human-factor preference:</strong> Best-fit scoring now penalizes backend-heavy patterns and rewards Friday-recovery patterns. Thursday and Friday load is still allowed when needed, but the optimizer will not prefer it solely because weekend recovery makes the math easier.</div>',
            _best_fit_table(planning_best_rows),
        ),
        _collapsible_section(
            "Best Sustainable UTE by PAI",
            _best_sustainable_ute_table(planning_best_rows, config.success_threshold),
        ),
        _collapsible_section(
            "Attrition Scenario Comparison",
            _attrition_comparison_table(planning_best_rows, config.success_threshold),
        ),
        _collapsible_section("Recovery Model Comparison", _recovery_model_comparison_table(planning_best_rows)),
        _collapsible_section(
            "Pattern Family Discovery",
            "<p>Pattern families are generated only from schedules that satisfy the TTP aircraft commit rule. A value like 8(6) means 8 total daily sorties using 6 front-line aircraft, with the additional sorties coming from turns.</p>",
            _family_comparison_table(family_rollup(planning_rows)),
            _family_success_chart(planning_rows),
            _family_recovery_chart(planning_rows),
        ),
        _collapsible_section("Discovery Highlights", _discovery_tables(planning_rows)),
        _collapsible_section(
            "Max-Commit Surge Duration",
            "<p>This section uses the 55% commit surge case. It estimates how long the selected surge pattern can continue before success probability degrades. Surge weeks accumulate deferred-maintenance debt, increase event pressure, and reduce fix effectiveness over time. The schedule is still forced to true max-commit front-line demand, but the recovery model allows available uncommitted MC aircraft to cover ground aborts when the fleet has enough aircraft.</p>",
            _surge_table(surge),
            _surge_chart(surge),
        ),
        _collapsible_section(
            "Detailed Pattern Diagnostics",
            "<h3>Best Pattern Per Family And Requirement</h3>",
            _best_fit_table(planning_family_rows[:250]),
            "<h3>All Best-Fit Requirement Rows</h3>",
            _best_fit_table(planning_best_rows),
        ),
    ]


def _planning_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [row for row in rows if row["capacity_label"] != REPORT_POLICY.surge_label]


def _collapsible_section(title: str, *content: str, open_by_default: bool = False) -> str:
    open_attr = " open" if open_by_default else ""
    return f'<details{open_attr}><summary>{title}</summary>{"".join(content)}</details>'


def _assumption_quality(config: OptimizationConfig) -> str:
    result = validate_optimizer_config(config)
    if result.is_valid and not result.warnings:
        return '<div class="note"><strong>Assumption quality:</strong> No optimizer input warnings detected.</div>'
    items = "".join(f"<li>{item}</li>" for item in (*result.errors, *result.warnings))
    heading = "Input errors detected" if result.errors else "Assumption warnings"
    return f'<div class="note"><strong>{heading}:</strong><ul>{items}</ul></div>'


def _filters(config: OptimizationConfig) -> str:
    options = '<option value="all">All PAI</option>' + "".join(
        f'<option value="{pai}">{pai} PAI</option>' for pai in range(1, 16)
    )
    attrition_options = '<option value="all">All Attrition</option>' + "".join(
        f'<option value="{name}">{name} ({rate:.0%})</option>'
        for name, rate in config.attrition_scenarios
    )
    ute_options = '<option value="all">All UTE</option>' + "".join(
        f'<option value="UTE {ute:.2f}">UTE {ute:.2f}</option>'
        for ute in (config.ute_levels or planning_ute_levels(config.policy))
    )
    event_count_options = '<option value="all">All Event Count Methods</option>' + "".join(
        f'<option value="{model}">{model}</option>' for model in config.event_count_models
    )
    fix_count_options = '<option value="all">All Fix Count Methods</option>' + "".join(
        f'<option value="{model}">{model}</option>' for model in config.fix_count_models
    )
    family_options = '<option value="all">All Families</option>' + "".join(
        f'<option value="{family}">{family}</option>'
        for family in (
            "Flat Turns",
            "Waterfall",
            "Reverse Waterfall",
            "Front-Loaded Push",
            "Back-Loaded Push",
            "Midweek Spike",
            "Multi-Spike",
            "Recovery Valley",
            "Sawtooth",
            "Step-Down",
            "Step-Up",
            "Compressed Surge",
            "Balanced Push",
        )
    )
    return (
        '<div class="filter-panel">'
        '<label for="pai-filter">Filter tables by PAI</label>'
        f'<select id="pai-filter">{options}</select>'
        '<label for="attrition-filter" style="margin-top:10px;">Filter by attrition scenario</label>'
        f'<select id="attrition-filter">{attrition_options}</select>'
        '<label for="required-sorties-filter" style="margin-top:10px;">Minimum weekly sorties required</label>'
        '<input id="required-sorties-filter" type="number" min="0" step="1" placeholder="Example: 24">'
        '<label for="event-count-filter" style="margin-top:10px;">Filter by event-count method</label>'
        f'<select id="event-count-filter">{event_count_options}</select>'
        '<label for="fix-count-filter" style="margin-top:10px;">Filter by fix-count method</label>'
        f'<select id="fix-count-filter">{fix_count_options}</select>'
        '<label for="model-filter" style="margin-top:10px;">Filter by model</label>'
        f'<select id="model-filter"><option value="all">All Models</option><option value="{FLEET_FLEX_MODEL}">{FLEET_FLEX_MODEL}</option><option value="{SCHEDULED_SPARES_MODEL}">{SCHEDULED_SPARES_MODEL}</option></select>'
        '<label for="ute-filter" style="margin-top:10px;">Filter by UTE point</label>'
        f'<select id="ute-filter">{ute_options}</select>'
        '<label for="risk-filter" style="margin-top:10px;">Filter by risk</label>'
        '<select id="risk-filter"><option value="all">All Risk</option><option value="Green">Green</option><option value="Yellow">Yellow</option><option value="Orange">Orange</option><option value="Red">Red</option></select>'
        '<label for="family-filter" style="margin-top:10px;">Filter by pattern family</label>'
        f'<select id="family-filter">{family_options}</select>'
        '<p class="caption">This filters report tables after the simulation has already run. '
        'Charts remain full-run summaries.</p>'
        "</div>"
    )


def _best_fit_callout() -> str:
    return (
        '<div class="best-fit-callout">'
        "<h2>Filtered Best-Fit Callout</h2>"
        '<p id="best-fit-empty" class="caption">No Green/Yellow best-fit pattern is visible under the current filters.</p>'
        '<div id="best-fit-detail">'
        '<h3 id="callout-name">None</h3>'
        '<div class="callout-grid">'
        '<div><span>Pattern</span><strong id="callout-pattern">None</strong></div>'
        '<div><span>PAI</span><strong id="callout-pai">None</strong></div>'
        '<div><span>Attrition</span><strong id="callout-attrition">None</strong></div>'
        '<div><span>Event Count</span><strong id="callout-event-count">None</strong></div>'
        '<div><span>Fix Count</span><strong id="callout-fix-count">None</strong></div>'
        '<div><span>UTE</span><strong id="callout-ute">None</strong></div>'
        '<div><span>Planned / Required</span><strong><span id="callout-planned">None</span> / <span id="callout-required">None</span></strong></div>'
        '<div><span>Peak Front-Lines</span><strong id="callout-frontlines">None</strong></div>'
        '<div><span>Thu/Fri Front-Lines</span><strong id="callout-backend-frontlines">None</strong></div>'
        '<div><span>Commit Aircraft</span><strong id="callout-commit">None</strong></div>'
        '<div><span>Turn Sorties</span><strong id="callout-turns">None</strong></div>'
        '<div><span>Thu/Fri Sorties</span><strong id="callout-backend">None</strong></div>'
        '<div><span>Friday Sorties</span><strong id="callout-friday">None</strong></div>'
        '<div><span>Success</span><strong id="callout-success">None</strong></div>'
        '<div><span>Next Mon MC</span><strong id="callout-nextmon">None</strong></div>'
        '<div><span>Recovery Debt</span><strong id="callout-debt">None</strong></div>'
        "</div></div></div>"
    )


def _capacity_table(config: OptimizationConfig) -> str:
    body = []
    attrs = []
    ute_levels = config.ute_levels or planning_ute_levels(config.policy)
    reference_ute_levels = tuple(
        ute for ute in (0.40, 0.45, 0.50, 0.52)
        if min(ute_levels) <= ute <= max(ute_levels)
    )
    for pai in range(config.pai_min, config.pai_max + 1):
        points = capacity_points(
            pai,
            flying_days=config.flying_days,
            ute_levels=config.ute_levels,
            policy=config.policy,
        )
        by_label = {point["label"]: point for point in points}
        body.append(
            [
                pai,
                by_label[config.policy.surge_label]["commit_aircraft"],
                *[
                    floor_count(pai * len(config.policy.flying_days) * ute)
                    for ute in reference_ute_levels
                ],
                len([point for point in points if point["label"] != config.policy.surge_label]),
                by_label[config.policy.surge_label]["weekly_sorties"],
                f"{by_label[config.policy.surge_label]['actual_ute']:.2f}",
            ]
        )
        attrs.append({"pai": pai})
    return table(
        [
            "PAI",
            "55% Commit Acft",
            *[f"{ute:.2f} UTE" for ute in reference_ute_levels],
            "Band Patterns",
            "Max-Commit Sorties",
            "Max-Commit UTE",
        ],
        body,
        row_attrs=attrs,
    )


def _best_fit_table(rows: list[dict[str, object]]) -> str:
    body = []
    classes = []
    attrs = []
    for row in rows:
        body.append(
            [
                row["pai"],
                row["attrition_scenario"],
                row["event_count_model"],
                row["fix_count_model"],
                row["capacity_label"],
                row["weekly_sorties"],
                row["required_sorties"],
                f"{row['sortie_margin']:+d}",
                f"{row['ute']:.2f}",
                row["model"],
                row["pattern_with_frontlines"],
                row["operational_assessment"],
                row["limiting_factor"],
                row["recommendation_confidence"],
                row["pattern_name"],
                row["pattern_family"],
                row["peak_frontlines"],
                row["frontline_backend"],
                row["commit_aircraft"],
                row["total_turn_sorties"],
                row["backend_sorties"],
                row["friday_sorties"],
                f"{row['success']:.1%}",
                f"{row['success_std_dev']:.1%}",
                f"{row['success_min']:.0%}-{row['success_max']:.0%}",
                f"{row['success_p10']:.0%}/{row['success_p50']:.0%}/{row['success_p90']:.0%}",
                f"{row['success_ci95_low']:.1%}-{row['success_ci95_high']:.1%}",
                f"{row['full_schedule_success']:.1%}",
                f"{row['sortie_success']:.1%}",
                f"{row['daily_schedule_success']:.1%}",
                f"{row['planned_attrition_success']:.1%}",
                f"{row['aircraft_success']:.1%}",
                f"{row['commit_success']:.1%}",
                f"{row['recovery_success']:.1%}",
                f"{row['backlog_success']:.1%}",
                f"{row['no_suppressed_events_success']:.1%}",
                f"{row['planned_attrition_rate']:.1%}",
                f"{row['avg_actual_attrition_rate']:.1%}",
                f"{row['avg_attrition_delta']:+.1%}",
                f"{row['avg_next_monday']:.1f}",
                f"{row['avg_repair_backlog']:.2f}",
                f"{row['recovery_debt']:.2f}",
                row["confidence_warnings"],
                row["risk_band"],
                f"{row['composite_score']:.3f}",
                row["failure_mode"],
            ]
        )
        row_classes = [""] * 47
        row_classes[22] = probability_class(float(row["success"]), SUCCESS_THRESHOLD)
        row_classes[44] = _risk_class(str(row["risk_band"]))
        classes.append(row_classes)
        attrs.append(
            {
                "role": "best-fit",
                "pai": row["pai"],
                "attrition": row["attrition_scenario"],
                "event-count": row["event_count_model"],
                "fix-count": row["fix_count_model"],
                "model": row["model"],
                "ute": row["capacity_label"],
                "risk": row["risk_band"],
                "family": row["pattern_family"],
                "score": f"{float(row['composite_score']):.6f}",
                "success": f"{float(row['success']):.6f}",
                "success-text": f"{row['success']:.1%}",
                "pattern-display": row["pattern_with_frontlines"],
                "name": row["pattern_name"],
                "planned": row["weekly_sorties"],
                "required": row["required_sorties"],
                "frontlines": row["peak_frontlines"],
                "backend-frontlines": f"{row['frontline_backend']:.0f}",
                "commit": row["commit_aircraft"],
                "turns": row["total_turn_sorties"],
                "backend": row["backend_sorties"],
                "friday": row["friday_sorties"],
                "nextmon": f"{row['avg_next_monday']:.1f}",
                "debt": f"{row['recovery_debt']:.2f}",
            }
        )
    return table(
        [
            "PAI",
            "Attrition",
            "Event Count",
            "Fix Count",
            "Requirement",
            "Sorties",
            "Required",
            "Margin",
            "UTE",
            "Model",
                "Pattern Total(Front-Line)",
            "Assessment",
            "Limiting Factor",
            "Confidence",
            "Name",
            "Family",
            "Peak Front-Line",
            "Thu/Fri Front-Line",
            "Commit Acft",
            "Turn Sorties",
            "Thu/Fri Sorties",
            "Fri Sorties",
            "Avg Success",
            "Success SD",
            "Success Range",
            "P10/P50/P90",
            "95% CI",
            "Full Schedule",
            "Required Sortie",
            "Daily Schedule",
            "Attrition",
            "Aircraft",
            "Commit",
            "Recovery",
            "Backlog",
            "No Suppression",
            "Planned Attr %",
            "Actual Attr %",
            "Attr Delta",
            "Next Mon",
            "Repair Backlog",
            "Recovery Debt",
            "Confidence Warning",
            "Risk",
            "Score",
            "Failure Mode",
        ],
        body,
        classes,
        row_attrs=attrs,
    )


def _best_sustainable_ute_table(rows: list[dict[str, object]], threshold: float) -> str:
    body = []
    attrs = []
    keys = sorted({(row["pai"], row["attrition_scenario"], row["event_count_model"], row["fix_count_model"]) for row in rows})
    for pai, attrition, event_count_model, fix_count_model in keys:
        candidates = [
            row
            for row in rows
            if row["pai"] == pai
            and row["attrition_scenario"] == attrition
            and row["event_count_model"] == event_count_model
            and row["fix_count_model"] == fix_count_model
            and row["model"] == FLEET_FLEX_MODEL
            and row["success"] >= threshold
            and row["sortie_margin"] >= 0
        ]
        row = max(candidates, key=lambda item: (item["ute"], item["weekly_sorties"], item["success"]), default=None)
        if row is None:
            body.append([pai, attrition, event_count_model, fix_count_model, "None", "None", "None", "None", "No fleet-flex pattern met threshold"])
        else:
            body.append(
                [
                    pai,
                    attrition,
                    event_count_model,
                    fix_count_model,
                    row["weekly_sorties"],
                    f"{row['ute']:.2f}",
                    row["pattern_with_frontlines"],
                    f"{row['success']:.1%}",
                    row["risk_band"],
                ]
            )
        attrs.append({
            "pai": pai,
            "attrition": attrition,
            "event-count": event_count_model,
            "fix-count": fix_count_model,
            "planned": row["weekly_sorties"] if row else 0,
            "risk": row["risk_band"] if row else "Red",
        })
    return table(["PAI", "Attrition", "Event Count", "Fix Count", "Best Sorties", "Best UTE", "Pattern", "Success", "Risk"], body, row_attrs=attrs)


def _attrition_comparison_table(rows: list[dict[str, object]], threshold: float) -> str:
    body = []
    attrs = []
    keys = sorted({(row["pai"], row["attrition_scenario"], row["event_count_model"], row["fix_count_model"]) for row in rows})
    for pai, attrition, event_count_model, fix_count_model in keys:
        candidates = [
            row
            for row in rows
            if row["pai"] == pai
            and row["attrition_scenario"] == attrition
            and row["event_count_model"] == event_count_model
            and row["fix_count_model"] == fix_count_model
            and row["model"] == FLEET_FLEX_MODEL
            and row["success"] >= threshold
        ]
        best = max(
            candidates,
            key=lambda row: (row["ute"], row["weekly_sorties"], row["success"]),
            default=None,
        )
        if best is None:
            body.append([pai, attrition, event_count_model, fix_count_model, "None", "None", "None", "None", "No green fleet-flex option"])
        else:
            body.append(
                [
                    pai,
                    attrition,
                    event_count_model,
                    fix_count_model,
                    best["weekly_sorties"],
                    best["required_sorties"],
                    f"{best['ute']:.2f}",
                    f"{best['success']:.1%}",
                    best["pattern_with_frontlines"],
                ]
            )
        attrs.append({
            "pai": pai,
            "attrition": attrition,
            "event-count": event_count_model,
            "fix-count": fix_count_model,
            "planned": best["weekly_sorties"] if best else 0,
            "risk": best["risk_band"] if best else "Red",
        })
    return table(
        ["PAI", "Attrition Scenario", "Event Count", "Fix Count", "Planned", "Required", "Best UTE", "Success", "Pattern"],
        body,
        row_attrs=attrs,
    )


def _recovery_model_comparison_table(rows: list[dict[str, object]]) -> str:
    pairs: dict[tuple[int, int, str, str, str, str], dict[str, dict[str, object]]] = {}
    for row in rows:
        key = (
            int(row["pai"]),
            int(row["weekly_sorties"]),
            str(row["capacity_label"]),
            str(row["attrition_scenario"]),
            str(row["event_count_model"]),
            str(row["fix_count_model"]),
        )
        pairs.setdefault(key, {})[str(row["model"])] = row
    body = []
    attrs = []
    for key, models in sorted(pairs.items()):
        scheduled_spares = models.get(SCHEDULED_SPARES_MODEL)
        fleet_flex = models.get(FLEET_FLEX_MODEL)
        if not scheduled_spares or not fleet_flex:
            continue
        body.append(
            [
                key[0],
                key[3],
                key[4],
                key[5],
                key[2],
                key[1],
                f"{scheduled_spares['success']:.1%}",
                f"{fleet_flex['success']:.1%}",
                f"{float(fleet_flex['success']) - float(scheduled_spares['success']):+.1%}",
                scheduled_spares["pattern_with_frontlines"],
                fleet_flex["pattern_with_frontlines"],
            ]
        )
        attrs.append({
            "pai": key[0],
            "attrition": key[3],
            "event-count": key[4],
            "fix-count": key[5],
            "planned": key[1],
            "ute": key[2],
        })
    return table(
        ["PAI", "Attrition", "Event Count", "Fix Count", "Requirement", "Sorties", SCHEDULED_SPARES_MODEL, FLEET_FLEX_MODEL, "Delta", "Scheduled-Spares Pattern", "Fleet-Flex Pattern"],
        body,
        row_attrs=attrs,
    )


def _family_comparison_table(rows: list[dict[str, object]]) -> str:
    return table(
        [
            "Family",
            "Runs",
            "Best Pattern Total(Front-Line)",
            "Best Name",
            "Peak Front-Line",
            "Commit Acft",
            "Best Success",
            "Avg Success",
            "Avg Recovery Debt",
        ],
        [
            [
                row["pattern_family"],
                row["tested"],
                row["best_pattern"],
                row["best_name"],
                row["best_peak_frontlines"],
                row["best_commit_aircraft"],
                f"{row['best_success']:.1%}",
                f"{row['avg_success']:.1%}",
                f"{row['avg_recovery_debt']:.2f}",
            ]
            for row in rows
        ],
    )


def _discovery_tables(rows: list[dict[str, object]]) -> str:
    unique = _unique_best_patterns(rows)
    top_success = sorted(unique, key=lambda row: (-float(row["success"]), -float(row["weekly_sorties"])))[:10]
    top_output = sorted(
        [row for row in unique if row["risk_band"] in ("Green", "Yellow")],
        key=lambda row: (-int(row["weekly_sorties"]), -float(row["success"])),
    )[:10]
    low_debt = sorted(unique, key=lambda row: (float(row["recovery_debt"]), -float(row["success"])))[:10]
    efficient = sorted(unique, key=lambda row: -(float(row["success"]) / max(int(row["weekly_sorties"]), 1)))[:10]
    return (
        "<h3>Top 10 Unique Patterns By Success</h3>"
        + _compact_pattern_table(top_success)
        + "<h3>Top 10 Green/Yellow Patterns By Output</h3>"
        + _compact_pattern_table(top_output)
        + "<h3>Lowest Recovery-Debt Patterns</h3>"
        + _compact_pattern_table(low_debt)
        + "<h3>Most Efficient Patterns By Success Per Sortie</h3>"
        + _compact_pattern_table(efficient)
    )


def _compact_pattern_table(rows: list[dict[str, object]]) -> str:
    return table(
        [
            "PAI",
            "Attrition",
            "Event Count",
            "Fix Count",
            "Sorties",
            "UTE",
            "Model",
            "Pattern Total(Front-Line)",
            "Name",
            "Family",
            "Peak Front-Line",
            "Commit Acft",
            "Turn Sorties",
            "Thu/Fri Sorties",
            "Fri Sorties",
            "Avg Success",
            "Success SD",
            "Success Range",
            "95% CI",
            "Recovery Debt",
            "Risk",
        ],
        [
            [
                row["pai"],
                row["attrition_scenario"],
                row["event_count_model"],
                row["fix_count_model"],
                row["weekly_sorties"],
                f"{row['ute']:.2f}",
                row["model"],
                row["pattern_with_frontlines"],
                row["pattern_name"],
                row["pattern_family"],
                row["peak_frontlines"],
                row["commit_aircraft"],
                row["total_turn_sorties"],
                row["backend_sorties"],
                row["friday_sorties"],
                f"{row['success']:.1%}",
                f"{row['success_std_dev']:.1%}",
                f"{row['success_min']:.0%}-{row['success_max']:.0%}",
                f"{row['success_ci95_low']:.1%}-{row['success_ci95_high']:.1%}",
                f"{row['recovery_debt']:.2f}",
                row["risk_band"],
            ]
            for row in rows
        ],
        row_attrs=[
            {
                "pai": row["pai"],
                "attrition": row["attrition_scenario"],
                "event-count": row["event_count_model"],
                "fix-count": row["fix_count_model"],
                "planned": row["weekly_sorties"],
                "model": row["model"],
                "risk": row["risk_band"],
                "family": row["pattern_family"],
                "backend": row["backend_sorties"],
            }
            for row in rows
        ],
    )


def _run_surge(best_rows: list[dict[str, object]]):
    surge_candidates = [
        row
        for row in best_rows
        if row["capacity_label"] == REPORT_POLICY.surge_label
        and row["model"] == FLEET_FLEX_MODEL
        and row["attrition_scenario"] == "Planning Attrition"
        and row["event_count_model"] == "Normal TTP"
        and row["fix_count_model"] == "Normal TTP"
    ]
    if not surge_candidates:
        surge_candidates = [
            row
            for row in best_rows
            if row["capacity_label"] == REPORT_POLICY.surge_label and row["model"] == FLEET_FLEX_MODEL
        ]
    if not surge_candidates:
        surge_candidates = [
            row
            for row in best_rows
            if row["capacity_label"] == REPORT_POLICY.surge_label
        ]
    surge_row = max(
        surge_candidates,
        key=lambda row: (row["success"], row["weekly_sorties"]),
    )
    template = base_optimizer_scenario(True, REPORT_POLICY)
    from simulation_engine import DaySchedule

    commit_aircraft = int(surge_row["commit_aircraft"])
    surge_schedule = {
        day: DaySchedule(first_go=commit_aircraft)
        for day in REPORT_POLICY.flying_days
    }
    scenario = replace(
        template,
        inventory=replace(template.inventory, paa=int(surge_row["pai"]), pai=int(surge_row["pai"])),
        homestation=replace(
            template.homestation,
            event_count_model=str(surge_row["event_count_model"]),
            fix_count_model=str(surge_row["fix_count_model"]),
            use_uncommitted_aircraft_for_ga_recovery=True,
        ),
        schedule=surge_schedule,
        total_required_sorties=max(1, int(surge_row["weekly_sorties"]) - int(surge_row["planned_attrition"])),
    )
    return simulate_surge_duration(
        scenario,
        max_surge_weeks=MAX_SURGE_WEEKS,
        iterations=SURGE_ITERATIONS,
        seed=900,
        success_threshold=SUCCESS_THRESHOLD,
    )


def _surge_table(surge) -> str:
    return table(
        ["Week", "Success", "Commit Capacity", "Ending MC", "Next-Mon MC", "Repair Backlog", "Surge Debt", "Risk"],
        [
            [
                week.week,
                f"{week.probability_success:.1%}",
                f"{week.probability_commit_capacity:.1%}",
                f"{week.average_ending_mc:.1f}",
                f"{week.average_next_monday_mc:.1f}",
                f"{week.average_repair_backlog:.2f}",
                f"{week.average_surge_debt:.2f}",
                week.risk_band,
            ]
            for week in surge.weeks
        ],
    )


def _surge_chart(surge) -> str:
    return bar_chart(
        [f"Wk {week.week}" for week in surge.weeks],
        [week.probability_success * 100 for week in surge.weeks],
        "55% Commit Surge Duration",
        "% success",
    )


def _family_success_chart(rows: list[dict[str, object]]) -> str:
    rollup = family_rollup(rows)[:12]
    return bar_chart(
        [str(row["pattern_family"]) for row in rollup],
        [float(row["avg_success"]) * 100 for row in rollup],
        "Success Rate by Pattern Family",
        "% success",
    )


def _family_recovery_chart(rows: list[dict[str, object]]) -> str:
    rollup = family_rollup(rows)[:12]
    return bar_chart(
        [str(row["pattern_family"]) for row in rollup],
        [float(row["avg_recovery_debt"]) for row in rollup],
        "Recovery Debt by Pattern Family",
        "aircraft",
    )


def _unique_best_patterns(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    best: dict[tuple[str, str, str], dict[str, object]] = {}
    for row in rows:
        key = (
            str(row["attrition_scenario"]),
            str(row["model"]),
            str(row["pattern_signature"]),
        )
        current = best.get(key)
        if current is None or (row["success"], row["weekly_sorties"]) > (current["success"], current["weekly_sorties"]):
            best[key] = row
    return list(best.values())


def _risk_class(risk: str) -> str:
    return {
        "Green": "green",
        "Yellow": "yellow",
        "Orange": "yellow",
        "Red": "red",
    }.get(risk, "")


if __name__ == "__main__":
    main()
