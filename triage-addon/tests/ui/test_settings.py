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


# menu shortcuts (found in review) -------------------------------------------------------------


def _window_with_menu_key(key: str, label: str = "Create Filtered Deck") -> tuple[Any, Any]:
    """A main window with one menu item on ``key``; returns (window, item)."""
    from aqt.qt import QAction, QMainWindow

    w = QMainWindow()
    bar = w.menuBar()
    assert bar is not None
    menu = bar.addMenu("&Tools")
    assert menu is not None
    action = QAction(label, w)
    action.setShortcut(key)
    menu.addAction(action)
    return w, action


def test_a_menu_shortcut_and_a_reviewer_key_on_one_key_both_stop_working(qt_app: object) -> None:
    """Why menu keys are refused: Qt calls the pair ambiguous and fires neither."""
    from aqt.qt import QKeySequence, QShortcut, Qt, qconnect
    from PyQt6.QtTest import QTest

    def press_f(menu_key: str) -> list[str]:
        w, action = _window_with_menu_key(menu_key)
        fired: list[str] = []
        qconnect(action.triggered, lambda *_: fired.append("menu"))
        ours = QShortcut(QKeySequence("f"), w)
        qconnect(ours.activated, lambda: fired.append("ours"))
        w.show()
        QTest.qWaitForWindowExposed(w)  # pyright: ignore[reportCallIssue]
        QTest.keyClick(w, Qt.Key.Key_F)  # pyright: ignore[reportCallIssue]
        w.close()
        return fired

    assert press_f("G") == ["ours"]  # the key reaches the window when nothing else has it
    assert press_f("F") == []  # with Create Filtered Deck on F, nothing happens at all


def test_menu_shortcuts_are_read_from_the_window(qt_app: object) -> None:
    w, _ = _window_with_menu_key("F")
    found = entry.action_keys(w)
    assert found == {"f": "the menu item “Create Filtered Deck”"}
    w2, _ = _window_with_menu_key("Ctrl+Shift+K", "&Some Add-on")
    assert entry.action_keys(w2) == {"ctrl+shift+k": "the menu item “Some Add-on”"}


def test_another_add_ons_menu_key_is_refused_in_the_dialog(qt_app: object) -> None:
    w, _ = _window_with_menu_key("Ctrl+Shift+K", "Some Add-on")
    d, saved = dialog(qt_app, live_keys=lambda: entry.action_keys(w))
    d.key.setText("Ctrl+Shift+K")
    assert d.try_accept() is False and saved == []
    assert "Some Add-on" in d.error.text()


def test_settings_use_the_reviewer_and_the_menu_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(entry, "live_reviewer_keys", lambda: {"q": "the reviewer"})
    monkeypatch.setattr(entry, "action_keys", lambda _w: {"f": "the menu item"})
    assert entry.live_keys() == {"q": "the reviewer", "f": "the menu item"}
