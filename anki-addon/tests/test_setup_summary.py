"""The setup panel's fold summaries (pure text; the panel's tests check them live)."""

from __future__ import annotations

from datetime import date

from recalldrill import setup_summary as ss


def test_cards_summary_reads_tag_types_and_order() -> None:
    assert ss.cards_summary("Layer::3", {"suspended_new", "new"}, "Deck order", 0) == (
        "Layer 3 · new + suspended new · Deck order"
    )
    assert ss.cards_summary("", {"new"}, "Priority first", 40) == (
        "all cards · new · Priority first · max 40"
    )
    assert ss.cards_summary("rd::drill::A1", set(), "Deck order", 0).startswith(
        "rd::drill::A1 · no card types"
    )


def test_settings_summary() -> None:
    assert ss.settings_summary(5, 2, True) == "5 per batch · 2 blind typings · hold back on"
    assert ss.settings_summary(0, 1, False) == (
        "whole deck in one batch · 1 blind typing · hold back off"
    )
    assert ss.settings_summary(5, 2, None) == "5 per batch · 2 blind typings"


def test_pacing_and_scope_summaries() -> None:
    assert ss.pacing_summary(False, None, None, range(7)) == "off"
    assert ss.pacing_summary(True, date(2026, 10, 20), None, range(7)) == (
        "finish Tue Oct 20 · every day"
    )
    assert ss.days_text([0, 2, 4]) == "Mon, Wed, Fri"
    assert ss.days_text([]) == "no drill days"
    assert ss.scope_summary(True, "AP Lab::Lab 2", "") == "AP Lab::Lab 2 · whole deck"
    assert ss.scope_summary(True, "AP Lab::Lab 2", "Layer::1") == "AP Lab::Lab 2 · tag Layer 1"
    assert ss.scope_summary(False, "tag:X", "") == "search: tag:X"
