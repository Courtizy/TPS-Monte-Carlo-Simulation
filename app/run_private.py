"""Private front door: the same engine and pages, on your own inputs, on your own machine.

    python app/run_private.py --config private/inputs.json [--runs 2000] [--seed 20261004]
    python -m http.server -d private/site 8000          # then open http://localhost:8000

--config may be one TPS config or a folder of them. Writes private/data (the results JSON) and
private/site (the Overview, Results and Method pages showing them). private/ is gitignored, so
nothing here is committed or published.

Personal-time data only. Work data goes through official channels, never a repo.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from export_site import current_commit, export  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default=str(ROOT / "private" / "inputs.json"))
    parser.add_argument("--runs", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20261004)
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
    print("Open with: python -m http.server -d private/site 8000")
    return 0


if __name__ == "__main__":
    sys.exit(main())
