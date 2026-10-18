from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

import math_path
from math_path import config

ADDON_ROOT = Path(__file__).resolve().parent.parent

needs_aqt = pytest.mark.skipif(
    importlib.util.find_spec("aqt") is None,
    reason="imports aqt (Anki's GUI package), which isn't installed",
)


def test_manifest_matches_package() -> None:
    manifest = json.loads((ADDON_ROOT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["package"] == "math_path"
    assert manifest["name"] == "Math Path"
    assert manifest["human_version"] == math_path.__version__ == "0.1.1"
    # Anki's int_version(): YYMMPP. 26.08.1 -> 260801.
    assert manifest["min_point_version"] == 260801


def test_the_entry_file_declares_the_same_version_as_the_package() -> None:
    assert math_path.VERSION == "0.1.1"
    entry = (ADDON_ROOT / "__init__.py").read_text(encoding="utf-8")
    assert "register(__name__" in entry


def test_config_defaults() -> None:
    raw = json.loads((ADDON_ROOT / "config.json").read_text(encoding="utf-8"))
    assert raw == {"problems_per_session": 3, "auto_open_in_review": True, "prereq_lock": True}
    assert config.parse_config(raw) == config.Config()
    assert config.parse_config(None) == config.Config()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"problems_per_session": 0}, 1),
        ({"problems_per_session": 99}, 12),
        ({"problems_per_session": "5"}, 3),
        ({"problems_per_session": True}, 3),
        ({"problems_per_session": 5}, 5),
    ],
)
def test_a_bad_session_size_is_clamped_or_defaulted(raw: dict[str, object], expected: int) -> None:
    assert config.parse_config(raw).problems_per_session == expected


def test_a_mistyped_flag_takes_its_default() -> None:
    cfg = config.parse_config({"auto_open_in_review": "no", "prereq_lock": 0})
    assert cfg.auto_open_in_review is True and cfg.prereq_lock is True
    cfg = config.parse_config({"auto_open_in_review": False, "prereq_lock": False})
    assert cfg.auto_open_in_review is False and cfg.prereq_lock is False


def test_config_md_documents_every_key() -> None:
    text = (ADDON_ROOT / "config.md").read_text(encoding="utf-8")
    for key in json.loads((ADDON_ROOT / "config.json").read_text(encoding="utf-8")):
        assert f"`{key}`" in text


def test_user_files_ships_only_its_readme() -> None:
    assert (ADDON_ROOT / "user_files" / "README.txt").is_file()
    gitignore = (ADDON_ROOT.parent / ".gitignore").read_text(encoding="utf-8")
    assert "mathpath-addon/user_files/*" in gitignore
    assert "!mathpath-addon/user_files/README.txt" in gitignore


@needs_aqt
def test_entry_registration_is_a_no_op_without_main_window(tmp_path: Path) -> None:
    from math_path.ui import entry

    entry.register("math_path", str(tmp_path))  # aqt.mw is None outside Anki
    assert entry.context() is None
    assert entry.display_name("math_path_dev") == "Math Path (dev)"
    assert entry.display_name("math_path") == "Math Path"
