"""tps_core must import only the standard library, so it loads in Pyodide unchanged."""
import ast
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "model" / "tps_core"


# [A-4]
def test_only_standard_library_imports():
    allowed = set(sys.stdlib_module_names) | {"tps_core", "__future__"}
    for path in PACKAGE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module]
            for name in names:
                assert name.split(".")[0] in allowed, f"{path.name} imports {name}"
