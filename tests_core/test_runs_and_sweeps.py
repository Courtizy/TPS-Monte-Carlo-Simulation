import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import example  # noqa: E402
from tps_core import web_api  # noqa: E402
from tps_core.metrics import wilson_interval  # noqa: E402
from tps_core.runs import run_plan, verify_record  # noqa: E402
from tps_core.sweep import apply_patch, derive_seed, plan_sweep, run_sweep  # noqa: E402


def test_same_seed_same_record_metrics():
    a, b = run_plan(example(), 500, 7), run_plan(example(), 500, 7)
    assert a["metrics_fingerprint"] == b["metrics_fingerprint"]
    assert run_plan(example(), 500, 8)["metrics_fingerprint"] != a["metrics_fingerprint"]


def test_record_survives_json_and_verifies():
    record = json.loads(json.dumps(run_plan(example(), 400, 11)))
    result = verify_record(record)
    assert result["identical"] and not result["problems"]


# [A-1]
@pytest.mark.parametrize("tamper, words", [
    (lambda r: r["metrics"].update(probability_success=0.999), "stored metrics were changed"),
    (lambda r: r["config"]["rates"].update(break_rate=0.1), "config was changed"),
    (lambda r: r.update(seed=r["seed"] + 1), "different metrics"),
])
def test_tampering_is_detected(tamper, words):
    record = run_plan(example(), 300, 5)
    tamper(record)
    result = verify_record(record)
    assert not result["identical"]
    assert any(words in p for p in result["problems"]), result["problems"]


# [M-4]
def test_wilson_interval():
    low, high = wilson_interval(0, 100)
    assert low < 1e-12 and 0 < high < 0.05
    low, high = wilson_interval(92, 100)
    assert low < 0.92 < high


def test_summary_text_is_plain():
    text = run_plan(example(), 1000, 3)["metrics"]["summary_text"]
    assert text.startswith("Succeeds") or text.startswith("Fails")


# [A-2]
def test_derived_seeds_are_stable_and_distinct():
    assert derive_seed(42, 0) == derive_seed(42, 0)
    assert len({derive_seed(42, i) for i in range(1000)}) == 1000
    assert derive_seed(42, 0) != derive_seed(43, 0)


def test_apply_patch_merges_deeply():
    patched = apply_patch(example(), {"rules": {"spare_rate": 0.0}, "options": {"allow_2407_adds": True}})
    assert patched["rules"]["spare_rate"] == 0.0 and patched["rules"]["commit_rate"] == 0.55
    assert patched["options"]["allow_2407_adds"] is True


def test_sweep_matches_individual_runs():
    variants = [{"label": "As planned"}, {"label": "No spares", "patch": {"rules": {"spare_rate": 0.0}}}]
    sweep = run_sweep(example(), variants, 300, seed=99)
    jobs = plan_sweep(example(), variants, seed=99)["jobs"]
    for result, job in zip(sweep["results"], jobs):
        alone = run_plan(job["config"], 300, job["seed"], example_weeks=0)
        assert result["record"]["metrics_fingerprint"] == alone["metrics_fingerprint"]


def test_web_api_round_trip():
    config_json = json.dumps(example())
    assert json.loads(web_api.check(config_json)) == {"errors": [], "warnings": []}
    record_json = web_api.run(config_json, 200, 4)
    assert json.loads(web_api.verify(record_json))["identical"]
    assert json.loads(web_api.check("{not json"))["errors"]
    assert json.loads(web_api.run(json.dumps(example(inventory={"pai": 0})), 10, 1))["errors"]
