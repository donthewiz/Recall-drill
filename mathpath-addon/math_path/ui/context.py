"""What every window needs from the add-on: storage, config, open windows, the problem bank."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from aqt import mw

from ..config import Config, parse_config
from ..problem import ProblemBank
from ..storage import Storage


@dataclass
class AddonContext:
    module: str
    """The add-on's package name (``__name__`` of its root ``__init__``), for getConfig."""
    user_files: str
    windows: list[Any] = field(default_factory=list[Any])
    """Open Math Path windows, kept alive and closed with the profile."""
    bank: ProblemBank = field(default_factory=ProblemBank)
    """One problem per recipe, prepared ahead on a worker thread."""
    progress_opener: Callable[[], Any] | None = None
    """Opens the progress map (set when that window exists); the learn window's Progress button."""

    @property
    def folder(self) -> str:
        """The add-on folder name (``math_path`` or the dev junction): where ``web/`` is served."""
        return self.module.split(".")[0]

    def storage(self) -> Storage:
        return Storage(self.user_files, mw.pm.name or "")

    def config(self) -> Config:
        return parse_config(mw.addonManager.getConfig(self.module))
