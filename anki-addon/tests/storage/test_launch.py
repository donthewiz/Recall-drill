"""addon_config.py and launch.py: from config and panel choices to a session."""

from __future__ import annotations

from pathlib import Path

import pytest
from controller_support import SHORT, Clock, source

from recalldrill import deck_settings, launch, sessions
from recalldrill.addon_config import DEFAULT_CONFIG, AddonConfig, parse_config
from recalldrill.controller import DrillController
from recalldrill.engine.session import select_trial
from recalldrill.sessions import SessionStore
from recalldrill.storage import Storage


@pytest.fixture
def st(tmp_path: Path) -> Storage:
    return Storage(tmp_path / "user_files", "User 1")


def test_parse_config_defaults_and_bad_values() -> None:
    assert parse_config(None) == DEFAULT_CONFIG
    assert parse_config({}) == AddonConfig()
    cfg = parse_config(
        {
            "encode_reps": 0,
            "batch_size": "5",
            "stem_tolerance": 1,
            "ladder_mode": "exhaustive",
            "cycle_order": "random",
            "autoplay_question_audio": True,
        }
    )
    assert cfg.encode_reps == 3 and cfg.batch_size == 5 and cfg.stem_tolerance is True
    assert cfg.ladder_mode == "exhaustive" and cfg.cycle_order == "shuffled"
    assert cfg.autoplay_question_audio is True


def test_config_json_matches_the_defaults() -> None:
    import json

    raw = json.loads((Path(__file__).parents[2] / "config.json").read_text(encoding="utf-8"))
    assert parse_config(raw) == DEFAULT_CONFIG


def test_session_config_deck_settings_win_over_config() -> None:
    cfg = AddonConfig(encode_reps=4, batch_size=7, chunk_difficulty=50)
    c = launch.session_config({}, cfg)
    assert c["encodeReps"] == 4 and c["batchSize"] == 7 and c["chunkDifficulty"] == 50
    c = launch.session_config({"encodeReps": 2, "batchSize": 3, "strictPunctuation": True}, cfg)
    assert c["encodeReps"] == 2 and c["batchSize"] == 3 and c["strictPunctuation"] is True
    assert c["ladderMode"] == "cumulative" and c.get("cycleOrder") == "shuffled"


def test_controller_settings_from_config() -> None:
    cfg = AddonConfig(collision_catch=False, autoplay_question_audio=True)
    s = launch.controller_settings(cfg, "Deck")
    assert s.deck_name == "Deck" and not s.collision_catch and s.autoplay_question_audio
    assert s.source_deck_editable
    assert not launch.controller_settings(cfg, "Deck", drill_again=True).source_deck_editable


def _start(st: Storage, settings_did: int | None = 42) -> tuple[DrillController, SessionStore]:
    return launch.start(
        st,
        scope=sessions.scope_json(deck_id=42),
        deck_name="Ch 3",
        deck_items=SHORT,
        sources=[source(i) for i in range(3)],
        settings_did=settings_did,
        settings={"batchSize": 3, "encodeReps": 1},
        select_options={"enabled": ["new"]},
        hints=False,
        cfg=DEFAULT_CONFIG,
        clock=Clock(),
    )


def test_start_saves_deck_settings_and_the_session(st: Storage) -> None:
    ctrl, store = _start(st)
    assert deck_settings.get_saved(st, 42) == {"batchSize": 3, "encodeReps": 1}
    assert store.meta.key == "deck-42"
    ctrl.start()
    saved = sessions.load(st, "deck-42")
    assert saved is not None and saved["deckName"] == "Ch 3"
    assert saved["encodeReps"] == 1 and saved["batchSize"] == 3
    assert saved["addon"]["deckSettings"] == {"batchSize": 3, "encodeReps": 1}


def test_start_without_a_settings_deck_saves_no_settings(st: Storage) -> None:
    _start(st, settings_did=None)
    assert deck_settings.load_all(st) == {}


def test_start_refuses_nothing_to_drill(st: Storage) -> None:
    with pytest.raises(ValueError):
        launch.start(
            st,
            scope=sessions.scope_json(deck_id=1),
            deck_name="x",
            deck_items=[],
            sources=[],
            settings_did=1,
            settings={},
            select_options={},
            hints=False,
            cfg=DEFAULT_CONFIG,
        )
    assert deck_settings.get_saved(st, 1) is None


def test_resume_lands_on_the_same_card(st: Storage) -> None:
    ctrl, _ = _start(st)
    ctrl.start()
    trial = select_trial(ctrl.state)
    assert trial is not None
    ctrl.save_and_stop()
    saved = sessions.load(st, "deck-42")
    assert saved is not None
    again, _ = launch.resume(st, "deck-42", saved, DEFAULT_CONFIG, Clock())
    resumed = select_trial(again.state)
    assert resumed is not None and resumed["itemId"] == trial["itemId"]
    assert again.settings.deck_name == "Ch 3"
