from __future__ import annotations

import importlib.util
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


@pytest.fixture(scope="session")
def browser() -> Iterator[Any]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:  # no Chromium for this Playwright
            pytest.skip(f"Chromium can't start here: {exc}")
        yield b
        b.close()


@pytest.fixture
def make_page(browser: Any, tmp_path: Path) -> Iterator[Any]:
    """``make_page(night=False, with_mathjax=True)`` -> a loaded :class:`page_harness.Browser`."""
    from page_harness import Browser, shell_html

    opened: list[Any] = []

    def make(*, night: bool = False, with_mathjax: bool = True, width: int = 1000) -> Browser:
        html = tmp_path / f"page{len(opened)}.html"
        html.write_text(shell_html(with_mathjax=with_mathjax, night=night), encoding="utf-8")
        page = browser.new_page(viewport={"width": width, "height": 900})
        requests: list[str] = []
        page.on("request", lambda r: requests.append(r.url))
        page.route(
            "**/*",
            lambda route: (
                route.continue_()
                if route.request.url.startswith(("file:", "data:", "blob:"))
                else route.abort()
            ),
        )
        page.goto(html.as_uri())
        page.wait_for_function("window.mp && typeof mp.render === 'function'")
        opened.append(page)
        return Browser(page, requests)

    yield make
    for p in opened:
        p.close()


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
