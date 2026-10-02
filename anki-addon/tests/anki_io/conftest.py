from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from anki.collection import Collection

# Make tests/anki_io/anki_fixtures.py importable (pytest runs with
# --import-mode=importlib, which doesn't put test directories on sys.path).
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


@pytest.fixture
def col(tmp_path: Path) -> Iterator[Collection]:
    """A scratch collection with FSRS on. Never a real profile."""
    c = Collection(str(tmp_path / "collection.anki2"))
    c.set_config("fsrs", True)
    try:
        yield c
    finally:
        c.close()
