"""Build the static proof-of-concept site into ./site.

    python scripts/build_site.py [--out site] [--commit SHA]

Stamps the model package with the commit and build time, zips it for the
browser, copies the web files and synthetic examples, and checks every example
config loads. GitHub Actions runs this on each push; you can run it locally too.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def current_commit() -> str:
    if os.environ.get("GITHUB_SHA"):
        return os.environ["GITHUB_SHA"]
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "local"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="site")
    parser.add_argument("--commit", default=None)
    args = parser.parse_args()
    out = ROOT / args.out
    commit = args.commit or current_commit()
    built_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    sys.path.insert(0, str(ROOT))
    from tps_core.schemas import validate_config
    from tps_core.version import __version__

    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "web", out)
    # The brand kit's web assets (stylesheet, icons, chart palette) ship with the site.
    for part in ("css", "icons", "js"):
        if (ROOT / "brand" / part).exists():
            shutil.copytree(ROOT / "brand" / part, out / "brand" / part)
    (out / ".nojekyll").write_text("")

    # Zip the package with the build stamp written in (source files stay untouched).
    stamp = f'"""Build stamp written by scripts/build_site.py."""\nCOMMIT = {commit!r}\nBUILT_AT = {built_at!r}\n'
    with zipfile.ZipFile(out / "tps_core.zip", "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted((ROOT / "tps_core").glob("*.py")):
            arcname = f"tps_core/{path.name}"
            bundle.writestr(arcname, stamp if path.name == "_build.py" else path.read_text(encoding="utf-8"))

    examples_out = out / "examples"
    examples_out.mkdir()
    listing = []
    for path in sorted((ROOT / "examples").glob("*.json")):
        config = json.loads(path.read_text(encoding="utf-8"))
        errors = validate_config(config)
        if errors:
            print(f"{path.name} is not a valid config:\n  " + "\n  ".join(errors))
            return 1
        shutil.copy(path, examples_out / path.name)
        listing.append({"file": path.name, "name": config.get("name", path.stem)})
    (examples_out / "index.json").write_text(json.dumps(listing, indent=2) + "\n")

    build = {"model_version": __version__, "build_commit": commit, "built_at": built_at}
    (out / "build.json").write_text(json.dumps(build, indent=2) + "\n")
    print(f"Built {out} (model {__version__}, commit {commit[:7]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
