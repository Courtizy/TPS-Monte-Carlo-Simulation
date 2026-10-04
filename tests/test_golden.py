"""Golden outputs: the engine must keep producing exactly what it produced before the kit migration.

tests/golden/golden.json was captured from the code before anything moved. If a deliberate change to
the simulation moves it, re-capture with `python tests/golden/capture.py` and say why in CHANGELOG.md.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "golden"))
import capture  # noqa: E402

GOLDEN = json.loads((Path(__file__).resolve().parent / "golden" / "golden.json").read_text())


# [A-5]
def test_engine_matches_golden_outputs():
    now = capture.capture()
    assert set(now) == set(GOLDEN), "public configs changed; re-capture deliberately"
    for name, expected in GOLDEN.items():
        assert now[name]["engine_digest"] == expected["engine_digest"], f"{name}: simulation output changed"
        assert now[name]["probability_success"] == expected["probability_success"], f"{name}: results changed"
