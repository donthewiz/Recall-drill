from __future__ import annotations

import re

import pytest

from card_triage import bar


def test_texts() -> None:
    assert bar.TIMER_TEXT == "Stuck on this one?"
    assert bar.again_text(2) == "2 Agains on this card."
    assert bar.again_text(1) == "1 Again on this card."
    assert bar.again_text(5) == "5 Agains on this card."


def test_only_the_prefix_is_ours() -> None:
    assert bar.is_ours("card_triage:set_aside")
    assert bar.is_ours(bar.CMD_KEEP_GOING)
    for other in ("mathpath:open", "mp:field:3", "ans", "", "card_triage", "xcard_triage:y"):
        assert not bar.is_ours(other)


@pytest.mark.parametrize(("key", "label"), [("x", "X"), ("X", "X"), ("Ctrl+T", "Ctrl+T")])
def test_key_label(key: str, label: str) -> None:
    assert bar.key_label(key) == label


def test_show_js_carries_the_wording_and_hide_js_removes_both_elements() -> None:
    js = bar.show_js(bar.TIMER_TEXT, "x")
    for part in ("Stuck on this one?", "Set aside (X)", "Keep going", bar.CMD_SET_ASIDE):
        assert part in js
    hide = bar.hide_js()
    assert bar.BAR_ID in hide and bar.STYLE_ID in hide


def test_every_css_rule_is_scoped_to_the_bar() -> None:
    """Nothing of Anki's page is restyled: each selector in the injected CSS ends in the bar's id
    (or starts with a night-mode class followed by it)."""
    css = bar._CSS  # pyright: ignore[reportPrivateUsage]
    selectors = [s.strip() for block in re.findall(r"([^{}]+)\{", css) for s in block.split(",")]
    assert selectors
    for sel in selectors:
        assert f"#{bar.BAR_ID}" in sel, sel
        assert not re.match(r"^(body|html|\*|\.card|#qa)\b", sel), sel
