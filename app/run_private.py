"""Private front door: the same engine and pages, on your own inputs, on your own machine.

    python app/run_private.py --config private/inputs.json [--runs 2000] [--seed 20261004]
                              [--history private/history.csv] [--times planned|flown] [--lookback 4]
    python -m http.server -d private/site 8000          # then open http://localhost:8000

--config may be one TPS config or a folder of them. Writes private/data (the results JSON) and
private/site (the Overview, Results and Method pages showing them). private/ is gitignored, so
nothing here is committed or published.

With a history file (private/history.csv is used if it exists), it also backtests your own past
weeks against the first config [B-6]: private/data/backtest.json and backtest_weeks.csv, and the
private Method page shows the backtest as "Done locally" with its results.

Personal-time data only. Work data goes through official channels, never a repo.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from export_site import current_commit, export  # noqa: E402
from tps.L4_evidence.backtest import report_csv, run_backtest  # noqa: E402


def backtest(history: Path, config_path: Path, outs: list[Path], times: str, lookback: int, runs: int) -> dict:
    """Backtest a history file against one config; write the report into each output folder."""
    report = run_backtest(history.read_text(encoding="utf-8-sig"), json.loads(config_path.read_text(encoding="utf-8")),
                          lookback=lookback, times=times, runs=runs)
    report["history_file"], report["config_file"] = history.name, config_path.name
    for out in outs:
        out.mkdir(parents=True, exist_ok=True)
        (out / "backtest.json").write_text(json.dumps(report, indent=1) + "\n")
        (out / "backtest_weeks.csv").write_text(report_csv(report))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default=str(ROOT / "private" / "inputs.json"))
    parser.add_argument("--runs", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20261004)
    parser.add_argument("--history", default=str(ROOT / "private" / "history.csv"),
                        help="your unit's history file to backtest, if it exists")
    parser.add_argument("--times", choices=("planned", "flown"), default="planned",
                        help="time each past week by its planned or flown first launch and last land")
    parser.add_argument("--lookback", type=int, default=4, help="weeks of history behind each week's rates")
    parser.add_argument("--backtest-runs", type=int, default=2000, help="weeks simulated per prediction")
    args = parser.parse_args()
    source = Path(args.config)
    configs = sorted(source.glob("*.json")) if source.is_dir() else [source]
    configs = [c for c in configs if c.name != "inputs.example.json" or source.is_file()]
    if not configs or not all(c.exists() for c in configs):
        print(f"No config at {source}. Copy private/inputs.example.json to private/inputs.json and edit it.")
        return 1
    out = ROOT / "private" / "site"
    out.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "styles.css", "app.js", "site.js", "tour.js", "worker.js", "kit-fallback.css"):
        shutil.copy(ROOT / "site" / name, out / name)
    index = export(configs, out, args.runs, args.seed, current_commit())
    data = ROOT / "private" / "data"
    shutil.rmtree(data, ignore_errors=True)
    shutil.copytree(out / "data", data)
    print(f"{len(index['presets'])} presets from {len(configs)} config(s) -> private/data and private/site")
    history = Path(args.history)
    if history.is_file():
        try:
            report = backtest(history, configs[0], [data, out / "data"], args.times, args.lookback, args.backtest_runs)
        except ValueError as error:
            print(f"Backtest skipped: {error}")
            return 1
        print(f"Backtest of {history.name} against {configs[0].name} ({args.times} times):")
        for line in report["sentences"]:
            print(f"  {line}")
        for problem in report.get("problems", []):
            print(f"  Note: {problem}")
        print("  -> private/data/backtest.json and backtest_weeks.csv")
    print("Open with: python -m http.server -d private/site 8000")
    return 0


if __name__ == "__main__":
    sys.exit(main())
