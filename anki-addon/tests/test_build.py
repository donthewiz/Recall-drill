"""build.py: the .ankiaddon holds exactly the runtime files. Needs no anki."""

from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import recalldrill

ADDON_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ADDON_ROOT))
import build  # noqa: E402  (anki-addon/build.py)

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
    assert built.name == f"recall_drill-{recalldrill.VERSION}.ankiaddon"
    expected = TOP_LEVEL | {
        p.relative_to(ADDON_ROOT).as_posix()
        for p in (ADDON_ROOT / "recalldrill").rglob("*.py")
        if "__pycache__" not in p.parts
    }
    with zipfile.ZipFile(built) as z:
        names = z.namelist()
    assert sorted(names) == sorted(set(names))  # no duplicates
    assert set(names) == expected


def test_manifest(built: Path) -> None:
    with zipfile.ZipFile(built) as z:
        meta = json.loads(z.read("manifest.json"))
    assert meta["package"] == "recall_drill"
    assert meta["name"] == "Recall Drill"
    assert meta["min_point_version"] == 260801
    assert meta["human_version"] == recalldrill.VERSION == "0.1.0"
    assert isinstance(meta["mod"], int) and meta["mod"] > 1_700_000_000
    assert set(meta) == {"package", "name", "min_point_version", "human_version", "mod"}


def test_no_test_or_dev_files(built: Path) -> None:
    with zipfile.ZipFile(built) as z:
        names = z.namelist()
    banned_parts = {"tests", "tools", "docs", ".venv", "dist", "__pycache__"}
    banned_names = {"meta.json", "pyproject.toml", "requirements-dev.txt", "build.py"}
    for name in names:
        parts = Path(name).parts
        assert not banned_parts & set(parts), name
        assert name not in banned_names, name  # root-level only: anki_io/build.py is runtime
        assert not name.startswith("recall_drill/"), "no top-level folder"
        if parts[0] == "user_files":
            assert name == "user_files/README.txt"
        if parts[0] == "recalldrill":
            assert name.endswith(".py")


def test_user_data_is_never_packaged(tmp_path: Path) -> None:
    """A profile folder next to README.txt stays out of the package."""
    files = build.package_files(ADDON_ROOT)
    assert [f for f in files if f.startswith("user_files/")] == ["user_files/README.txt"]


def test_refuses_a_dirty_tree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "x.txt").write_text("x")
    with pytest.raises(build.BuildError, match="dirty"):
        build.check_clean(repo)


def test_a_failing_engine_test_stops_the_build(tmp_path: Path) -> None:
    root = tmp_path / "addon"
    (root / "tests" / "engine").mkdir(parents=True)
    (root / "tests" / "engine" / "test_fail.py").write_text("def test_x():\n    assert False\n")
    with pytest.raises(build.BuildError, match="tests/engine failed"):
        build.run_engine_tests(root)
