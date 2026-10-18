"""The review window offscreen: it opens when the reviewer shows a Math Path card, solves one fresh
problem, and rates *that* card through the reviewer's answer path."""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import anki.collection  # noqa: F401  # must load before anki.cards (circular import)
import pytest
from anki.cards import CardId
from anki.collection import Collection
from anki.decks import DeckId
from anki.notes import NoteId
from anki.scheduler.v3 import CardAnswer
from scenes import make_course, recipe_dir

from math_path.anki_io import importer, notetype

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("aqt") is None, reason="aqt (Anki's GUI package) isn't installed"
)

EASE = {1: CardAnswer.AGAIN, 2: CardAnswer.HARD, 3: CardAnswer.GOOD, 4: CardAnswer.EASY}


class StubReviewer:
    """What ``mw.reviewer`` offers: a card, a state, ``_showAnswer`` and ``_answerCard``. The
    answer is a real one on the scratch collection (build_answer + answer_card, as 26.08.1)."""

    def __init__(self, col: Collection, card: Any) -> None:
        self.col = col
        self.card = card
        self.state = "question"
        self.calls: list[Any] = []

    def _showAnswer(self) -> None:  # noqa: N802
        self.calls.append("show")
        self.state = "answer"

    def _answerCard(self, ease: int) -> None:  # noqa: N802
        assert self.state == "answer"
        self.calls.append(("answer", ease))
        sched: Any = self.col.sched
        queued = sched.get_queued_cards(fetch_limit=100)
        states = next(q.states for q in queued.cards if q.card.id == self.card.id)
        self.card.start_timer()
        answer = sched.build_answer(card=self.card, states=states, rating=EASE[ease])
        sched.answer_card(answer)
        self.state = "transition"


@pytest.fixture
def env(qt_app: object, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Any]:
    import aqt
    from drive import sequential_problems
    from stubs import FakeWeb, StubMw

    from math_path.ui import context, entry, page_window, review_bridge, review_window

    col = Collection(str(tmp_path / "collection.anki2"))
    stub = StubMw(col)
    monkeypatch.setattr(aqt, "mw", stub)
    for mod in (context, page_window, review_bridge, review_window, entry):
        monkeypatch.setattr(mod, "mw", stub, raising=False)
    monkeypatch.setattr(page_window, "AnkiWebView", FakeWeb)
    tips: list[str] = []
    monkeypatch.setattr(review_window, "tooltip", tips.append)
    monkeypatch.setattr(entry, "tooltip", tips.append)
    stub.tips = tips  # type: ignore[attr-defined]
    course = make_course(col, sections=("3.1", "3.2"))
    col.decks.set_current(DeckId(course.top))  # the reviewer queue is the current deck
    files = importer.scan_folder(recipe_dir(tmp_path, limit=8), smoke=False)
    summary = importer.apply_import(col, importer.plan_import(col, files))
    stub.nids = list(summary.nids)  # type: ignore[attr-defined]
    for nid in summary.nids:  # a due card is not suspended
        col.sched.unsuspend_cards([c.id for c in col.get_note(NoteId(nid)).cards()])
    ctx = context.AddonContext("math_path", str(tmp_path / "user_files"))

    class Bank:
        def __init__(self) -> None:
            self.get = sequential_problems()

        def prepare(self, recipe: Any) -> None:
            return None

        def take(self, recipe: Any) -> Any:
            return self.get(recipe)

    ctx.bank = Bank()  # type: ignore[assignment]
    monkeypatch.setattr(entry, "_ctx", ctx)
    stub.state = "review"
    stub.ctx = ctx  # type: ignore[attr-defined]
    yield stub
    col.close()


def _card(env: Any, i: int = 0) -> Any:
    return env.col.get_note(NoteId(env.nids[i])).cards()[0]


def _show(env: Any, i: int = 0) -> Any:
    """The reviewer shows card ``i``'s question (and the hook fires)."""
    from math_path.ui import entry

    card = _card(env, i)
    env.reviewer = StubReviewer(env.col, card)
    entry.on_show_question(card)
    from math_path.ui.review_window import ReviewWindow

    return next((w for w in env.ctx.windows if isinstance(w, ReviewWindow)), None)


def _solve(w: Any, right_first: bool = True) -> None:
    from drive import type_answer

    run = w.session.run
    if not right_first:
        type_answer(run, right=False)
        w.web.bridge("mp:act:check")
    type_answer(run)
    w.web.bridge("mp:act:check")
    assert w.session.screen == "done"


def _revlog(env: Any) -> list[tuple[int, int]]:
    assert env.col.db is not None
    return [(int(c), int(e)) for c, e in env.col.db.all("select cid, ease from revlog order by id")]


def test_the_window_opens_when_the_reviewer_shows_a_math_path_card(env: Any) -> None:
    w = _show(env)
    assert w is not None and w.card_id == _card(env).id
    assert w.windowTitle() == "Math Path: review"
    html = w.web.last_render()["html"]
    assert "Review" in html and "Solve" in html or "mp-problem" in html
    assert w.session.run is not None and w.session.run.mode == "solo"


def test_a_clean_solve_rates_good_and_the_reviewer_moves_on(env: Any) -> None:
    w = _show(env)
    w.show()
    _solve(w)
    assert w.session.suggested == 3
    w.web.bridge("mp:act:next")
    assert env.reviewer.calls == ["show", ("answer", 3)]
    assert _revlog(env) == [(int(_card(env).id), 3)]
    assert not w.isVisible() and w not in env.ctx.windows
    lines = env.ctx.storage().read_jsonl("history.jsonl")
    assert lines[-1]["mode"] == "review" and lines[-1]["rating"] == 3 and lines[-1]["rated"] is True


def test_a_wrong_try_rates_again_and_the_chips_change_it(env: Any) -> None:
    w = _show(env)
    _solve(w, right_first=False)
    assert w.session.suggested == 1 and w.session.rating == 1
    w.web.bridge("mp:act:rate:4")
    assert "Next (Easy)" in w.web.last_render()["html"]
    w.web.bridge("mp:act:next")
    assert _revlog(env) == [(int(_card(env).id), 4)]
    lines = env.ctx.storage().read_jsonl("history.jsonl")
    assert lines[-1]["suggested"] == 1 and lines[-1]["rating"] == 4


def test_a_shown_answer_rates_again(env: Any) -> None:
    w = _show(env)
    w.web.bridge("mp:act:help:answer")
    assert w.session.screen == "done" and w.session.suggested == 1
    w.web.bridge("mp:enter:")  # Enter on the done screen is Next
    assert _revlog(env) == [(int(_card(env).id), 1)]


def test_only_that_card_is_rated(env: Any) -> None:
    w = _show(env, 0)
    _solve(w)
    other = _card(env, 1)
    w.web.bridge("mp:act:next")
    rated = {c for c, _e in _revlog(env)}
    assert rated == {int(_card(env, 0).id)} and int(other.id) not in rated


def test_if_the_reviewer_moved_on_nothing_is_rated_and_the_window_says_so(env: Any) -> None:
    from math_path.ui.review_bridge import NOT_ON_CARD

    w = _show(env, 0)
    w.show()
    _solve(w)
    env.reviewer.card = _card(env, 1)  # the reviewer is on another card now
    w.web.bridge("mp:act:next")
    assert env.reviewer.calls == [] and _revlog(env) == []
    assert w.isVisible()  # the window stays so the learner can see why
    assert "no longer on this card" in w.web.last_render()["html"]
    assert NOT_ON_CARD in env.tips
    lines = env.ctx.storage().read_jsonl("history.jsonl")
    assert lines[-1]["rating"] is None and lines[-1]["rated"] is False
    env.state = "deckBrowser"  # and the reviewer is gone altogether
    w.web.bridge("mp:act:next")
    assert env.reviewer.calls == []


def test_closing_without_finishing_rates_nothing(env: Any) -> None:
    w = _show(env)
    w.show()
    w.web.bridge("mp:field:ans:x")
    w.close()
    assert not w.isVisible()
    assert env.reviewer.calls == [] and _revlog(env) == []
    assert env.ctx.storage().read_jsonl("history.jsonl") == []


def test_closing_a_finished_problem_without_next_rates_nothing_but_is_logged(env: Any) -> None:
    w = _show(env)
    w.show()
    _solve(w)
    w.close()
    assert env.reviewer.calls == [] and _revlog(env) == []
    (line,) = env.ctx.storage().read_jsonl("history.jsonl")
    assert line["rating"] is None and line["rated"] is False and line["suggested"] == 3


def test_the_same_card_brings_its_window_forward_and_another_card_replaces_it(env: Any) -> None:
    from math_path.ui import entry
    from math_path.ui.review_window import ReviewWindow

    w = _show(env, 0)
    assert w is not None
    entry.on_show_question(_card(env, 0))
    assert [x for x in env.ctx.windows if isinstance(x, ReviewWindow)] == [w]
    w2 = _show(env, 1)
    assert w2 is not None and w2 is not w and w2.card_id == _card(env, 1).id
    assert [x for x in env.ctx.windows if isinstance(x, ReviewWindow)] == [w2]


def test_a_card_that_is_not_math_path_closes_a_stale_window_and_opens_nothing(env: Any) -> None:
    from math_path.ui import entry
    from math_path.ui.review_window import ReviewWindow

    w = _show(env, 0)
    assert w is not None
    basic = env.col.new_note(env.col.models.by_name("Basic"))
    basic["Front"], basic["Back"] = "q", "a"
    env.col.add_note(basic, env.col.decks.id("Default"))
    entry.on_show_question(basic.cards()[0])
    assert not [x for x in env.ctx.windows if isinstance(x, ReviewWindow)]


def test_auto_open_can_be_switched_off(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from math_path.config import Config

    monkeypatch.setattr(env.ctx, "config", lambda: Config(auto_open_in_review=False))
    assert _show(env) is None


def test_the_card_faces_link_opens_the_window_even_with_auto_open_off(
    env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from math_path.config import Config
    from math_path.ui import entry

    monkeypatch.setattr(env.ctx, "config", lambda: Config(auto_open_in_review=False))
    card = _card(env)
    env.reviewer = StubReviewer(env.col, card)
    assert entry.on_js_message((False, None), "ease3", env.reviewer) == (False, None)  # not ours
    assert entry.on_js_message((False, None), notetype.PYCMD_OPEN, env.reviewer) == (True, None)
    from math_path.ui.review_window import ReviewWindow

    assert [x for x in env.ctx.windows if isinstance(x, ReviewWindow)]


def test_a_note_whose_recipe_cannot_be_read_says_so(env: Any) -> None:
    from math_path.ui import entry
    from math_path.ui.review_window import ReviewWindow

    note = env.col.get_note(NoteId(env.nids[2]))
    note["Recipe"] = "not json at all"
    env.col.update_note(note)
    entry.on_show_question(note.cards()[0])
    assert not [x for x in env.ctx.windows if isinstance(x, ReviewWindow)]
    assert any("can't be read" in t for t in env.tips)


def test_the_bridge_goes_through_the_answer_state_first(env: Any) -> None:
    from math_path.ui import review_bridge

    card = _card(env)
    env.reviewer = StubReviewer(env.col, card)
    assert review_bridge.reviewer_card_id() == card.id
    assert review_bridge.rate_current(int(card.id), 2) == (True, "")
    assert env.reviewer.calls == ["show", ("answer", 2)]
    env.reviewer = StubReviewer(env.col, card)
    env.reviewer.state = "answer"  # already showing the answer: no second _showAnswer
    assert review_bridge.rate_current(int(card.id), 3)[0]
    assert env.reviewer.calls == [("answer", 3)]
    assert review_bridge.rate_current(12345, 3) == (False, review_bridge.NOT_ON_CARD)
    env.reviewer = None
    assert review_bridge.reviewer_card_id() is None
    assert CardId(0) == 0
