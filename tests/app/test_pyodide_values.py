"""Values as Pyodide hands them to Python from the browser.

In Pyodide 0.29, a JavaScript null arrives as a JsNull object (and undefined as
JsUndefined in some paths), not None. The web API must treat both as missing.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from helpers import ROOT, example  # noqa: E402
from tps_core import web_api  # noqa: E402


class JsNull:   # stand-in with the same type name Pyodide uses
    pass


class JsUndefined:
    pass


def test_blank_seed_from_the_browser_picks_a_seed():
    for missing in (None, JsNull(), JsUndefined()):
        record = json.loads(web_api.run(json.dumps(example()), 100, missing))
        assert "errors" not in record and isinstance(record["seed"], int)
        jobs = json.loads(web_api.sweep_jobs(json.dumps(example()), json.dumps([{"label": "a"}]), missing))
        assert isinstance(jobs["main_seed"], int)


def test_worker_never_sends_null_for_optional_values():
    worker = (ROOT / "app" / "web" / "worker.js").read_text()
    assert not re.search(r"\?\?\s*null", worker), "send undefined (or leave the value out), not null, to Python"
