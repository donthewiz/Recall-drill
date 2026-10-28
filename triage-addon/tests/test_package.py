"""The shipped files agree with each other."""

from __future__ import annotations

import json
from pathlib import Path

import card_triage

ROOT = Path(__file__).resolve().parent.parent


def test_manifest() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["package"] == "card_triage"
    assert manifest["name"] == "Card Triage"
    assert manifest["min_point_version"] == 260801
    assert manifest["human_version"] == card_triage.__version__


def test_root_init_is_importable_outside_anki() -> None:
    import runpy

    runpy.run_path(str(ROOT / "__init__.py"), run_name="card_triage_root")
