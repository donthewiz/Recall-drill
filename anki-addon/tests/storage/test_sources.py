"""sources.py: SourceRef's JSON round trip (session saves keep the sources)."""

from __future__ import annotations

import json

import pytest
from controller_support import source

from recalldrill.sources import source_from_json, source_to_json


def test_round_trip_through_json() -> None:
    s = source(3, hint=" (-a___)", colliding_answers=("arteries", "vein"), has_audio=True)
    d = json.loads(json.dumps(source_to_json(s)))
    assert d["colliding_answers"] == ["arteries", "vein"]
    assert source_from_json(d) == s


def test_older_saves_and_unknown_keys() -> None:
    d = source_to_json(source(0))
    del d["hint"], d["colliding_answers"]
    d["future_field"] = 1
    assert source_from_json(d) == source(0)


def test_bad_sources_raise() -> None:
    d = source_to_json(source(0))
    with pytest.raises(ValueError, match="card class"):
        source_from_json({**d, "card_class": "nope"})
    del d["cid"]
    with pytest.raises(TypeError):
        source_from_json(d)
