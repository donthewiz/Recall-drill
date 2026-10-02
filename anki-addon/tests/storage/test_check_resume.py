"""anki_io/resume.py: check_resume on a scratch collection (needs anki)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

# anki.collection must load before anki.cards (circular import). A plain
# `import` always sorts above the `from` imports, so isort keeps this order.
import anki.collection  # noqa: F401
import pytest
from anki.cards import CardId
from anki.collection import Collection
from anki_fixtures import add_note, deck
from controller_support import Clock, config

from recalldrill import sessions
from recalldrill.anki_io.build import build_session
from recalldrill.anki_io.notetypes import MappingTable
from recalldrill.anki_io.resume import check_resume
from recalldrill.anki_io.select import (
    Scope,
    SelectOptions,
    options_from_json,
    options_to_json,
    scope_from_json,
    scope_to_json,
    select_cards,
)
from recalldrill.controller import ControllerSettings
from recalldrill.storage import Storage


@pytest.fixture
def col(tmp_path: Path) -> Iterator[Collection]:
    """A scratch collection. Never a real profile."""
    c = Collection(str(tmp_path / "collection.anki2"))
    try:
        yield c
    finally:
        c.close()


def _saved(col: Collection, tmp_path: Path) -> tuple[dict[str, Any], list[int]]:
    did = deck(col, "Med Term")
    for front, back in [("heart", "cardi"), ("liver", "hepat"), ("kidney", "nephr")]:
        add_note(col, "Basic", did, {"Front": front, "Back": back})
    table = MappingTable(col)
    scope = Scope(deck_id=did)
    options = SelectOptions()
    sel = select_cards(col, scope, options, table)
    res = build_session(col, sel, None, table, {})
    st = Storage(tmp_path / "user_files", "User 1")
    ctrl, _ = sessions.start_session(
        st,
        key=sessions.deck_key(did),
        deck_items=res.deck_items,
        sources=res.sources,
        config=config(),
        scope=sessions.scope_json(deck_id=did),
        select_options=options_to_json(options),
        deck_settings={},
        hints=res.hints_on,
        settings=ControllerSettings(),
        now_ms=Clock(),
    )
    ctrl.start()
    saved = sessions.load(st, sessions.deck_key(did))
    assert saved is not None
    return saved, [s.cid for s in res.sources]


def test_unchanged_collection_resumes_cleanly(col: Collection, tmp_path: Path) -> None:
    saved, _ = _saved(col, tmp_path)
    check = check_resume(col, saved)
    assert check.ok and check.missing == () and check.changed == ()


def test_a_deleted_card_is_missing(col: Collection, tmp_path: Path) -> None:
    saved, cids = _saved(col, tmp_path)
    col.remove_notes([col.get_card(CardId(cids[1])).nid])
    check = check_resume(col, saved)
    assert check.missing == (cids[1],) and check.changed == () and not check.ok


def test_an_edited_answer_is_changed(col: Collection, tmp_path: Path) -> None:
    saved, cids = _saved(col, tmp_path)
    note = col.get_card(CardId(cids[2])).note()
    note["Back"] = "nephr/o"
    col.update_note(note)
    # A front-only edit doesn't change the answer.
    other = col.get_card(CardId(cids[0])).note()
    other["Front"] = "the heart"
    col.update_note(other)
    check = check_resume(col, saved)
    assert check.changed == (cids[2],) and check.missing == ()


def test_a_card_id_that_never_existed_is_missing(col: Collection, tmp_path: Path) -> None:
    saved, _ = _saved(col, tmp_path)
    saved["addon"]["sources"][0]["cid"] = 999_999  # no such card
    check = check_resume(col, saved, MappingTable(col))
    assert check.missing == (999_999,)


def test_scope_and_options_round_trip_through_json() -> None:
    options = SelectOptions(
        enabled=frozenset({"new", "flagged"}),
        card_ords={12: frozenset({1, 0})},
        max_cards=20,
        extra_tag="rd::drill::A",
        order="deck_order",
        young_ivl=14,
        flag=2,
    )
    assert options_from_json(options_to_json(options)) == options
    assert options_to_json(options)["card_ords"] == {"12": [0, 1]}
    assert options_from_json({}) == SelectOptions()
    assert options_from_json({"enabled": ["new", "nonsense"]}).enabled == frozenset({"new"})
    for scope in (Scope(deck_id=5), Scope(search="tag:x")):
        assert scope_from_json(scope_to_json(scope)) == scope
