"""Exam tracker hover test (v0.4 step 1): the HTML/data builder, the toggle, the hooks.

The builder and the toggle need no Anki. The hook tests need aqt (and offscreen Qt for the
menu action). How the card looks and feels is checked by hand in Anki ("Needs eyes").
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from recalldrill.ui import exam_tracker_demo as et

ADDON_ROOT = Path(__file__).resolve().parent.parent
needs_aqt = pytest.mark.skipif(
    importlib.util.find_spec("aqt") is None, reason="aqt (Anki's GUI package) isn't installed"
)


def node(
    deck_id: int, name: str, level: int, children: list[Any] | None = None, collapsed: bool = False
) -> Any:
    return SimpleNamespace(
        deck_id=deck_id, name=name, level=level, collapsed=collapsed, children=children or []
    )


def tree(*, ap_collapsed: bool = True, hap_collapsed: bool = True) -> Any:
    lab2 = node(12, "Lab 2", 2)
    muscle = node(32, "Muscle Tissue Chapter 10", 3)
    lecture3 = node(31, "Lecture 3", 2, [muscle], collapsed=hap_collapsed)
    return node(
        0,
        "",
        0,
        [
            node(10, "AP Lab", 1, [node(11, "Lab 1", 2), lab2], collapsed=ap_collapsed),
            node(30, "Human A&P", 1, [lecture3], collapsed=hap_collapsed),
            node(40, "Medical Terminology", 1),
            node(50, "Other", 1),
        ],
    )


def payload(**kw: Any) -> dict[str, Any]:
    return et.build_payload(et.rows_from_tree(tree(**kw)), None)


def test_the_three_fake_states() -> None:
    p = payload(ap_collapsed=False, hap_collapsed=False)["decks"]
    assert set(p) == {"12", "32", "40"}
    assert [p[k]["status"] for k in ("12", "32", "40")] == ["red", "amber", "green"]
    red = p["12"]
    assert "Behind" in red["row"] and "8 days left" in red["row"]
    assert "61 a day needed · 18 done today" in red["row"]
    assert "<button" in red["row"] and "Practical · Fri Oct 23" in red["card"]
    assert "<b>490</b><span>cards left</span>" in red["card"]
    assert "<b>18 of 61</b>" in red["card"]
    assert "330 drill · 110 new · 50 reviews · Est. 55 min today" in red["card"]
    assert "TEST" in red["card"]
    assert "Slightly behind" in p["32"]["row"] and "11 days left" in p["32"]["row"]
    assert "90 drill · 40 new · 10 reviews · Est. 10 min today" in p["32"]["card"]
    assert "On pace" in p["40"]["row"] and "54 days left" in p["40"]["row"]
    assert "<b>3,780</b>" in p["40"]["card"]
    assert "1,500 drill · 2,100 new · 180 reviews · Est. 60 min today" in p["40"]["card"]
    assert "70 of 70" in p["40"]["card"]


def test_fake_numbers_add_up() -> None:
    for name, f in et.FAKE.items():
        assert f.cards_left == {"AP Lab::Lab 2": 490, "Medical Terminology": 3780}.get(
            name, f.cards_left
        )
    assert et.FAKE["Human A&P::Lecture 3::Muscle Tissue Chapter 10"].cards_left == 140


def test_collapsed_parent_shows_its_worst_descendant_and_expanded_shows_none() -> None:
    p = payload()["decks"]  # AP Lab and Human A&P collapsed
    assert p["10"]["status"] == "red" and "via Lab 2" in p["10"]["row"]
    assert "AP Lab::Lab 2" in p["10"]["card"]
    assert p["30"]["status"] == "amber"  # grandchild rolls up through a collapsed parent
    assert "12" not in p and "32" not in p and "31" not in p  # hidden rows get nothing
    expanded = payload(ap_collapsed=False, hap_collapsed=False)["decks"]
    assert "10" not in expanded and "30" not in expanded and "31" not in expanded
    assert "50" not in p and "50" not in expanded  # no fake entry: nothing extra


def test_worst_status_wins_and_ties_go_to_the_first() -> None:
    fake = {
        "P::a": et.Fake("green", "x", 1, 1, 1, 1, 1, 1, 1),
        "P::b": et.Fake("amber", "x", 1, 1, 1, 1, 1, 1, 1),
        "P::c": et.Fake("red", "x", 1, 1, 1, 1, 1, 1, 1),
        "P::d": et.Fake("red", "x", 1, 1, 1, 1, 1, 1, 1),
    }
    kids = [node(i, n, 2) for i, n in ((2, "a"), (3, "b"), (4, "c"), (5, "d"))]
    top = node(0, "", 0, [node(1, "P", 1, kids, collapsed=True)])
    shown = et.display_for(et.rows_from_tree(top)[0], fake)
    assert shown is not None and shown[0] == "P::c"
    mild = et.display_for(et.rows_from_tree(top)[0], {"P::a": fake["P::a"], "P::b": fake["P::b"]})
    assert mild is not None and mild[0] == "P::b"


def test_a_deck_with_its_own_entry_shows_it_even_with_children() -> None:
    top = node(0, "", 0, [node(1, "Medical Terminology", 1, [node(2, "Ch 1", 2)], collapsed=False)])
    assert set(et.build_payload(et.rows_from_tree(top), None)["decks"]) == {"1"}


def test_deck_names_are_escaped() -> None:
    f = et.FAKE["Medical Terminology"]
    nasty = '<script>alert(1)</script> & "q"'
    row = et.row_html(nasty, f, via=nasty, level=1)
    card = et.card_html(nasty, f)
    for out in (row, card):
        assert "<script>" not in out
        assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; &quot;q&quot;" in out
    # ...and in the JSON block nothing can close the tag early.
    top = node(0, "", 0, [node(1, nasty, 1)])
    fake = {nasty: f}
    block = et.script_tag(et.build_payload(et.rows_from_tree(top), None, fake))
    assert block.count("<") == 2 and block.count("</script>") == 1  # open tag + the closing tag
    inner = block[block.index(">") + 1 : block.rindex("</script>")]
    assert "<" not in inner and "&" not in inner
    assert "alert(1)" in json.loads(inner)["decks"]["1"]["card"]


def test_pin_survives_a_redraw_and_a_missing_row_drops_it() -> None:
    rows = et.rows_from_tree(tree())
    assert et.build_payload(rows, 10)["pinned"] == 10
    assert et.build_payload(rows, 999)["pinned"] is None
    assert et.build_payload(rows, 12)["pinned"] is None  # row hidden by the collapse


def test_pin_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(et, "_pinned", None)
    assert et.handle_message("rdet:pin:12") and et.pinned() == 12
    assert et.handle_message("rdet:pin:abc") and et.pinned() is None
    assert et.handle_message("rdet:pin:7") and et.handle_message("rdet:unpin")
    assert et.pinned() is None
    assert not et.handle_message("open:5") and not et.handle_message("collapse:5")


class FakeManager:
    def __init__(self, conf: dict[str, Any] | None) -> None:
        self.conf = conf
        self.writes: list[dict[str, Any]] = []

    def getConfig(self, module: str) -> dict[str, Any] | None:  # noqa: N802
        return self.conf

    def writeConfig(self, module: str, conf: dict[str, Any]) -> None:  # noqa: N802
        self.conf = conf
        self.writes.append(conf)


def test_toggle_flips_the_flag_and_requests_a_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(et, "_pinned", 10)
    mgr = FakeManager({"batch_size": 5})
    calls: list[int] = []
    assert not et.is_on(mgr, "m")
    assert et.toggle(mgr, "m", lambda: calls.append(1)) is True
    assert mgr.conf == {"batch_size": 5, "exam_tracker_test": True} and calls == [1]
    assert et.pinned() == 10
    assert et.toggle(mgr, "m", lambda: calls.append(2)) is False
    assert mgr.conf == {"batch_size": 5, "exam_tracker_test": False} and calls == [1, 2]
    assert et.pinned() is None  # turning it off forgets the pin
    assert et.toggle(FakeManager(None), "m", lambda: None) is True


def test_config_default_is_off() -> None:
    from recalldrill.addon_config import DEFAULT_CONFIG, parse_config

    assert DEFAULT_CONFIG.exam_tracker_test is False
    assert parse_config({"exam_tracker_test": True}).exam_tracker_test is True
    assert parse_config({"exam_tracker_test": "yes"}).exam_tracker_test is False


def test_inject_appends_one_block_and_keeps_the_stats() -> None:
    out = et.inject(tree(), '<div id="studiedToday"></div>', None)
    assert out.startswith('<div id="studiedToday"></div><script type="application/json"')
    assert out.count(f'id="{et.DATA_ID}"') == 1


@pytest.fixture(scope="module")
def qt_app() -> object:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from aqt.qt import QApplication
    except ImportError as exc:  # no Qt platform plugin / display
        pytest.skip(f"Qt can't start here: {exc}")
    return QApplication.instance() or QApplication([])


@pytest.fixture
def hooked(qt_app: object, monkeypatch: pytest.MonkeyPatch) -> Any:
    """``register`` against a fake main window; the real hooks, restored afterwards."""
    import aqt
    from aqt import gui_hooks

    state = SimpleNamespace(
        conf={"exam_tracker_test": False}, exports=[], refreshed=0, actions=[], state="deckBrowser"
    )

    class Manager:
        def getConfig(self, m: str) -> dict[str, Any]:  # noqa: N802
            return dict(state.conf)

        def writeConfig(self, m: str, c: dict[str, Any]) -> None:  # noqa: N802
            state.conf = dict(c)

        def addonFromModule(self, m: str) -> str:  # noqa: N802
            return "recall_drill_dev"

        def setWebExports(self, m: str, pattern: str) -> None:  # noqa: N802
            state.exports.append(pattern)

    menu = SimpleNamespace(addAction=state.actions.append)
    deck_browser = SimpleNamespace(refresh=lambda: setattr(state, "refreshed", state.refreshed + 1))
    fake_mw = SimpleNamespace(
        addonManager=Manager(),
        form=SimpleNamespace(menuTools=menu),
        state="deckBrowser",
        deckBrowser=deck_browser,
    )
    # QAction needs a QObject parent; a bare QObject stands in for the main window.
    from aqt.qt import QObject

    parent = QObject()
    monkeypatch.setattr(aqt, "mw", fake_mw)
    hook_names = (
        "deck_browser_will_render_content",
        "webview_will_set_content",
        "webview_did_receive_js_message",
    )
    before = {n: list(getattr(gui_hooks, n)._hooks) for n in hook_names}  # pyright: ignore
    import aqt.qt as aqt_qt

    real_action = aqt_qt.QAction
    monkeypatch.setattr(aqt_qt, "QAction", lambda label, _mw: real_action(label, parent))
    et.register("recall_drill_dev")
    state.parent = parent
    yield state
    for n in hook_names:
        getattr(gui_hooks, n)._hooks[:] = before[n]  # pyright: ignore


@needs_aqt
def test_flag_off_leaves_the_deck_screen_alone(hooked: Any) -> None:
    from aqt import gui_hooks
    from aqt.deckbrowser import DeckBrowser, DeckBrowserContent
    from aqt.webview import WebContent

    browser = DeckBrowser.__new__(DeckBrowser)
    browser._render_data = SimpleNamespace(tree=tree())  # pyright: ignore
    content = DeckBrowserContent(tree="<tr>rows</tr>", stats="<div>stats</div>")
    gui_hooks.deck_browser_will_render_content(browser, content)
    assert (content.tree, content.stats) == ("<tr>rows</tr>", "<div>stats</div>")
    web = WebContent(body="<p>x</p>")
    gui_hooks.webview_will_set_content(web, browser)
    assert web.css == [] and web.js == [] and web.body == "<p>x</p>"
    assert hooked.exports == [et.WEB_PATTERN]  # serving the files is harmless while off

    hooked.conf["exam_tracker_test"] = True  # on: block and files appear, only for the deck screen
    gui_hooks.deck_browser_will_render_content(browser, content)
    assert content.stats.startswith("<div>stats</div><script") and content.tree == "<tr>rows</tr>"
    gui_hooks.webview_will_set_content(web, browser)
    assert web.css == ["/_addons/recall_drill_dev/web/exam_tracker.css"]
    assert web.js == ["/_addons/recall_drill_dev/web/exam_tracker.js"]
    other = WebContent(body="x")
    gui_hooks.webview_will_set_content(other, object())  # any other screen
    assert other.css == [] and other.js == []


@needs_aqt
def test_menu_item_toggles_and_redraws(hooked: Any) -> None:
    (action,) = hooked.actions
    assert action.text() == et.LABEL and action.isCheckable() and not action.isChecked()
    action.trigger()
    assert hooked.conf["exam_tracker_test"] is True and hooked.refreshed == 1
    assert action.isChecked()
    action.trigger()
    assert hooked.conf["exam_tracker_test"] is False and hooked.refreshed == 2


@needs_aqt
def test_page_messages_reach_the_pin_state(hooked: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from aqt import gui_hooks
    from aqt.deckbrowser import DeckBrowser

    monkeypatch.setattr(et, "_pinned", None)
    browser = DeckBrowser.__new__(DeckBrowser)
    assert gui_hooks.webview_did_receive_js_message((False, None), "rdet:pin:12", browser) == (
        True,
        None,
    )
    assert et.pinned() == 12
    assert gui_hooks.webview_did_receive_js_message((False, None), "open:12", browser) == (
        False,
        None,
    )


# --- the pure JS placement function, run under node ------------------------------------

JS = ADDON_ROOT / "web" / "exam_tracker.js"
VIEW = {"width": 900, "height": 600}
CARD = {"width": 340, "height": 150}


def place(anchor: dict[str, int], view: dict[str, int] = VIEW, card: dict[str, int] = CARD) -> Any:
    script = (
        "const m={exports:{}};"  # the repo is "type": "module", so load the plain script by hand
        "require('vm').runInNewContext(require('fs').readFileSync(process.argv[1],'utf8'),"
        "{module:m});const {placeCard}=m.exports;"
        "const a=JSON.parse(process.argv[2]);"
        "console.log(JSON.stringify(placeCard(a.anchor,a.card,a.view,6,8)));"
    )
    out = subprocess.run(
        ["node", "-e", script, str(JS), json.dumps({"anchor": anchor, "card": card, "view": view})],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout)


def row(top: int, left: int = 20, width: int = 400, h: int = 40) -> dict[str, int]:
    return {"left": left, "top": top, "right": left + width, "bottom": top + h}


@pytest.mark.skipif(shutil.which("node") is None, reason="node isn't installed")
@pytest.mark.parametrize(
    ("anchor", "view", "expect"),
    [
        (row(100), VIEW, {"left": 20, "top": 146, "side": "below"}),  # room below
        (row(500), VIEW, {"left": 20, "top": 344, "side": "above"}),  # near the bottom: flips up
        (row(100, left=700), VIEW, {"left": 552, "top": 146, "side": "below"}),  # pulled left
        (row(100, left=-30), VIEW, {"left": 8, "top": 146, "side": "below"}),  # off the left edge
        (
            row(100),
            {"width": 300, "height": 600},
            {"left": 8, "top": 146, "side": "below"},
        ),  # narrow
        (
            row(30, h=40),
            {"width": 900, "height": 190},
            {"left": 20, "top": 32, "side": "below"},
        ),  # tiny window
        (
            row(150),
            {"width": 900, "height": 240},
            {"left": 20, "top": 8, "side": "above"},
        ),  # neither fits: more room, kept on screen
    ],
)
def test_place_card_flips_and_stays_on_screen(
    anchor: dict[str, int], view: dict[str, int], expect: dict[str, Any]
) -> None:
    got = place(anchor, view)
    assert got == expect
    assert 8 <= got["left"] <= max(8, view["width"] - CARD["width"] - 8)
    assert got["top"] >= 8 and (
        got["top"] + CARD["height"] <= view["height"] - 8 or view["height"] < 166
    )


def test_js_has_no_eval_and_only_the_one_screen_hooks() -> None:
    text = JS.read_text(encoding="utf-8")
    assert not re.search(r"\beval\s*\(|new Function|document\.write", text)
