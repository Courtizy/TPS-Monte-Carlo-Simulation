"""MODEL_LOGIC.md must stay in step with the code and the tests.

Every rule ID in the document must appear as a [tag] in the model code and in
a test; every tag in the code and tests must be documented; every test and
code location the document names must exist; and the version must match.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = (ROOT / "docs" / "MODEL_LOGIC.md").read_text(encoding="utf-8")
PACKAGE = ROOT / "model" / "tps_core"
# Keyed by path inside the package (e.g. "L1_engine/reference.py"); several files share the name __init__.py.
CODE = {str(p.relative_to(PACKAGE)).replace("\\", "/"): p.read_text(encoding="utf-8") for p in PACKAGE.rglob("*.py")}
TESTS = {str(p.relative_to(ROOT / "tests")): p.read_text(encoding="utf-8") for p in (ROOT / "tests").rglob("test_*.py")
         if p.name != Path(__file__).name}
TAG = re.compile(r"\[([A-Z]-\d+)\]")
RULES = {m.group(1): m.group(0) for m in re.finditer(r"^### ([A-Z]-\d+):.*$", DOC, re.M)}
BLOCKS = dict(zip(re.findall(r"^### ([A-Z]-\d+):", DOC, re.M), re.split(r"^### [A-Z]-\d+:", DOC, flags=re.M)[1:]))


def test_document_has_rules():
    assert len(RULES) >= 40


def test_every_rule_is_in_the_code_and_a_test():
    code_tags = {t for text in CODE.values() for t in TAG.findall(text)}
    test_tags = {t for text in TESTS.values() for t in TAG.findall(text)}
    assert not set(RULES) - code_tags, f"rules with no [tag] in tps_core: {sorted(set(RULES) - code_tags)}"
    assert not set(RULES) - test_tags, f"rules with no [tag] in tests: {sorted(set(RULES) - test_tags)}"


def test_no_undocumented_tags():
    tags = {t for text in list(CODE.values()) + list(TESTS.values()) for t in TAG.findall(text)}
    assert not tags - set(RULES), f"tags missing from MODEL_LOGIC.md: {sorted(tags - set(RULES))}"


def test_named_tests_exist():
    defined = {name for text in TESTS.values() for name in re.findall(r"^def (test_\w+)\(", text, re.M)}
    for rid, block in BLOCKS.items():
        line = re.search(r"\*\*Test:\*\* (.+)", block)
        assert line, f"{rid} names no test"
        for name in re.findall(r"`(test_\w+)`", line.group(1)):
            assert name in defined, f"{rid} names a missing test: {name}"


def _code_file(token: str) -> str | None:
    """The package file a document path refers to, matched from the end (e.g. "L1_engine/reference.py")."""
    token = token.removeprefix("tps_core/")
    if token in CODE:            # an exact path inside the package wins (e.g. the top-level __init__.py)
        return token
    hits = [path for path in CODE if path.endswith("/" + token)]
    return hits[0] if len(hits) == 1 else None


def test_named_code_exists():
    for rid, block in BLOCKS.items():
        line = re.search(r"\*\*Code:\*\* (.+)", block)
        assert line, f"{rid} names no code location"
        current = None
        for token in re.findall(r"`([^`]+)`", line.group(1)):
            if token.endswith(".py"):
                current = _code_file(token)
                assert current, f"{rid} names a file that isn't in the package (or isn't unique): {token}"
            else:
                assert current and token in CODE[current], f"{rid}: `{token}` not found in {current}"


def test_document_version_matches_the_model():
    version = re.search(r'__version__ = "(\d+\.\d+)', CODE["version.py"]).group(1)
    assert f"`tps_core` {version}" in DOC.split("\n", 4)[2], "update the version line at the top of MODEL_LOGIC.md"
