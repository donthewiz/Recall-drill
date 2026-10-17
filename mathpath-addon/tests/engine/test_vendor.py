"""The vendored SymPy: pinned, licensed, loaded lazily from the add-on's own folder."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from math_path import loader

ADDON_ROOT = Path(__file__).resolve().parents[2]


def test_pins_are_the_vendored_versions() -> None:
    sympy_release = (ADDON_ROOT / "vendor" / "sympy" / "release.py").read_text(encoding="utf-8")
    assert f'__version__ = "{loader.PINS["sympy"]}"' in sympy_release
    mpmath_init = (ADDON_ROOT / "vendor" / "mpmath" / "__init__.py").read_text(encoding="utf-8")
    assert f"__version__ = '{loader.PINS['mpmath']}'" in mpmath_init


def test_no_system_sympy_is_installed_for_the_tests() -> None:
    """requirements-dev.txt leaves SymPy out on purpose: the tests run on the shipped copy."""
    text = (ADDON_ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    assert not re.search(r"^(sympy|mpmath)==", text, re.MULTILINE)
    out = _run("import importlib.util; print(importlib.util.find_spec('sympy') is None)")
    assert out == "True"


def test_licenses_ship_with_the_code() -> None:
    sympy_licence = (ADDON_ROOT / "vendor" / "LICENSE-sympy.txt").read_text(encoding="utf-8")
    assert "Redistribution and use in source and binary forms" in sympy_licence
    mpmath_licence = (ADDON_ROOT / "vendor" / "LICENSE-mpmath.txt").read_text(encoding="utf-8")
    assert "Fredrik Johansson" in mpmath_licence
    assert (ADDON_ROOT / "web" / "mathlive" / "LICENSE.txt").is_file()


def test_no_tests_are_vendored() -> None:
    names = {p.name for p in (ADDON_ROOT / "vendor").rglob("*") if p.is_dir()}
    assert not names & {"tests", "test"}
    assert not list((ADDON_ROOT / "vendor").rglob("test_*.py"))


def _run(code: str) -> str:
    """Python in a fresh process: -I so cwd adds nothing, -B so no caches land in vendor/."""
    env_code = f"import sys; sys.path.insert(0, {str(ADDON_ROOT)!r}); {code}"
    out = subprocess.run(
        [sys.executable, "-I", "-B", "-c", env_code], capture_output=True, text=True, check=True
    )
    return out.stdout.strip()


def test_nothing_is_imported_until_the_first_problem_and_then_from_vendor() -> None:
    out = _run(
        "from math_path import loader, problem, display, recipe; "
        "before = 'sympy' in sys.modules; "
        "core = loader.load(); "
        "print(before, loader.is_loaded(), core.sympy.__file__)"
    )
    before, loaded, path = out.split(" ", 2)
    assert (before, loaded) == ("False", "True")
    assert Path(path).resolve().is_relative_to((ADDON_ROOT / "vendor").resolve())


def test_sys_path_is_touched_in_one_place() -> None:
    sources = [
        p
        for p in (ADDON_ROOT / "math_path").rglob("*.py")
        if "sys.path" in p.read_text(encoding="utf-8")
    ]
    assert [p.name for p in sources] == ["loader.py"]
