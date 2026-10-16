"""Math cards (v0.6) on a scratch collection: the card contract, the build, a full session,
and the handoff, history and outcomes rows."""

from __future__ import annotations

from pathlib import Path

import pytest
from anki.collection import Collection
from anki_fixtures import (
    AMC,
    AMC_SAMPLE,
    add_amc_models,
    add_math_model,
    add_math_note,
    add_note,
    deck,
)
from layer_scene import build as build_lab

from recalldrill import history_store, sessions
from recalldrill.anki_io.build import build_session, rebuild_card
from recalldrill.anki_io.export import export_outcomes
from recalldrill.anki_io.handoff import HandoffSettings, apply_handoff, handoff_line, plan_handoff
from recalldrill.anki_io.mathcards import math_answer_text, math_card, math_status
from recalldrill.anki_io.notetypes import MappingTable
from recalldrill.anki_io.resume import check_resume
from recalldrill.anki_io.select import Scope, SelectOptions, options_to_json, select_cards
from recalldrill.controller import ControllerSettings
from recalldrill.engine.session import select_trial
from recalldrill.math_answer import engine_target
from recalldrill.storage import Storage

NOW = 1_790_000_000_000
QUADRATIC = "x=(-b+-sqrt(b^2-4ac))/(2a)"


def _math_notes(col: Collection, did: int) -> dict[str, int]:
    """The math notes of the contract's examples, plus the edge cases; name -> note id."""
    add_math_model(col)
    d = did  # type: ignore[assignment]
    ids: dict[str, int] = {}

    def add(name: str, *args: object, **kw: object) -> None:
        ids[name] = add_math_note(col, d, *args, **kw).id  # type: ignore[arg-type]

    add(
        "quadratic",
        "The quadratic formula:",
        r"x=\frac{-b\pm\sqrt{b^2-4ac}}{2a}",
        QUADRATIC,
        ("rd::math", "Layer::1"),
    )
    add(
        "slope",
        "Slope:",
        r"m=\frac{y_2-y_1}{x_2-x_1}",
        "m=(y2-y1)/(x2-x1)",
        ("rd::math", "Layer::1"),
    )
    add(
        "diff",
        "Difference of squares:",
        r"(a+b)(a-b)",
        "(a+b)(a-b)",
        ("rd::math", "rd::math::equiv", "Layer::1"),
    )
    add("interval", "Interval:", r"[-2,5)", "[-2,5)", ("rd::math", "Layer::2"))
    add("points", "Points:", r"(1,2),(3,4),(5,6)", "(1,2),(3,4),(5,6)", ("rd::math", "Layer::2"))
    add("gap_empty", "Empty:", "x", "", ("rd::math", "Layer::2"))
    add("gap_unreadable", "Broken:", "x", "x+(", ("rd::math", "Layer::2"))
    add("untagged", "Not tagged:", "x+1", "x+1", ("Layer::2",))
    add("equiv_only", "Equiv tag only:", "x+1", "x+1", ("rd::math::equiv", "Layer::2"))
    add("lookalike", "Other tag:", "x+1", "x+1", ("rd::mathx", "rd::drill::A", "Layer::2"))
    return ids


def _scene(col: Collection, tmp_path: Path) -> tuple[Storage, int, dict[str, int]]:
    st = Storage(tmp_path / "user_files", "User 1")
    scene = build_lab(col, st)
    return st, scene.chapters["Bones"], _math_notes(col, scene.chapters["Bones"])


def _pick(col: Collection, did: int, **opts: object):
    table = MappingTable(col)
    sel = select_cards(col, Scope(deck_id=did), SelectOptions(**opts), table)  # type: ignore[arg-type]
    return sel, build_session(col, sel, None, table, {})


# -- the contract -------------------------------------------------------------------


def test_the_contract(col: Collection, tmp_path: Path) -> None:
    _, bones, ids = _scene(col, tmp_path)
    notes = {k: col.get_note(v) for k, v in ids.items()}  # type: ignore[arg-type]
    assert math_status(notes["quadratic"], notes["quadratic"].tags) == "math"
    mc = math_card(notes["quadratic"], notes["quadratic"].tags)
    assert mc is not None and mc.target == QUADRATIC and not mc.equiv
    diff = math_card(notes["diff"], notes["diff"].tags)
    assert diff is not None and diff.equiv
    for name in ("gap_empty", "gap_unreadable"):
        assert math_status(notes[name], notes[name].tags) == "no_answer"
        assert math_card(notes[name], notes[name].tags) is None
    # Exact tags: neither the equiv tag alone, nor a lookalike, nor no tag makes a math note.
    for name in ("untagged", "equiv_only", "lookalike"):
        assert math_status(notes[name], notes[name].tags) is None
    assert math_answer_text(notes["quadratic"]) == QUADRATIC


def test_a_cloze_without_the_field_is_drilled_as_a_normal_card(
    col: Collection, tmp_path: Path
) -> None:
    add_amc_models(col)
    did = int(deck(col, "Plain"))
    note = add_note(col, AMC, did, AMC_SAMPLE, ("rd::math",))  # type: ignore[arg-type]
    assert math_status(note, note.tags) == "no_answer"
    sel, res = _pick(col, did)
    assert sel.math_cards == 0 and sel.math_gaps == 1
    assert res.sources[0].math_target == "" and res.deck_items[0]["back"] == "osseous tissue"


# -- the build ------------------------------------------------------------------------


def test_the_build_makes_one_item_per_math_card(col: Collection, tmp_path: Path) -> None:
    _, bones, ids = _scene(col, tmp_path)
    sel, res = _pick(col, bones)
    by_nid = {s.nid: (s, i) for s, i in zip(res.sources, res.deck_items, strict=True)}
    for name, answer, equiv in (
        ("quadratic", QUADRATIC, False),
        ("slope", "m=(y2-y1)/(x2-x1)", False),
        ("diff", "(a+b)(a-b)", True),
        ("interval", "[-2,5)", False),
        ("points", "(1,2),(3,4),(5,6)", False),
    ):
        src, item = by_nid[ids[name]]
        assert src.math_target == answer and src.math_equiv is equiv, name
        assert item["back"] == engine_target(answer) and "anyOrder" not in item
        assert src.answer_hash and src.colliding_answers == () and src.hint == ""
    # The untagged note is an ordinary cloze: its answer is the cloze text.
    src, item = by_nid[ids["untagged"]]
    assert src.math_target == "" and item["back"] != engine_target("x+1")
    # The panel counts: 5 math cards, 2 tagged cards without a usable answer.
    assert sel.math_cards == 5 and sel.math_gaps == 2


def test_the_front_is_the_cloze_with_its_mathjax(col: Collection, tmp_path: Path) -> None:
    _, bones, ids = _scene(col, tmp_path)
    _, res = _pick(col, bones)
    src = next(s for s in res.sources if s.nid == ids["quadratic"])
    assert "\\(x=\\frac{-b\\pm" in src.front_html or "[...]" in src.front_html


def test_rebuild_and_resume_follow_the_math_answer(col: Collection, tmp_path: Path) -> None:
    _, bones, ids = _scene(col, tmp_path)
    table = MappingTable(col)
    _, res = _pick(col, bones)
    src = next(s for s in res.sources if s.nid == ids["interval"])
    rebuilt = rebuild_card(col, src, table)
    assert rebuilt is not None and rebuilt.back == engine_target("[-2,5)")
    assert rebuilt.source.math_target == "[-2,5)" and rebuilt.any_order is None
    saved = {"addon": {"sources": [s.__dict__ | {"colliding_answers": []} for s in res.sources]}}
    assert check_resume(col, saved, table).changed == ()
    note = col.get_note(ids["interval"])  # type: ignore[arg-type]
    note["MathAnswer"] = "(-2,5)"
    col.update_note(note)
    assert check_resume(col, saved, table).changed == (src.cid,)
    rebuilt = rebuild_card(col, src, table)
    assert rebuilt is not None and rebuilt.source.math_target == "(-2,5)"


# -- a full session --------------------------------------------------------------------


def _session(col: Collection, st: Storage, scope: Scope, miss_math: bool = False):
    options = SelectOptions()
    table = MappingTable(col)
    sel = select_cards(col, scope, options, table)
    res = build_session(col, sel, None, table, {})
    sj = sessions.scope_json(deck_id=scope.deck_id)
    ctrl, store = sessions.start_session(
        st,
        key=sessions.scope_key(sj),
        deck_items=res.deck_items,
        sources=res.sources,
        config={
            "encodeReps": 2,
            "chunkDifficulty": 35,
            "stemTolerance": True,
            "ladderMode": "cumulative",
            "strictPunctuation": False,
            "batchSize": 0,
        },
        scope=sj,
        select_options=options_to_json(options),
        deck_settings={},
        hints=False,
        settings=ControllerSettings(),
        now_ms=lambda: NOW,
    )
    ctrl.start()
    stages: dict[int, set[str]] = {}
    missed = not miss_math
    for _ in range(3000):
        if ctrl.finished:
            break
        if ctrl.view().buttons.continue_:
            ctrl.continue_()
            continue
        trial = select_trial(ctrl.state)
        assert trial is not None
        src = res.sources[trial["itemId"]]
        stages.setdefault(trial["itemId"], set()).add(trial["stage"])
        typed = src.math_target or trial["target"]
        if src.math_target and not missed:
            typed, missed = "x^2", True  # wrong for every math card here
        ctrl.submit(typed)
        if ctrl.processing:
            ctrl.dwell_elapsed()
    assert ctrl.finished == "complete"
    return ctrl, store, res, stages


def test_a_lab_2_session_drills_math_cards_through_every_stage(
    col: Collection, tmp_path: Path
) -> None:
    st, bones, ids = _scene(col, tmp_path)
    ctrl, store, res, stages = _session(col, st, Scope(deck_id=bones), miss_math=True)
    math_items = [i for i, s in enumerate(res.sources) if s.math_target]
    assert len(math_items) == 5
    for i in math_items:
        assert stages[i] == {"full", "cycle", "final"}, i  # never chunked, even the long ones
        item = ctrl.state["items"][i]
        assert item["status"] == "mastered" and item.get("finalDone") and item["chunks"] is None
    assert sum(ctrl.state["items"][i].get("misses", 0) for i in math_items) == 1
    # Other cards got their ordinary stages.
    others = [i for i in range(len(res.sources)) if i not in math_items]
    assert others and all(ctrl.state["items"][i]["status"] == "mastered" for i in others)

    # The session line in the history has every card, math ones included.
    lines = history_store.read_all(st, str(bones))
    session_lines = [ln for ln in lines if ln["type"] == "session"]
    assert len(session_lines) == 1
    line = session_lines[0]
    assert len(line["cards"]) == len(res.sources) == len(line["anki"])
    assert {a["cid"] for a in line["anki"]} == {s.cid for s in res.sources}

    # The handoff writes its rows as for other cards.
    saved = sessions.load(st, store.meta.key)
    assert saved is not None
    plan = plan_handoff(col, saved, HandoffSettings(mode="B"))
    apply_handoff(col, plan)
    handed = set(col.find_cards("tag:rd::drilled"))
    assert {s.cid for s in res.sources if s.math_target} <= handed
    sessions.complete_handoff(st, store.meta.key, saved, handoff_line(plan, None, NOW + 1))
    lines = history_store.read_all(st, str(bones))
    assert any(ln["type"] == "handoff" for ln in lines)

    # And the outcomes export has a row per drilled card.
    result = export_outcomes(col, st, now_ms=NOW + 5)
    csv_text = Path(result.path).read_text(encoding="utf-8")
    for s in res.sources:
        assert str(s.cid) in csv_text


@pytest.mark.parametrize("miss", [False, True])
def test_non_math_cards_are_the_same_with_and_without_math_cards(
    col: Collection, tmp_path: Path, miss: bool
) -> None:
    """The ordinary cards of the Lab 2 deck end a session with the same counters whether or
    not the math notes are in the deck."""
    st = Storage(tmp_path / "a", "User 1")
    scene = build_lab(col, st)
    plain_ctrl, _, plain_res, _ = _session(col, st, Scope(deck_id=scene.chapters["Bones"]))
    by_cid = {s.cid: plain_ctrl.state["items"][i] for i, s in enumerate(plain_res.sources)}
    _math_notes(col, scene.chapters["Bones"])
    st2 = Storage(tmp_path / "b", "User 1")
    ctrl, _, res, _ = _session(col, st2, Scope(deck_id=scene.chapters["Bones"]), miss_math=miss)
    keys = ("status", "attempts", "misses", "reveals", "nearMisses", "finalDone", "stage")
    for i, s in enumerate(res.sources):
        if s.math_target or s.cid not in by_cid:
            continue
        got, want = ctrl.state["items"][i], by_cid[s.cid]
        assert {k: got.get(k) for k in keys} == {k: want.get(k) for k in keys}, s.cid
