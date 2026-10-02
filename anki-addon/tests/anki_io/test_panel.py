"""anki_io/panel.py and build.rebuild_card: the setup panel's data, headless.

Replaces the Phase 2 dev preview tests: the same decks, read the way the panel
reads them.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from anki.collection import Collection
from anki_fixtures import (
    AMC,
    AMC_SAMPLE,
    AMC_TAGS,
    IOL_LABELS,
    add_amc_models,
    add_bqe_model,
    add_bqe_note,
    add_io_note,
    add_iol_model,
    add_iol_note,
    add_note,
    deck,
)

from recalldrill import deck_settings, sessions
from recalldrill.addon_config import DEFAULT_CONFIG
from recalldrill.anki_io.build import rebuild_card
from recalldrill.anki_io.cards import DEFAULT_ENABLED
from recalldrill.anki_io.notetypes import MappingOverride, MappingTable, save_override
from recalldrill.anki_io.panel import (
    PanelData,
    hard_exclusions,
    initial_settings,
    options_for,
    read_panel,
    read_saved,
    save_hint,
    settings_deck,
)
from recalldrill.anki_io.select import Scope
from recalldrill.deck_settings import DeckSettings
from recalldrill.launch import start
from recalldrill.storage import DECK_SETTINGS, HINTS, Storage


def _read(
    col: Collection,
    st: Storage,
    scope: Scope,
    draft: DeckSettings | None = None,
    max_cards: int | None = None,
) -> PanelData:
    d: DeckSettings = draft if draft is not None else {}
    options = options_for(
        d, enabled=DEFAULT_ENABLED, max_cards=max_cards, extra_tag=None, order="priority_first"
    )
    did = settings_deck(col, st, scope)
    return read_panel(col, st, scope, options, d, did, DEFAULT_CONFIG)


def _med_term(col: Collection) -> int:
    add_bqe_model(col)
    deck(col, "Medical Terminology")
    ch1 = deck(col, "Medical Terminology::Ch 1")
    for term, meaning in [
        ("-algia", "pain"),
        ("-dynia", "pain"),
        ("nat", "birth"),
        ("natal", "birth"),
    ]:
        add_bqe_note(col, ch1, term, meaning, notes="n")
    col.sched.suspend_cards(col.find_cards('deck:"Medical Terminology"'))
    return int(deck(col, "Medical Terminology"))


def test_med_term_deck(col: Collection, tmp_path: Path) -> None:
    top = _med_term(col)
    st = Storage(tmp_path, "User 1")
    p = _read(col, st, Scope(deck_id=top))
    assert p.label == "Medical Terminology" and p.key == f"deck-{top}"
    assert p.drillable == 8 and p.selection.eligible_counts["suspended_new"] == 8
    assert p.selection.sibling_cards == 8 and p.selection.sibling_notes == 4
    # Nothing saved: the proposal is offered, not applied, and nothing is written.
    assert p.saved_settings is None
    assert p.proposal == {"stemTolerance": False, "strictPunctuation": True, "hints": True}
    assert not p.build.hints_on
    assert not st.path(DECK_SETTINGS).exists() and not st.path(HINTS).exists()
    (nt,) = p.note_types
    assert [name for _, name in nt.templates] == ["Normal", "Reverse"]
    assert "FrontText" in nt.fields
    assert p.estimate is not None and p.estimate_text().startswith("about ")
    assert not p.personal_history

    # The proposal applied in the draft: hints on, flagged prompts listed.
    p = _read(col, st, Scope(deck_id=top), dict(p.proposal))  # type: ignore[arg-type]
    assert p.build.hints_on
    flagged = [h for h in p.hint_rows if h.flagged]
    assert {h.prompt for h in flagged} == {"birth"}

    # Reverse only (the template filter), max 6: siblings go to 0.
    draft: DeckSettings = {"card_ords": {str(nt.ntid): [1]}}
    p = _read(col, st, Scope(deck_id=top), draft, max_cards=6)
    assert [s.ord for s in p.build.sources] == [1, 1, 1, 1]
    assert p.selection.sibling_cards == 0 and p.selection.template_excluded == 4
    assert p.select_options["card_ords"] == {str(nt.ntid): [1]}


def test_hint_rows_and_save_hint(col: Collection, tmp_path: Path) -> None:
    top = _med_term(col)
    st = Storage(tmp_path, "p")
    terminology: DeckSettings = {"strictPunctuation": True, "hints": True}
    p = _read(col, st, Scope(deck_id=top), terminology)
    row = next(h for h in p.hint_rows if h.term == "nat")
    save_hint(st, row.key, "no -al")
    p = _read(col, st, Scope(deck_id=top), terminology)
    mine = next(h for h in p.hint_rows if h.key == row.key)
    assert not mine.flagged and mine.hint == "no -al" and mine.prompt == "birth"
    front = next(
        i["front"]
        for i, s in zip(p.build.deck_items, p.build.sources, strict=True)
        if f"{s.nid}:{s.ord}" == row.key
    )
    assert front == "birth (no -al)"
    save_hint(st, row.key, None)
    assert st.read_json(HINTS, None) == {}


def test_settings_deck_and_initial_settings(col: Collection, tmp_path: Path) -> None:
    top = _med_term(col)
    st = Storage(tmp_path, "p")
    ch1 = int(deck(col, "Medical Terminology::Ch 1"))
    assert settings_deck(col, st, Scope(search="tag:no-such-tag")) is None
    assert settings_deck(col, st, Scope(search='"note:Basic Quizlet Extended"')) == ch1
    assert initial_settings(st, top) == {} and initial_settings(st, None) == {}
    deck_settings.save(st, top, {"batchSize": 3})
    assert initial_settings(st, top) == {"batchSize": 3}
    assert _read(col, st, Scope(deck_id=top)).proposal is None  # something saved


def test_cloze_deck_with_io(col: Collection, tmp_path: Path) -> None:
    add_amc_models(col)
    did = deck(col, "Human A&P::Lecture 2")
    add_note(col, AMC, did, AMC_SAMPLE, AMC_TAGS)
    add_io_note(col, did)
    p = _read(col, Storage(tmp_path, "p"), Scope(deck_id=did))
    assert p.build.deck_items == [
        {
            "front": "Bone tissue is formally called [...].",
            "back": "osseous tissue",
            "extra": "From oss- (bone).",
        }
    ]
    assert p.selection.ineligible["image_occlusion"] == 1 and p.ineligible_total == 1
    kinds = {nt.name: nt.kind for nt in p.note_types}
    assert kinds[AMC] == "cloze" and "image_occlusion" in kinds.values()


def test_search_scope(col: Collection, tmp_path: Path) -> None:
    add_amc_models(col)
    did = deck(col, "Human A&P::Lecture 2")
    add_note(col, AMC, did, AMC_SAMPLE, AMC_TAGS)
    st = Storage(tmp_path, "p")
    search = '"deck:Human A&P::Lecture 2" tag:rd::drill::A1'
    p = _read(col, st, Scope(search=search))
    assert p.label == search and p.key.startswith("search-") and p.settings_did == did
    assert p.drillable == len(col.find_cards(search))


def test_hard_cards_scope_leaves_out_cards_that_werent_hard(
    col: Collection, tmp_path: Path
) -> None:
    from recalldrill import history_store
    from recalldrill.anki_io.handoff import HARD_SEARCH

    top = _med_term(col)
    st = Storage(tmp_path, "p")
    nids = col.find_notes('deck:"Medical Terminology"')[:2]
    col.tags.bulk_add(nids, "rd::hard")
    cards = [sorted(col.get_note(n).cards(), key=lambda c: c.ord) for n in nids]
    # The last handoff: note 0's Reverse card was hard, its Normal card wasn't;
    # note 1 was tagged by hand (no handoff data): all its cards stay in.
    history_store.append_handoff(
        st,
        str(top),
        {
            "type": "handoff",
            "sessionId": "s",
            "timestamp": "2026-10-02T10:00:00.000Z",
            "cards": [
                {"cid": cards[0][1].id, "hard": True},
                {"cid": cards[0][0].id, "hard": False},
            ],
        },
    )
    assert hard_exclusions(st, Scope(deck_id=top)) == frozenset()
    scope = Scope(search=HARD_SEARCH)
    exclude = hard_exclusions(st, scope)
    assert exclude == frozenset({cards[0][0].id})
    options = options_for(
        {},
        enabled=DEFAULT_ENABLED,
        max_cards=None,
        extra_tag=None,
        order="priority_first",
        exclude_cids=exclude,
    )
    p = read_panel(col, st, scope, options, {}, settings_deck(col, st, scope), DEFAULT_CONFIG)
    assert p.selection.excluded == 1
    assert sorted(s.cid for s in p.build.sources) == sorted(
        [cards[0][1].id, cards[1][0].id, cards[1][1].id]
    )
    assert p.select_options["exclude_cids"] == [cards[0][0].id]


def test_nothing_eligible(col: Collection, tmp_path: Path) -> None:
    add_iol_model(col)
    did = deck(col, "Lab")
    note = add_iol_note(col, did, IOL_LABELS["Nucleus"])
    st = Storage(tmp_path, "p")
    save_override(st, note.mid, 0, MappingOverride(None, None, True))
    p = _read(col, st, Scope(deck_id=did))
    assert p.drillable == 0 and p.estimate is None
    assert p.selection.ineligible["marked_ineligible"] == 1 and p.ineligible_total == 1


def test_image_cards(col: Collection, tmp_path: Path) -> None:
    add_iol_model(col)
    did = deck(col, "Lab 3")
    for label in IOL_LABELS.values():
        add_iol_note(col, did, label, extra="see text")
    p = _read(col, Storage(tmp_path, "p"), Scope(deck_id=did))
    assert p.drillable == 3 and all(s.image_front for s in p.build.sources)
    assert all(".occ-mask" in s.css for s in p.build.sources)
    assert {i["back"] for i in p.build.deck_items} == set(IOL_LABELS)
    assert not p.hint_rows


def test_read_saved_and_resume_check(col: Collection, tmp_path: Path) -> None:
    top = _med_term(col)
    st = Storage(tmp_path, "p")
    assert read_saved(col, st, f"deck-{top}") is None
    p = _read(col, st, Scope(deck_id=top), max_cards=4)
    ctrl, store = start(
        st,
        scope=sessions.scope_json(deck_id=top),
        deck_name=p.label,
        deck_items=p.build.deck_items,
        sources=p.build.sources,
        settings_did=top,
        settings={},
        select_options=p.select_options,
        hints=False,
        cfg=DEFAULT_CONFIG,
    )
    ctrl.start()
    info = read_saved(col, st, store.meta.key)
    assert info is not None and info.status == "resume" and info.total == 4
    assert info.check is not None and info.check.ok

    # Change one answer and delete a card of another note (both its cards go).
    first = p.build.sources[0]
    second = next(s for s in p.build.sources if s.nid != first.nid)
    note = col.get_note(first.nid)  # type: ignore[arg-type]
    note["BackText" if first.ord == 0 else "FrontText"] = "changed"
    col.update_note(note)
    col.remove_notes([second.nid])  # type: ignore[list-item]
    info = read_saved(col, st, store.meta.key)
    assert info is not None and info.check is not None and not info.check.ok
    assert len(info.changed) == 1 and len(info.missing) == 2
    assert "→" in info.changed[0]

    store.meta.handoff_pending = True
    store.persist(ctrl.saved_dict())
    info = read_saved(col, st, store.meta.key)
    assert info is not None and info.status == "handoff" and info.check is None


def test_rebuild_card_after_an_edit(col: Collection, tmp_path: Path) -> None:
    top = _med_term(col)
    st = Storage(tmp_path, "p")
    p = _read(col, st, Scope(deck_id=top), {"strictPunctuation": True, "hints": True})
    i, src = next((i, s) for i, s in enumerate(p.build.sources) if s.hint and s.ord == 1)
    table = MappingTable(col)
    same = rebuild_card(col, src, table)
    assert same is not None and same.front == p.build.deck_items[i]["front"]
    assert same.back == p.build.deck_items[i]["back"] and same.source == src

    note = col.get_note(src.nid)  # type: ignore[arg-type]
    note["BackText"] = note["BackText"] + " (more)"  # Reverse: the front
    col.update_note(note)
    edited = rebuild_card(col, src, MappingTable(col))
    assert edited is not None and "(more)" in edited.front and edited.front.endswith(src.hint)
    assert edited.back == same.back and edited.source.answer_hash == src.answer_hash
    assert "(more)" in edited.source.front_html

    note["FrontText"] = ""  # Reverse: the answer
    col.update_note(note)
    assert rebuild_card(col, src, MappingTable(col)) is None
    col.remove_notes([src.nid])  # type: ignore[list-item]
    assert rebuild_card(col, src, MappingTable(col)) is None


@pytest.mark.parametrize("hint", ["", "x"])
def test_save_hint_suppress_or_set(tmp_path: Path, hint: str) -> None:
    st = Storage(tmp_path, "p")
    save_hint(st, "1:0", hint)
    assert st.read_json(HINTS, None) == {"1:0": hint}
