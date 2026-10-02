""" "Edit mapping…": pick a template's answer and Extra fields, or mark it ineligible.

Writes ``mappings.json`` (``notetypes.save_override``); nothing in the collection.
"""

from __future__ import annotations

from collections.abc import Sequence

from aqt.qt import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
    qconnect,
)
from aqt.utils import disable_help_button

from ..anki_io.notetypes import MappingOverride, NoteMapping, save_override
from ..anki_io.panel import NoteTypeTemplates
from ..storage import Storage

NO_EXTRA = "(no Extra)"


class MappingDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        storage: Storage,
        mappings: Sequence[NoteMapping],
        note_types: Sequence[NoteTypeTemplates],
        first: tuple[int, int] | None = None,
    ) -> None:
        super().__init__(parent)
        disable_help_button(self)
        self.setWindowTitle("Recall Drill: edit mapping")
        self.storage = storage
        self.mappings = list(mappings)
        self.fields = {nt.ntid: list(nt.fields) for nt in note_types}
        self.saved = False

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Which field is the typed answer, and which is shown as Extra after it.\n"
                "Saved in the add-on's mappings.json; your cards are not changed."
            )
        )
        form = QFormLayout()
        self.which = QComboBox()
        for m in self.mappings:
            self.which.addItem(f"{m.notetype_name} › {m.template_name}")
        self.why = QLabel()
        self.why.setWordWrap(True)
        self.answer = QComboBox()
        self.extra = QComboBox()
        self.ineligible = QCheckBox("Not drillable (mark this template ineligible)")
        form.addRow("Template", self.which)
        form.addRow("Now", self.why)
        form.addRow("Answer field", self.answer)
        form.addRow("Extra field", self.extra)
        form.addRow("", self.ineligible)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close
        )
        qconnect(buttons.accepted, self._save)
        qconnect(buttons.rejected, self.reject)
        layout.addWidget(buttons)

        qconnect(self.which.currentIndexChanged, self._load)
        qconnect(self.ineligible.toggled, self._toggle)
        start = 0
        if first is not None:
            start = next(
                (i for i, m in enumerate(self.mappings) if (m.ntid, m.template_ord) == first), 0
            )
        self.which.setCurrentIndex(start)
        self._load(start)

    def _current(self) -> NoteMapping | None:
        i = self.which.currentIndex()
        return self.mappings[i] if 0 <= i < len(self.mappings) else None

    def _load(self, _index: int = 0) -> None:
        m = self._current()
        if m is None:
            return
        names = self.fields.get(m.ntid, [])
        self.why.setText(
            f"{m.kind}; answer {m.answer_field or '—'}, extra {m.extra_field or '—'} ({m.why})"
        )
        self.answer.clear()
        self.answer.addItems(names)
        if m.answer_field in names:
            self.answer.setCurrentIndex(names.index(m.answer_field))
        self.extra.clear()
        self.extra.addItems([NO_EXTRA, *names])
        self.extra.setCurrentIndex(names.index(m.extra_field) + 1 if m.extra_field in names else 0)
        io = m.kind == "image_occlusion"
        self.ineligible.setChecked(m.ineligible)
        self.ineligible.setEnabled(not io)
        if io:
            self.why.setText(self.why.text() + "\nAnki's Image Occlusion holds shapes, not text.")
        self._toggle(m.ineligible)

    def _toggle(self, ineligible: bool) -> None:
        m = self._current()
        io = m is not None and m.kind == "image_occlusion"
        self.answer.setEnabled(not ineligible and not io)
        self.extra.setEnabled(not ineligible and not io)

    def _save(self) -> None:
        m = self._current()
        if m is None or m.kind == "image_occlusion":
            return
        extra = self.extra.currentText()
        save_override(
            self.storage,
            m.ntid,
            m.template_ord,
            MappingOverride(
                answer_field=None if self.ineligible.isChecked() else self.answer.currentText(),
                extra_field=None if extra == NO_EXTRA else extra,
                ineligible=self.ineligible.isChecked(),
                notetype_name=m.notetype_name,
                template_name=m.template_name,
            ),
        )
        self.saved = True
        self.accept()
