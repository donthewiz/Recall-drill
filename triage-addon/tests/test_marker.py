from __future__ import annotations

import json

import pytest

from card_triage import marker


@pytest.mark.parametrize("raw", ["", "  ", "{}"])
def test_empty_custom_data_has_no_keys(raw: str) -> None:
    assert marker.parse_custom_data(raw) == {}


@pytest.mark.parametrize("raw", ["[1]", "not json", "3", "null"])
def test_custom_data_that_is_not_an_object_is_unreadable(raw: str) -> None:
    assert marker.parse_custom_data(raw) is None


def test_marker_is_added_and_other_keys_kept() -> None:
    out = marker.with_marker({"a": 1}, 2)
    assert out is not None
    assert json.loads(out) == {"a": 1, "tri": 2}
    assert " " not in out  # compact, like Anki writes it


def test_marker_is_removed_and_other_keys_kept() -> None:
    assert json.loads(marker.without_marker({"a": 1, "tri": 2})) == {"a": 1}
    assert marker.without_marker({"tri": 0}) == ""


def test_saved_flag_reads_0_to_7_only() -> None:
    assert [marker.saved_flag({"tri": v}) for v in (0, 1, 7)] == [0, 1, 7]
    assert [marker.saved_flag({"tri": v}) for v in (8, -1, "2", True, None)] == [0] * 5
    assert marker.saved_flag({}) == 0
    assert marker.has_marker({"tri": 0}) and not marker.has_marker({"a": 1})


def test_over_100_bytes_or_a_key_over_8_bytes_is_refused() -> None:
    assert marker.with_marker({"a": "x" * 70}, 0) is not None
    assert marker.with_marker({"a": "x" * 90}, 0) is None
    assert marker.with_marker({"123456789": 1}, 0) is None
    assert marker.with_marker({"12345678": 1}, 0) is not None
    assert marker.with_marker({"é": "é" * 45}, 0) is None  # bytes, not characters
