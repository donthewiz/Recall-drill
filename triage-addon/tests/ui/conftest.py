from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from typing import Any

import pytest


@pytest.fixture(scope="session")
def qt_app() -> object:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from aqt.qt import QApplication
    except ImportError as exc:  # no Qt platform plugin / display
        pytest.skip(f"Qt can't start here: {exc}")
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _application_style_is_untouched() -> Iterator[Any]:
    """No window of ours may style the application: Anki's own windows keep their look."""
    if importlib.util.find_spec("aqt") is None:
        yield
        return
    from aqt.qt import QApplication

    def sheet() -> str:
        app = QApplication.instance()
        return app.styleSheet() if isinstance(app, QApplication) else ""

    before = sheet()
    yield
    assert sheet() == before
