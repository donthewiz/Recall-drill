"""The key, the menu and the actions, on stand-ins (a scratch collection behind them)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("aqt")

from scenes import add_note, card_ids, make_review, new_collection, state  # noqa: E402
from stubs import Recorder, StubMw, SyncOp  # noqa: E402

from card_triage.anki_io import triage  # noqa: E402
from card_triage.config import Config  # noqa: E402
from card_triage.ui import actions, entry  # noqa: E402


@pytest.fixture
def col(tmp_path: Path):
    c = new_collection(tmp_path)
    yield c
    c.close()


@pytest.fixture
def rec(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    r = Recorder()
    monkeypatch.setattr(actions, "tooltip", r.tooltips.append)

    def ask(text: str, **_kw: Any) -> bool:
        r.questions.append(text)
        return r.answer

    monkeypatch.setattr(actions, "askUser", ask)
    monkeypatch.setattr(actions, "CollectionOp", SyncOp)
    return r


def install_mw(monkeypatch: pytest.MonkeyPatch, mw: StubMw) -> None:
    SyncOp.mw = mw
    monkeypatch.setattr(actions, "mw", mw)


# the key -------------------------------------------------------------------------------------


def test_key_is_registered_only_for_the_review_state_with_the_configured_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(entry, "config", lambda: Config(set_aside_key="z"))
    others: list[Any] = [("e", print)]

    for st in ("deckBrowser", "overview", "profileManager", "resetRequired"):
        keys = list(others)
        entry.on_shortcuts(st, keys)
        assert keys == others, st

    keys = list(others)
    entry.on_shortcuts("review", keys)
    assert keys[:1] == others
    assert [k for k, _ in keys[1:]] == ["z"]
    assert keys[1][1] is actions.set_aside_current


def test_menu_has_both_items(qt_app: object) -> None:
    from aqt.qt import QMenu

    tools = QMenu()
    menu = entry.build_menu(tools)
    assert menu.title() == "Card Triage"
    labels = [a.text() for a in menu.actions()]
    assert labels[:2] == ["Show set-aside cards", "Release all set-aside cards…"]


# the actions ---------------------------------------------------------------------------------


def test_key_sets_the_card_aside_and_says_so(
    col: Any, rec: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    (cid,) = card_ids(col, add_note(col, "d", "x"))
    install_mw(monkeypatch, StubMw(col, card=col.get_card(cid)))

    actions.set_aside_current()

    assert state(col, cid).suspended
    assert rec.tooltips == ["Set aside. Ctrl+Z to undo."]


def test_key_on_a_review_card_changes_nothing_and_says_why(
    col: Any, rec: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    (cid,) = card_ids(col, add_note(col, "d", "x"))
    make_review(col, cid)
    before = state(col, cid)
    install_mw(monkeypatch, StubMw(col, card=col.get_card(cid)))

    actions.set_aside_current()

    assert state(col, cid) == before
    assert rec.tooltips == ["Card Triage sets aside only new and learning cards."]


def test_key_outside_the_reviewer_does_nothing(
    col: Any, rec: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    (cid,) = card_ids(col, add_note(col, "d", "x"))
    install_mw(monkeypatch, StubMw(col, card=col.get_card(cid), state="overview"))
    actions.set_aside_current()
    install_mw(monkeypatch, StubMw(col, card=None))
    actions.set_aside_current()
    assert not state(col, cid).suspended
    assert rec.tooltips == []


def test_release_with_none_set_aside_shows_a_tooltip_and_no_dialog(
    col: Any, rec: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_mw(monkeypatch, StubMw(col))
    actions.release_all()
    assert rec.tooltips == ["No set-aside cards."]
    assert rec.questions == []


def test_release_asks_with_the_count_then_releases(
    col: Any, rec: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    cids = [card_ids(col, add_note(col, "d", f"c{i}"))[0] for i in range(3)]
    for c in cids:
        triage.set_aside(col, c)
    install_mw(monkeypatch, StubMw(col))

    rec.answer = False
    actions.release_all()
    assert rec.questions == ["Release 3 set-aside cards? They go back to where they were."]
    assert all(state(col, c).suspended for c in cids)  # declined: nothing changed

    rec.answer = True
    actions.release_all()
    assert not any(state(col, c).suspended for c in cids)
    assert rec.tooltips == ["Released 3 set-aside cards. Ctrl+Z to undo."]


def test_show_opens_browse_on_the_marker_search(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[tuple[Any, ...]] = []

    class Dialogs:
        def open(self, *args: Any, **kwargs: Any) -> None:
            opened.append((args, kwargs))

    mw = StubMw()
    install_mw(monkeypatch, mw)
    monkeypatch.setattr(actions, "dialogs", Dialogs())
    actions.show_set_aside()
    assert opened == [(("Browser", mw), {"search": ("has-cd:tri",)})]
