"""Dev preview: selection + build on one deck, as an HTML report.

Temporary (Phase 2, for Don's manual check). The Phase 3b panel replaces it.
No Qt here; ``ui/preview.py`` shows the HTML in a dialog.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from html import escape

from anki.collection import Collection

from .. import deck_settings
from ..deck_settings import DeckSettings, SettingsSource
from ..prompts import parse_hint_overrides
from ..storage import HINTS, Storage
from .build import BuildResult, build_session
from .cards import CARD_CLASSES, DEFAULT_ENABLED, NoteCache
from .notetypes import MappingTable, load_overrides
from .select import INELIGIBLE_REASONS, Scope, Selection, SelectOptions, select_cards

PREVIEW_ITEMS = 40
_EXTRA_CHARS = 160


@dataclass
class Preview:
    deck_name: str
    selection: Selection
    build: BuildResult
    settings: DeckSettings
    settings_source: SettingsSource
    seconds: float


def build_preview(col: Collection, storage: Storage, did: int) -> Preview:
    started = time.perf_counter()
    table = MappingTable(col, load_overrides(storage))
    saved = deck_settings.get_saved(storage, did)
    options = SelectOptions(card_ords=deck_settings.card_ords_option(saved))
    notes = NoteCache(col)
    scope = Scope(deck_id=did)
    selection = select_cards(col, scope, options, table, notes)
    settings, source = deck_settings.effective(saved, [c.answer for c in selection.picked])
    hints = parse_hint_overrides(storage.read_json(HINTS, {}))
    result = build_session(col, selection, settings, table, hints, notes)
    name = scope.deck_name(col) or ""
    return Preview(name, selection, result, settings, source, time.perf_counter() - started)


def _table(header: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{escape(h)}</th>" for h in header)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table border=1 cellspacing=0 cellpadding=3><tr>{head}</tr>{body}</table>"


def _short(text: str, n: int = _EXTRA_CHARS) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def preview_html(p: Preview, max_items: int = PREVIEW_ITEMS) -> str:
    sel, res = p.selection, p.build
    parts: list[str] = [
        f"<h2>{escape(p.deck_name)}</h2>",
        f"<p>{sel.total} cards in scope; {len(sel.picked)} picked; "
        f"{len(res.deck_items)} items built ({p.seconds:.1f} s).</p>",
    ]

    rows = [
        [
            escape(c) + ("" if c in DEFAULT_ENABLED else " <i>(off)</i>"),
            str(sel.eligible_counts[c]),
            str(sel.picked_counts[c]),
        ]
        for c in CARD_CLASSES
        if sel.eligible_counts[c] or sel.picked_counts[c] or c in DEFAULT_ENABLED
    ]
    parts += ["<h3>Classes</h3>", _table(["class", "eligible", "picked"], rows)]

    rows = [[escape(r), str(sel.ineligible[r])] for r in INELIGIBLE_REASONS]
    parts += ["<h3>Ineligible</h3>", _table(["reason", "cards"], rows)]
    extras: list[str] = []
    if sel.template_excluded:
        extras.append(f"{sel.template_excluded} cards left out by the template filter.")
    if res.empty_answers:
        extras.append(f"{res.empty_answers} picked cards dropped at build: empty answer.")
    if sel.sibling_cards:
        extras.append(
            f"<b>Siblings:</b> {sel.sibling_cards} picked cards share a note with another "
            f"picked card ({sel.sibling_notes} notes)."
        )
    if extras:
        parts.append("<p>" + "<br>".join(extras) + "</p>")

    rows = [
        [
            escape(m.notetype_name),
            f"{escape(m.template_name)} ({m.template_ord})",
            escape(m.kind),
            escape(m.answer_field or "—"),
            escape(m.extra_field or "—"),
            escape(("override: " if m.overridden else "") + m.why),
        ]
        for m in sel.mappings.values()
    ]
    parts += [
        "<h3>Mapping per note type and template</h3>",
        _table(["note type", "template", "kind", "answer", "extra", "why"], rows),
    ]

    s = p.settings
    shown = ", ".join(f"{k}={v}" for k, v in s.items() if k != "card_ords") or "(none)"
    parts.append(
        f"<h3>Settings</h3><p>{escape(p.settings_source)}: {escape(shown)}; "
        f"hints {'on' if res.hints_on else 'off'}"
        + (f" (conflict pool {res.hint_pool} cards)" if res.hints_on else "")
        + ".</p>"
    )

    rows = [
        [
            escape(src.card_class),
            escape(item["front"]),
            escape(item["back"]),
            escape(_short(item.get("extra", ""))),
        ]
        for item, src in list(zip(res.deck_items, res.sources, strict=True))[:max_items]
    ]
    parts += [
        f"<h3>First {min(max_items, len(res.deck_items))} items</h3>",
        _table(["class", "front", "back", "extra"], rows),
    ]

    if res.flagged_hints:
        rows = [
            [escape(f.key), escape(f.meaning), escape(f.term), escape(", ".join(f.conflicts))]
            for f in res.flagged_hints
        ]
        parts += [
            "<h3>Flagged hints (need a manual hint)</h3>",
            _table(["nid:ord", "meaning", "term", "conflicts with"], rows),
        ]
    elif res.hints_on:
        parts.append("<p>No flagged hints.</p>")
    return "\n".join(parts)
