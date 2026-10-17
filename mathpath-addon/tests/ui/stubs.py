"""Stand-ins so Math Path's windows run offscreen (QtWebEngine can't start on Qt's offscreen
platform, so the web view records what the window sends it; ``mw`` is a stub with what the windows
read). Everything else is real: the controllers, the commands, the Anki I/O on a scratch collection.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aqt.qt import QWidget


class FakeWeb(QWidget):
    """Records ``stdHtml`` and every ``eval``; ``bridge`` is the window's ``pycmd`` handler."""

    def __init__(self, parent: QWidget | None = None, title: str = "") -> None:
        super().__init__(parent)
        self.evals: list[str] = []
        self.shell = ""
        self.html_args: dict[str, Any] = {}
        self.bridge: Callable[[str], Any] = lambda _c: None

    def set_bridge_command(self, fn: Callable[[str], Any], context: object) -> None:
        self.bridge = fn

    def stdHtml(self, body: str, **kw: Any) -> None:  # noqa: N802
        self.shell = body
        self.html_args = kw

    def eval(self, js: str) -> None:
        self.evals.append(js)

    def cleanup(self) -> None:
        pass

    def last_render(self) -> dict[str, Any]:
        """The newest ``mp.render({...})`` payload."""
        import json

        for js in reversed(self.evals):
            if js.startswith("mp.render("):
                return json.loads(js[len("mp.render(") : -2])
        raise AssertionError("nothing was rendered")


class PM:
    name = "test"

    def __init__(self) -> None:
        self.profile: dict[str, object] = {}


class AddonManager:
    def __init__(self) -> None:
        self.exports: list[tuple[str, str]] = []

    def setWebExports(self, module: str, pattern: str) -> None:  # noqa: N802
        self.exports.append((module, pattern))

    def getConfig(self, module: str) -> dict[str, Any]:  # noqa: N802
        return {}


class StubMw:
    def __init__(self, col: Any = None) -> None:
        self.col = col
        self.pm = PM()
        self.addonManager = AddonManager()
        self.state = "deckBrowser"
        self.reviewer: Any = None

    def geometry(self) -> object:
        from aqt.qt import QRect

        return QRect(50, 50, 900, 700)


class SyncQueryOp:
    """``QueryOp`` that runs at once on the stub's collection."""

    col: Any = None

    def __init__(self, parent: object, op: Callable[[Any], Any], success: Callable[[Any], None]):
        self.op, self.on_success = op, success
        self.on_failure: Callable[[Exception], None] | None = None

    def failure(self, fn: Callable[[Exception], None]) -> SyncQueryOp:
        self.on_failure = fn
        return self

    def with_progress(self, *_a: object, **_k: object) -> SyncQueryOp:
        return self

    def run_in_background(self) -> None:
        try:
            result = self.op(SyncQueryOp.col)
        except Exception as exc:  # noqa: BLE001
            if self.on_failure is None:
                raise
            self.on_failure(exc)
            return
        self.on_success(result)


class SyncCollectionOp:
    """``CollectionOp`` that runs at once on the stub's collection."""

    col: Any = None

    def __init__(self, parent: object, op: Callable[[Any], Any]):
        self.op = op
        self.on_success: Callable[[Any], None] | None = None
        self.on_failure: Callable[[Exception], None] | None = None

    def success(self, fn: Callable[[Any], None]) -> SyncCollectionOp:
        self.on_success = fn
        return self

    def failure(self, fn: Callable[[Exception], None]) -> SyncCollectionOp:
        self.on_failure = fn
        return self

    def run_in_background(self, initiator: object = None) -> None:
        try:
            result = self.op(SyncCollectionOp.col)
        except Exception as exc:  # noqa: BLE001
            if self.on_failure is None:
                raise
            self.on_failure(exc)
            return
        if self.on_success is not None:
            self.on_success(result)
