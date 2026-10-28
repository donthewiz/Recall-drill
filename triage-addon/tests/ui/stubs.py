"""Stand-ins so the add-on's UI code runs without Anki's main window: ``mw`` records what the
code reads, ``CollectionOp`` runs the op at once on a scratch collection, ``tooltip`` and
``askUser`` record what they were shown."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any


class StubMw:
    def __init__(self, col: Any = None, card: Any = None, state: str = "review") -> None:
        self.col = col
        self.state = state
        self.reviewer = SimpleNamespace(card=card)
        self.addonManager = StubAddonManager()


class StubAddonManager:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config
        self.saved: list[tuple[str, dict[str, Any]]] = []
        self.config_actions: list[tuple[str, Callable[[], Any]]] = []

    def getConfig(self, module: str) -> dict[str, Any] | None:  # noqa: N802
        return self.config

    def writeConfig(self, module: str, conf: dict[str, Any]) -> None:  # noqa: N802
        self.saved.append((module, conf))
        self.config = conf

    def setConfigAction(self, module: str, fn: Callable[[], Any]) -> None:  # noqa: N802
        self.config_actions.append((module, fn))


class SyncOp:
    """``CollectionOp`` that runs now, on the stand-in ``mw``'s collection."""

    mw: StubMw

    def __init__(self, parent: object, op: Callable[[Any], Any]) -> None:
        self._op = op
        self._success: Callable[[Any], Any] | None = None

    def success(self, fn: Callable[[Any], Any] | None) -> SyncOp:
        self._success = fn
        return self

    def failure(self, fn: Callable[[Exception], Any] | None) -> SyncOp:
        return self

    def run_in_background(self) -> None:
        result = self._op(self.mw.col)
        if self._success is not None:
            self._success(result)


class Recorder:
    def __init__(self) -> None:
        self.tooltips: list[str] = []
        self.questions: list[str] = []
        self.answer = True
        self.browser_opens: list[tuple[Any, ...]] = []
