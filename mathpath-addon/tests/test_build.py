"""build.py: the .ankiaddon holds exactly the runtime files. Needs no anki."""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import pytest

import math_path

ADDON_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ADDON_ROOT))
import build  # noqa: E402  (mathpath-addon/build.py)

TOP_LEVEL = {
    "__init__.py",
    "manifest.json",
    "config.json",
    "config.md",
    "user_files/README.txt",
}


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("dist")
    return build.build(ADDON_ROOT, out, allow_dirty=True, skip_tests=True)


def test_file_name_and_exact_file_list(built: Path) -> None:
    assert built.name == f"math_path-{math_path.VERSION}.ankiaddon" == "math_path-0.1.0.ankiaddon"
    expected = (
        TOP_LEVEL
        | {
            p.relative_to(ADDON_ROOT).as_posix()
            for p in (ADDON_ROOT / "math_path").rglob("*.py")
            if "__pycache__" not in p.parts
        }
        | {
            p.relative_to(ADDON_ROOT).as_posix()
            for folder in ("core", "vendor", "web")
            for p in (ADDON_ROOT / folder).rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and p.name != "SOURCE.md"
        }
    )
    with zipfile.ZipFile(built) as z:
        names = z.namelist()
    assert sorted(names) == sorted(set(names))  # no duplicates
    assert set(names) == expected


def test_manifest(built: Path) -> None:
    with zipfile.ZipFile(built) as z:
        meta = json.loads(z.read("manifest.json"))
    assert meta["package"] == "math_path"
    assert meta["name"] == "Math Path"
    assert meta["min_point_version"] == 260801
    assert meta["human_version"] == math_path.VERSION == "0.1.0"
    assert isinstance(meta["mod"], int) and meta["mod"] > 1_700_000_000
    assert set(meta) == {"package", "name", "min_point_version", "human_version", "mod"}


def test_no_test_or_dev_files(built: Path) -> None:
    with zipfile.ZipFile(built) as z:
        names = z.namelist()
    banned_parts = {"tests", "docs", ".venv", "dist", "__pycache__"}
    banned_names = {"meta.json", "pyproject.toml", "requirements-dev.txt", "build.py"}
    for name in names:
        parts = Path(name).parts
        assert not banned_parts & set(parts), name
        assert name not in banned_names, name
        assert not name.startswith("math_path/") or name.endswith(".py")
        if parts[0] == "user_files":
            assert name == "user_files/README.txt"
        assert (
            not name.endswith((".json",))
            or name
            in {
                "manifest.json",
                "config.json",
            }
            or parts[0] in ("web", "vendor", "core")
        ), name


def test_the_checker_and_the_vendor_folder_are_in_the_package(built: Path) -> None:
    with zipfile.ZipFile(built) as z:
        names = set(z.namelist())
    assert {
        "core/verify_math.py",
        "core/recipe_validator.py",
        "core/drill_check/math_parse.py",
    } <= names
    assert "vendor/sympy/__init__.py" in names and "vendor/LICENSE-sympy.txt" in names
    assert "web/mathlive/mathlive.min.js" in names and "web/mp_page.js" in names


def test_the_build_is_reproducible_apart_from_the_manifest(tmp_path: Path) -> None:
    a = build.build(ADDON_ROOT, tmp_path / "a", allow_dirty=True, skip_tests=True)
    b = build.build(ADDON_ROOT, tmp_path / "b", allow_dirty=True, skip_tests=True)
    with zipfile.ZipFile(a) as za, zipfile.ZipFile(b) as zb:
        assert za.namelist() == zb.namelist()
        for name in za.namelist():
            if name != "manifest.json":
                assert za.read(name) == zb.read(name)
