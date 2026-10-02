"""anki_io/preview.py: the dev preview's data and HTML, headless."""

from __future__ import annotations

import os
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

from recalldrill import deck_settings
from recalldrill.anki_io.preview import build_preview, preview_html
from recalldrill.storage import DECK_SETTINGS, HINTS, Storage


def test_preview_of_a_med_term_style_deck(col: Collection, tmp_path: Path) -> None:
    add_bqe_model(col)
    top = deck(col, "Medical Terminology")
    ch1 = deck(col, "Medical Terminology::Ch 1")
    for term, meaning in [
        ("-algia", "pain"),
        ("-dynia", "pain"),
        ("nat", "birth"),
        ("natal", "birth"),
    ]:
        add_bqe_note(col, ch1, term, meaning, notes="n")
    col.sched.suspend_cards(col.find_cards('deck:"Medical Terminology"'))
    st = Storage(tmp_path, "User 1")

    p = build_preview(col, st, top)
    assert p.deck_name == "Medical Terminology"
    assert len(p.build.deck_items) == 8
    # No saved settings: the terminology proposal is used, and nothing is saved.
    assert p.settings_source == "proposed" and p.build.hints_on
    assert not st.path(DECK_SETTINGS).exists() and not st.path(HINTS).exists()

    html = preview_html(p)
    for text in (
        "<h2>Medical Terminology</h2>",
        "<td>suspended_new</td><td>8</td><td>8</td>",
        "<b>Siblings:</b> 8 picked cards share a note with another picked card (4 notes).",
        "<td>Basic Quizlet Extended</td><td>Normal (0)</td><td>standard</td><td>BackText</td>"
        "<td>Notes</td>",
        "<td>Reverse (1)</td><td>standard</td><td>FrontText</td><td>Notes</td>",
        "pain (-a___)",
        "Flagged hints (need a manual hint)",
        "<td>birth</td><td>nat</td><td>natal</td>",
        "proposed: stemTolerance=False, strictPunctuation=True, hints=True; hints on",
    ):
        assert text in html, text
    assert "[sound:" not in html and "[anki:play" not in html

    # A saved template filter (Reverse only) and saved settings are used.
    ntid = p.selection.picked[0].snap.ntid
    deck_settings.save(st, top, {"strictPunctuation": True, "card_ords": {str(ntid): [1]}})
    p = build_preview(col, st, top)
    assert p.settings_source == "saved"
    assert [s.ord for s in p.build.sources] == [1, 1, 1, 1]
    assert p.selection.template_excluded == 4
    assert "4 cards left out by the template filter." in preview_html(p)


def test_preview_of_a_cloze_deck_with_io(col: Collection, tmp_path: Path) -> None:
    add_amc_models(col)
    did = deck(col, "Human A&P::Lecture 2")
    add_note(col, AMC, did, AMC_SAMPLE, AMC_TAGS)
    add_io_note(col, did)
    p = build_preview(col, Storage(tmp_path, "p"), did)
    html = preview_html(p)
    assert p.build.deck_items == [
        {
            "front": "Bone tissue is formally called [...].",
            "back": "osseous tissue",
            "extra": "From oss- (bone).",
        }
    ]
    assert p.settings_source == "proposed"  # "osseous tissue" is a short answer
    assert "<td>image_occlusion</td><td>1</td>" in html
    assert "<td>cloze</td><td>Text</td><td>Extra</td>" in html
    assert "Image Occlusion: nothing to type" in html
    assert "items show an image on the front" not in html


def test_preview_counts_image_fronts(col: Collection, tmp_path: Path) -> None:
    add_iol_model(col)
    did = deck(col, "Lab 3")
    for label in IOL_LABELS.values():
        add_iol_note(col, did, label, extra="see text")
    html = preview_html(build_preview(col, Storage(tmp_path, "p"), did))
    assert "3 items show an image on the front: no hints for them." in html
    assert "<td>Image Occlusion (anki-medical-cards)</td><td>Reveal (0)</td>" in html
    assert "<td>standard</td><td>Answer</td><td>Extra</td>" in html


def test_preview_dialog_renders_offscreen(
    col: Collection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Qt dialog itself, on Qt's offscreen platform (no display needed)."""
    monkeypatch.setenv("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM", "offscreen"))
    from aqt.qt import QApplication, QTextBrowser

    from recalldrill.ui import preview as ui_preview

    _app = QApplication.instance() or QApplication([])  # kept alive for the test
    add_bqe_model(col)
    did = deck(col, "Medical Terminology")
    add_bqe_note(col, did, "-algia", "pain")
    dialog = ui_preview.show_dialog(build_preview(col, Storage(tmp_path, "p"), did))
    try:
        assert dialog.windowTitle() == "Recall Drill (dev) preview: Medical Terminology"
        browser = dialog.findChild(QTextBrowser)
        assert browser is not None
        assert "Basic Quizlet Extended" in browser.toPlainText()
        assert dialog.isVisible()
    finally:
        dialog.close()
