"""Load the page Math Path's windows show into real Chromium (Playwright), the way Anki's web view
would, and draw a view into it.

QtWebEngine can't start on Qt's offscreen platform, so the page the window loads
(``pages.shell_body`` plus ``web/mp_page.css``, MathLive, ``mp_page.js`` and Anki's own MathJax) is
loaded here from ``file://`` URLs, with ``pycmd`` stubbed to record what the window would be sent.
Anki's MathJax comes from the ``_aqt`` package (installed with ``aqt``); without it the page falls
back to MathLive's own renderer, which is also checked.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from math_path import pages

needs_playwright = pytest.mark.skipif(
    importlib.util.find_spec("playwright") is None, reason="Playwright isn't installed"
)

WEB = Path(__file__).resolve().parents[2] / "web"


def mathjax_dir() -> Path | None:
    spec = importlib.util.find_spec("_aqt")
    if spec is None or not spec.submodule_search_locations:
        return None
    path = (
        Path(next(iter(spec.submodule_search_locations)))
        / "data"
        / "web"
        / "js"
        / "vendor"
        / "mathjax"
    )
    return path if (path / "tex-chtml-full.js").is_file() else None


def shell_html(*, with_mathjax: bool = True, night: bool = False) -> str:
    mj = mathjax_dir() if with_mathjax else None
    mathjax = ""
    if mj is not None:
        config = {
            "tex": {"displayMath": [["\\[", "\\]"]], "processEscapes": False},
            "loader": {"paths": {"mathjax": mj.as_uri()}},
            "startup": {"typeset": False},
        }
        mathjax = (
            f"<script>window.MathJax = {json.dumps(config)};</script>"
            f'<script src="{(mj / "tex-chtml-full.js").as_uri()}"></script>'
        )
    cls = ' class="night-mode"' if night else ""
    return f"""<!doctype html><html{cls}><head><meta charset="utf-8">
<link rel="stylesheet" href="{(WEB / "mp_page.css").as_uri()}">
<script>window.__cmds = []; window.pycmd = function (c) {{ window.__cmds.push(c); }};</script>
{mathjax}
<script src="{(WEB / "mathlive" / "mathlive.min.js").as_uri()}"></script>
<script src="{(WEB / "mp_page.js").as_uri()}"></script>
</head><body>{pages.shell_body()}</body></html>"""


class Browser:
    """One loaded page."""

    def __init__(self, page: Any, requests: list[str]) -> None:
        self.page = page
        self.requests = requests

    def draw(self, view: pages.PageView) -> None:
        self.page.evaluate(pages.render_call(view).rstrip(";"))
        self.page.wait_for_timeout(50)

    def settle(self) -> None:
        """Wait until MathJax (or the fallback) has typeset the page."""
        self.page.evaluate(
            """() => {
                if (!(window.MathJax && MathJax.typesetPromise)) { return null; }
                const root = document.getElementById('mp-root');
                return MathJax.startup.promise.then(() => MathJax.typesetPromise([root]));
            }"""
        )
        self.page.wait_for_timeout(120)

    def cmds(self) -> list[str]:
        return list(self.page.evaluate("window.__cmds"))

    def clear_cmds(self) -> None:
        self.page.evaluate("window.__cmds.length = 0")

    def screenshot(self, path: Path, width: int = 1000, height: int = 1100) -> None:
        self.page.set_viewport_size({"width": width, "height": height})
        self.page.wait_for_timeout(80)
        self.page.screenshot(path=str(path), full_page=True)

    def text(self, selector: str = "#mp-root") -> str:
        """The text on screen with its capitals as written (labels are shown in capitals by CSS)."""
        return str(self.page.text_content(selector) or "")
