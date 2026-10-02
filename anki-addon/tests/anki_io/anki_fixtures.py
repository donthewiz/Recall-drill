"""Note types and notes for the anki_io tests, built in a scratch collection.

- Stock: Basic, Basic (and reversed card), Basic (type in the answer), Cloze,
  Image Occlusion (all present in a new collection).
- ``Basic Quizlet Extended``: a copy of Don's Med Term note type.
- ``Cloze (anki-medical-cards)+`` and ``... + TypeIn``: copies of the
  anki-cards skill's cloze types.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Mapping, Sequence

# anki.collection must load before anki.cards (circular import).
import anki.collection  # noqa: F401
from anki.cards import Card
from anki.collection import Collection
from anki.decks import DeckId
from anki.models import NotetypeDict
from anki.notes import Note
from pytest import mark

needs_aqt = mark.skipif(
    importlib.util.find_spec("aqt") is None,
    reason="imports aqt (Anki's GUI package), which isn't installed: "
    "CI's addon-anki job installs anki only",
)
"""For tests that import ``aqt``. Every other anki_io test needs ``anki`` alone."""

BQE = "Basic Quizlet Extended"
BQE_FIELDS = ["FrontText", "FrontAudio", "BackText", "BackAudio", "Image", "Add Reverse", "Notes"]
BQE_NORMAL_Q = "{{FrontText}}\n<br><br>\n{{FrontAudio}}"
BQE_NORMAL_A = (
    "{{FrontText}}\n<hr id=answer>\n{{BackText}}\n<br><br>\n{{Image}}\n<br><br>\n{{BackAudio}}"
)
BQE_REVERSE_Q = "{{#Add Reverse}}{{BackText}}\n<br><br>\n{{BackAudio}}{{/Add Reverse}}"
BQE_REVERSE_A = "{{BackText}}\n<hr id=answer>\n{{FrontText}}\n<br><br>\n{{FrontAudio}}\n{{Image}}"

AMC = "Cloze (anki-medical-cards)+"
AMC_TYPEIN = "Cloze (anki-medical-cards)+ TypeIn"
AMC_FIELDS = ["Text", "Extra", "FullContext", "Source", "Notes"]
AMC_BACK = (
    "<br><hr id=answer>{{#Extra}}<div class='extra'>{{Extra}}</div>{{/Extra}}"
    "{{#FullContext}}<details class='full-context'><summary>Show more</summary>"
    "<div class='full-context-body'>{{FullContext}}</div></details>{{/FullContext}}"
    "{{#Source}}<div class='source'>{{Source}}</div>{{/Source}}"
)
AMC_FRONT = "{{cloze:Text}}"
AMC_TYPEIN_FRONT = "{{cloze:Text}}\n<br>\n{{type:cloze:Text}}"


def deck(col: Collection, name: str) -> DeckId:
    did = col.decks.id(name)
    assert did is not None
    return did


def model(col: Collection, name: str) -> NotetypeDict:
    m = col.models.by_name(name)
    assert m is not None, name
    return m


def add_note(
    col: Collection,
    note_type: str | NotetypeDict,
    did: DeckId,
    fields: Mapping[str, str],
    tags: Sequence[str] = (),
) -> Note:
    m = model(col, note_type) if isinstance(note_type, str) else note_type
    note = col.new_note(m)
    for k, v in fields.items():
        note[k] = v
    for t in tags:
        note.add_tag(t)
    col.add_note(note, did)
    return note


def cards_by_ord(note: Note) -> list[Card]:
    return sorted(note.cards(), key=lambda c: c.ord)


def _standard_model(
    col: Collection, name: str, fields: Sequence[str], templates: Sequence[tuple[str, str, str]]
) -> NotetypeDict:
    mm = col.models
    m = mm.new(name)
    for f in fields:
        mm.add_field(m, mm.new_field(f))
    for tname, q, a in templates:
        t = mm.new_template(tname)
        t["qfmt"] = q
        t["afmt"] = a
        mm.add_template(m, t)
    mm.add(m)
    return model(col, name)


def add_bqe_model(col: Collection) -> NotetypeDict:
    return _standard_model(
        col,
        BQE,
        BQE_FIELDS,
        [("Normal", BQE_NORMAL_Q, BQE_NORMAL_A), ("Reverse", BQE_REVERSE_Q, BQE_REVERSE_A)],
    )


def add_bqe_note(
    col: Collection,
    did: DeckId,
    term: str,
    meaning: str,
    notes: str = "",
    tags: Sequence[str] = (),
    reverse: bool = True,
) -> Note:
    return add_note(
        col,
        BQE,
        did,
        {
            "FrontText": term,
            "FrontAudio": "[sound:q-front.mp3]",
            "BackText": meaning,
            "BackAudio": "[sound:q-back.mp3]",
            "Image": "",
            "Add Reverse": "True" if reverse else "",
            "Notes": notes,
        },
        tags,
    )


def _cloze_model(col: Collection, name: str, front: str) -> NotetypeDict:
    """A copy of stock Cloze (originalStockKind stays Cloze), re-fielded."""
    mm = col.models
    m = mm.copy(model(col, "Cloze"), add=False)
    m["name"] = name
    for f in list(m["flds"]):
        if f["name"] != "Text":
            mm.remove_field(m, f)
    for f in AMC_FIELDS[1:]:
        mm.add_field(m, mm.new_field(f))
    t = m["tmpls"][0]
    t["qfmt"] = front
    t["afmt"] = front + AMC_BACK
    mm.add(m)
    return model(col, name)


def add_amc_models(col: Collection) -> tuple[NotetypeDict, NotetypeDict]:
    return _cloze_model(col, AMC, AMC_FRONT), _cloze_model(col, AMC_TYPEIN, AMC_TYPEIN_FRONT)


AMC_SAMPLE = {
    "Text": "Bone tissue is formally called {{c1::osseous tissue}}.",
    "Extra": "From <i>oss-</i> (bone).",
    "FullContext": "Bone tissue, or osseous tissue, is a connective tissue.",
    "Source": "Lecture 2, slide 4",
    "Notes": "",
}
AMC_TAGS = ("rd::drill::A1", "Layer::1", "Part::A")


def add_io_note(col: Collection, did: DeckId) -> Note:
    return add_note(
        col,
        "Image Occlusion",
        did,
        {
            "Occlusion": "{{c1::image-occlusion:rect:left=.1:top=.1:width=.2:height=.2:oi=1}}",
            "Image": '<img src="bones.png">',
        },
    )


# The anki-cards skill's Image Occlusion lookalike: a STANDARD note type. Its
# Answer repeats the Question HTML (header, image, masks) and adds the label.
IOL = "Image Occlusion (anki-medical-cards)"
IOL_FIELDS = ["Question", "Answer", "Extra", "FullContext", "Source", "Notes"]
IOL_FRONT = "{{Question}}"
IOL_BACK = (
    "{{Answer}}<hr id=answer>{{#Extra}}<div class='extra'>{{Extra}}</div>{{/Extra}}"
    "{{#FullContext}}<details class='full-context'><summary>Show more</summary>"
    "<div class='full-context-body'>{{FullContext}}</div></details>{{/FullContext}}"
    "{{#Source}}<div class='source'>{{Source}}</div>{{/Source}}"
)
IOL_CSS = (
    ".occ-mask { position: absolute; background: #e33; }\n.occ-mask.active { background: #fc0; }"
)
IOL_QUESTION = (
    '<div class="occ-header">Figure 4.3 Cell and tissue structures</div>'
    '<div class="occ-wrap"><img src="fig-4-3.png">'
    '<div class="occ-mask active" style="left:12%;top:30%;width:20%;height:8%"></div>'
    '<div class="occ-mask" style="left:52%;top:61%;width:25%;height:9%"></div></div>'
)
# The three label variants seen in Don's collection.
IOL_LABELS = {
    "Nucleus": '<div class="occ-caption">Nucleus</div>',
    "Goblet cells": "<br><b>Goblet cells</b>",
    "Hyaline (articular) cartilage": (
        '<div style="margin-top:8px;font-weight:bold">Hyaline (articular) cartilage</div>'
    ),
}


def add_iol_model(col: Collection) -> NotetypeDict:
    m = _standard_model(col, IOL, IOL_FIELDS, [("Reveal", IOL_FRONT, IOL_BACK)])
    m["css"] = IOL_CSS
    col.models.update_dict(m)
    return model(col, IOL)


def add_iol_note(
    col: Collection, did: DeckId, label_html: str, extra: str = "", question: str = IOL_QUESTION
) -> Note:
    return add_note(
        col,
        IOL,
        did,
        {
            "Question": question,
            "Answer": question + label_html,
            "Extra": extra,
            "FullContext": "Simple columnar epithelium lines the gut.",
            "Source": "Lab 3, slide 12",
        },
        AMC_TAGS,
    )
