"""anki_io/notetypes.py: kinds, template parsing, default mappings, overrides."""

from __future__ import annotations

from pathlib import Path

import pytest
from anki.collection import Collection
from anki.consts import MODEL_CLOZE
from anki_fixtures import (
    AMC,
    AMC_SAMPLE,
    AMC_TAGS,
    AMC_TYPEIN,
    BQE,
    IOL,
    IOL_CSS,
    IOL_LABELS,
    add_amc_models,
    add_bqe_model,
    add_bqe_note,
    add_io_note,
    add_iol_model,
    add_iol_note,
    add_note,
    deck,
    model,
)

from recalldrill.anki_io.notetypes import (
    FieldRef,
    MappingOverride,
    MappingTable,
    NoteMapping,
    answer_candidates,
    answer_section,
    field_refs,
    front_fields,
    img_srcs,
    is_reference_field,
    kind_of,
    load_overrides,
    looks_like_media,
    parse_overrides,
    sample_nids,
    save_override,
    shares_image,
    split_answer_template,
    strip_front,
)
from recalldrill.storage import MAPPINGS, Storage

# ---------------------------------------------------------------------------
# Template parsing (pure)
# ---------------------------------------------------------------------------


def test_field_refs() -> None:
    tmpl = (
        "{{#Add Reverse}}{{Front}}{{/Add Reverse}}{{^Empty}}x{{/Empty}} {{FrontSide}}"
        "{{text:Back}} {{type:Typed}} {{type:cloze:Text}} {{cloze:Text}} {{furigana:Reading}}"
        "{{ tts en_US voices=Apple_Samantha:Spoken }} {{hint:Notes}} {{!comment}}"
    )
    assert field_refs(tmpl) == [
        FieldRef("Front"),
        FieldRef("Back", ("text",)),
        FieldRef("Typed", ("type",)),
        FieldRef("Text", ("type", "cloze")),
        FieldRef("Text", ("cloze",)),
        FieldRef("Reading", ("furigana",)),
        FieldRef("Spoken", ("tts en_US voices=Apple_Samantha",)),
        FieldRef("Notes", ("hint",)),
    ]
    assert FieldRef("Text", ("type", "cloze")).is_type
    assert FieldRef("Text", ("type", "cloze")).is_cloze
    assert FieldRef("Spoken", ("tts en_US",)).is_tts


@pytest.mark.parametrize(
    "afmt",
    ["{{Q}}<hr id=answer>{{A}}", '{{Q}}<HR id="answer">{{A}}', "{{Q}}<hr id='answer' />{{A}}"],
)
def test_answer_section(afmt: str) -> None:
    assert answer_section(afmt) == "{{A}}"


def test_answer_section_without_rule_is_the_whole_template() -> None:
    assert answer_section("{{Q}}<br>{{A}}") == "{{Q}}<br>{{A}}"


@pytest.mark.parametrize(
    ("name", "media"),
    [
        ("FrontAudio", True),
        ("Image", True),
        ("Sound", True),
        ("Picture", True),
        ("Photo 2", True),
        ("Image Mask", True),
        ("BackText", False),
        ("Notes", False),
    ],
)
def test_looks_like_media(name: str, media: bool) -> None:
    assert looks_like_media(name) is media


def _model(fields: list[str], qfmt: str, afmt: str, **extra: object) -> dict[str, object]:
    return {
        "name": "T",
        "type": 0,
        "flds": [{"name": f} for f in fields],
        "tmpls": [{"name": "Card 1", "qfmt": qfmt, "afmt": afmt}],
        **extra,
    }


def test_answer_candidates_order_and_filters() -> None:
    m = _model(
        ["Q", "A", "B", "Audio", "Back Image", "Spoken", "Notes"],
        "{{Q}}",
        "{{Q}}<hr id=answer>{{B}} {{A}} {{Audio}} {{Back Image}}"
        " {{tts en:Spoken}} {{B}} {{Missing}}",
    )
    assert answer_candidates(m, m["tmpls"][0]) == ["B", "A"]  # type: ignore[index]


def test_answer_candidates_without_rule_drop_front_fields() -> None:
    m = _model(["Q", "A"], "{{Q}}", "{{Q}}<br>{{A}}")
    assert answer_candidates(m, m["tmpls"][0]) == ["A"]  # type: ignore[index]


@pytest.mark.parametrize(
    "name",
    ["Extra", "back extra", "Notes", "Remarks", "FullContext", "Full Context", "Source",
     "Sources", "Comments", "Header", "Footer", "full_context"],
)  # fmt: skip
def test_reference_fields_are_never_answers(name: str) -> None:
    assert is_reference_field(name)
    m = _model(["Q", name, "A"], "{{Q}}", f"{{{{Q}}}}<hr id=answer>{{{{{name}}}}} {{{{A}}}}")
    assert answer_candidates(m, m["tmpls"][0]) == ["A"]  # type: ignore[index]


@pytest.mark.parametrize("name", ["Answer", "Back", "Meaning", "Definition"])
def test_ordinary_fields_are_not_reference_fields(name: str) -> None:
    assert not is_reference_field(name)


def test_candidates_before_the_rule_when_nothing_is_left_after_it() -> None:
    fields = ["Question", "Answer", "Extra", "FullContext", "Source", "Notes"]
    afmt = "{{Answer}}<hr id=answer>{{#Extra}}{{Extra}}{{/Extra}}{{FullContext}}{{Source}}"
    m = _model(fields, "{{Question}}", afmt)
    assert split_answer_template(afmt)[0] == "{{Answer}}"
    assert answer_candidates(m, m["tmpls"][0]) == ["Answer"]  # type: ignore[index]
    # Something left after the rule wins over anything before it.
    m = _model(["Q", "Shown", "A"], "{{Q}}", "{{Shown}}<hr id=answer>{{A}}")
    assert answer_candidates(m, m["tmpls"][0]) == ["A"]  # type: ignore[index]


def test_front_fields() -> None:
    m = _model(
        ["Header", "Q", "Back", "Spoken"],
        "{{Header}} {{Q}} {{type:Back}} {{tts en:Spoken}} {{Q}} {{Missing}}",
        "",
    )
    assert front_fields(m, m["tmpls"][0], "Back") == ["Header", "Q"]  # type: ignore[index]
    assert front_fields(m, m["tmpls"][0], "Q") == ["Header"]  # type: ignore[index]


def test_img_srcs() -> None:
    html = (
        '<img src="fig 4.3.png"><IMG class=x SRC=\'b.jpg\'><img src=c.gif alt="c">'
        '<img alt="no src"><img src="">'
    )
    assert img_srcs(html) == {"fig 4.3.png", "b.jpg", "c.gif"}
    assert img_srcs("no images") == set()


@pytest.mark.parametrize(
    ("answer", "fronts", "shared"),
    [
        (
            '<div>H</div><img src="fig.png"><b>Nucleus</b>',
            ['<div>H</div><img src="fig.png">'],
            True,
        ),
        ('<img src="fig.png">x', ["header only", "<img src='fig.png'>"], True),  # 2nd front field
        ('<img src="other.png">x', ['<img src="fig.png">'], False),
        ("Bone marrow", ["Bone"], False),  # text only
        ('<img src="fig.png">', ["Bone"], False),  # image on one side only
        ("Bone marrow", ['<img src="fig.png">'], False),
        ('<img src="fig.png">', [], False),
    ],
)
def test_shares_image(answer: str, fronts: list[str], shared: bool) -> None:
    assert shares_image(answer, fronts) is shared


@pytest.mark.parametrize(
    ("answer", "front", "expected"),
    [
        ("Figure 4.3 Cell structures Nucleus", "Figure 4.3 Cell structures", "Nucleus"),
        ("Figure 4.3 Nucleus", "Figure 4.3", "Nucleus"),
        ("Figure 4.3", "Figure 4.3", ""),  # nothing added: empty answer
        ("Nucleus", "", "Nucleus"),  # image-only front
        ("Nucleus", "Figure 4.3", "Nucleus"),  # doesn't start with the front
        ("painful", "pain", "painful"),  # mid-word: not a copy
        ("pain: severe", "pain", ": severe"),
    ],
)
def test_strip_front(answer: str, front: str, expected: str) -> None:
    assert strip_front(answer, front) == expected


def test_kind_of_pure() -> None:
    assert kind_of(_model(["F"], "", "")) == "standard"
    assert kind_of(_model(["Text"], "{{cloze:Text}}", "", type=MODEL_CLOZE)) == "cloze"
    assert kind_of(_model(["Text"], "", "", type=MODEL_CLOZE, originalStockKind=6)) == (
        "image_occlusion"
    )
    # The name plays no part: the anki-cards lookalike is a drillable standard type.
    named = {**_model(["F"], "", ""), "name": "Image Occlusion (anki-medical-cards)"}
    assert kind_of(named) == "standard"
    assert kind_of({**named, "type": MODEL_CLOZE, "name": "Image Occlusion Enhanced+"}) == "cloze"
    # Cloze's own originalStockKind (5) is Kind.KIND_IMAGE_OCCLUSION: not IO.
    assert kind_of(_model(["T"], "", "", type=MODEL_CLOZE, originalStockKind=5)) == "cloze"


def test_sample_nids_spreads_evenly() -> None:
    assert sample_nids([3, 1, 2]) == [1, 2, 3]
    picked = sample_nids(list(range(1000)), 50)
    assert len(picked) == 50 and picked[0] == 0 and picked[-1] == 980


# ---------------------------------------------------------------------------
# Default mapping per fixture template
# ---------------------------------------------------------------------------


def _mapping(col: Collection, name: str, ord_: int = 0) -> NoteMapping:
    return MappingTable(col).get(int(model(col, name)["id"]), ord_)


def _fields(m: NoteMapping) -> tuple[str, str | None, str | None]:
    return (m.kind, m.answer_field, m.extra_field)


def test_stock_basic_types(col: Collection) -> None:
    did = deck(col, "X")
    add_note(col, "Basic", did, {"Front": "q", "Back": "a"})
    add_note(col, "Basic (and reversed card)", did, {"Front": "q", "Back": "a"})
    add_note(col, "Basic (type in the answer)", did, {"Front": "q", "Back": "a"})
    assert _fields(_mapping(col, "Basic")) == ("standard", "Back", None)
    assert _fields(_mapping(col, "Basic (and reversed card)", 0)) == ("standard", "Back", None)
    assert _fields(_mapping(col, "Basic (and reversed card)", 1)) == ("standard", "Front", None)
    typed = _mapping(col, "Basic (type in the answer)")
    assert _fields(typed) == ("standard", "Back", None)
    assert typed.why == "{{type:Back}} on the front"


def test_stock_cloze_and_io(col: Collection) -> None:
    did = deck(col, "X")
    add_note(col, "Cloze", did, {"Text": "{{c1::a}}", "Back Extra": "more"})
    add_io_note(col, did)
    assert _fields(_mapping(col, "Cloze")) == ("cloze", "Text", "Back Extra")
    io = _mapping(col, "Image Occlusion")
    assert io.kind == "image_occlusion" and io.ineligible and io.answer_field is None


def test_basic_quizlet_extended(col: Collection) -> None:
    add_bqe_model(col)
    did = deck(col, "Medical Terminology::Ch 1")
    add_bqe_note(col, did, "ankyl/o", "crooked, bent, stiff")
    add_bqe_note(col, did, "-algia", "pain", notes="also -dynia")
    normal, reverse = _mapping(col, BQE, 0), _mapping(col, BQE, 1)
    assert (normal.template_name, reverse.template_name) == ("Normal", "Reverse")
    assert _fields(normal) == ("standard", "BackText", "Notes")
    assert _fields(reverse) == ("standard", "FrontText", "Notes")
    # Audio and image fields are never candidates.
    assert normal.candidates == ("BackText",)
    assert reverse.candidates == ("FrontText",)


def test_extra_needs_content_in_a_sampled_note(col: Collection) -> None:
    add_bqe_model(col)
    did = deck(col, "X")
    add_bqe_note(col, did, "ankyl/o", "crooked, bent, stiff", notes="")
    assert _mapping(col, BQE, 0).extra_field is None


def test_anki_cards_cloze_types(col: Collection) -> None:
    add_amc_models(col)
    did = deck(col, "Human A&P::Lecture 2")
    add_note(col, AMC, did, AMC_SAMPLE, AMC_TAGS)
    add_note(col, AMC_TYPEIN, did, AMC_SAMPLE, AMC_TAGS)
    for name in (AMC, AMC_TYPEIN):
        m = _mapping(col, name)
        assert _fields(m) == ("cloze", "Text", "Extra")
        assert m.extra_field not in ("FullContext", "Source", "Notes")


def test_first_candidate_filled_in_half_the_notes_wins(col: Collection) -> None:
    mm = col.models
    m = mm.new("Two answers")
    for f in ("Q", "Hint", "Answer"):
        mm.add_field(m, mm.new_field(f))
    t = mm.new_template("Card 1")
    t["qfmt"] = "{{Q}}"
    t["afmt"] = "{{Q}}<hr id=answer>{{Hint}}<br>{{Answer}}"
    mm.add_template(m, t)
    mm.add(m)
    did = deck(col, "X")
    for i in range(4):
        add_note(
            col, "Two answers", did, {"Q": f"q{i}", "Hint": "h" if i == 0 else "", "Answer": "a"}
        )
    got = _mapping(col, "Two answers")
    assert got.answer_field == "Answer"
    assert got.candidates == ("Hint", "Answer")
    assert got.why == "first answer-side field filled in 4/4 sampled notes"


def test_no_candidate_filled_enough_is_unmapped(col: Collection) -> None:
    add_bqe_model(col)
    did = deck(col, "X")
    for i in range(3):
        add_bqe_note(col, did, f"t{i}", "<img src=x.jpg>" if i else "meaning")
    m = _mapping(col, BQE, 0)
    assert m.answer_field is None
    assert m.why == "no candidate filled in 50% of 3 sampled notes"


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------


def test_parse_overrides_skips_bad_entries() -> None:
    data = {
        "17": {
            "0": {"answer_field": "BackText", "extra_field": None, "ineligible": False},
            "1": {"answer_field": "", "extra_field": "Notes", "ineligible": True},
            "x": {"answer_field": "A"},
            "2": "nope",
        },
        "18": [],
        "y": {"0": {}},
    }
    assert parse_overrides(data) == {
        (17, 0): MappingOverride("BackText", None, False),
        (17, 1): MappingOverride(None, "Notes", True),
    }
    assert parse_overrides(None) == {}
    assert parse_overrides([1]) == {}


def test_overrides_round_trip_through_storage(tmp_path: Path) -> None:
    st = Storage(tmp_path, "User 1")
    o = MappingOverride("FrontText", None, False, BQE, "Reverse")
    save_override(st, 1700000000001, 1, o)
    save_override(st, 1700000000001, 0, MappingOverride(None, None, True, BQE, "Normal"))
    assert load_overrides(st) == {
        (1700000000001, 0): MappingOverride(None, None, True, BQE, "Normal"),
        (1700000000001, 1): o,
    }
    raw = st.read_json(MAPPINGS, None)
    assert raw["1700000000001"]["1"] == {
        "answer_field": "FrontText",
        "extra_field": None,
        "ineligible": False,
        "notetype_name": BQE,
        "template_name": "Reverse",
    }


def test_stored_overrides_win(col: Collection, tmp_path: Path) -> None:
    add_bqe_model(col)
    did = deck(col, "X")
    add_bqe_note(col, did, "-algia", "pain", notes="n")
    ntid = int(model(col, BQE)["id"])
    st = Storage(tmp_path, "User 1")
    save_override(st, ntid, 0, MappingOverride("Notes", None, False, BQE, "Normal"))
    save_override(st, ntid, 1, MappingOverride(None, None, True, BQE, "Reverse"))
    table = MappingTable(col, load_overrides(st))
    normal, reverse = table.get(ntid, 0), table.get(ntid, 1)
    assert _fields(normal) == ("standard", "Notes", None) and normal.overridden
    assert reverse.ineligible and reverse.overridden
    assert reverse.why == "marked ineligible in mappings.json"
    # The defaults are still there for the panel.
    assert table.default(ntid, 0).answer_field == "BackText"


def test_override_naming_a_missing_field_is_unmapped(col: Collection) -> None:
    add_bqe_model(col)
    ntid = int(model(col, BQE)["id"])
    table = MappingTable(col, {(ntid, 0): MappingOverride("Gone", "Gone too", False)})
    m = table.get(ntid, 0)
    assert m.answer_field is None and m.extra_field is None
    assert "missing field 'Gone'" in m.why


def test_io_lookalike_maps_to_the_answer_field(col: Collection) -> None:
    add_iol_model(col)
    did = deck(col, "Human A&P::Lab 3")
    for label in IOL_LABELS.values():
        add_iol_note(col, did, label, extra="Simple columnar")
    m = _mapping(col, IOL)
    assert (m.template_name, m.kind, m.ineligible) == ("Reveal", "standard", False)
    assert (m.answer_field, m.extra_field) == ("Answer", "Extra")
    assert m.candidates == ("Answer",)  # Extra, FullContext, Source are reference fields
    assert m.front_fields == ("Question",)
    assert m.why == "first field before <hr id=answer> filled in 3/3 sampled notes"
    assert model(col, IOL)["css"] == IOL_CSS


def test_a_name_with_image_occlusion_is_not_io(col: Collection) -> None:
    mm = col.models
    m = mm.copy(model(col, "Cloze"), add=False)
    m["name"] = "Image Occlusion Enhanced+"
    mm.add(m)
    did = deck(col, "X")
    add_note(col, m["name"], did, {"Text": "{{c1::femur}} is a bone"})
    ntid = int(model(col, m["name"])["id"])
    assert _fields(MappingTable(col).get(ntid, 0)) == ("cloze", "Text", "Back Extra")


def test_no_override_makes_stock_io_drillable(col: Collection) -> None:
    add_io_note(col, deck(col, "X"))
    ntid = int(model(col, "Image Occlusion")["id"])
    m = MappingTable(col, {(ntid, 0): MappingOverride("Occlusion", None, False)}).get(ntid, 0)
    assert m.kind == "image_occlusion" and m.ineligible


def test_override_answer_field_gets_its_own_front_fields(col: Collection) -> None:
    add_iol_model(col)
    ntid = int(model(col, IOL)["id"])
    m = MappingTable(col, {(ntid, 0): MappingOverride("Notes", "Extra", False)}).get(ntid, 0)
    assert (m.answer_field, m.extra_field, m.front_fields) == ("Notes", "Extra", ("Question",))


def test_cloze_cards_share_template_zero(col: Collection) -> None:
    did = deck(col, "X")
    note = add_note(col, "Cloze", did, {"Text": "{{c1::a}} {{c2::b}} {{c3::c}}"})
    table = MappingTable(col)
    ntid = int(note.mid)
    assert {table.for_card(ntid, c.ord).template_ord for c in note.cards()} == {0}
