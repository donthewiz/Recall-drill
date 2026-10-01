"""Port of the renderFirstLetterCue cases in src/test/c5.spec.ts. The selectTrial
and applyAnswer cases are Phase 1b. One test per TS `it(...)`; the TS name is in
each docstring.
"""

from __future__ import annotations

from recalldrill.engine.items import render_first_letter_cue


def test_first_character_of_each_word() -> None:
    """TS: renderFirstLetterCue > keeps the first character of each word and underscores
    the rest, preserving word count"""
    assert render_first_letter_cue("The heart pumps blood") == "T__ h____ p____ b____"


def test_punctuation_stays_in_place() -> None:
    """TS: renderFirstLetterCue > leaves punctuation visible in place, only underscoring
    letters/digits"""
    assert render_first_letter_cue("blood.") == "b____."


def test_one_character_words_unchanged() -> None:
    """TS: renderFirstLetterCue > leaves a one-character word as-is"""
    assert render_first_letter_cue("a b c") == "a b c"


def test_preserves_case() -> None:
    """TS: renderFirstLetterCue > preserves the first character's original case"""
    assert render_first_letter_cue("Recall Drill") == "R_____ D____"


def test_reveals_each_run_after_punctuation() -> None:
    """TS: renderFirstLetterCue > reveals the first alphanumeric character of each run,
    even mid-word after punctuation"""
    assert render_first_letter_cue("don't stop") == "d__'t s___"


def test_medical_word_parts() -> None:
    """TS: renderFirstLetterCue > reveals the first alphanumeric of each run for medical
    word parts led/trailed by punctuation"""
    assert render_first_letter_cue("-itis") == "-i___"
    assert render_first_letter_cue("-emia") == "-e___"
    assert render_first_letter_cue("brady-") == "b____-"
    assert render_first_letter_cue("cardi/o") == "c____/o"


def test_single_character_after_punctuation() -> None:
    """TS: renderFirstLetterCue > degenerate case: a single alphanumeric character after
    punctuation is left fully revealed"""
    assert render_first_letter_cue("-a") == "-a"
