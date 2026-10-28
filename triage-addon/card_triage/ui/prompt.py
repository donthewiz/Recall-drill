"""When to show the prompt bar on the reviewer page, and what its buttons do.

The controller holds the rules of *when* (one timer per card, the Again count) and talks to Anki
through four injected functions, so it runs under test without Anki's main window.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .. import bar, marker, rules
from ..config import Config


@dataclass
class _Shown:
    card_id: int
    bar_up: bool = False
    dismissed: bool = False


class PromptController:
    def __init__(
        self,
        *,
        config: Callable[[], Config],
        run_js: Callable[[str], None],
        again_count: Callable[[int], int],
        schedule: Callable[[int, Callable[[], None]], None],
        cancel: Callable[[], None],
        current_card_id: Callable[[], int | None],
        set_aside: Callable[[], None],
    ) -> None:
        self._config = config
        self._run_js = run_js
        self._again_count = again_count
        self._schedule = schedule
        self._cancel = cancel
        self._current_card_id = current_card_id
        self._set_aside = set_aside
        self._shown: _Shown | None = None

    # reviewer hooks ----------------------------------------------------------------------

    def question_shown(self, card: Any) -> None:
        """A card's question is on screen. The previous card's bar and timer are gone."""
        card_id = int(card.id)
        if self._shown is not None and self._shown.card_id == card_id:
            return  # the same card drawn again (an edit, a refresh): the clock keeps running
        self._clear()
        self._shown = _Shown(card_id)
        data = marker.parse_custom_data(card.custom_data)
        marked = data is None or marker.has_marker(data)
        if not rules.prompt_eligible(int(card.type), int(card.queue), marked):
            return
        cfg = self._config()
        if cfg.again_prompt and int(card.type) == rules.CARD_LEARNING:
            agains = self._again_count(card_id)
            if rules.again_prompt_due(int(card.type), agains, cfg.again_count):
                self._show(bar.again_text(agains), cfg)
                return
        if cfg.timer_prompt:
            self._schedule(cfg.timer_seconds, lambda: self._timer_fired(card_id))

    def card_answered(self) -> None:
        """The card was answered: nothing to offer on it any more."""
        self._clear()

    def reviewer_ended(self) -> None:
        """The reviewer is closing: stop the clock (its page is going away, nothing to hide)."""
        self._cancel()
        self._shown = None

    # the bar ------------------------------------------------------------------------------

    def command(self, cmd: str) -> None:
        """A click on the bar."""
        if cmd == bar.CMD_SET_ASIDE:
            self._set_aside()
        elif cmd == bar.CMD_KEEP_GOING:
            self._cancel()
            if self._shown is not None:
                self._shown.dismissed = True
            self._run_js(bar.hide_js())

    # internals ----------------------------------------------------------------------------

    def _timer_fired(self, card_id: int) -> None:
        shown = self._shown
        if shown is None or shown.card_id != card_id or shown.bar_up or shown.dismissed:
            return
        if self._current_card_id() != card_id:
            return
        self._show(bar.TIMER_TEXT, self._config())

    def _show(self, text: str, cfg: Config) -> None:
        assert self._shown is not None
        self._shown.bar_up = True
        self._run_js(bar.show_js(text, cfg.set_aside_key))

    def _clear(self) -> None:
        self._cancel()
        self._run_js(bar.hide_js())
        self._shown = None
