"""The import dialog's state machine (pure). The window carries out what ``command`` returns."""

from __future__ import annotations

from .import_plan import ImportPlan, ImportSummary
from .pages import Command
from .views import import_view
from .views.import_view import ImportState

CHOOSE = "choose"
START_IMPORT = "import"
CLOSE = "close"


class ImportController:
    def __init__(self) -> None:
        self.state = ImportState()

    def view_html(self) -> str:
        return import_view.render(self.state)

    @property
    def busy(self) -> bool:
        return self.state.stage in ("scanning", "importing")

    def command(self, cmd: Command) -> str:
        """Handle a click or a list change; returns the effect for the window ("" for none)."""
        if cmd.kind == "act":
            if cmd.a == "choose" and not self.busy:
                return CHOOSE
            if cmd.a == "import" and self.state.stage == "review" and not self.busy:
                return START_IMPORT
            if cmd.a == "close":
                return CLOSE
        elif cmd.kind == "select" and cmd.a.startswith(import_view.PICK_PREFIX):
            rid = cmd.a[len(import_view.PICK_PREFIX) :]
            self.state.picks[rid] = int(cmd.b) if cmd.b.isdigit() else None
        return ""

    def folder_chosen(self, folder: str) -> None:
        self.state = ImportState(stage="scanning", folder=folder)

    def scanned(self, plan: ImportPlan) -> None:
        self.state.plan = plan
        self.state.picks = {}
        self.state.stage = "review"

    def importing(self) -> None:
        self.state.stage = "importing"

    def done(self, summary: ImportSummary) -> None:
        self.state.summary = summary
        self.state.stage = "done"

    def failed(self, message: str) -> None:
        self.state.message = message
        self.state.stage = "error"
