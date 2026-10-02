"""anki_io/build.py: selection -> (deck_items, sources), cloze answers, hints."""

from __future__ import annotations

import hashlib

import pytest
from anki.collection import Collection
from anki.decks import DeckId
from anki.notes import Note
from anki_fixtures import (
    AMC,
    AMC_SAMPLE,
    AMC_TAGS,
    AMC_TYPEIN,
    BQE,
    IOL_CSS,
    IOL_LABELS,
    IOL_QUESTION,
    add_amc_models,
    add_bqe_model,
    add_bqe_note,
    add_io_note,
    add_iol_model,
    add_iol_note,
    add_note,
    cards_by_ord,
    deck,
    model,
)

from recalldrill.anki_io.build import BuildResult, build_session, build_session_items, hint_key
from recalldrill.anki_io.notetypes import MappingTable
from recalldrill.anki_io.select import Scope, Selection, SelectOptions, select_cards
from recalldrill.anki_io.text import grading_text
from recalldrill.deck_settings import DeckSettings
from recalldrill.engine.items import build_items
from recalldrill.engine.types import DeckItem

STRICT: DeckSettings = {"strictPunctuation": True}


def run(
    col: Collection,
    did: DeckId,
    settings: DeckSettings | None = None,
    hints: dict[str, str] | None = None,
    **options: object,
) -> tuple[Selection, BuildResult]:
    table = MappingTable(col)
    sel = select_cards(col, Scope(deck_id=did), SelectOptions(**options), table)  # type: ignore[arg-type]
    return sel, build_session(col, sel, settings, table, hints or {})


def by_back(result: BuildResult) -> dict[str, DeckItem]:
    return {i["back"]: i for i in result.deck_items}


# ---------------------------------------------------------------------------
# Basic Quizlet Extended
# ---------------------------------------------------------------------------


@pytest.fixture
def medterm(col: Collection) -> tuple[DeckId, DeckId, int]:
    """Two chapters of BQE notes, all suspended new, like Don's Med Term deck."""
    add_bqe_model(col)
    ch1, ch2 = deck(col, "Medical Terminology::Ch 1"), deck(col, "Medical Terminology::Ch 2")
    add_bqe_note(col, ch1, "ankyl/o", "crooked, bent, stiff", notes="<i>ankylosis</i>")
    add_bqe_note(col, ch1, "-algia", "pain")
    add_bqe_note(col, ch2, "-dynia", "pain")
    add_bqe_note(col, ch2, "ten/o", "tendon")
    add_bqe_note(col, ch2, "tendin/o", "tendon")
    add_bqe_note(col, ch2, "nat/i", "birth")
    add_bqe_note(col, ch2, "natal", "pertaining<br>to birth")
    add_bqe_note(col, ch2, "nat", "birth")
    col.sched.suspend_cards(col.find_cards('deck:"Medical Terminology"'))
    return ch1, ch2, int(model(col, BQE)["id"])


def test_bqe_items_read_meaning_to_term(
    col: Collection, medterm: tuple[DeckId, DeckId, int]
) -> None:
    ch1, _, ntid = medterm
    sel, res = run(col, ch1, card_ords={ntid: frozenset({1})})
    assert res.deck_items == [
        {"front": "crooked, bent, stiff", "back": "ankyl/o", "extra": "ankylosis"},
        {"front": "pain", "back": "-algia"},
    ]
    assert not res.hints_on
    src = res.sources[0]
    assert (src.cid, src.ord, src.did, src.ntid) == (sel.picked[0].snap.cid, 1, ch1, ntid)
    assert src.card_class == "suspended_new" and src.flags == 0
    assert src.front_html.startswith("crooked, bent, stiff\n<br><br>\n[anki:play:q:0]")
    assert src.extra_html == "<i>ankylosis</i>"
    assert src.answer_hash == hashlib.sha1(b"ankyl/o").hexdigest()
    assert src.has_audio  # FrontAudio on the Reverse back
    assert src.hint == ""
    assert src.answer_html.startswith("crooked, bent, stiff\n<hr id=answer>\nankyl/o")
    assert src.css == model(col, BQE)["css"] and ".card" in src.css
    assert not src.image_front


def test_no_media_text_and_no_glued_words(
    col: Collection, medterm: tuple[DeckId, DeckId, int]
) -> None:
    _, ch2, _ = medterm
    _, res = run(col, ch2)
    for item in res.deck_items:
        for value in (item["front"], item["back"], item.get("extra", "")):
            assert "[sound:" not in value and "[anki:" not in value and "<" not in value
    assert by_back(res)["natal"]["front"] == "pertaining to birth"
    assert by_back(res)["pertaining to birth"]["front"] == "natal"


def test_both_directions_by_default_in_selection_order(
    col: Collection, medterm: tuple[DeckId, DeckId, int]
) -> None:
    ch1, _, _ = medterm
    sel, res = run(col, ch1)
    assert [s.cid for s in res.sources] == [c.snap.cid for c in sel.picked]
    assert [(i["front"], i["back"]) for i in res.deck_items] == [
        ("ankyl/o", "crooked, bent, stiff"),
        ("crooked, bent, stiff", "ankyl/o"),
        ("-algia", "pain"),
        ("pain", "-algia"),
    ]
    assert sel.sibling_cards == 4
    # build_session_items is the same pair.
    items, sources = build_session_items(col, sel, None, MappingTable(col), {})
    assert (items, sources) == (res.deck_items, res.sources)
    # The engine takes them as they are; item id = index.
    drill = build_items(items, shuffle_within_batch=False)
    assert [(d["id"], d["front"], d["back"]) for d in drill] == [
        (i, it["front"], it["back"]) for i, it in enumerate(items)
    ]
    assert "extra" not in drill[2]


# ---------------------------------------------------------------------------
# Hints
# ---------------------------------------------------------------------------


def test_hints_across_chapters(col: Collection, medterm: tuple[DeckId, DeckId, int]) -> None:
    _, ch2, ntid = medterm
    sel, res = run(col, ch2, STRICT, card_ords={ntid: frozenset({1})})
    assert res.hints_on
    fronts = {i["back"]: i["front"] for i in res.deck_items}
    assert fronts == {
        "-dynia": "pain (-d___)",  # -algia is in Ch 1
        "ten/o": "tendon (ten/___)",
        "tendin/o": "tendon (tend___)",
        "nat/i": "birth (nat/___)",
        "natal": "pertaining to birth (nata___)",
        "nat": "birth",
    }
    (flag,) = res.flagged_hints
    assert (flag.term, flag.meaning) == ("nat", "birth")
    assert set(flag.conflicts) == {"nat/i", "natal"}
    assert res.hint_pool == 8  # both chapters' Reverse cards
    assert {s.hint for s in res.sources if s.nid == sel.picked[0].snap.nid} == {" (-d___)"}


def test_hint_overrides_by_note_and_ord(
    col: Collection, medterm: tuple[DeckId, DeckId, int]
) -> None:
    _, ch2, ntid = medterm
    sel, _ = run(col, ch2, card_ords={ntid: frozenset({1})})
    keys = {
        col.get_note(c.snap.nid)["FrontText"]: hint_key(c.snap.nid, c.snap.ord)  # type: ignore[arg-type]
        for c in sel.picked
    }
    hints = {keys["nat"]: "3 letters", keys["natal"]: "", keys["nat/i"]: ""}
    _, res = run(col, ch2, STRICT, hints, card_ords={ntid: frozenset({1})})
    fronts = {i["back"]: i["front"] for i in res.deck_items}
    assert fronts["nat"] == "birth (3 letters)"
    assert fronts["natal"] == "pertaining to birth"
    assert fronts["nat/i"] == "birth"
    assert res.flagged_hints == []


def test_hints_off_unless_settings_say_so(
    col: Collection, medterm: tuple[DeckId, DeckId, int]
) -> None:
    _, ch2, _ = medterm
    cases: list[DeckSettings | None] = [
        None,
        {"strictPunctuation": False},
        {"hints": False, "strictPunctuation": True},
    ]
    for settings in cases:
        _, res = run(col, ch2, settings)
        assert not res.hints_on
        assert all("(" not in i["front"] for i in res.deck_items)


def _colliding(res: BuildResult) -> dict[str, set[str]]:
    return {
        i["back"]: set(s.colliding_answers)
        for i, s in zip(res.deck_items, res.sources, strict=True)
    }


CH2_COLLISIONS = {
    "-dynia": {"-algia"},  # Ch 1's card counts: same pool as the hints
    "ten/o": {"tendin/o"},
    "tendin/o": {"ten/o"},
    "nat/i": {"natal", "nat"},
    "natal": {"nat/i", "nat"},
    "nat": {"nat/i", "natal"},
}


def test_colliding_answers_with_hints_off(
    col: Collection, medterm: tuple[DeckId, DeckId, int]
) -> None:
    _, ch2, ntid = medterm
    _, res = run(col, ch2, None, card_ords={ntid: frozenset({1})})
    assert not res.hints_on
    assert all("(" not in i["front"] for i in res.deck_items)
    assert _colliding(res) == CH2_COLLISIONS
    assert res.hint_pool == 8


def test_colliding_answers_with_hints_on_match(
    col: Collection, medterm: tuple[DeckId, DeckId, int]
) -> None:
    _, ch2, ntid = medterm
    _, res = run(col, ch2, STRICT, card_ords={ntid: frozenset({1})})
    assert res.hints_on and _colliding(res) == CH2_COLLISIONS
    assert all(len(set(s.colliding_answers)) == len(s.colliding_answers) for s in res.sources)


def test_colliding_answers_can_be_skipped(
    col: Collection, medterm: tuple[DeckId, DeckId, int]
) -> None:
    _, ch2, ntid = medterm
    table = MappingTable(col)
    sel = select_cards(
        col, Scope(deck_id=ch2), SelectOptions(card_ords={ntid: frozenset({1})}), table
    )
    res = build_session(col, sel, None, table, {}, collisions=False)
    assert all(s.colliding_answers == () for s in res.sources)
    assert res.hint_pool == 0  # the pool isn't read at all


def test_image_fronts_have_no_colliding_answers(col: Collection) -> None:
    did = deck(col, "Med::Ch 1")
    add_note(col, "Basic", did, {"Front": 'pain <img src="x.png">', "Back": "-dynia"})
    add_note(col, "Basic", did, {"Front": "pain", "Back": "-algia"})
    _, res = run(col, did)
    assert [
        (i["back"], s.colliding_answers) for i, s in zip(res.deck_items, res.sources, strict=True)
    ] == [
        ("-dynia", ()),
        ("-algia", ()),
    ]


def test_n_forms_on_the_normal_direction(
    col: Collection, medterm: tuple[DeckId, DeckId, int]
) -> None:
    ch1, _, ntid = medterm
    _, res = run(col, ch1, STRICT, card_ords={ntid: frozenset({0})})
    assert by_back(res)["crooked, bent, stiff"]["front"] == "ankyl/o (3 forms)"


# ---------------------------------------------------------------------------
# anki-cards cloze decks
# ---------------------------------------------------------------------------


def test_anki_cards_fixture(col: Collection) -> None:
    add_amc_models(col)
    did = deck(col, "Human A&P::Lecture 2::Bones and Bone Tissue Chapter 6")
    add_note(col, AMC, did, AMC_SAMPLE, AMC_TAGS)
    add_note(col, AMC_TYPEIN, did, AMC_SAMPLE, AMC_TAGS)
    sel, res = run(col, did, {"hints": True, "strictPunctuation": True})
    assert [c.card_class for c in sel.picked] == ["new", "new"]
    expected = {
        "front": "Bone tissue is formally called [...].",
        "back": "osseous tissue",
        "extra": "From oss- (bone).",
    }
    assert res.deck_items == [expected, expected]  # TypeIn: no [[type:]] text
    for src in res.sources:
        assert src.extra_html == "From <i>oss-</i> (bone)."
        assert src.hint == ""
        assert not src.has_audio
    assert "[[type:cloze:Text]]" in res.sources[1].front_html
    # Reference fields never reach the drill.
    for item in res.deck_items:
        assert "connective" not in str(item) and "slide" not in str(item)


def test_no_hints_on_cloze_cards(col: Collection) -> None:
    add_amc_models(col)
    did = deck(col, "X")
    add_note(col, AMC, did, {"Text": "Pain: {{c1::-algia}}"})
    add_note(col, AMC, did, {"Text": "Pain: {{c1::-dynia}}"})
    _, res = run(col, did, {"hints": True})
    assert res.hints_on
    assert [i["front"] for i in res.deck_items] == ["Pain: [...]", "Pain: [...]"]
    assert res.flagged_hints == [] and res.hint_pool == 0


def _cloze(col: Collection, text: str) -> tuple[DeckId, Note]:
    did = deck(col, "Cloze")
    return did, add_note(col, "Cloze", did, {"Text": text})


@pytest.mark.parametrize(
    ("text", "items"),
    [
        (
            "Bone is {{c1::osseous tissue::bone}}.",
            [("Bone is [bone].", "osseous tissue")],
        ),
        (
            "The {{c1::heart}} and {{c1::lymph}} vessels",
            [("The [...] and [...] vessels", "heart, lymph")],
        ),
        (
            "{{c1::femur}} and {{c2::tibia}}",
            [("[...] and tibia", "femur"), ("femur and [...]", "tibia")],
        ),
        (
            "{{c1::outer {{c2::inner}} text}} end",
            [("[...] end", "outer inner text"), ("outer [...] text end", "inner")],
        ),
        (
            "<b>{{c1::os}}</b>seous&nbsp;tissue<br>{{c2::bone}}",
            [("[...]seous tissue bone", "os"), ("osseous tissue [...]", "bone")],
        ),
    ],
)
def test_cloze_fronts_and_answers(col: Collection, text: str, items: list[tuple[str, str]]) -> None:
    did, note = _cloze(col, text)
    sel, res = run(col, did)
    assert [(i["front"], i["back"]) for i in res.deck_items] == items
    assert [s.ord for s in res.sources] == [c.ord for c in cards_by_ord(note)]
    assert all(c.mapping.kind == "cloze" for c in sel.picked)


# ---------------------------------------------------------------------------
# Empty answers
# ---------------------------------------------------------------------------


def test_image_only_answer_is_ineligible(col: Collection) -> None:
    did = deck(col, "X")
    add_note(col, "Basic", did, {"Front": "q", "Back": "<img src=x.jpg>"})
    add_note(col, "Basic", did, {"Front": "q2", "Back": "a2"})
    sel, res = run(col, did)
    assert sel.ineligible["empty_answer"] == 1
    assert res.deck_items == [{"front": "q2", "back": "a2"}]


def test_answer_emptied_after_selection_is_dropped(col: Collection) -> None:
    did = deck(col, "X")
    first = add_note(col, "Basic", did, {"Front": "q1", "Back": "a1"})
    add_note(col, "Basic", did, {"Front": "q2", "Back": "a2"})
    table = MappingTable(col)
    sel = select_cards(col, Scope(deck_id=did), SelectOptions(), table)
    first["Back"] = "[sound:only.mp3]"
    col.update_note(first)
    res = build_session(col, sel, None, table, {})
    assert res.empty_answers == 1
    assert res.deck_items == [{"front": "q2", "back": "a2"}]
    assert [s.nid for s in res.sources] == [sel.picked[1].snap.nid]


# ---------------------------------------------------------------------------
# Image Occlusion lookalike (anki-cards), a standard note type
# ---------------------------------------------------------------------------


def test_io_lookalike_cards_drill_their_label(col: Collection) -> None:
    add_iol_model(col)
    did = deck(col, "Human A&P::Lab 3::Figure 4.3")
    for label in IOL_LABELS.values():
        add_iol_note(col, did, label, extra="Lines the <i>gut</i>.")
    add_io_note(col, did)  # stock IO (originalStockKind 6): still ineligible
    sel, res = run(col, did, {"strictPunctuation": True, "hints": True})
    header = "Figure 4.3 Cell and tissue structures"
    assert res.deck_items == [
        {"front": header, "back": label, "extra": "Lines the gut."} for label in IOL_LABELS
    ]
    assert [c.card_class for c in sel.picked] == ["new"] * 3
    assert sel.ineligible["image_occlusion"] == 1
    assert sum(sel.ineligible.values()) == 1
    # No hints and no conflict-pool entries: the image tells these cards apart.
    assert res.hints_on and res.hint_pool == 0 and res.flagged_hints == []
    for src, label in zip(res.sources, IOL_LABELS, strict=True):
        assert src.image_front and src.hint == ""
        assert "<img" in src.front_html
        assert label in grading_text(src.answer_html) and "<hr id=answer>" in src.answer_html
        assert src.css == IOL_CSS  # masks drawn by CSS class need it
        assert src.extra_html == "Lines the <i>gut</i>."
        assert src.answer_hash == hashlib.sha1(label.encode()).hexdigest()


def test_io_lookalike_with_no_label_is_an_empty_answer(col: Collection) -> None:
    add_iol_model(col)
    did = deck(col, "X")
    add_iol_note(col, did, "")  # the Answer only repeats the Question
    add_iol_note(col, did, IOL_LABELS["Nucleus"])
    sel, res = run(col, did)
    assert sel.ineligible["empty_answer"] == 1
    assert [i["back"] for i in res.deck_items] == ["Nucleus"]


def test_io_lookalike_without_header_text(col: Collection) -> None:
    add_iol_model(col)
    did = deck(col, "X")
    image_only = IOL_QUESTION.split("</div>", 1)[1]  # no occ-header
    add_iol_note(col, did, "<br><b>Goblet cells</b>", question=image_only)
    _, res = run(col, did)
    assert res.deck_items == [{"front": "", "back": "Goblet cells"}]
    assert res.sources[0].image_front


def test_image_fronts_stay_out_of_other_cards_conflict_pool(col: Collection) -> None:
    ch1, ch2 = deck(col, "Med::Ch 1"), deck(col, "Med::Ch 2")
    add_note(col, "Basic", ch1, {"Front": 'pain <img src="x.png">', "Back": "-dynia"})
    add_note(col, "Basic", ch2, {"Front": "pain", "Back": "-algia"})
    add_note(col, "Basic", ch2, {"Front": "tendon", "Back": "ten/o"})
    _, res = run(col, ch2, STRICT)
    assert res.hints_on
    assert [i["front"] for i in res.deck_items] == ["pain", "tendon"]
    assert res.hint_pool == 2  # the Ch 1 image card isn't in it
    # With the image gone, the same card does conflict.
    add_note(col, "Basic", ch1, {"Front": "pain", "Back": "-odynia"})
    _, res = run(col, ch2, STRICT)
    assert res.deck_items[0]["front"] == "pain (-a___)"


def test_text_cards_grade_the_full_answer_even_when_it_starts_with_the_prompt(
    col: Collection,
) -> None:
    did = deck(col, "X")
    add_note(col, "Basic", did, {"Front": "Bone", "Back": "Bone marrow"})
    add_note(col, "Basic (and reversed card)", did, {"Front": "Bone marrow", "Back": "Bone"})
    _, res = run(col, did)
    assert [(i["front"], i["back"]) for i in res.deck_items] == [
        ("Bone", "Bone marrow"),
        ("Bone marrow", "Bone"),
        ("Bone", "Bone marrow"),
    ]


def test_io_lookalike_with_a_different_answer_image_is_graded_in_full(col: Collection) -> None:
    add_iol_model(col)
    did = deck(col, "X")
    question = '<div class="occ-header">Figure 9</div><img src="fig-9.png">'
    note = add_iol_note(col, did, "<br><b>Femur</b>", question=question)
    note["Answer"] = '<div class="occ-header">Figure 9</div><img src="fig-9-labelled.png"><br>Femur'
    col.update_note(note)
    _, res = run(col, did)
    assert [i["back"] for i in res.deck_items] == ["Figure 9 Femur"]
