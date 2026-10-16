"""The vendored SymPy: pinned, licensed, loaded lazily from the add-on's own folder."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from recalldrill import math_vendor

ADDON_ROOT = Path(__file__).resolve().parent.parent


def _dev_pins() -> dict[str, str]:
    text = (ADDON_ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    return dict(re.findall(r"^(sympy|mpmath)==([0-9.]+)", text, re.MULTILINE))


def test_pins_match_requirements_dev_and_the_vendored_files() -> None:
    assert _dev_pins() == math_vendor.PINS
    sympy_release = (ADDON_ROOT / "vendor" / "sympy" / "release.py").read_text(encoding="utf-8")
    assert f'__version__ = "{math_vendor.PINS["sympy"]}"' in sympy_release
    mpmath_init = (ADDON_ROOT / "vendor" / "mpmath" / "__init__.py").read_text(encoding="utf-8")
    assert f"__version__ = '{math_vendor.PINS['mpmath']}'" in mpmath_init


def test_licenses_ship_with_the_code() -> None:
    sympy_licence = (ADDON_ROOT / "vendor" / "LICENSE-sympy.txt").read_text(encoding="utf-8")
    assert "Redistribution and use in source and binary forms" in sympy_licence
    mpmath_licence = (ADDON_ROOT / "vendor" / "LICENSE-mpmath.txt").read_text(encoding="utf-8")
    assert "Fredrik Johansson" in mpmath_licence


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


def test_sympy_is_imported_lazily_and_from_the_add_ons_folder() -> None:
    out = _run(
        "from recalldrill import math_answer, math_vendor; "
        "before = 'sympy' in sys.modules; "
        "right = math_answer.check_answer('x^2', 'x-2').outcome; "  # wrong by form: no SymPy
        "mid = 'sympy' in sys.modules; "
        "eq = math_answer.check_answer('a^2-b^2', '(a+b)(a-b)').outcome; "  # needs simplify
        "import sympy; "
        "print(before, mid, eq, sympy.__file__)"
    )
    before, mid, eq, path = out.split(" ", 3)
    assert (before, mid, eq) == ("False", "False", "equivalent")
    assert Path(path).resolve().is_relative_to((ADDON_ROOT / "vendor").resolve())


def test_vendor_dir_is_put_on_the_path_in_one_place() -> None:
    sources = [
        p
        for p in (ADDON_ROOT / "recalldrill").rglob("*.py")
        if "sys.path" in p.read_text(encoding="utf-8")
    ]
    assert [p.name for p in sources] == ["math_vendor.py"]
