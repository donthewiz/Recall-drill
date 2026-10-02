from __future__ import annotations

import json
from pathlib import Path

import recalldrill  # importable via conftest's sys.path entry

ADDON_ROOT = Path(__file__).resolve().parent.parent


def test_manifest_matches_package() -> None:
    manifest = json.loads((ADDON_ROOT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["package"] == "recall_drill"
    assert manifest["human_version"] == recalldrill.__version__
    # Anki's int_version(): YYMMPP. 26.08.1 -> 260801.
    assert manifest["min_point_version"] == 260801


def test_config_defaults_match_web_app() -> None:
    config = json.loads((ADDON_ROOT / "config.json").read_text(encoding="utf-8"))
    assert config == {
        "encode_reps": 3,
        "chunk_difficulty": 35,
        "batch_size": 5,
        "stem_tolerance": True,
        "ladder_mode": "cumulative",
        "cycle_order": "shuffled",
        # Add-on only (Phase 3a): the drill controller's settings.
        "collision_catch": True,
        "play_audio_on_feedback": True,
        # Add-on only (Phase 3b).
        "autoplay_question_audio": False,
    }


def test_about_menu_registration_is_a_no_op_without_main_window() -> None:
    from recalldrill.ui import about

    assert about.MENU_LABEL == "Recall Drill (dev)"
    about.register_menu()  # aqt.mw is None outside Anki


def test_entry_registration_is_a_no_op_without_main_window(tmp_path: Path) -> None:
    from recalldrill.ui import entry

    assert entry.TOOLS_LABEL == "Recall Drill…"
    entry.register("recall_drill", str(tmp_path))  # aqt.mw is None outside Anki
    assert entry._ctx is None  # pyright: ignore[reportPrivateUsage]
