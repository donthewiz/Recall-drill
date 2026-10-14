"""layers.py: the skill's ``Layer::N`` tag."""

from __future__ import annotations

import pytest

from recalldrill.layers import NO_LAYER_RANK, layer_of, layer_rank


@pytest.mark.parametrize(
    ("tags", "want"),
    [
        ((), None),
        (("APLab::Ch7::LongBone",), None),
        (("Layer::1",), 1),
        (("layer::3",), 3),
        (("LAYER::2", "x"), 2),
        (("Layer::4", "Layer::2", "Layer::3"), 2),  # several: the lowest
        (("Layer::0",), None),  # not a positive integer
        (("Layer::x",), None),
        (("Layer::",), None),
        (("Layer",), None),
        (("Layer::1::sub",), None),  # only the exact two-part tag
        (("MyLayer::1",), None),
        (("Layer::0", "Layer::5"), 5),
        (("Layer::10", "Layer::9"), 9),  # numeric, not alphabetical
    ],
)
def test_layer_of(tags: tuple[str, ...], want: int | None) -> None:
    assert layer_of(tags) == want


def test_no_layer_sorts_after_every_layer() -> None:
    assert layer_rank(()) == NO_LAYER_RANK > layer_rank(("Layer::999",))
    assert layer_rank(("Layer::1",)) < layer_rank(("Layer::2",))
