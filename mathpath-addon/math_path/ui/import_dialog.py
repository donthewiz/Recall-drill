"""Tools → Math Path → Import recipes… (v0.1)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from anki.collection import Collection, OpChanges
from aqt import mw
from aqt.operations import CollectionOp, QueryOp
from aqt.qt import QFileDialog
from aqt.utils import showWarning

from ..anki_io import importer
from ..import_controller import CHOOSE, CLOSE, START_IMPORT, ImportController
from ..import_plan import ImportPlan, ImportSummary
from ..pages import Command, PageView
from ..storage import UI_STATE
from ..views.import_view import PICK_PREFIX
from .context import AddonContext
from .page_window import PageWindow

LAST_FOLDER_KEY = "import_folder"


@dataclass
class _Outcome:
    """What ``CollectionOp`` needs: the changes, plus the summary for the dialog."""

    changes: OpChanges
    summary: ImportSummary


class ImportDialog(PageWindow):
    GEOM_KEY = "mathpath_import"
    DEFAULT_SIZE = (900, 760)

    def __init__(self, ctx: AddonContext) -> None:
        super().__init__(ctx, "Math Path: import recipes")
        self.ctrl = ImportController()
        self.redraw()

    def page_view(self) -> PageView:
        picks = {
            f"{PICK_PREFIX}{rid}": ("" if did is None else str(did))
            for rid, did in self.ctrl.state.picks.items()
        }
        return PageView(html=self.ctrl.view_html(), texts=picks, night=self.night)

    def on_command(self, cmd: Command) -> None:
        effect = self.ctrl.command(cmd)
        if effect == CHOOSE:
            self.choose_folder()
        elif effect == START_IMPORT:
            self.start_import()
        elif effect == CLOSE:
            self.close()

    def allow_close(self) -> bool:
        return not self.ctrl.busy

    # -- steps ------------------------------------------------------------------------

    def choose_folder(self) -> None:
        ui = self.ctx.storage().read_json(UI_STATE, {})
        start = str(ui.get(LAST_FOLDER_KEY, "")) if isinstance(ui, dict) else ""
        folder = QFileDialog.getExistingDirectory(
            self, "Choose the folder with the recipe files", start
        )
        if folder:
            self.open_folder(folder)

    def open_folder(self, folder: str) -> None:
        """Read and smoke-test the folder's recipes off the main thread, then show the plan."""
        store = self.ctx.storage()
        ui = store.read_json(UI_STATE, {})
        if isinstance(ui, dict):
            ui[LAST_FOLDER_KEY] = folder
            store.write_json(UI_STATE, ui)
        self.ctrl.folder_chosen(folder)
        self.redraw()

        def op(col: Collection) -> ImportPlan:
            return importer.plan_import(col, importer.scan_folder(Path(folder)))

        def done(plan: ImportPlan) -> None:
            self.ctrl.scanned(plan)
            self.redraw()

        def failed(exc: Exception) -> None:
            self.ctrl.failed(f"Couldn't read the folder: {exc}")
            self.redraw()

        QueryOp(parent=self, op=op, success=done).failure(failed).run_in_background()

    def start_import(self) -> None:
        plan = self.ctrl.state.plan
        if plan is None:
            return
        picks = dict(self.ctrl.state.picks)
        self.ctrl.importing()
        self.redraw()

        def done(summary: ImportSummary) -> None:
            self.ctrl.done(summary)
            self.redraw()

        def failed(exc: Exception) -> None:
            self.ctrl.failed(f"The import failed and was undone: {exc}")
            self.redraw()
            showWarning(f"Math Path: the import failed.\n\n{exc}")

        def op(col: Collection) -> _Outcome:
            summary = importer.apply_import(col, plan, picks)
            return _Outcome(summary.changes, summary)

        CollectionOp(self, op).success(lambda r: done(r.summary)).failure(
            failed
        ).run_in_background()


def open_import_dialog(ctx: AddonContext) -> ImportDialog | None:
    for w in ctx.windows:
        if isinstance(w, ImportDialog):
            w.showNormal()
            w.raise_()
            w.activateWindow()
            return w
    if mw.col is None:
        return None
    dialog = ImportDialog(ctx)
    dialog.show()
    return dialog
