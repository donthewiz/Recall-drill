"""A scratch deck shaped like the anki-cards skill's: ``AP Lab::Lab 2`` with four
chapter subdecks, notes added Layer 1 of every chapter, then Layer 2, then Layer 4,
then one Layer 3 card added days later, two Image Occlusion cards, and part of
Layer 1 drilled."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from anki.cards import Card
from anki.collection import Collection
from anki_fixtures import add_io_note, add_note, deck

from recalldrill import history_store
from recalldrill.storage import Storage

# Created out of name order on purpose: alphabetical is Bones, Joints, Muscles, Nerves.
CHAPTERS = ("Muscles", "Bones", "Joints", "Nerves")


@dataclass
class Scene:
    lab: int
    chapters: dict[str, int]
    cards: dict[str, Card] = field(default_factory=dict[str, Card])
    io: list[Card] = field(default_factory=list[Card])
    drilled: list[Card] = field(default_factory=list[Card])


def build(col: Collection, st: Storage, drill_layer1: int = 2) -> Scene:
    lab = int(deck(col, "AP Lab::Lab 2"))
    chapters = {c: int(deck(col, f"AP Lab::Lab 2::{c}")) for c in CHAPTERS}
    scene = Scene(lab, chapters)

    def add(layer: int, chapter: str, n: int = 2) -> None:
        for i in range(n):
            front = f"L{layer}-{chapter}-{i}"
            note = add_note(
                col,
                "Basic",
                chapters[chapter],  # type: ignore[arg-type]
                {"Front": front, "Back": f"{front} a"},
                (f"Layer::{layer}", f"APLab::Ch_{chapter}::Topic"),
            )
            scene.cards[front] = note.cards()[0]

    for layer in (1, 2, 4):
        for chapter in CHAPTERS:
            add(layer, chapter)
    add(3, "Joints", 1)  # added days later: last in the new queue
    for chapter in ("Bones", "Bones"):
        scene.io.append(add_io_note(col, chapters[chapter]).cards()[0])  # type: ignore[arg-type]
        note = scene.io[-1].note()
        note.add_tag("Layer::1")
        col.update_note(note)

    # Part of Layer 1 drilled: handed off (they stay new under handoff B).
    first = [scene.cards[f"L1-{c}-0"] for c in CHAPTERS][:drill_layer1]
    scene.drilled = first
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    history_store.append_handoff(
        st,
        str(lab),
        {
            "type": "handoff",
            "sessionId": "s1",
            "timestamp": stamp,
            "groups": {"drilled_new": [c.id for c in first]},
            "cards": [{"cid": c.id, "nid": c.nid, "ord": 0} for c in first],
        },
    )
    return scene
