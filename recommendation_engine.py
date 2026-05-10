from __future__ import annotations

from dataclasses import dataclass

from ttp_rules import DEFAULT_TTP_POLICY, TtpPolicy


@dataclass(frozen=True)
class Recommendation:
    pattern: str
    assessment: str
    confidence: str
    limiting_factor: str
    recommendation: str
    feasible: bool
    executable: bool
    sustainable: bool


def add_recommendations(
    rows: list[dict[str, object]],
    policy: TtpPolicy = DEFAULT_TTP_POLICY,
) -> list[dict[str, object]]:
    return [{**row, **recommendation_fields(row, policy)} for row in rows]


def recommendation_fields(
    row: dict[str, object],
    policy: TtpPolicy = DEFAULT_TTP_POLICY,
) -> dict[str, object]:
    threshold = policy.green_success_threshold
    feasible = _feasible(row)
    executable = _executable(row, threshold)
    sustainable = _sustainable(row, threshold)
    confidence = _confidence(row)
    limiting_factor = _limiting_factor(row)
    assessment = _assessment(feasible, executable, sustainable, confidence)
    recommendation = _recommendation_sentence(row, assessment, limiting_factor)
    return {
        "feasible": feasible,
        "executable": executable,
        "sustainable": sustainable,
        "operational_assessment": assessment,
        "recommendation_confidence": confidence,
        "limiting_factor": limiting_factor,
        "recommendation": recommendation,
    }


def best_recommendation(
    rows: list[dict[str, object]],
    policy: TtpPolicy = DEFAULT_TTP_POLICY,
) -> Recommendation | None:
    if not rows:
        return None
    enriched = add_recommendations(rows, policy)
    best = max(
        enriched,
        key=lambda row: (
            bool(row["sustainable"]),
            bool(row["executable"]),
            bool(row["feasible"]),
            float(row["success"]),
            float(row["composite_score"]),
            -float(row["recovery_debt"]),
        ),
    )
    return Recommendation(
        pattern=str(best["pattern_with_frontlines"]),
        assessment=str(best["operational_assessment"]),
        confidence=str(best["recommendation_confidence"]),
        limiting_factor=str(best["limiting_factor"]),
        recommendation=str(best["recommendation"]),
        feasible=bool(best["feasible"]),
        executable=bool(best["executable"]),
        sustainable=bool(best["sustainable"]),
    )


def compare_baseline_candidate(
    baseline: dict[str, object],
    candidate: dict[str, object],
) -> dict[str, object]:
    return {
        "baseline_pattern": baseline["pattern_with_frontlines"],
        "candidate_pattern": candidate["pattern_with_frontlines"],
        "success_delta": float(candidate["success"]) - float(baseline["success"]),
        "planned_sorties_delta": int(candidate["weekly_sorties"]) - int(baseline["weekly_sorties"]),
        "next_monday_delta": float(candidate["avg_next_monday"]) - float(baseline["avg_next_monday"]),
        "backlog_delta": float(candidate["avg_repair_backlog"]) - float(baseline["avg_repair_backlog"]),
        "recovery_debt_delta": float(candidate["recovery_debt"]) - float(baseline["recovery_debt"]),
        "baseline_limiting_factor": baseline.get("limiting_factor", baseline.get("failure_mode", "Unknown")),
        "candidate_limiting_factor": candidate.get("limiting_factor", candidate.get("failure_mode", "Unknown")),
    }


def _feasible(row: dict[str, object]) -> bool:
    return (
        float(row["commit_success"]) >= 1.0
        and int(row["peak_frontlines"]) <= int(row["commit_aircraft"])
        and int(row["weekly_sorties"]) >= int(row["required_sorties"])
        and int(row["suppressed_events_count"]) == 0
    )


def _executable(row: dict[str, object], threshold: float) -> bool:
    return (
        _feasible(row)
        and float(row["sortie_success"]) >= threshold
        and float(row["aircraft_success"]) >= threshold
        and float(row["daily_schedule_success"]) >= threshold
    )


def _sustainable(row: dict[str, object], threshold: float) -> bool:
    return (
        _executable(row, threshold)
        and float(row["recovery_success"]) >= threshold
        and float(row["backlog_success"]) >= threshold
        and float(row["recovery_debt"]) <= 1.0
    )


def _confidence(row: dict[str, object]) -> str:
    ci_width = float(row["success_ci95_high"]) - float(row["success_ci95_low"])
    warnings = str(row.get("confidence_warnings", "None"))
    validation = str(row.get("validation_warnings", "None"))
    if bool(row.get("low_confidence")) or ci_width > 0.10 or warnings != "None":
        return "Low Confidence"
    if ci_width > 0.05 or validation != "None":
        return "Moderate Confidence"
    return "High Confidence"


def _limiting_factor(row: dict[str, object]) -> str:
    dimensions = {
        "Sortie Capacity Limited": float(row["sortie_success"]),
        "Daily Schedule Limited": float(row["daily_schedule_success"]),
        "Aircraft Availability Limited": float(row["aircraft_success"]),
        "Commit-Cap Limited": float(row["commit_success"]),
        "Recovery-Time Limited": float(row["recovery_success"]),
        "Backlog Limited": float(row["backlog_success"]),
        "Event-Suppression Limited": float(row["no_suppressed_events_success"]),
    }
    limiting_factor, value = min(dimensions.items(), key=lambda item: item[1])
    if value >= 0.999:
        failure_mode = str(row.get("failure_mode", "None"))
        return "No dominant limiter" if failure_mode == "None" else failure_mode
    return limiting_factor


def _assessment(
    feasible: bool,
    executable: bool,
    sustainable: bool,
    confidence: str,
) -> str:
    if not feasible:
        return "Not Feasible"
    if not executable:
        return "Feasible / Not Executable"
    if not sustainable:
        return "Executable / Not Sustainable"
    if confidence == "Low Confidence":
        return "Sustainable / Low Confidence"
    return "Sustainable"


def _recommendation_sentence(row: dict[str, object], assessment: str, limiting_factor: str) -> str:
    if assessment == "Sustainable":
        return (
            f"Execute as a primary candidate; {row['pattern_with_frontlines']} meets the sortie target "
            f"with {float(row['success']):.0%} modeled success and {float(row['avg_next_monday']):.1f} average next-Monday MC."
        )
    if assessment == "Sustainable / Low Confidence":
        return "Treat as promising but rerun with more iterations or cleaner assumptions before briefing as recommended."
    if assessment == "Executable / Not Sustainable":
        return f"Use cautiously for short duration only; primary limiter is {limiting_factor.lower()}."
    if assessment == "Feasible / Not Executable":
        return f"Do not use as the primary weekly plan; primary limiter is {limiting_factor.lower()}."
    return f"Do not use without changing inputs; primary limiter is {limiting_factor.lower()}."
