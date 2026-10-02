"""What every window needs from the add-on: storage, config, open windows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aqt import mw

from ..addon_config import AddonConfig, parse_config
from ..storage import Storage


@dataclass
class AddonContext:
    module: str
    """The add-on's package name (``__name__`` of its root ``__init__``), for getConfig."""
    user_files: str
    windows: list[Any] = field(default_factory=list[Any])
    """Open drill windows (``DrillWindow``), kept alive and closed with the profile."""
    dialogs: list[Any] = field(default_factory=list[Any])
    """Open setup panels."""

    def storage(self) -> Storage:
        return Storage(self.user_files, mw.pm.name or "")

    def config(self) -> AddonConfig:
        return parse_config(mw.addonManager.getConfig(self.module))

    def raise_window(self, key: str) -> bool:
        """Brings the open drill window for session ``key`` to the front, if
        any: two windows must never drive the same save."""
        for w in self.windows:
            if w.store.meta.key == key and not w.ctrl.finished:
                w.showNormal()
                w.raise_()
                w.activateWindow()
                return True
        return False
