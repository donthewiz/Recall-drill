"""Static rules that keep JS semantics in recalldrill/engine/jscompat.py.

Each rule bans a Python built-in that differs from the JS operation the TS
engine uses (see jscompat's docstring for the differences).
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

import pytest
from engine_test_support import ENGINE_DIR

ENGINE_FILES = sorted(ENGINE_DIR.glob("*.py"))
NOT_JSCOMPAT = [p for p in ENGINE_FILES if p.name != "jscompat.py"]


def _ids(paths: list[Path]) -> list[str]:
    return [p.name for p in paths]


def _code_only(source: str) -> str:
    """The source with comments removed and every string literal replaced by a
    placeholder (so `s.split(" ")` stays a call with an argument)."""
    out: list[str] = []
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.COMMENT:
            continue
        if tok.type in (tokenize.STRING, tokenize.FSTRING_MIDDLE):
            out.append("_STR_")
        else:
            out.append(tok.string)
    return "".join(out)  # tokens only: `s . strip ( )` becomes `s.strip()`


def _non_docstring_strings(source: str) -> list[str]:
    tree = ast.parse(source)
    docstrings = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


@pytest.mark.parametrize("path", NOT_JSCOMPAT, ids=_ids(NOT_JSCOMPAT))
def test_no_python_round(path: Path) -> None:
    """Python's round() is banker's rounding; JS Math.round is jscompat.js_round."""
    source = path.read_text(encoding="utf-8")
    assert not re.findall(r"(?<![\w.])round\(", source)


SUM_CALL = re.compile(r"(?<![\w.])sum\(")


@pytest.mark.parametrize("path", NOT_JSCOMPAT, ids=_ids(NOT_JSCOMPAT))
def test_no_python_sum(path: Path) -> None:
    """Python 3.12+'s sum() of floats is compensated; JS reduce isn't. Use jscompat.js_sum."""
    assert not SUM_CALL.findall(_code_only(path.read_text(encoding="utf-8")))


BARE_TEXT_CALLS = re.compile(
    r"\.(?:split|rsplit|strip|lstrip|rstrip)\(\)"
    r"|\.(?:splitlines|isspace|isdigit|isdecimal|isnumeric|isalnum|isalpha)\("
)


@pytest.mark.parametrize("path", ENGINE_FILES, ids=_ids(ENGINE_FILES))
def test_no_bare_split_or_strip(path: Path) -> None:
    """str.split()/strip() and the is*() predicates use Python's Unicode classes, not
    JS's. Use jscompat (js_trim, js_split_ws, is_js_ws) or an explicit set."""
    code = _code_only(path.read_text(encoding="utf-8"))
    assert not BARE_TEXT_CALLS.findall(code)


@pytest.mark.parametrize("path", NOT_JSCOMPAT, ids=_ids(NOT_JSCOMPAT))
def test_no_unicode_wide_regex_classes(path: Path) -> None:
    """re's \\s, \\d, \\w and \\b are Unicode-wide; the TS patterns' are not. Spell out
    jscompat.JS_WS or [0-9] instead."""
    for value in _non_docstring_strings(path.read_text(encoding="utf-8")):
        assert not re.search(r"\\[sSdDwWbB]", value), value


@pytest.mark.parametrize("path", ENGINE_FILES, ids=_ids(ENGINE_FILES))
def test_engine_source_is_ascii(path: Path) -> None:
    """Invisible characters (NBSP, BOM, the private-use markers) are easy to lose in an
    editor or formatter, so the engine writes every non-ASCII character as an escape or a
    code point."""
    data = path.read_bytes()
    bad = sorted({b for b in data if b > 0x7F})
    assert not bad, f"non-ASCII bytes in {path.name}"


@pytest.mark.parametrize("path", ENGINE_FILES, ids=_ids(ENGINE_FILES))
def test_only_rand_uses_stdlib_random(path: Path) -> None:
    """rand.random() is the engine's one random stream (the port of Math.random)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    if path.name != "rand.py":
        assert "random" not in imports


def test_rules_catch_violations() -> None:
    """The scanners themselves flag what they should, so the tests above can't pass vacuously."""
    assert re.findall(r"(?<![\w.])round\(", "x = round(2.5)")
    assert not re.findall(r"(?<![\w.])round\(", "x = js_round(2.5) + Math.round")
    assert SUM_CALL.findall(_code_only("t = sum(xs)\n"))
    assert not SUM_CALL.findall(_code_only("t = js_sum(xs) + np.sum(xs)  # sum(xs)\n"))
    assert BARE_TEXT_CALLS.findall(_code_only("y = s.strip()\nz = s.split()\nw = c.isdigit()\n"))
    assert not BARE_TEXT_CALLS.findall(_code_only('y = s.strip(CHARS)  # s.strip()\n"s.split()"\n'))
    strings = _non_docstring_strings('"""doc \\\\s"""\nP = "[0-9]\\\\s"\n')
    assert any(re.search(r"\\[sSdDwWbB]", v) for v in strings)
    assert len(strings) == 1
