"""The Tools → Card Triage menu and the reviewer hooks."""

from __future__ import annotations

from aqt import mw


def register(module: str) -> None:
    """Called once from the add-on's ``__init__``."""
    # aqt.mw is typed AnkiQt but is None until Anki's main window exists (and under pytest).
    if mw is None:  # pyright: ignore[reportUnnecessaryComparison]
        return
