"""What-if sweeps: run many variants of one plan, each with a reproducible seed.

Each variant's seed is derived from the sweep's main seed and the variant's
position, so a sweep re-runs identically however its variants are split across
workers.
"""
from __future__ import annotations

import copy
import hashlib
from typing import Any

from tps.L4_evidence.runs import new_seed, run_plan
from tps.L0_inputs.schemas import fingerprint


# [A-2]
def derive_seed(main_seed: int, index: int) -> int:
    digest = hashlib.sha256(f"tps-sweep:{int(main_seed)}:{int(index)}".encode()).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF


def apply_patch(config: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge a patch into a copy of the config (a null value removes a key)."""
    result = copy.deepcopy(config)

    def merge(target: dict, changes: dict) -> None:
        for key, value in changes.items():
            if value is None:
                target.pop(key, None)
            elif isinstance(value, dict) and isinstance(target.get(key), dict):
                merge(target[key], value)
            else:
                target[key] = copy.deepcopy(value)

    merge(result, patch)
    return result


def plan_sweep(config: dict[str, Any], variants: list[dict[str, Any]], seed: int | None = None) -> dict[str, Any]:
    """A sweep's jobs: one per variant, each with its config and derived seed."""
    seed = new_seed() if seed is None else int(seed)
    jobs = []
    for index, variant in enumerate(variants):
        jobs.append({
            "index": index,
            "label": variant.get("label", f"Variant {index + 1}"),
            "patch": variant.get("patch", {}),
            "config": apply_patch(config, variant.get("patch", {})),
            "seed": derive_seed(seed, index),
        })
    return {"main_seed": seed, "base_fingerprint": fingerprint(config), "jobs": jobs}


def run_sweep(config: dict[str, Any], variants: list[dict[str, Any]], iterations: int,
              seed: int | None = None) -> dict[str, Any]:
    """Run every variant in order (the browser runs the same jobs in parallel workers)."""
    sweep = plan_sweep(config, variants, seed)
    results = []
    for job in sweep["jobs"]:
        record = run_plan(job["config"], iterations, job["seed"], example_weeks=0)
        results.append({"index": job["index"], "label": job["label"], "patch": job["patch"], "record": record})
    return {"main_seed": sweep["main_seed"], "base_fingerprint": sweep["base_fingerprint"],
            "iterations": iterations, "results": results}
