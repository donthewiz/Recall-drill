from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from anki.collection import Collection


@pytest.fixture
def col(tmp_path: Path) -> Iterator[Collection]:
    """A scratch collection with FSRS on. Never a real profile."""
    c = Collection(str(tmp_path / "collection.anki2"))
    c.set_config("fsrs", True)
    try:
        yield c
    finally:
        c.close()
