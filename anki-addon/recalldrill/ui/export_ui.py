"""The outcomes export's triggers (v0.3): after a handoff, at profile open, and
Tools → "Recall Drill: export outcomes now".

All three run ``anki_io/export.export_outcomes`` in a ``QueryOp`` (the collection
is only read; the file is written atomically). The automatic runs are quiet: a
failure is logged and never interrupts a handoff or the profile opening.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from aqt import mw
from aqt.operations import QueryOp
from aqt.utils import showInfo, showWarning

from ..anki_io.export import ExportResult, export_outcomes
from .context import AddonContext

log = logging.getLogger(__name__)

TITLE = "Recall Drill: export outcomes"


def export_in_background(
    ctx: AddonContext, then: Callable[[ExportResult], None] | None = None
) -> None:
    """The automatic export: quiet on success and on failure."""
    if mw is None or mw.col is None:  # pyright: ignore[reportUnnecessaryComparison]
        return
    storage = ctx.storage()

    def failed(exc: Exception) -> None:
        log.warning("Recall Drill: the outcomes export failed: %s", exc, exc_info=exc)

    def done(result: ExportResult) -> None:
        if then is not None:
            then(result)

    QueryOp(parent=mw, op=lambda col: export_outcomes(col, storage), success=done).failure(
        failed
    ).run_in_background()


def export_now(ctx: AddonContext) -> None:
    """Tools → export outcomes now: the same export, then the folder path."""
    if mw is None or mw.col is None:  # pyright: ignore[reportUnnecessaryComparison]
        return
    storage = ctx.storage()

    def done(result: ExportResult) -> None:
        showInfo(
            f"Wrote {result.rows} rows to:\n{result.path}\n\nFolder: {result.folder}",
            title=TITLE,
        )

    QueryOp(parent=mw, op=lambda col: export_outcomes(col, storage), success=done).failure(
        lambda exc: showWarning(f"The export failed: {exc}", title=TITLE)
    ).run_in_background()
