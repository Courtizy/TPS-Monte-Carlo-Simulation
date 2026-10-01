"""Score simulated weeks and summarize a run.

A week succeeds only if it:
  - meets the required weekly sorties,
  - flies every day's planned sorties,
  - has the front-line aircraft ready every flying day,
  - keeps every day's plan within commit,
  - recovers next Monday (aircraft ready >= the week's highest first go + spares,
    or the configured minimum), and
  - passes the backlog check when a backlog threshold is set.
2407 adds and days over commit in practice are reported, not pass/fail.
"""
from __future__ import annotations

from math import ceil, floor, sqrt
from statistics import mean, median
from typing import Any

from tps_core.rules import risk_band

Z95 = 1.959963984540054
FAILURE_WORDS = {
    "Daily Schedule Miss": "a day's planned sorties aren't all flown",
    "Sortie Shortfall": "the week falls short of required sorties",
    "Aircraft Availability": "too few aircraft are ready for a day's front line",
    "TTP Commit": "a day's plan is above commit",
    "Recovery": "too few aircraft are ready for next Monday",
    "Repair Backlog": "the repair backlog is above its limit",
}


# [M-4]
def wilson_interval(successes: int, n: int, z: float = Z95) -> tuple[float, float]:
    """95% Wilson score interval; stays inside 0-1 even near 0% or 100%."""
    if n == 0:
        return 0.0, 1.0
    p = successes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


# [M-1] [M-2]
def score_week(days: list[dict[str, Any]], week: dict[str, Any], flying_days: tuple[str, ...]) -> dict[str, Any]:
    flying = [d for d in days if d["day"] in flying_days]
    total = sum(d["sorties_flown"] for d in flying)
    planned = sum(d["planned_sorties"] for d in flying)
    required = week["required_sorties"]
    failed = [d for d in flying if d["sorties_flown"] < d["planned_sorties"]]
    meets_sorties = total >= required
    daily_ok = not failed
    aircraft_ok = all(d["meets_aircraft_required"] for d in flying)
    commit_ok = all(d["within_ttp_commit"] for d in flying)
    target = max((d["aircraft_required"] for d in flying), default=0)
    if week["minimum_required_monday_aircraft"] is not None:
        target = week["minimum_required_monday_aircraft"]
    next_monday = days[-1]["available_eod"]
    recovery = next_monday >= target
    threshold = week["backlog_threshold"]
    backlog_ok = threshold is None or week["repair_backlog"] <= threshold
    succeeds = meets_sorties and daily_ok and aircraft_ok and commit_ok and recovery and backlog_ok

    modes = []
    for failed_check, name in (
        (total < planned, "Full Schedule Not Flown"),
        (not meets_sorties, "Sortie Shortfall"),
        (not daily_ok, "Daily Schedule Miss"),
        (not aircraft_ok, "Aircraft Availability"),
        (not commit_ok, "TTP Commit"),
        (not recovery, "Recovery"),
        (not backlog_ok, "Repair Backlog"),
    ):
        if failed_check:
            modes.append(name)

    first_failure = next(
        (d["day"] for d in flying
         if not d["meets_aircraft_required"] or not d["within_ttp_commit"]
         or d["sorties_flown"] < d["planned_sorties"]),
        None,
    )
    if first_failure is None and not meets_sorties:
        first_failure = "Week"
    if first_failure is None and not recovery:
        first_failure = "Next Mon"

    return {
        "succeeds": succeeds,
        "total_sorties": total,
        "planned_sorties": planned,
        "required_sorties": required,
        "full_schedule": total >= planned,
        "meets_sorties": meets_sorties,
        "daily_schedule": daily_ok,
        "aircraft_ready": aircraft_ok,
        "within_commit": commit_ok,
        "recovery": recovery,
        "backlog_ok": backlog_ok,
        "failure_modes": modes,
        "first_failure_day": first_failure,
        "next_monday_ready": next_monday,
        "repair_backlog": week["repair_backlog"],
        "adds_2407": sum(d["adds_2407"] for d in days),
        "days_over_commit": sum(1 for d in flying if d["actual_exceeds_commit"]),
        "spare_sorties": sum(d["spares_used"] for d in days),
        "repeat_recur_events": sum(d["repeat_recur_events"] for d in days),
        "new_beyond_24hr": sum(d["new_beyond_24hr"] for d in days),
        "lost_turn_short": sum(d["lost_turn_short"] for d in flying),
        "lost_abort_uncovered": sum(d["lost_abort_uncovered"] for d in flying),
        "lost_first_go_short": sum(d["lost_first_go_short"] for d in flying),
        "recovery_target": target,
        "only_recovery_failed": modes == ["Recovery"],
    }


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct / 100
    low, high = floor(k), ceil(k)
    return float(ordered[low] + (ordered[high] - ordered[low]) * (k - low))


def _distribution(values: list[float]) -> dict[str, float]:
    return {
        "mean": mean(values),
        "min": float(min(values)),
        "p10": _percentile(values, 10),
        "p50": float(median(values)),
        "p90": _percentile(values, 90),
        "max": float(max(values)),
    }


def _share(flags) -> float:
    flags = list(flags)
    return sum(flags) / len(flags) if flags else 0.0


def _counts(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        if value:
            counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def summarize(weeks: list[tuple[list[dict], dict]], flying_days: tuple[str, ...], all_days: tuple[str, ...],
              sute_target: float | None = None, sute_ceiling: float | None = None,
              sute_basis: str = "sute") -> dict[str, Any]:
    """Metrics for a run. Contains no timestamps, so it can be fingerprinted."""
    scores = [score_week(days, week, flying_days) for days, week in weeks]
    n = len(scores)
    wins = sum(s["succeeds"] for s in scores)
    p = wins / n
    low, high = wilson_interval(wins, n)
    failed = [s for s in scores if not s["succeeds"]]

    daily = {}
    for index, day in enumerate(all_days):
        rows = [days[index] for days, _ in weeks]
        ready = [r["mc_aircraft_for_flying"] for r in rows]
        needed = rows[0]["aircraft_required"]
        daily[day] = {
            "aircraft_needed": needed,
            "ready_p10": _percentile(ready, 10),
            "ready_p50": float(median(ready)),
            "ready_p90": _percentile(ready, 90),
            "share_short_aircraft": _share(r < needed for r in ready) if day in flying_days else 0.0,
            "mean_lost_turn_short": mean(r["lost_turn_short"] for r in rows),
            "mean_lost_abort_uncovered": mean(r["lost_abort_uncovered"] for r in rows),
            "mean_lost_first_go_short": mean(r["lost_first_go_short"] for r in rows),
            "mean_ready_at_start": mean(ready),
            "mean_sorties_flown": mean(r["sorties_flown"] for r in rows),
            "mean_lost_sorties": mean(r["lost_sorties"] for r in rows),
            "mean_breaks_and_aborts": mean(r["ga_plus_code_3"] for r in rows),
            "share_missing_schedule": _share(r["sorties_flown"] < r["planned_sorties"] for r in rows)
            if day in flying_days else 0.0,
            "mean_2407_adds": mean(r["adds_2407"] for r in rows),
        }

    metrics = {
        "iterations": n,
        "successes": wins,
        "probability_success": p,
        "ci95_low": low,
        "ci95_high": high,
        "ci_method": "Wilson score, 95%",
        "risk_band": risk_band(p),
        "components": {
            "full_schedule": _share(s["full_schedule"] for s in scores),
            "meets_required_sorties": _share(s["meets_sorties"] for s in scores),
            "every_day_flown": _share(s["daily_schedule"] for s in scores),
            "aircraft_ready_every_day": _share(s["aircraft_ready"] for s in scores),
            "plan_within_commit": _share(s["within_commit"] for s in scores),
            "next_monday_recovery": _share(s["recovery"] for s in scores),
            "backlog_within_limit": _share(s["backlog_ok"] for s in scores),
        },
        "plan": {
            "planned_sorties": scores[0]["planned_sorties"],
            "required_sorties": scores[0]["required_sorties"],
        },
        "distributions": {
            "sorties_flown": _distribution([s["total_sorties"] for s in scores]),
            "next_monday_ready": _distribution([s["next_monday_ready"] for s in scores]),
            "repair_backlog": _distribution([s["repair_backlog"] for s in scores]),
        },
        "failures": {
            "failed_weeks": len(failed),
            "failure_mode_counts": _counts(m for s in failed for m in s["failure_modes"]),
            "first_failure_day_counts": _counts(s["first_failure_day"] for s in failed),
        },
        "reported": {
            "mean_2407_adds_per_week": mean(s["adds_2407"] for s in scores),
            "share_weeks_with_2407_adds": _share(s["adds_2407"] > 0 for s in scores),
            "mean_days_over_commit_in_practice": mean(s["days_over_commit"] for s in scores),
            "mean_spare_sorties_per_week": mean(s["spare_sorties"] for s in scores),
            "mean_repeat_recur_breaks_per_week": mean(s["repeat_recur_events"] for s in scores),
            "mean_new_beyond_24hr_per_week": mean(s["new_beyond_24hr"] for s in scores),
        },
        "daily": daily,
        "recovery": {
            "target": scores[0]["recovery_target"],
            "share_short": 1 - _share(s["recovery"] for s in scores),
            "weeks_failing_only_recovery": sum(s["only_recovery_failed"] for s in scores),
        },
        "causes": _causes(scores, failed),
        "weakest_day": _weakest_day(daily, flying_days),
        "goes": _by_go(weeks, flying_days, scores),
        "sute": _sute(weeks, flying_days, scores, sute_target, sute_ceiling, sute_basis),
    }
    metrics["summary_text"] = plain_summary(metrics)
    return metrics


DAY_NAMES = {"Mon": "Monday", "Tue": "Tuesday", "Wed": "Wednesday", "Thu": "Thursday",
             "Fri": "Friday", "Sat": "Saturday", "Sun": "Sunday"}


# [M-6]
def _by_go(weeks, flying_days, scores) -> dict[str, Any]:
    """Planned and flown sorties for each go, plus turn success and generation effectiveness."""
    planned = [0] * 4
    flown = [0] * 4
    for days, _ in weeks:
        for day in days:
            if day["day"] in flying_days:
                for g in range(4):
                    planned[g] += day["planned_by_go"][g]
                    flown[g] += day["flown_by_go"][g]
    by_go = [{"go": g + 1, "planned": planned[g], "flown": flown[g], "share_flown": flown[g] / planned[g]}
             for g in range(4) if planned[g]]
    later_planned, later_flown = sum(planned[1:]), sum(flown[1:])
    total_planned, total_flown = sum(planned), sum(flown)
    return {
        "by_go": by_go,
        "turn_success_rate": later_flown / later_planned if later_planned else None,
        "sortie_generation_effectiveness": total_flown / total_planned if total_planned else None,
        "weakest_go": min(by_go, key=lambda g: g["share_flown"])["go"] if by_go else None,
    }


# [M-7]
def _sute(weeks, flying_days, scores, target, ceiling, basis="sute") -> dict[str, Any]:
    """Daily SUTE per PAI across the flying days, and sorties per aircraft per week [M-7] [M-9]."""
    from tps_core.tempo import DAYS_PER_WEEK, home_requirements
    pai = weeks[0][0][0]["pai"]
    per = pai * len(flying_days)
    flown = [s["total_sorties"] / per for s in scores]
    planned = scores[0]["planned_sorties"] / per
    per_aircraft = [s["total_sorties"] / pai for s in scores]
    deployed_per_aircraft = target * DAYS_PER_WEEK if target else None
    return {
        "planned": planned,
        "flown": _distribution(flown),
        "target": target,
        "ceiling": ceiling,
        "share_weeks_meeting_target": _share(f >= target - 1e-9 for f in flown) if target else None,
        "planned_above_ceiling": planned > ceiling + 1e-9 if ceiling else None,
        "per_aircraft": {
            "planned": scores[0]["planned_sorties"] / pai,
            "flown": _distribution(per_aircraft),
            "deployed": deployed_per_aircraft,
            "share_weeks_meeting_deployed": _share(p >= deployed_per_aircraft - 1e-9 for p in per_aircraft)
            if deployed_per_aircraft else None,
        },
        "requirements": home_requirements(target, pai, len(flying_days)) if target else None,
        "requirement_basis": basis,
    }


CAUSE_KEYS = ("lost_turn_short", "lost_abort_uncovered", "lost_first_go_short")


# [M-5]
def _causes(scores: list[dict], failed: list[dict]) -> dict[str, Any]:
    """Where lost sorties came from, across every week and across failed weeks."""
    def tally(group):
        totals = {key: sum(s[key] for s in group) for key in CAUSE_KEYS}
        lost = sum(totals.values())
        return {"lost_sorties": lost, "counts": totals,
                "shares": {k: (v / lost if lost else 0.0) for k, v in totals.items()}}
    everything = tally(scores)
    main = max(CAUSE_KEYS, key=lambda k: everything["counts"][k]) if everything["lost_sorties"] else None
    return {"all_weeks": everything, "failed_weeks": tally(failed), "main_cause": main,
            "mean_lost_per_week": everything["lost_sorties"] / len(scores)}


# [M-8]
def _weakest_day(daily: dict[str, dict], flying_days: tuple[str, ...]) -> str | None:
    """The flying day most likely to miss its schedule (ties: most likely short of aircraft)."""
    candidates = [d for d in flying_days if d in daily]
    if not candidates:
        return None
    day = max(candidates, key=lambda d: (daily[d]["share_missing_schedule"], daily[d]["share_short_aircraft"]))
    risky = daily[day]["share_missing_schedule"] > 0 or daily[day]["share_short_aircraft"] > 0
    return day if risky else None


CAUSE_WORDS = {
    "lost_turn_short": "no aircraft is back in time for a turn after a break or abort",
    "lost_abort_uncovered": "ground aborts use up the spares",
    "lost_first_go_short": "the day starts with too few aircraft for the first go",
}


def plain_summary(m: dict[str, Any]) -> str:
    p = m["probability_success"]
    if p >= 0.995:
        text = "Succeeds in nearly every simulated week."
    elif p <= 0.005:
        text = "Fails in nearly every simulated week."
    else:
        text = f"Succeeds in about {round(p * 100)} of every 100 simulated weeks."
    failures = m["failures"]
    reasons = [k for k in failures["failure_mode_counts"] if k in FAILURE_WORDS]
    if failures["failed_weeks"] and reasons:
        reason = reasons[0]
        lead = " In the rare weeks it fails, the most common reason is" if p >= 0.99 else " The most common reason it fails is"
        text += f"{lead} that {FAILURE_WORDS[reason]}"
        if reason in ("Daily Schedule Miss", "Aircraft Availability", "TTP Commit"):
            days = [d for d in failures["first_failure_day_counts"] if d in DAY_NAMES]
            if days:
                text += f", most often starting {DAY_NAMES[days[0]]}"
        text += "."
    sute = m.get("sute") or {}
    if sute.get("target"):
        text += (f" Planned SUTE is {sute['planned']:.2f} against a deployed target of {sute['target']:.2f};"
                 f" the SUTE actually flown meets the target in {round(sute['share_weeks_meeting_target'] * 100)}% of weeks.")
    goes = m.get("goes") or {}
    if len(goes.get("by_go", [])) > 1 and failures["failed_weeks"]:
        weakest = goes["by_go"][goes["weakest_go"] - 1]
        if weakest["share_flown"] < 0.999:
            text += f" Go {weakest['go']} loses the most, flying {weakest['share_flown'] * 100:.1f}% of its planned sorties."
    main = m.get("causes", {}).get("main_cause")
    if failures["failed_weeks"] and main:
        text += f" Most lost sorties happen because {CAUSE_WORDS[main]}."
    adds = m["reported"]["mean_2407_adds_per_week"]
    if adds >= 0.05:
        text += f" It relies on about {adds:.1f} 2407 adds per week."
    return text
