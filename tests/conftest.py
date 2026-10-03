"""Put the model package and every layer's test folder on the import path."""
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
for path in [ROOT / "model", TESTS, *sorted(p for p in TESTS.iterdir() if p.is_dir() and not p.name.startswith((".", "__")))]:
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
