"""Public front door: run the engine on configs/public and write what the site displays.

    python scripts/export_site.py [--runs 2000] [--seed 20261004] [--commit SHA] [--stamp]

Writes into site/ (the generated parts are gitignored):
  site/data/presets.json + site/data/preset_<id>.json   precomputed results for every public preset
  site/data/changelog.json                                CHANGELOG.md, for the Method page
  site/brand/                                             the brand kit's css, icons and js
  site/tps.zip, site/examples/                            the engine and public configs, for Run ▸
  site/build.json                                         model version, commit, build time
With --stamp, the page's files are tagged ?v=<commit> so browsers never show a stale copy (CI only:
it edits site/index.html and site/app.js in place).

app/run_private.py reuses export() to build the same pages from private inputs, on your own machine.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from tps import run_plan  # noqa: E402
from tps.L0_inputs.presets import RECOVERY, SCENARIOS, scenario_config  # noqa: E402
from tps.L0_inputs.schemas import load_scenario, validate_config  # noqa: E402
from tps.version import __version__  # noqa: E402

FLYING_STATUS = ((0.98, "good", "On track"), (0.90, "warning", "At risk"), (0.0, "critical", "Shortfall"))


def current_commit() -> str:
    if os.environ.get("GITHUB_SHA"):
        return os.environ["GITHUB_SHA"]
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "local"


def day_status(p_met: float) -> tuple[str, str]:
    for floor, level, label in FLYING_STATUS:
        if p_met >= floor:
            return level, label
    return "critical", "Shortfall"


def insights_for(config: dict, record: dict, runs: int, seed: int, with_search: bool) -> dict:
    """Everything the shared results views show, precomputed by the engine so the public page only displays it."""
    from tps.L0_inputs.seasonality import has_seasonality, season_view
    from tps.L1_engine.replay import replay
    from tps.L3_levers.levers import build_levers
    from tps.L3_levers.sensitivity import INPUTS, break_even, describe
    from tps.L3_levers.sweep import apply_patch
    slim = lambda r: {"metrics": r["metrics"], "seed": r["seed"]}  # noqa: E731
    fixes = []
    for lever in build_levers(config, record["metrics"]):
        result = run_plan(apply_patch(config, lever["patch"]), runs, seed, example_weeks=0)
        fixes.append({**{k: v for k, v in lever.items() if k != "patch"}, "record": slim(result)})
    margins = []
    for name in INPUTS:
        m = break_even(config, name, seed, min(1000, runs), 0.85)
        m["sentence"] = describe(m)
        margins.append(m)
    replays = {}
    for key, week in (record.get("replay_weeks") or {}).items():
        if week is not None and str(week) not in replays:
            r = replay(config, seed, week)
            r.pop("events", None)
            replays[str(week)] = r
    out = {"fixes": fixes, "margins": margins, "replays": replays,
           "season": season_view(config, min(1000, runs), seed) if has_seasonality(config) else None, "search": None}
    if with_search:
        from tps.L3_levers.patterns import analyze, generate
        from tps.L3_levers.sweep import plan_sweep
        gen = generate(config, budget=90, seed=seed)
        jobs = plan_sweep(config, gen["candidates"], seed)["jobs"]
        results = []
        for cand, job in zip(gen["candidates"], jobs):
            met = run_plan(job["config"], 500, seed, example_weeks=0)["metrics"]
            results.append({**{k: v for k, v in cand.items() if k != "patch"}, "index": job["index"], "metrics": met})
        analysis = analyze(config, results, 0.85)
        out["search"] = {"analysis": analysis, "screenWeeks": 500,
                         "results": [{**{k: v for k, v in r.items() if k != "metrics"}, "record": {"metrics": {
                             "probability_success": r["metrics"]["probability_success"]}}} for r in results]}
    return out


def preset_result(unit_id: str, base: dict, scenario: str, recovery: str, runs: int, seed: int, stamp: dict) -> dict:
    """One preset, run by the engine, in the JSON shape the Results page reads."""
    config = scenario_config(base, scenario, recovery)
    full = run_plan(config, runs, seed)
    record = full
    m = record["metrics"]
    sc = load_scenario(config)
    days = []
    for d in [d for d in sc.rules.flying_days if d in m["daily"]]:
        daily = m["daily"][d]
        p_met = 1 - daily["share_missing_schedule"]
        level, label = day_status(p_met)
        days.append({"day": d, "sorties_planned": sc.schedule[d].daily_sorties, "needed": daily["aircraft_needed"],
                     "p_day_met": p_met, "available_p10": daily["ready_p10"], "available_p50": daily["ready_p50"],
                     "available_p90": daily["ready_p90"], "status": level, "status_label": label})
    nm = m["distributions"]["next_monday_ready"]
    p_rec = 1 - m["recovery"]["share_short"]
    level, label = day_status(p_rec)
    days.append({"day": "Next Mon", "sorties_planned": 0, "needed": m["recovery"]["target"], "p_day_met": p_rec,
                 "available_p10": nm["p10"], "available_p50": nm["p50"], "available_p90": nm["p90"],
                 "status": level, "status_label": label})
    weakest = min(days, key=lambda r: r["p_day_met"])
    rates = config["rates"]
    windows = rates.get("fix_windows") or [{"hours": h, "rate": rates[k]} for k, h in
                                           (("fix_8hr_rate", 8), ("fix_12hr_rate", 12), ("fix_24hr_rate", 24)) if k in rates]
    return {
        "id": f"{unit_id}__{scenario}__{recovery}",
        "unit": unit_id, "unit_name": base.get("name", unit_id),
        "scenario": scenario, "scenario_label": SCENARIOS[scenario][0], "scenario_note": SCENARIOS[scenario][1],
        "recovery": recovery, "recovery_label": RECOVERY[recovery][0], "recovery_note": RECOVERY[recovery][1],
        "simulation": {
            "runs": runs, "runs_used": m["iterations"], "seed": seed,
            "inputs": {
                "pai": sc.inventory.pai, "mc_rate": rates["mc_rate"], "break_rate": rates["break_rate"],
                "ground_abort_rate": rates["ground_abort_rate"], "fix_windows": windows,
                "commit_rate": sc.rules.commit_rate, "spare_rate": sc.rules.spare_rate,
                "goes_per_day": sc.goes_per_day, "weekly_sorties": m["plan"]["planned_sorties"],
                "required_sorties": m["plan"]["required_sorties"],
                "weekend_hours": config.get("options", {}).get("weekend_coverage_hours", {}),
                "fleet_flex": recovery == "flex",
            },
        },
        "kpis": {
            "weeks_meeting_every_requirement": m["probability_success"],
            "ci95": [m["ci95_low"], m["ci95_high"]],
            "sortie_compliance": m["goes"]["sortie_generation_effectiveness"],
            "available_median": median(r["available_p50"] for r in days[:-1]) if len(days) > 1 else None,
            "ready_next_monday_median": nm["p50"], "recovery_target": m["recovery"]["target"],
            "adds_2407_per_week": m["reported"]["mean_2407_adds_per_week"],
        },
        "binding": {"day": weakest["day"], "p_day_met": weakest["p_day_met"],
                    "requirement": "recovery next Monday" if weakest["day"] == "Next Mon" else "every planned sortie"},
        "summary": m["summary_text"],
        "days": days,
        "record": full,
        "insights": insights_for(config, full, runs, seed, with_search=(scenario == "baseline" and recovery == "spares")),
        **stamp,
    }


def parse_changelog(text: str) -> list[dict]:
    """'## [0.10.0] - 2026-10-04' headings with '- ' bullets under each."""
    entries, current = [], None
    for line in text.splitlines():
        head = re.match(r"^## \[([^\]]+)\]\s*-\s*(\S+)", line)
        if head:
            current = {"version": head.group(1), "date": head.group(2), "changes": []}
            entries.append(current)
        elif current and line.startswith("- "):
            current["changes"].append(line[2:].strip())
    return entries


def export(configs: list[Path], out: Path, runs: int, seed: int, commit: str, include_engine: bool = True) -> dict:
    built_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    stamp = {"generated_at": built_at, "model_version": __version__, "commit": commit}
    out.mkdir(parents=True, exist_ok=True)
    for part in ("css", "icons", "js"):
        if (ROOT / "brand" / part).exists():
            shutil.rmtree(out / "brand" / part, ignore_errors=True)
            shutil.copytree(ROOT / "brand" / part, out / "brand" / part)
    (out / ".nojekyll").write_text("")

    units = []
    for path in configs:
        config = json.loads(path.read_text(encoding="utf-8"))
        errors = validate_config(config)
        if errors:
            raise SystemExit(f"{path.name} is not a valid config:\n  " + "\n  ".join(errors))
        units.append((path.stem, config))

    data = out / "data"
    shutil.rmtree(data, ignore_errors=True)
    data.mkdir()
    index = {"units": [{"id": u, "name": c.get("name", u)} for u, c in units],
             "scenarios": [{"id": k, "label": v[0], "note": v[1]} for k, v in SCENARIOS.items()],
             "recovery": [{"id": k, "label": v[0], "note": v[1]} for k, v in RECOVERY.items()],
             "default": None, "presets": [], **stamp}
    for unit_id, config in units:
        for scenario in SCENARIOS:
            for recovery in RECOVERY:
                result = preset_result(unit_id, config, scenario, recovery, runs, seed, stamp)
                (data / f"preset_{result['id']}.json").write_text(json.dumps(result, separators=(",", ":")) + "\n")
                index["presets"].append({"id": result["id"], "unit": unit_id, "scenario": scenario, "recovery": recovery,
                                         "weeks_meeting_every_requirement": result["kpis"]["weeks_meeting_every_requirement"]})
    preferred = [p for p in index["presets"] if p["scenario"] == "baseline" and p["recovery"] == "spares"]
    index["default"] = next((p["id"] for p in preferred if p["unit"] == "synthetic_week"), preferred[0]["id"] if preferred else None)
    (data / "presets.json").write_text(json.dumps(index, indent=1) + "\n")
    changelog = ROOT / "CHANGELOG.md"
    entries = parse_changelog(changelog.read_text(encoding="utf-8")) if changelog.exists() else []
    (data / "changelog.json").write_text(json.dumps(entries, indent=1) + "\n")

    if include_engine:   # what Run ▸ needs: the engine for Pyodide and the public configs
        bundle_stamp = f'"""Build stamp written by scripts/export_site.py."""\nCOMMIT = {commit!r}\nBUILT_AT = {built_at!r}\n'
        with zipfile.ZipFile(out / "tps.zip", "w", zipfile.ZIP_DEFLATED) as bundle:
            package = ROOT / "src" / "tps"
            for path in sorted(package.rglob("*.py")):
                arcname = "tps/" + path.relative_to(package).as_posix()
                bundle.writestr(arcname, bundle_stamp if arcname == "tps/_build.py" else path.read_text(encoding="utf-8"))
        examples = out / "examples"
        shutil.rmtree(examples, ignore_errors=True)
        examples.mkdir()
        for unit_id, config in units:
            (examples / f"{unit_id}.json").write_text(json.dumps(config, indent=2) + "\n")
        (examples / "index.json").write_text(json.dumps([{"file": f"{u}.json", "name": c.get("name", u)} for u, c in units], indent=2) + "\n")
        template = ROOT / "configs" / "public" / "history_template.csv"
        if template.exists():
            shutil.copy(template, examples / "history_template.csv")
    (out / "build.json").write_text(json.dumps({"model_version": __version__, "build_commit": commit, "built_at": built_at}, indent=2) + "\n")
    return index


def stamp_files(out: Path, commit: str) -> None:
    """Tag what the page loads with the commit, so a new deploy is never hidden by the browser cache."""
    tag = "".join(ch for ch in commit if ch.isalnum())[:12] or "dev"
    index = out / "index.html"
    html = index.read_text(encoding="utf-8")
    for ref in ('href="brand/css/brand.css"', 'href="styles.css"', 'src="app.js"', 'src="site.js"', 'src="tour.js"'):
        html = html.replace(ref, ref[:-1] + f'?v={tag}"')
    index.write_text(html, encoding="utf-8")
    app = out / "app.js"
    app.write_text(app.read_text(encoding="utf-8").replace('new Worker("worker.js")', f'new Worker("worker.js?v={tag}")'), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20261004)
    parser.add_argument("--commit", default=None)
    parser.add_argument("--stamp", action="store_true", help="tag page files with ?v=<commit> (CI)")
    args = parser.parse_args()
    commit = args.commit or current_commit()
    configs = sorted(p for p in (ROOT / "configs" / "public").glob("*.json"))
    index = export(configs, ROOT / "site", args.runs, args.seed, commit)
    if args.stamp:
        stamp_files(ROOT / "site", commit)
    print(f"Exported {len(index['presets'])} presets to site/data (model {__version__}, commit {commit[:7]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
