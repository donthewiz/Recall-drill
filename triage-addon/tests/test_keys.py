from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

from card_triage import keys
from card_triage.keys import check_key, normalize_key


@pytest.mark.parametrize(
    ("typed", "norm"),
    [
        ("x", "x"),
        ("X", "x"),
        (" T ", "t"),
        ("Shift+T", "shift+t"),
        ("Alt+Ctrl+x", "ctrl+alt+x"),
        ("ctrl + shift + D", "ctrl+shift+d"),
        ("F5", "f5"),
        ("Space", "space"),
        ("@", "@"),
        ("+", "+"),
        ("ㅕ", "ㅕ"),
    ],
)
def test_normalize_accepts_one_key_with_modifiers(typed: str, norm: str) -> None:
    assert normalize_key(typed) == norm


@pytest.mark.parametrize(
    "typed", ["", "  ", "xy", "Ctrl+", "Ctrl+Ctrl+x", "Hyper+x", "Ctrl+xy", "x+y", "F13"]
)
def test_normalize_rejects_what_is_not_one_key(typed: str) -> None:
    assert normalize_key(typed) is None
    assert not check_key(typed).ok


def test_default_key_is_free() -> None:
    result = check_key("x")
    assert result.ok and result.key == "x"


@pytest.mark.parametrize(
    ("typed", "where"),
    [
        ("e", "the reviewer"),
        ("r", "the reviewer"),
        ("u", "the reviewer"),
        ("@", "the reviewer"),
        ("1", "the reviewer"),
        (" ", None),
        ("U", "the reviewer"),  # case does not matter for a plain letter
        ("Shift+V", "the reviewer"),
        ("Ctrl+3", "the reviewer"),
        ("t", "Anki's main window"),  # Statistics: pressing T would do nothing at all
        ("T", "Anki's main window"),
        ("Shift+T", "Anki's main window"),
        ("d", "Anki's main window"),
        ("y", "Anki's main window"),
        ("f", "Anki's menus"),  # Tools -> Create Filtered Deck: F would do nothing at all
        ("F", "Anki's menus"),
        ("/", "Anki's menus"),  # Study Deck
        ("Ctrl+Z", "Anki's menus"),  # Undo
        ("Ctrl+Shift+Z", "Anki's menus"),  # Redo
    ],
)
def test_clashing_keys_are_refused_with_a_clear_message(typed: str, where: str | None) -> None:
    result = check_key(typed)
    if where is None:
        assert not result.ok  # a bare space is not "one key" here
        return
    assert not result.ok
    shown = typed.strip()
    assert result.message == f"{shown} is already used by Anki in {where}. Pick another key."


def test_live_keys_add_to_the_list() -> None:
    assert check_key("q").ok
    refused = check_key("q", {"q": "the reviewer"})
    assert not refused.ok and "already used" in refused.message


# The lists above against the installed aqt, so a new Anki key can't slip past them ----------

AQT = importlib.util.find_spec("aqt")
needs_aqt = pytest.mark.skipif(AQT is None, reason="aqt isn't installed")


def _aqt_source(name: str) -> ast.Module:
    assert AQT is not None and AQT.submodule_search_locations
    path = Path(AQT.submodule_search_locations[0]) / name
    return ast.parse(path.read_text(encoding="utf-8"))


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in aqt")


def _first_elements(fn: ast.FunctionDef) -> set[str]:
    """Every key written as the first item of a (key, handler) tuple in ``fn``."""
    found: set[str] = set()

    def add(node: ast.expr) -> None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.add("Space" if node.value == " " else node.value)
        elif isinstance(node, ast.IfExp):  # "Ctrl+Backspace" if is_mac else "Ctrl+Delete"
            add(node.body)
            add(node.orelse)
        elif isinstance(node, ast.JoinedStr):  # f"Ctrl+{flag.index}": flags 1 to 7
            prefix = node.values[0]
            assert isinstance(prefix, ast.Constant)
            found.update(f"{prefix.value}{n}" for n in range(1, 8))
        elif isinstance(node, ast.Attribute) and node.attr.startswith("Key_"):  # Qt.Key.Key_Return
            found.add(node.attr.removeprefix("Key_"))

    for node in ast.walk(fn):
        if isinstance(node, ast.Tuple) and len(node.elts) == 2:
            add(node.elts[0])
    return found


@needs_aqt
def test_every_reviewer_key_is_known() -> None:
    reviewer = _aqt_source("reviewer.py")
    typed = _first_elements(_function(reviewer, "_shortcutKeys"))
    typed |= _first_elements(_function(reviewer, "korean_shortcuts"))
    typed |= {"1", "2", "3", "4"}  # ProfileManager.default_answer_keys (checked below)
    assert len(typed) > 30
    unknown = {k for k in typed if normalize_key(k) not in keys.RESERVED}
    assert unknown == set()


@needs_aqt
def test_answer_keys_default_to_1_to_4() -> None:
    profiles = _aqt_source("profiles.py")
    source = ast.unparse(profiles)
    assert "default_answer_keys = {ease_num: str(ease_num) for ease_num in range(1, 5)}" in source


@needs_aqt
def test_every_main_window_key_is_known() -> None:
    main = _aqt_source("main.py")
    typed = _first_elements(_function(main, "setupKeys"))
    assert {"d", "s", "a", "b", "t", "Shift+t", "y"} <= typed
    unknown = {k for k in typed if normalize_key(k) not in keys.RESERVED}
    assert unknown == set()


@needs_aqt
def test_every_menu_key_is_known() -> None:
    """The main window's menu shortcuts (Qt Designer form), e.g. F = Create Filtered Deck."""
    spec = importlib.util.find_spec("_aqt.forms.main_qt6")
    assert spec is not None and spec.origin
    tree = ast.parse(Path(spec.origin).read_text(encoding="utf-8"))
    typed: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "setShortcut"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            typed.add(node.args[0].value)
    assert {"F", "/", "Ctrl+Z"} <= typed
    unknown = {k for k in typed if normalize_key(k) not in keys.RESERVED}
    assert unknown == set()
