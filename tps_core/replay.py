"""Watch one simulated week: the play-by-play.

replay() rebuilds any week of a run exactly. It runs the weeks before it with
the fast engine, which leaves the random draws exactly where the original run
had them, then plays the chosen week through the readable engine with its
recorder on [X-2]. It returns the events, a bar for everything each aircraft
did, the story in plain words, and the chain of events behind a failure.
"""
from __future__ import annotations

from random import Random
from typing import Any

from tps_core import reference
from tps_core.engine import compile_plan, coverage_by_day, run_compiled_week
from tps_core.metrics import score_week
from tps_core.schemas import load_scenario

DAY_NAMES = {"Mon": "Monday", "Tue": "Tuesday", "Wed": "Wednesday", "Thu": "Thursday", "Fri": "Friday",
             "Sat": "Saturday", "Sun": "Sunday", "Next Mon": "next Monday"}
ROLE_WORDS = {"planned": "", "lineup": " (from the lineup)", "spare": " (spare)", "2407": " (2407 add)"}
MAX_REPLAY_WEEK = 200_000


# ---------------------------------------------------------------- clock
def clock(hours: float, all_days: tuple[str, ...], first_launch: str | None) -> str:
    """'Wed +10:00', or with a first launch time, 'Wed 17:30' [X-5]."""
    day = min(int(hours // 24), len(all_days) - 1)
    offset = hours - 24 * day
    if not first_launch:
        h, m = divmod(round(offset * 60), 60)
        return f"{all_days[day]} +{h}:{m:02d}"
    fh, fm = (int(x) for x in first_launch.split(":"))
    total = fh * 60 + fm + round(offset * 60)
    day = min(day + total // 1440, len(all_days) - 1)
    h, m = divmod(total % 1440, 60)
    return f"{all_days[day]} {h:02d}:{m:02d}"


# ---------------------------------------------------------------- choosing weeks
def pick_weeks(weeks: list[tuple[list[dict], dict]], flying_days: tuple[str, ...]) -> dict[str, int | None]:
    """Weeks worth watching: typical, typical failure, worst, and failed only at recovery [X-3]."""
    scores = [score_week(days, week, flying_days) for days, week in weeks]
    if not scores:
        return {}
    flown = sorted(s["total_sorties"] for s in scores)
    middle = flown[len(flown) // 2]
    typical = min(range(len(scores)), key=lambda i: (abs(scores[i]["total_sorties"] - middle), not scores[i]["succeeds"], i))
    failed = [i for i, s in enumerate(scores) if not s["succeeds"]]
    typical_failure = None
    on_flying_days = [i for i in failed if scores[i]["first_failure_day"] in flying_days] or failed
    if on_flying_days:
        days = {}
        for i in on_flying_days:
            days[scores[i]["first_failure_day"]] = days.get(scores[i]["first_failure_day"], 0) + 1
        common = max(days, key=days.get)
        typical_failure = next(i for i in on_flying_days if scores[i]["first_failure_day"] == common)
    worst = min(range(len(scores)), key=lambda i: (scores[i]["total_sorties"], scores[i]["next_monday_ready"], i))
    recovery_only = next((i for i in failed if scores[i]["failure_modes"] == ["Recovery"]), None)
    return {"typical": typical, "typical_failure": typical_failure, "worst": worst, "recovery_only": recovery_only}


# ---------------------------------------------------------------- the replay
def replay(config: dict[str, Any], seed: int, week_index: int) -> dict[str, Any]:
    scenario = load_scenario(config)
    if not 0 <= week_index < MAX_REPLAY_WEEK:
        raise ValueError(f"week must be between 1 and {MAX_REPLAY_WEEK:,}")
    plan = compile_plan(scenario)
    rng = Random(seed)
    for _ in range(week_index):
        run_compiled_week(plan, rng)
    state = rng.getstate()
    fast = run_compiled_week(plan, rng)
    rng.setstate(state)
    log: list[dict[str, Any]] = []
    days, week = reference.run_week(scenario, rng, log)
    rules = scenario.rules
    all_days = rules.all_days
    score = score_week(days, week, rules.flying_days)
    first_launch = scenario.options.first_launch_time
    t = lambda hours: clock(hours, all_days, first_launch)  # noqa: E731
    return {
        "week": week_index + 1,
        "seed": seed,
        "matches_run": fast == (days, week),
        "succeeds": score["succeeds"],
        "failure_modes": score["failure_modes"],
        "first_failure_day": score["first_failure_day"],
        "days": all_days,
        "flying_days": rules.flying_days,
        "go_times": [list(p) for p in scenario.options.go_times],
        "first_launch_time": first_launch,
        "week_hours": 24 * len(all_days),
        "start_mc": week["repair_backlog"] + days[-1]["available_eod"],
        "down_at_start": scenario.inventory.pai - (week["repair_backlog"] + days[-1]["available_eod"]),
        "recovery": {"ready": days[-1]["available_eod"], "target": score["recovery_target"]},
        "day_rows": [{k: d[k] for k in ("day", "planned_sorties", "sorties_flown", "lost_sorties", "code_3",
                                        "ground_abort", "mc_aircraft_for_flying", "aircraft_required")} for d in days],
        "tails": _tail_bars(log, scenario, 24 * len(all_days), week["repair_backlog"] + days[-1]["available_eod"]),
        "lost": [{"t": e["t"], "day": e["day"], "go": e["go"], "cause": e["cause"]} for e in log if e["kind"] == "lost"],
        "story": _story(log, days, score, all_days, t),
        "why": _why(log, days, score, scenario, t),
        "events": log,
    }


def _tail_bars(log, scenario, week_end: float, start_mc: int) -> list[dict[str, Any]]:
    """Everything each MC aircraft did, as bars: flying, waiting, in fix, paused, down [X-1].

    Every aircraft MC at the start of the week gets a row, including ones that sat ready all week.
    """
    coverage = coverage_by_day(scenario.rules.all_days, scenario.options)
    tails = {i: {"tail": i + 1, "bars": [], "marks": []} for i in range(start_mc)}
    for e in log:
        if "tail" not in e:
            continue
        row = tails.setdefault(e["tail"], {"tail": e["tail"] + 1, "bars": [], "marks": []})
        if e["kind"] == "launch":
            row["bars"].append({"kind": "fly", "start": e["t"], "end": e["land"], "go": e["go"], "role": e["role"]})
        elif e["kind"] == "abort":
            row["marks"].append({"kind": "abort", "t": e["t"], "go": e["go"]})
        elif e["kind"] == "break":
            row["marks"].append({"kind": "break", "t": e["t"], "go": e["go"], "rebreak": e["rebreak"]})
        elif e["kind"] == "fix":
            if e["beyond"]:
                row["bars"].append({"kind": "down", "start": e["t"], "end": week_end, "reason": e["reason"]})
                continue
            if e["clock_start"] > e["t"]:
                row["bars"].append({"kind": "wait", "start": e["t"], "end": e["clock_start"], "reason": "first-day rule"})
            row["bars"].extend(_fix_pieces(e["clock_start"], e["ready"], coverage, e["window"], week_end))
    return [tails[i] for i in sorted(tails)]


def _fix_pieces(start: float, ready: float, coverage: list[float], window: float, week_end: float) -> list[dict]:
    """A fix bar, split where the weekend clock pauses."""
    pieces, t = [], start
    end = min(ready, week_end)
    while t < end - 1e-9:
        day = int(t // 24)
        covered_until = 24 * day + (coverage[day] if day < len(coverage) else 24)
        day_end = 24 * (day + 1)
        if t < covered_until:
            stop = min(end, covered_until)
            pieces.append({"kind": "fix", "start": t, "end": stop, "window": window})
        else:
            stop = min(end, day_end)
            pieces.append({"kind": "paused", "start": t, "end": stop})
        t = stop if stop > t else day_end
    merged = []
    for p in pieces:
        if merged and merged[-1]["kind"] == p["kind"] and abs(merged[-1]["end"] - p["start"]) < 1e-9:
            merged[-1]["end"] = p["end"]
        else:
            merged.append(dict(p))
    return merged


def _story(log, days, score, all_days, t) -> list[dict[str, Any]]:
    """The week in plain sentences, grouped by day [X-1]."""
    by_day: dict[str, list[dict[str, Any]]] = {d: [] for d in all_days}
    launches: dict[tuple[str, int], list[int]] = {}
    go_lines: dict[tuple[str, int], dict[str, Any]] = {}
    for e in log:
        kind = e["kind"]
        if kind == "day":
            spare_text = f", {len(e['spares'])} spare{'s' if len(e['spares']) != 1 else ''}" if e["spares"] else ""
            by_day[e["day"]].append({"h": e["t"], "p": 0, "t": t(e["t"]), "tone": "danger" if e["ready"] < e["needed"] else "",
                                     "text": f"{e['ready']} aircraft ready, {e['needed']} needed "
                                             f"({e['first_go']} on the first go{spare_text})."})
        elif kind == "go":
            line = {"h": e["t"], "p": 1, "t": t(e["t"]), "tone": "", "text": "", "go": e["go"], "needed": e["needed"]}
            go_lines[(e["day"], e["go"])] = line
            by_day[e["day"]].append(line)
        elif kind == "launch":
            launches.setdefault((e["day"], e["go"]), []).append(e["tail"] + 1)
            if e["role"] in ("spare", "2407", "lineup"):
                by_day[e["day"]].append({"h": e["t"], "p": 4, "t": t(e["t"]), "tone": "", "text": f"Tail {e['tail'] + 1} launches on go {e['go']}{ROLE_WORDS[e['role']]}."})
        elif kind == "abort":
            by_day[e["day"]].append({"h": e["t"], "p": 2, "t": t(e["t"]), "tone": "warn", "text": f"Tail {e['tail'] + 1} ground aborts on go {e['go']}."})
        elif kind == "break":
            note = " again (repeat or recur)" if e["rebreak"] else ""
            by_day[e["day"]].append({"h": e["t"], "p": 2, "t": t(e["t"]), "tone": "warn", "text": f"Tail {e['tail'] + 1} lands Code 3{note} from go {e['go']}."})
        elif kind == "fix":
            day = all_days[min(int(e["t"] // 24), len(all_days) - 1)]
            if e["beyond"]:
                text = f"Tail {e['tail'] + 1} won't be fixed within the longest window: down for the week."
            else:
                wait = f" Work starts {t(e['clock_start'])} (first-day rule)." if e["clock_start"] > e["t"] else ""
                text = f"Tail {e['tail'] + 1}: {e['window']:g}-hour fix, ready {t(e['ready'])}.{wait}"
            by_day[day].append({"h": e["t"], "p": 3, "t": t(e["t"]), "tone": "", "text": text})
        elif kind == "lost":
            by_day[e["day"]].append({"h": e["t"], "p": 5, "t": t(e["t"]), "tone": "danger", "text": f"Go {e['go']} sortie lost: {_cause_words(e['cause'])}."})
    for (day, go), line in go_lines.items():
        tails = launches.get((day, go), [])
        flown = f"{len(tails)} of {line['needed']} flown" + (f" (tails {_tail_list(tails)})" if tails else "")
        line["text"] = f"Go {go} launches: {flown}."
        line["tone"] = "danger" if len(tails) < line["needed"] else ""
        del line["go"], line["needed"]
    out = []
    for index, d in enumerate(days):
        lines = sorted(by_day.get(d["day"], []), key=lambda line: (line["h"], line["p"]))
        lines = [{k: v for k, v in line.items() if k not in ("h", "p")} for line in lines]
        status = (f"{d['sorties_flown']} of {d['planned_sorties']} flown" if d["planned_sorties"]
                  else f"{d['available_eod']} aircraft ready" if d["day"] == all_days[-1] else "Repairs only")
        failed = d["day"] == score["first_failure_day"] or (d["day"] == all_days[-1] and not score["recovery"])
        out.append({"day": d["day"], "status": status, "failed": failed, "lines": lines})
    return out


def _tail_list(tails: list[int]) -> str:
    tails = sorted(tails)
    if len(tails) > 2 and tails == list(range(tails[0], tails[-1] + 1)):
        return f"{tails[0]}–{tails[-1]}"
    return ", ".join(map(str, tails))


def _tails_phrase(tails: list[int]) -> str:
    names = [str(x + 1) for x in tails]
    if len(names) == 1:
        return f"Tail {names[0]}"
    return f"Tails {', '.join(names[:-1])} and {names[-1]}"


def _cause_words(cause: str) -> str:
    return {"lost_turn_short": "no aircraft back in time",
            "lost_abort_uncovered": "an abort with no spare left",
            "lost_first_go_short": "too few aircraft ready for the first go"}[cause]


def _last_fix_before(log, tail: int, at: float) -> dict | None:
    fixes = [e for e in log if e["kind"] == "fix" and e["tail"] == tail and e["t"] <= at]
    return fixes[-1] if fixes else None


def _down_reason(log, tail: int, at: float, t) -> str:
    fix = _last_fix_before(log, tail, at)
    if not fix:
        return f"Tail {tail + 1} was down."
    what = "aborted" if fix["reason"] == "abort" else "broke again" if fix["reason"] == "repeat or recur" else "broke"
    when = t(fix["t"]).split(" ")[0]
    if fix["beyond"]:
        return f"Tail {tail + 1} {what} {when} and wasn't fixed within the longest window."
    return f"Tail {tail + 1} {what} {when} and needed {fix['window']:g} hours (ready {t(fix['ready'])})."


def _why(log, days, score, scenario, t) -> list[str]:
    """The chain of events behind the week's first failure [X-4]."""
    if score["succeeds"]:
        return ["This week succeeded: every planned sortie flew and enough aircraft were ready next Monday."]
    allow_2407 = scenario.options.allow_2407_adds
    failure_day = score["first_failure_day"]
    lines: list[str] = []
    if failure_day in DAY_NAMES and failure_day != "Next Mon":
        row = next(d for d in days if d["day"] == failure_day)
        name = DAY_NAMES[failure_day]
        lost = [e for e in log if e["kind"] == "lost" and e["day"] == failure_day]
        day_event = next((e for e in log if e["kind"] == "day" and e["day"] == failure_day), None)
        if lost:
            gos = sorted({e["go"] for e in lost})
            go_text = " and ".join(map(str, gos))
            lines.append(f"{name} missed its plan by {len(lost)} sortie{'s' if len(lost) > 1 else ''} "
                         f"on go{'es' if len(gos) > 1 else ''} {go_text}.")
        elif day_event and day_event["ready"] < day_event["needed"]:
            lines.append(f"{name} started with {day_event['ready']} aircraft ready for a front line of {day_event['needed']}.")
        if day_event and day_event["ready"] < day_event["first_go"]:
            for d in day_event["down"][:3]:
                lines.append(_down_reason(log, d["tail"], 24 * days.index(row), t))
        seen: set[tuple[int, str]] = set()
        for e in lost:
            key = (e["go"], e["cause"])
            if key in seen or len(lines) >= 5:
                continue
            seen.add(key)
            if e["cause"] == "lost_abort_uncovered":
                aborts = [a for a in log if a["kind"] == "abort" and a["day"] == failure_day and a["t"] <= e["t"]]
                spares = len(day_event["spares"]) if day_event else 0
                abort_goes = sorted({a["go"] for a in aborts})
                lines.append(f"{_tails_phrase([a['tail'] for a in aborts])} ground aborted on "
                             f"go{'es' if len(abort_goes) > 1 else ''} {' and '.join(map(str, abort_goes))}; with {spares} spare"
                             f"{'s' if spares != 1 else ''} on the front line, go {e['go']} ran out of replacements.")
            elif e["cause"] == "lost_turn_short":
                earlier = [b for b in log if b["kind"] in ("break", "abort") and b["day"] == failure_day and b["t"] <= e["t"]]
                for b in earlier[:3]:
                    fix = _last_fix_before(log, b["tail"], b["t"] + 0.001)
                    verb = "aborted" if b["kind"] == "abort" else "broke"
                    if fix and fix["beyond"]:
                        lines.append(f"Tail {b['tail'] + 1} {verb} on go {b['go']} and is down for the week.")
                    elif fix and fix["ready"] > e["t"]:
                        lines.append(f"Tail {b['tail'] + 1} {verb} on go {b['go']} and needed {fix['window']:g} hours "
                                     f"(ready {t(fix['ready'])}), too late for go {e['go']}.")
            elif e["cause"] == "lost_first_go_short" and day_event:
                lines.append(f"Only {day_event['ready']} aircraft were ready for a first go of {day_event['first_go']}.")
                for d in day_event["down"][:2]:
                    lines.append(_down_reason(log, d["tail"], e["t"], t))
        if lost:
            lines.append("2407 adds were off." if not allow_2407 else "No unscheduled aircraft were ready for a 2407 add.")
        if not lines:
            lines.append(f"{name} failed: {', '.join(score['failure_modes']).lower()}.")
    elif failure_day == "Next Mon" or not score["recovery"]:
        ready, target = days[-1]["available_eod"], score["recovery_target"]
        lines.append(f"Every sortie flew, but only {ready} aircraft were ready next Monday; {target} were needed.")
        down = [e for e in log if e["kind"] == "fix"]
        latest = {}
        for e in down:
            latest[e["tail"]] = e
        still = [e for e in latest.values() if e["beyond"] or (e["ready"] or 0) > 24 * (len(days) - 1)]
        for e in still[:3]:
            lines.append(_down_reason(log, e["tail"], e["t"] + 0.001, t))
        if scenario.options.weekend_coverage_hours and any(h < 24 for _, h in scenario.options.weekend_coverage_hours):
            hours = dict(scenario.options.weekend_coverage_hours)
            lines.append(f"Weekend repair hours: Saturday {hours.get('Sat', 24)}, Sunday {hours.get('Sun', 24)}.")
    else:
        lines.append(f"The week fell short: {', '.join(score['failure_modes']).lower()}.")
    return lines
