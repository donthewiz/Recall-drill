from __future__ import annotations

import json
from pathlib import Path

import pytest

from card_triage.config import Config, parse_config

ROOT = Path(__file__).resolve().parent.parent


def test_config_json_holds_the_defaults() -> None:
    raw = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    assert raw == {
        "set_aside_key": "x",
        "timer_prompt": False,
        "timer_seconds": 30,
        "again_prompt": False,
        "again_count": 2,
    }
    assert parse_config(raw) == Config()


@pytest.mark.parametrize("raw", [None, {}])
def test_missing_values_take_defaults(raw: dict[str, object] | None) -> None:
    assert parse_config(raw) == Config()


def test_wrong_types_take_defaults() -> None:
    raw = {
        "set_aside_key": 5,
        "timer_prompt": "yes",
        "timer_seconds": "30",
        "again_prompt": 1,
        "again_count": True,
    }
    assert parse_config(raw) == Config()


def test_numbers_are_clamped_and_blank_key_falls_back() -> None:
    cfg = parse_config(
        {"set_aside_key": "  ", "timer_seconds": 1, "again_count": 99, "timer_prompt": True}
    )
    assert (cfg.set_aside_key, cfg.timer_seconds, cfg.again_count, cfg.timer_prompt) == (
        "x",
        5,
        10,
        True,
    )
    assert parse_config({"timer_seconds": 9999}).timer_seconds == 600


def test_good_values_are_kept() -> None:
    cfg = parse_config(
        {"set_aside_key": "q", "timer_prompt": True, "timer_seconds": 45, "again_prompt": True,
         "again_count": 3}
    )
    assert cfg == Config("q", True, 45, True, 3)


@pytest.mark.parametrize("key", ["e", "u", "1", "@", "t", "T", "xy", "Ctrl+"])
def test_a_bad_key_in_a_hand_edited_config_falls_back(key: str) -> None:
    assert parse_config({"set_aside_key": key}).set_aside_key == "x"


def test_a_valid_other_key_is_kept() -> None:
    assert parse_config({"set_aside_key": "Ctrl+K"}).set_aside_key == "Ctrl+K"
