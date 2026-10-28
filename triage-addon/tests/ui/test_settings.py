from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("aqt")

from stubs import StubAddonManager, StubMw  # noqa: E402

from card_triage.config import Config, parse_config  # noqa: E402
from card_triage.ui import entry  # noqa: E402
from card_triage.ui.settings_dialog import SettingsDialog  # noqa: E402


def dialog(qt_app: object, config: Config | None = None, **kw: Any) -> tuple[SettingsDialog, list]:
    saved: list[dict[str, Any]] = []
    return SettingsDialog(config or Config(), saved.append, **kw), saved


def test_dialog_shows_the_current_settings(qt_app: object) -> None:
    d, _ = dialog(qt_app, Config("q", True, 45, True, 3))
    assert d.key.text() == "q"
    assert (d.timer_on.isChecked(), d.timer_seconds.value()) == (True, 45)
    assert (d.again_on.isChecked(), d.again_count.value()) == (True, 3)


def test_ranges(qt_app: object) -> None:
    d, _ = dialog(qt_app)
    assert (d.timer_seconds.minimum(), d.timer_seconds.maximum()) == (5, 600)
    assert (d.again_count.minimum(), d.again_count.maximum()) == (1, 10)


def test_defaults_are_off_x_30_and_2(qt_app: object) -> None:
    d, _ = dialog(qt_app)
    assert d.key.text() == "x"
    assert not d.timer_on.isChecked() and not d.again_on.isChecked()
    assert (d.timer_seconds.value(), d.again_count.value()) == (30, 2)


def test_ok_saves_the_values(qt_app: object) -> None:
    d, saved = dialog(qt_app)
    d.key.setText("Q")
    d.timer_on.setChecked(True)
    d.timer_seconds.setValue(90)
    d.again_on.setChecked(True)
    d.again_count.setValue(4)
    assert d.try_accept() is True
    assert saved == [
        {
            "set_aside_key": "Q",
            "timer_prompt": True,
            "timer_seconds": 90,
            "again_prompt": True,
            "again_count": 4,
        }
    ]
    assert parse_config(saved[0]) == Config("Q", True, 90, True, 4)


@pytest.mark.parametrize("key", ["e", "r", "u", "1", "t", "T"])
def test_a_clashing_key_is_refused_with_a_message_and_nothing_is_saved(
    qt_app: object, key: str
) -> None:
    d, saved = dialog(qt_app)
    d.key.setText(key)
    assert d.try_accept() is False
    assert saved == []
    assert f"{key} is already used by Anki" in d.error.text()


def test_a_key_the_reviewer_has_right_now_is_refused(qt_app: object) -> None:
    d, saved = dialog(qt_app, live_keys=lambda: {"q": "the reviewer"})
    d.key.setText("q")
    assert d.try_accept() is False and saved == []


def test_a_message_goes_away_once_the_key_is_fixed(qt_app: object) -> None:
    d, saved = dialog(qt_app)
    d.key.setText("e")
    d.try_accept()
    d.key.setText("w")
    assert d.try_accept() and d.error.text() == "" and len(saved) == 1


def test_save_config_writes_to_the_add_on_config(monkeypatch: pytest.MonkeyPatch) -> None:
    mw = StubMw(state="deckBrowser")
    monkeypatch.setattr(entry, "mw", mw)
    monkeypatch.setattr(entry, "_module", "card_triage")
    entry.save_config({"set_aside_key": "q"})
    mgr: StubAddonManager = mw.addonManager
    assert mgr.saved == [("card_triage", {"set_aside_key": "q"})]
