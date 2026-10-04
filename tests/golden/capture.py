"""Capture golden outputs: what the engine simulates for each public config at fixed seeds.

Run once before a migration; tests/test_golden.py checks every later change against it.
The digest covers the engine's raw week-by-week output, so adding a metric or renaming a
JSON field never moves it. Only a change to the simulation itself does.
"""
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIGS = sorted((ROOT / "configs" / "public").glob("*.json")) or sorted((ROOT / "configs" / "public").glob("*.json"))
SEEDS = (11, 2026)
WEEKS = 300


def engine_digest(config: dict, seed: int, weeks: int = WEEKS) -> str:
    from tps.L0_inputs.schemas import load_scenario
    from tps.L1_engine.engine import compile_plan, run_compiled_week
    plan, rng = compile_plan(load_scenario(config)), random.Random(seed)
    h = hashlib.sha256()
    for _ in range(weeks):
        h.update(json.dumps(run_compiled_week(plan, rng), sort_keys=True, default=str).encode())
    return h.hexdigest()


def capture() -> dict:
    from tps import run_plan
    out = {}
    for path in CONFIGS:
        if path.name == "index.json":
            continue
        config = json.loads(path.read_text())
        out[path.stem] = {
            "engine_digest": {str(s): engine_digest(config, s) for s in SEEDS},
            "probability_success": {str(s): run_plan(config, 1000, s, example_weeks=0)["metrics"]["probability_success"] for s in SEEDS},
        }
    return out


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "src"))
    target = Path(__file__).with_name("golden.json")
    target.write_text(json.dumps(capture(), indent=2) + "\n")
    print(f"wrote {target}")
