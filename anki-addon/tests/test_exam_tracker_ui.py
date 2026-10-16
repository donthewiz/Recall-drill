"""Exam tracker on the deck screen (v0.4 step 2): the HTML/data builder, the pin, the toggle,
the hooks, and the cache-only render.

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
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from recalldrill import exam_tracker as rules
from recalldrill.exam_tracker import Rates, TrackerNumbers
from recalldrill.storage import Storage
from recalldrill.ui import exam_tracker as et

ADDON_ROOT = Path(__file__).resolve().parent.parent
needs_aqt = pytest.mark.skipif(
    importlib.util.find_spec("aqt") is None, reason="aqt (Anki's GUI package) isn't installed"
)
TODAY = date(2026, 10, 15)


def node(
    deck_id: int, name: str, level: int, children: list[Any] | None = None, collapsed: bool = False
) -> Any:
    return SimpleNamespace(
        deck_id=deck_id, name=name, level=level, collapsed=collapsed, children=children or []
    )


HAP = "Human Anatomy & Physiology 1"


def tree(
    *,
    hap_collapsed: bool = True,
    lab_collapsed: bool = True,
    lec_collapsed: bool = True,
    lec3_collapsed: bool = True,
) -> Any:
    """The user's real deck names. Ids: HAP 10, Lab 11, Lab 1 12, Lab 2 13, Lecture 20,
    Lecture 3 21, Muscle Tissue Chapter 10 22, Medical Terminology 40, Other 50."""
    lab = node(11, "Lab", 2, [node(12, "Lab 1", 3), node(13, "Lab 2", 3)], collapsed=lab_collapsed)
    muscle = node(22, "Muscle Tissue Chapter 10", 4)
    lecture3 = node(21, "Lecture 3", 3, [muscle], collapsed=lec3_collapsed)
    lecture = node(20, "Lecture", 2, [lecture3], collapsed=lec_collapsed)
    return node(
        0,
        "",
        0,
        [
            node(10, HAP, 1, [lab, lecture], collapsed=hap_collapsed),
            node(40, "Medical Terminology", 1),
            node(50, "Other", 1),
        ],
    )


def make(
    drill: int,
    new: int,
    reviews: int,
    done: int,
    pace_total: int,
    exam: date,
    today: date = TODAY,
    rates: Rates = Rates(30, 20, 10),  # noqa: B008
    finish_days_before: int = 1,
) -> TrackerNumbers:
    n = rules.compute(
        exam=exam,
        today=today,
        drill=drill,
        new=new,
        reviews=reviews,
        done_today=done,
        pace_total=pace_total,
        pace_days=7,
        rates=rates,
        finish_days_before=finish_days_before,
    )
    assert n is not None
    return n


# The user's three examples, as real numbers: Lab 2 red (Fri Oct 23), the Lecture 3 chapter
# amber (Mon Oct 26), Medical Terminology green (Tue Dec 8).
LAB2 = make(330, 110, 50, 18, 350, date(2026, 10, 23))
MUSCLE = make(90, 40, 10, 8, 90, date(2026, 10, 26))
MEDTERM = make(1500, 2100, 180, 70, 4000, date(2026, 12, 8), rates=Rates())
NUMBERS = {13: LAB2, 22: MUSCLE, 40: MEDTERM}


def payload_of(numbers: dict[int, TrackerNumbers], **kw: bool) -> dict[str, Any]:
    return et.build_payload(et.rows_from_tree(tree(**kw)), None, numbers)


def payload(**kw: bool) -> dict[str, Any]:
    return payload_of(NUMBERS, **kw)


OPEN = {
    "hap_collapsed": False,
    "lab_collapsed": False,
    "lec_collapsed": False,
    "lec3_collapsed": False,
}


def test_the_three_states_from_real_numbers() -> None:
    assert (LAB2.status, MUSCLE.status, MEDTERM.status) == ("red", "amber", "green")
    p = payload(**OPEN)["decks"]
    assert set(p) == {"13", "22", "40"}
    assert [p[k]["status"] for k in ("13", "22", "40")] == ["red", "amber", "green"]
    red = p["13"]
    assert "Behind" in red["row"] and "8 days to finish" in red["row"]
    assert '<span class="rd-exam-on">· exam Fri Oct 23</span>' in red["row"]
    assert "<div>Finish by Thu Oct 22</div>" in red["card"]  # default: the day before
    assert f"{LAB2.needed} a day needed · 18 done today" in red["row"]
    assert "<button" in red["row"] and "Exam · Fri Oct 23" in red["card"]
    assert "<b>490</b><span>left</span>" in red["card"]
    assert f"<b>18 of {LAB2.needed}</b><span>today</span>" in red["card"]
    assert f"<b>{LAB2.needed}</b><span>a day</span>" in red["card"]
    # drill 30 s + its first day in Anki 20 s, new 20 s, review 10 s, over the share of
    # today's cards left: 46 x (330 x 50 + 110 x 20 + 50 x 10) / 490 = 1,802 s
    assert "<div>330 drill · 110 new · 50 reviews</div><div>Est. 30 min today</div>" in red["card"]
    assert "Slightly behind" in p["22"]["row"] and "11 days to finish" in p["22"]["row"]
    assert "Exam · Mon Oct 26" in p["22"]["card"]
    assert "On pace" in p["40"]["row"] and "54 days to finish" in p["40"]["row"]
    assert "<b>3,780</b>" in p["40"]["card"]
    assert "<div>1,500 drill · 2,100 new · 180 reviews</div>" in p["40"]["card"]
    assert "70 of" in p["40"]["card"]


def test_the_row_counts_to_the_finish_date_and_still_shows_the_exam() -> None:
    """Don, 2026-10-15: count down to the finish date (the exam minus "finish N days
    before"), and keep the exam date on the row and the card."""
    two = make(330, 110, 50, 18, 350, date(2026, 10, 23), finish_days_before=2)
    assert (two.days_left, two.finish_date, two.finish_passed) == (7, date(2026, 10, 21), False)
    p = payload_of({13: two}, **OPEN)["decks"]["13"]
    assert "7 days to finish" in p["row"] and "· exam Fri Oct 23" in p["row"]
    assert "Exam · Fri Oct 23" in p["card"] and "<div>Finish by Wed Oct 21</div>" in p["card"]
    # Past the finish date (Thu Oct 22): it counts to the day before the exam and says so.
    late = make(5, 0, 2, 0, 70, date(2026, 10, 23), today=date(2026, 10, 22), finish_days_before=2)
    assert (late.days_left, late.finish_passed) == (1, True)
    p = payload_of({13: late}, **OPEN)["decks"]["13"]
    assert "finish date passed" in p["row"] and "· exam Fri Oct 23" in p["row"]
    assert "<div>Finish date Wed Oct 21 passed</div>" in p["card"]


def test_est_line_without_history_and_the_bar_lengths() -> None:
    card = payload(**OPEN)["decks"]["40"]["card"]
    assert "<div>Est. time: not enough history yet</div>" in card
    row = payload(**OPEN)["decks"]["13"]["row"]
    # done today / drill / new / reviews, in this order, as flex-grow lengths
    grows = [int(x) for x in re.findall(r"flex-grow:(\d+)", row)]
    assert grows == [18, 330, 110, 50]
    assert re.findall(r'class="rd-seg (rd-seg-\w+)"', row) == [
        "rd-seg-done",
        "rd-seg-drill",
        "rd-seg-new",
        "rd-seg-rev",
    ]


def test_exam_day_shows_the_exam_today_pill_and_two_numbers() -> None:
    today = make(5, 6, 7, 3, 70, TODAY)
    assert today.status == "exam"
    p = payload_of({13: today}, **OPEN)["decks"]["13"]
    assert p["status"] == "exam" and 'class="rd-et rd-exam"' in p["row"]
    assert "Exam today" in p["row"] and "to finish" not in p["row"] and "rd-exam-on" not in p["row"]
    assert "a day needed" not in p["row"] and "3 done today" in p["row"]
    assert "<b>18</b><span>left</span>" in p["card"]
    assert "<b>3</b><span>done today</span>" in p["card"]
    assert "a day" not in p["card"] and "Est." not in p["card"]
    assert "5 drill · 6 new · 7 reviews" in p["card"]


def status_of(p: dict[str, Any], did: int) -> str | None:
    entry = p.get(str(did))
    return entry["status"] if entry else None


def test_rollup_through_the_exact_tree() -> None:
    # Everything collapsed: only the top parent has a row; it shows the worst (red, Lab 2).
    p = payload()["decks"]
    assert status_of(p, 10) == "red" and "via Lab 2" in p["10"]["row"]
    assert "Human Anatomy &amp; Physiology 1::Lab::Lab 2" in p["10"]["card"]  # the aria-label
    assert "Human Anatomy &amp; Physiology 1 › Lab" in p["10"]["card"]
    assert set(p) == {"10", "40"}  # Lab, Lecture, Lecture 3 and the leaves have no row

    # Top expanded: Lab shows red (Lab 2), Lecture shows amber (via Lecture 3 -> Muscle Tissue).
    p = payload(hap_collapsed=False)["decks"]
    assert "10" not in p
    assert status_of(p, 11) == "red" and "via Lab 2" in p["11"]["row"]
    assert status_of(p, 20) == "amber" and "via Muscle Tissue Chapter 10" in p["20"]["row"]
    assert set(p) == {"11", "20", "40"}

    # Lecture expanded too: Lecture shows nothing, Lecture 3 (collapsed) shows amber.
    p = payload(hap_collapsed=False, lec_collapsed=False)["decks"]
    assert "20" not in p and status_of(p, 21) == "amber" and status_of(p, 11) == "red"

    # Lab expanded: Lab shows nothing; Lab 2 shows its own red, Lab 1 nothing.
    p = payload(hap_collapsed=False, lab_collapsed=False)["decks"]
    assert "11" not in p and "12" not in p and status_of(p, 13) == "red"

    # Everything expanded: only the three decks with their own numbers.
    p = payload(**OPEN)["decks"]
    assert set(p) == {"13", "22", "40"}
    assert "via" not in p["13"]["row"] and "via" not in p["22"]["row"]


def test_a_child_that_only_inherits_a_date_has_no_row_of_its_own() -> None:
    # Lecture 3 (21) has no numbers of its own though it sits under an exam deck: expanded, it
    # shows nothing; its child Muscle Tissue (22) has its own.
    p = payload_of({22: MUSCLE}, **OPEN)["decks"]
    assert set(p) == {"22"}


def test_worst_status_wins_and_ties_go_to_the_first() -> None:
    green = make(0, 0, 0, 0, 7, date(2026, 10, 23))
    amber = make(0, 488, 0, 0, 350, date(2026, 10, 23))
    red = make(0, 504, 0, 0, 350, date(2026, 10, 23))
    assert (green.status, amber.status, red.status) == ("green", "amber", "red")
    kids = [node(i, n, 2) for i, n in ((2, "a"), (3, "b"), (4, "c"), (5, "d"))]
    top = node(0, "", 0, [node(1, "P", 1, kids, collapsed=True)])
    row = et.rows_from_tree(top)[0]
    both = {2: green, 3: amber, 4: red, 5: red}
    shown = et.display_for(row, both)
    assert shown is not None and shown[0] == "P::c"
    mild = et.display_for(row, {2: green, 3: amber})
    assert mild is not None and mild[0] == "P::b"
    # an exam today is neutral: it ranks under green
    today = make(1, 1, 1, 0, 7, TODAY)
    only = et.display_for(row, {2: today, 3: green})
    assert only is not None and only[0] == "P::b"


def test_a_deck_with_its_own_numbers_shows_them_even_with_children() -> None:
    top = node(0, "", 0, [node(1, "Medical Terminology", 1, [node(2, "Ch 1", 2)], collapsed=False)])
    assert set(et.build_payload(et.rows_from_tree(top), None, {1: MEDTERM})["decks"]) == {"1"}


def test_numbers_are_keyed_by_deck_id_so_a_rename_changes_nothing() -> None:
    def build(name: str) -> dict[str, Any]:
        top = node(0, "", 0, [node(7, name, 1)])
        return et.build_payload(et.rows_from_tree(top), 7, {7: LAB2})

    before, after = build("Lab 2"), build("Practical 2 (renamed)")
    assert before["pinned"] == after["pinned"] == 7  # the pin follows the id
    assert before["decks"]["7"]["status"] == after["decks"]["7"]["status"]
    assert "Practical 2 (renamed)" in after["decks"]["7"]["card"]
    # the row text carries no deck name except in the pill's aria-label
    assert before["decks"]["7"]["row"].replace("Lab 2", "") == after["decks"]["7"]["row"].replace(
        "Practical 2 (renamed)", ""
    )


@pytest.mark.parametrize(
    ("did", "leaf", "path"),
    [
        ("13", "Lab 2", "Human Anatomy &amp; Physiology 1 › Lab"),
        (
            "22",
            "Muscle Tissue Chapter 10",
            "Human Anatomy &amp; Physiology 1 › Lecture › Lecture 3",
        ),
        ("40", "Medical Terminology", None),
    ],
)
def test_card_title_is_the_leaf_with_the_parent_path_under_it(
    did: str, leaf: str, path: str | None
) -> None:
    card = payload(**OPEN)["decks"][did]["card"]
    assert f'<strong class="rd-card-title">{leaf}</strong>' in card
    assert '<span class="rd-card-exam">' in card  # the exam stays on the title line
    if path is None:
        assert "rd-card-path" not in card  # a top-level deck has no path line
    else:
        assert f'<div class="rd-card-path">{path}</div>' in card
        head = card[card.index("rd-card-head") : card.index("rd-card-nums")]
        assert "::" not in head  # the raw path never shows in the title
        assert card.index("rd-card-title") < card.index("rd-card-path")


def test_card_title_escapes_every_part() -> None:
    amp = et.card_html("A & B::C & D", MEDTERM)
    assert '<div class="rd-card-path">A &amp; B</div>' in amp
    assert '<strong class="rd-card-title">C &amp; D</strong>' in amp
    nasty = et.card_html("<script>x</script>::<script>y</script>", MEDTERM)
    assert "<script>" not in nasty
    assert '<div class="rd-card-path">&lt;script&gt;x&lt;/script&gt;</div>' in nasty
    assert '<strong class="rd-card-title">&lt;script&gt;y&lt;/script&gt;</strong>' in nasty


def test_deck_names_are_escaped() -> None:
    nasty = '<script>alert(1)</script> & "q"'
    row = et.row_html(nasty, MEDTERM, via=nasty, level=1)
    card = et.card_html(nasty, MEDTERM)
    for out in (row, card):
        assert "<script>" not in out
        assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; &quot;q&quot;" in out
    # ...and in the JSON block nothing can close the tag early.
    top = node(0, "", 0, [node(1, nasty, 1)])
    block = et.script_tag(et.build_payload(et.rows_from_tree(top), None, {1: MEDTERM}))
    assert block.count("<") == 2 and block.count("</script>") == 1  # open tag + the closing tag
    inner = block[block.index(">") + 1 : block.rindex("</script>")]
    assert "<" not in inner and "&" not in inner
    assert "alert(1)" in json.loads(inner)["decks"]["1"]["card"]


def test_the_json_block_gives_back_the_exact_html() -> None:
    """What the page's ``JSON.parse`` reads is the row and card HTML unchanged: spaces stay
    spaces, and only the two line separators (and <, >, &) are escaped. A plain space
    replaced by U+2028 once broke every tag on Don's deck screen."""
    name = "Lab 2 \u2028 x\u2029y & <b>"
    top = node(0, "", 0, [node(1, name, 1)])
    payload = et.build_payload(et.rows_from_tree(top), None, {1: MEDTERM})
    block = et.script_tag(payload)
    inner = block[block.index(">") + 1 : block.rindex("</script>")]
    assert json.loads(inner) == payload
    row = payload["decks"]["1"]["row"]
    assert row.startswith('<div class="rd-et rd-')
    assert "\u2028" not in inner and "\u2029" not in inner
    assert "\\u2028" in inner and "\\u2029" in inner
    assert " " in inner  # ordinary spaces pass through untouched
    source = Path(et.__file__).read_text(encoding="utf-8")
    assert "\u2028" not in source and "\u2029" not in source  # escapes only, never raw


def test_pin_in_the_payload_needs_a_row_now() -> None:
    rows = et.rows_from_tree(tree())
    assert et.build_payload(rows, 10, NUMBERS)["pinned"] == 10
    assert et.build_payload(rows, 999, NUMBERS)["pinned"] is None
    assert et.build_payload(rows, 13, NUMBERS)["pinned"] is None  # row hidden by the collapse


def test_a_pin_is_dropped_only_for_a_deck_that_is_no_longer_an_exam_deck() -> None:
    assert et.pin_to_drop(13, NUMBERS, fresh=True) is False
    assert et.pin_to_drop(99, NUMBERS, fresh=True) is True
    assert et.pin_to_drop(99, NUMBERS, fresh=False) is False  # not judged before numbers exist
    assert et.pin_to_drop(None, NUMBERS, fresh=True) is False


def test_pin_messages_are_saved_in_the_profile(tmp_path: Path) -> None:
    st = Storage(tmp_path, "User 1")
    assert et.read_pin(st) is None
    assert et.handle_message("rdet:pin:12", st) and et.read_pin(st) == 12
    # saved as the profile's exam_tracker.json: {"pinned": 12}, schemaVersion 1
    raw = json.loads((st.dir / "exam_tracker.json").read_text(encoding="utf-8"))
    assert raw == {"schemaVersion": 1, "data": {"pinned": 12}}
    # "after an Anki restart": a new Storage over the same folder reads it back
    assert et.read_pin(Storage(tmp_path, "User 1")) == 12
    assert et.read_pin(Storage(tmp_path, "Other profile")) is None
    assert et.handle_message("rdet:pin:abc", st) and et.read_pin(st) is None
    assert et.handle_message("rdet:pin:7", st) and et.handle_message("rdet:unpin", st)
    assert et.read_pin(st) is None
    assert not et.handle_message("open:5", st) and not et.handle_message("collapse:5", st)


def test_a_corrupt_or_odd_pin_file_reads_as_no_pin(tmp_path: Path) -> None:
    st = Storage(tmp_path, "User 1")
    for data in ({"pinned": "x"}, {"pinned": True}, {"pinned": None}, [], {}):
        st.write_json("exam_tracker.json", data)
        assert et.read_pin(st) is None


class FakeManager:
    def __init__(self, conf: dict[str, Any] | None) -> None:
        self.conf = conf
        self.writes: list[dict[str, Any]] = []

    def getConfig(self, module: str) -> dict[str, Any] | None:  # noqa: N802
        return self.conf

    def writeConfig(self, module: str, conf: dict[str, Any]) -> None:  # noqa: N802
        self.conf = conf
        self.writes.append(conf)


def test_toggle_flips_the_flag_and_requests_a_refresh(tmp_path: Path) -> None:
    st = Storage(tmp_path, "User 1")
    et.write_pin(st, 10)
    mgr = FakeManager({"batch_size": 5, "exam_tracker": True})
    calls: list[int] = []
    assert et.is_on(mgr, "m")
    assert et.toggle(mgr, "m", lambda: calls.append(1), st) is False
    assert mgr.conf == {"batch_size": 5, "exam_tracker": False} and calls == [1]
    assert et.read_pin(st) is None  # turning it off forgets the pin
    assert not et.is_on(mgr, "m")
    assert et.toggle(mgr, "m", lambda: calls.append(2), st) is True
    assert mgr.conf == {"batch_size": 5, "exam_tracker": True} and calls == [1, 2]
    # no config yet: the default is on, so the first flip turns it off
    assert et.toggle(FakeManager(None), "m", lambda: None) is False


def test_config_default_is_on_and_the_old_test_key_is_ignored() -> None:
    from recalldrill.addon_config import DEFAULT_CONFIG, parse_config

    assert DEFAULT_CONFIG.exam_tracker is True
    assert parse_config(None).exam_tracker is True
    assert parse_config({"exam_tracker": False}).exam_tracker is False
    assert parse_config({"exam_tracker": "no"}).exam_tracker is True  # mistyped: the default
    # a user's old config still has exam_tracker_test: not an error, and it changes nothing
    assert parse_config({"exam_tracker_test": True}).exam_tracker is True
    assert parse_config({"exam_tracker_test": False}).exam_tracker is True
    assert parse_config({"exam_tracker_test": False, "exam_tracker": False}).exam_tracker is False
    assert et.is_on(FakeManager({"exam_tracker_test": False}), "m") is True


def test_inject_appends_one_block_and_keeps_the_stats() -> None:
    out = et.inject(tree(), '<div id="studiedToday"></div>', None, NUMBERS)
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
def hooked(qt_app: object, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """``register`` against a fake main window; the real hooks, restored afterwards. The
    reader is replaced by a recorder: a test finishes a run by hand."""
    import aqt
    from aqt import gui_hooks

    state = SimpleNamespace(
        conf={"exam_tracker": True},
        exports=[],
        refreshed=0,
        actions=[],
        runs=[],
        storage=Storage(tmp_path, "User 1"),
        today=TODAY,
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
        col=object(),
    )
    # QAction needs a QObject parent; a bare QObject stands in for the main window.
    from aqt.qt import QObject

    parent = QObject()
    monkeypatch.setattr(aqt, "mw", fake_mw)
    import recalldrill.anki_io.workload as workload

    monkeypatch.setattr(workload, "today_for", lambda col: (state.today, 4))
    monkeypatch.setattr(et, "start_reader", lambda storage, finish: state.runs.append(finish))
    monkeypatch.setattr(et, "_cache", et.NumbersCache())
    hook_names = (
        "deck_browser_will_render_content",
        "webview_will_set_content",
        "webview_did_receive_js_message",
        "operation_did_execute",
        "sync_did_finish",
        "profile_will_close",
    )
    before = {n: list(getattr(gui_hooks, n)._hooks) for n in hook_names}  # pyright: ignore
    import aqt.qt as aqt_qt

    real_action = aqt_qt.QAction
    monkeypatch.setattr(aqt_qt, "QAction", lambda label, _mw: real_action(label, parent))
    ctx = SimpleNamespace(module="recall_drill_dev", storage=lambda: state.storage)
    et.register(ctx)
    state.parent = parent
    state.mw = fake_mw
    yield state
    et._refresher = None  # pyright: ignore[reportPrivateUsage]
    for n in hook_names:
        getattr(gui_hooks, n)._hooks[:] = before[n]  # pyright: ignore


def render(tree_: Any, stats: str = "<div>stats</div>") -> Any:
    from aqt import gui_hooks
    from aqt.deckbrowser import DeckBrowser, DeckBrowserContent

    browser = DeckBrowser.__new__(DeckBrowser)
    browser._render_data = SimpleNamespace(tree=tree_)  # pyright: ignore
    content = DeckBrowserContent(tree="<tr>rows</tr>", stats=stats)
    gui_hooks.deck_browser_will_render_content(browser, content)
    return content


def result(numbers: dict[int, TrackerNumbers], day: date = TODAY) -> Any:
    return SimpleNamespace(day=day, numbers=numbers)


@needs_aqt
def test_flag_off_leaves_the_deck_screen_alone_byte_for_byte(hooked: Any) -> None:
    from aqt import gui_hooks
    from aqt.deckbrowser import DeckBrowser
    from aqt.webview import WebContent

    hooked.conf["exam_tracker"] = False
    content = render(tree())
    assert (content.tree, content.stats) == ("<tr>rows</tr>", "<div>stats</div>")
    assert hooked.runs == []  # and no reader is started
    browser = DeckBrowser.__new__(DeckBrowser)
    web = WebContent(body="<p>x</p>")
    gui_hooks.webview_will_set_content(web, browser)
    assert web.css == [] and web.js == [] and web.body == "<p>x</p>"
    assert hooked.exports == [et.WEB_PATTERN]  # serving the files is harmless while off


@needs_aqt
def test_on_adds_the_block_and_the_files_to_the_deck_screen_only(hooked: Any) -> None:
    from aqt import gui_hooks
    from aqt.deckbrowser import DeckBrowser
    from aqt.webview import WebContent

    browser = DeckBrowser.__new__(DeckBrowser)
    web = WebContent(body="<p>x</p>")
    gui_hooks.webview_will_set_content(web, browser)
    assert web.css == ["/_addons/recall_drill_dev/web/exam_tracker.css"]
    assert web.js == ["/_addons/recall_drill_dev/web/exam_tracker.js"]
    other = WebContent(body="x")
    gui_hooks.webview_will_set_content(other, object())  # any other screen
    assert other.css == [] and other.js == []
    content = render(tree())
    assert content.stats.startswith("<div>stats</div><script") and content.tree == "<tr>rows</tr>"


@needs_aqt
def test_render_draws_only_the_cache_and_a_miss_schedules_one_run(hooked: Any) -> None:
    content = render(tree(**OPEN))
    block = _block(content.stats)
    assert block["decks"] == {}  # nothing computed in the hook: no rows, no placeholder
    assert len(hooked.runs) == 1  # one background run scheduled
    render(tree(**OPEN))  # drawn again before the run ends: still one run
    assert len(hooked.runs) == 1
    assert hooked.refreshed == 0
    # the run ends: its result is cached and the deck screen is redrawn once
    hooked.runs.pop(0)(result(NUMBERS))
    assert hooked.refreshed == 1
    block = _block(render(tree(**OPEN)).stats)
    assert set(block["decks"]) == {"13", "22", "40"}
    assert len(hooked.runs) == 0  # fresh cache: nothing more to run


def _block(stats: str) -> dict[str, Any]:
    m = re.search(r'id="rd-exam-tracker-data">(.*?)</script>', stats, re.S)
    assert m is not None
    return json.loads(m.group(1))


@needs_aqt
def test_a_result_for_another_day_is_not_drawn(hooked: Any) -> None:
    from datetime import timedelta

    render(tree(**OPEN))
    hooked.runs.pop(0)(result(NUMBERS, TODAY - timedelta(days=1)))
    block = _block(render(tree(**OPEN)).stats)
    assert block["decks"] == {}  # yesterday's numbers are never drawn today
    assert len(hooked.runs) == 1  # and a new run is asked for


@needs_aqt
def test_two_requests_during_a_run_make_exactly_one_more_run(hooked: Any) -> None:
    from aqt import gui_hooks

    render(tree(**OPEN))
    assert len(hooked.runs) == 1
    changes = SimpleNamespace(card=True, note=False, deck=False, study_queues=False)
    gui_hooks.operation_did_execute(changes, None)
    gui_hooks.sync_did_finish()
    et.request_refresh()
    assert len(hooked.runs) == 1  # still the first run
    hooked.runs.pop(0)(result(NUMBERS))
    assert len(hooked.runs) == 1  # exactly one extra, after it
    hooked.runs.pop(0)(result(NUMBERS))
    assert hooked.runs == []


@needs_aqt
def test_only_collection_changes_that_matter_refresh(hooked: Any) -> None:
    from aqt import gui_hooks

    hooked.state = "deckBrowser"
    render(tree(**OPEN))
    hooked.runs.pop(0)(result(NUMBERS))
    hooked.refreshed = 0
    nothing = SimpleNamespace(card=False, note=False, deck=False, study_queues=False)
    gui_hooks.operation_did_execute(nothing, None)
    assert hooked.runs == []
    for field in ("card", "note", "deck", "study_queues"):
        changes = SimpleNamespace(card=False, note=False, deck=False, study_queues=False)
        setattr(changes, field, True)
        gui_hooks.operation_did_execute(changes, None)
        assert len(hooked.runs) == 1, field
        hooked.runs.pop(0)(result(NUMBERS))
    # while another screen shows, the change only marks the cache stale
    hooked.mw.state = "review"
    changes = SimpleNamespace(card=True, note=False, deck=False, study_queues=False)
    gui_hooks.operation_did_execute(changes, None)
    assert hooked.runs == []
    hooked.mw.state = "deckBrowser"
    render(tree(**OPEN))  # shown again: now it recomputes (the old numbers are still drawn)
    assert len(hooked.runs) == 1


@needs_aqt
def test_a_failed_run_draws_nothing_new(hooked: Any) -> None:
    render(tree(**OPEN))
    hooked.runs.pop(0)(None)
    assert hooked.refreshed == 0


@needs_aqt
def test_pin_is_restored_on_render_and_dropped_when_no_longer_an_exam_deck(hooked: Any) -> None:
    from aqt import gui_hooks
    from aqt.deckbrowser import DeckBrowser

    browser = DeckBrowser.__new__(DeckBrowser)
    assert gui_hooks.webview_did_receive_js_message((False, None), "rdet:pin:13", browser) == (
        True,
        None,
    )
    assert et.read_pin(hooked.storage) == 13
    assert gui_hooks.webview_did_receive_js_message((False, None), "open:12", browser) == (
        False,
        None,
    )
    render(tree(**OPEN))
    assert et.read_pin(hooked.storage) == 13  # before any result, the pin is kept
    hooked.runs.pop(0)(result(NUMBERS))
    block = _block(render(tree(**OPEN)).stats)
    assert block["pinned"] == 13  # restored after a redraw (and, being a file, a restart)
    et.request_refresh()  # a change; the run finds that Lab 2's exam is over
    hooked.runs.pop(0)(result({40: MEDTERM}))  # Lab 2's exam is over: no longer an exam deck
    block = _block(render(tree(**OPEN)).stats)
    assert block["pinned"] is None and et.read_pin(hooked.storage) is None


@needs_aqt
def test_menu_item_toggles_and_redraws_without_a_restart(hooked: Any) -> None:
    (action,) = hooked.actions
    assert action.text() == et.LABEL == "Exam tracker on deck screen"
    assert action.isCheckable() and action.isChecked()
    action.trigger()
    assert hooked.conf["exam_tracker"] is False and hooked.refreshed == 1
    assert not action.isChecked()
    assert render(tree()).stats == "<div>stats</div>"  # off: Anki's own, byte for byte
    action.trigger()
    assert hooked.conf["exam_tracker"] is True and hooked.refreshed == 2 and action.isChecked()


# --- the pure JS placement function, run under node ------------------------------------

JS = ADDON_ROOT / "web" / "exam_tracker.js"
CSS = ADDON_ROOT / "web" / "exam_tracker.css"
VIEW = {"width": 1000, "height": 600}
CARD = {"width": 280, "height": 150}


def place(anchor: dict[str, int], view: dict[str, int] = VIEW, card: dict[str, int] = CARD) -> Any:
    script = (
        "const m={exports:{}};"  # the repo is "type": "module", so load the plain script by hand
        "require('vm').runInNewContext(require('fs').readFileSync(process.argv[1],'utf8'),"
        "{module:m});const {placeCard}=m.exports;"
        "const a=JSON.parse(process.argv[2]);"
        "console.log(JSON.stringify(placeCard(a.anchor,a.card,a.view,6,8,10)));"
    )
    out = subprocess.run(
        ["node", "-e", script, str(JS), json.dumps({"anchor": anchor, "card": card, "view": view})],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout)


def row(top: int, left: int = 40, right: int = 600, h: int = 40) -> dict[str, int]:
    """`left` is the pill's left edge, `right` the table's right edge."""
    return {"left": left, "top": top, "right": right, "bottom": top + h}


NO_NODE = pytest.mark.skipif(shutil.which("node") is None, reason="node isn't installed")


@NO_NODE
@pytest.mark.parametrize(
    ("anchor", "view", "expect"),
    [
        # room on the right: beside the table (600 + 10), level with the row, arrow at its middle
        (row(100), VIEW, {"left": 610, "top": 100, "side": "right", "arrow": 20}),
        # row near the bottom: card pulled up onto the screen; arrow still aims at the row
        (row(520), VIEW, {"left": 610, "top": 442, "side": "right", "arrow": 98}),
        # row near the top edge: top stays at the margin
        (row(2), VIEW, {"left": 610, "top": 8, "side": "right", "arrow": 16}),
        # no room on the right (610 + 280 + 8 > 800): below the row, left edge on the pill
        (
            row(100, right=560),
            {"width": 800, "height": 600},
            {"left": 40, "top": 146, "side": "below", "arrow": 20},
        ),
        # no room below: flips above the row
        (
            row(500, right=560),
            {"width": 800, "height": 600},
            {"left": 40, "top": 344, "side": "above", "arrow": 20},
        ),
        # narrow window: below, shifted left to stay on screen
        (
            row(100, left=200, right=560),
            {"width": 400, "height": 600},
            {"left": 112, "top": 146, "side": "below", "arrow": 108},
        ),
        # very short window: nothing fits; stays on screen with the roomier side
        (
            row(150, right=560),
            {"width": 800, "height": 240},
            {"left": 40, "top": 8, "side": "above", "arrow": 20},
        ),
        # very short window, room on the right: pinned to the margin
        (
            row(30),
            {"width": 1000, "height": 120},
            {"left": 610, "top": 8, "side": "right", "arrow": 42},
        ),
    ],
)
def test_place_card_beside_then_below_then_above(
    anchor: dict[str, int], view: dict[str, int], expect: dict[str, Any]
) -> None:
    got = place(anchor, view)
    assert got == expect
    assert 8 <= got["left"] <= max(8, view["width"] - CARD["width"] - 8)
    assert got["top"] >= 8
    if view["height"] >= CARD["height"] + 16:
        assert got["top"] + CARD["height"] <= view["height"] - 8
    if got["side"] == "right":
        assert got["left"] - anchor["right"] == 10  # the 10 px gap, so no deck is covered
    else:  # below or above: the card never covers the hovered row
        assert (
            got["top"] >= anchor["bottom"]
            or got["top"] + CARD["height"] <= anchor["top"]
            or (view["height"] <= 240)
        )


def slide(samples: list[tuple[int, int]], side: str) -> Any:
    pts = [{"x": x, "y": y, "t": i * 20} for i, (x, y) in enumerate(samples)]
    script = (
        "const m={exports:{}};"
        "require('vm').runInNewContext(require('fs').readFileSync(process.argv[1],'utf8'),"
        "{module:m});const {slideFrom}=m.exports;"
        "const a=JSON.parse(process.argv[2]);"
        "console.log(JSON.stringify(slideFrom(a.samples,a.side)));"
    )
    out = subprocess.run(
        ["node", "-e", script, str(JS), json.dumps({"samples": pts, "side": side})],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout)


@NO_NODE
@pytest.mark.parametrize(
    ("samples", "side", "expect"),
    [
        ([(100, 100), (100, 130)], "right", {"dx": 0, "dy": -6}),  # moving down: starts higher
        ([(100, 130), (100, 100)], "right", {"dx": 0, "dy": 6}),  # moving up: starts lower
        ([(100, 100), (130, 100)], "below", {"dx": -6, "dy": 0}),  # moving right: starts left
        ([(130, 100), (100, 100)], "below", {"dx": 6, "dy": 0}),  # moving left: starts right
        ([(100, 100), (120, 110)], "right", {"dx": -6, "dy": 0}),  # diagonal: x dominates
        ([(100, 100), (110, 125)], "right", {"dx": 0, "dy": -6}),  # diagonal: y dominates
        ([(100, 100), (110, 90)], "right", {"dx": 0, "dy": 6}),  # tie: vertical (up)
        ([(100, 100), (110, 110)], "right", {"dx": 0, "dy": -6}),  # tie: vertical (down)
        ([(100, 100), (102, 102)], "right", {"dx": -6, "dy": 0}),  # under 4 px: default
        ([(100, 100), (103, 100)], "above", {"dx": 0, "dy": 6}),  # under 4 px: default
        ([(100, 100), (104, 100)], "right", {"dx": -6, "dy": 0}),  # exactly 4 px counts
        ([(100, 100)], "below", {"dx": 0, "dy": -6}),  # one sample: default
        ([], "right", {"dx": -6, "dy": 0}),  # none: right
        ([], "below", {"dx": 0, "dy": -6}),  # none: below
        ([], "above", {"dx": 0, "dy": 6}),  # none: above
        # reverses: first -> last wins (net down 10 px, though it went down 40 then up 30)
        ([(100, 100), (100, 140), (100, 110)], "right", {"dx": 0, "dy": -6}),
        # reverses to a net tiny movement: default
        ([(100, 100), (100, 140), (100, 101)], "above", {"dx": 0, "dy": 6}),
    ],
)
def test_slide_from_follows_the_cursor(
    samples: list[tuple[int, int]], side: str, expect: dict[str, int]
) -> None:
    assert slide(samples, side) == expect


def test_js_has_no_eval_and_only_the_one_screen_hooks() -> None:
    text = JS.read_text(encoding="utf-8")
    assert not re.search(r"\beval\s*\(|new Function|document\.write", text)


def test_timing_constants_are_named_in_the_js() -> None:
    text = JS.read_text(encoding="utf-8")
    for name, value in (
        ("SHOW_MS", 300),
        ("HIDE_MS", 200),
        ("FADE_MS", 400),
        ("SLIDE_MS", 600),
        ("CLOSE_MS", 150),
        ("SLIDE_PX", 6),
        ("SAMPLE_MS", 200),
        ("MAX_SAMPLES", 6),
        ("MIN_MOVE", 4),
        ("SIDE_GAP", 10),
    ):
        assert re.search(rf"var {name} = {re.escape(str(value))};", text), name
    assert "var EASE = 'ease';" in text
    assert "OPEN_MS" not in text and "START_SCALE" not in text and "scale" not in text.lower()
    assert "stale" not in text and "tests/test_exam_tracker_ui.py" in text
    assert "test_exam_tracker_js" not in text


def test_css_size_motion_and_row_alignment() -> None:
    css = CSS.read_text(encoding="utf-8")
    start = css.index(".rd-card {\n  position: fixed")
    card = css[start : css.index("}", start)]
    for rule in (
        "width: 280px",
        "padding: 8px 12px 9px",
        "border-radius: 10px",
        "border-left: 3px solid",
        "box-shadow: 0 6px 16px rgba(0, 0, 0, 0.4)",
        "pointer-events: none",  # a hidden or fading card takes no clicks
    ):
        assert rule in card, rule
    assert ".rd-card.rd-in" in css and "pointer-events: auto" in css
    # the card starts displaced by the cursor-direction variables (no scale)
    assert "transform: translate(var(--rd-from-x, 0), var(--rd-from-y, 0));" in card
    assert "scale" not in css
    opening = css[css.index(".rd-card.rd-in {") :]
    opening = opening[: opening.index("}")]
    assert "opacity var(--rd-fade-ms) var(--rd-ease)" in opening
    assert "transform var(--rd-slide-ms) var(--rd-ease)" in opening
    # closing: opacity only (no transform transition), and still click-through
    closing = css[css.index(".rd-card.rd-out {") :]
    closing = closing[: closing.index("}")]
    assert "transition: opacity var(--rd-close-ms) var(--rd-ease)" in closing
    assert "pointer-events: none" in closing
    assert "transform: none" in closing and "transform var" not in closing
    reduced = css[css.index("@media (prefers-reduced-motion: reduce)") :]
    reduced = reduced[: reduced.index("\n}")]
    assert "transition: none" in reduced and "transform: none" in reduced
    assert ".rd-card.rd-out" in reduced  # no fade, slide or scale: it just appears
    # the numbers sit on the deck name's baseline: no pixel offset, no Redesign-specific height
    align = re.search(r"table tr\.deck\.rd-has-et > td \{([^}]*)\}", css)
    assert align is not None and "vertical-align: baseline !important" in align.group(1)
    assert not re.search(r"(padding|margin|top|height)[^;{}]*\d+px[^;{}]*;", align.group(1))
    assert "table tr.deck.rd-has-et > td.opts { vertical-align: top !important; }" in css
    sizes = [int(x) for x in re.findall(r"font-size: (\d+)px", css)]
    assert min(sizes) >= 11  # the 11px is only the pill's tiny icon glyph
    for sel in (".rd-card-exam", ".rd-card-nums span", ".rd-card-split"):
        assert re.search(re.escape(sel) + r"[^}]*font-size: 12px", css), sel


def test_js_hands_the_motion_constants_to_the_css() -> None:
    text = JS.read_text(encoding="utf-8")
    for var, const in (
        ("--rd-fade-ms", "FADE_MS"),
        ("--rd-slide-ms", "SLIDE_MS"),
        ("--rd-close-ms", "CLOSE_MS"),
        ("--rd-ease", "EASE"),
    ):
        assert re.search(rf"setProperty\('{var}', [^;]*{const}", text), var
    assert "'--rd-from-x'" in text and "'--rd-from-y'" in text
    assert "mousemove" in text


def test_payload_shape_is_unchanged() -> None:
    p = payload(**OPEN)
    assert set(p) == {"decks", "pinned"}
    assert all(set(v) == {"status", "row", "card"} for v in p["decks"].values())


def test_the_test_label_and_the_fake_table_are_gone() -> None:
    assert not hasattr(et, "FAKE") and not hasattr(et, "Fake")
    assert ".rd-card-test" not in CSS.read_text(encoding="utf-8")
    card = payload(**OPEN)["decks"]["13"]["card"]
    assert "TEST" not in card and "fake" not in card.lower()
    assert "rd-exam" in CSS.read_text(encoding="utf-8")  # the neutral exam-day pill
