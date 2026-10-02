"""Note type kinds and which fields a card is drilled on.

Three kinds, checked in this order (Phase 0 facts, docs/DECISIONS.md):

1. ``image_occlusion``: ``originalStockKind`` is
   ``StockNotetype.OriginalStockKind.ORIGINAL_STOCK_KIND_IMAGE_OCCLUSION`` (6;
   never ``StockNotetype.Kind.KIND_IMAGE_OCCLUSION``, which is 5 = cloze).
   Ineligible: there is nothing to type.
2. ``cloze``: ``model["type"] == 1`` and not IO (stock IO is also type 1). A
   single note whose cloze field holds ``image-occlusion:`` is ineligible on its
   own (:func:`is_io_note`); the rest of the type is drilled.
3. ``standard``: everything else, whatever the name. The anki-cards
   "Image Occlusion (anki-medical-cards)" lookalike is a standard type with a
   typeable label, so it goes through the mapping like any other.

The front is never mapped: it is always Anki's own render of the question
(``card.render_output(reload=True).question_text``). A mapping only names the
answer field and the Extra field.

Default mapping for a standard template (pure parts: :func:`field_refs`,
:func:`answer_candidates`):

- ``{{type:F}}`` in the front template: the answer is F.
- Otherwise the candidates are the fields the answer side shows after
  ``<hr id=answer>`` (or all of it) that the front doesn't, in template order,
  minus reference fields (:data:`REFERENCE_FIELDS`) and names that look like
  media. If none is left there, the fields *before* the rule that the front
  doesn't show. The first candidate with a non-empty answer in at least half
  of up to 50 sampled notes wins.
- The answer is the delta: when the answer field's text starts with the text
  of the fields the front shows (an Answer that repeats the Question and then
  adds the label), only the rest is graded (:func:`strip_front`).
- Extra: the first of ``Extra``, ``Back Extra``, ``Notes``, ``Remarks`` that
  exists, isn't the answer, and has content in a sampled note.

Cloze: the answer is ``extract_cloze_for_typing(field, card.ord + 1)`` on the
first ``{{cloze:F}}`` field of the front template; Extra is ``Extra`` or
``Back Extra``. Never ``FullContext`` or ``Source``, which are reference
fields. Known limitation: a note type with several cloze fields is drilled on
the first one only.

Overrides from ``mappings.json`` (note type id, then template ord) win over the
defaults. A cloze note type has one template, so its key is ord 0 for every
cloze number.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from anki.collection import Collection
from anki.consts import MODEL_CLOZE
from anki.models import NotetypeDict, NotetypeId, StockNotetype
from anki.notes import Note

from ..engine.jscompat import js_trim
from ..storage import MAPPINGS, Storage
from .text import grading_text, tidy

log = logging.getLogger(__name__)

NoteKind = Literal["standard", "cloze", "image_occlusion"]

IO_ORIGINAL_STOCK_KIND = int(StockNotetype.OriginalStockKind.ORIGINAL_STOCK_KIND_IMAGE_OCCLUSION)
IO_MARKER = "image-occlusion:"

SAMPLE_SIZE = 50
FILLED_SHARE = 0.5

STANDARD_EXTRA_NAMES = ("Extra", "Back Extra", "Notes", "Remarks")
CLOZE_EXTRA_NAMES = ("Extra", "Back Extra")
REFERENCE_FIELDS = (
    "Extra",
    "Back Extra",
    "Notes",
    "Remarks",
    "FullContext",
    "Source",
    "Sources",
    "Comments",
    "Header",
    "Footer",
)
"""Never an answer: shown next to it for reference."""

_MEDIA_NAME_RE = re.compile(r"audio|sound|image|picture|photo|mask", re.IGNORECASE)
_REF_RE = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)
_ANSWER_HR_RE = re.compile(r"<hr\b[^>]*\bid\s*=\s*[\"']?answer\b[^>]*>", re.IGNORECASE)
_FIELD_KEY_RE = re.compile(r"[\s_-]+")


# ---------------------------------------------------------------------------
# Pure: template parsing and kind
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldRef:
    """One ``{{filter:...:Field}}`` reference in a card template."""

    field: str
    filters: tuple[str, ...] = ()

    @property
    def is_type(self) -> bool:
        return bool(self.filters) and self.filters[0] == "type"

    @property
    def is_cloze(self) -> bool:
        return "cloze" in self.filters

    @property
    def is_tts(self) -> bool:
        return any(f.split(" ")[0] == "tts" for f in self.filters)


def field_refs(template: str) -> list[FieldRef]:
    """Field references in template order. ``{{#F}}``/``{{^F}}``/``{{/F}}``
    (conditionals) and ``{{FrontSide}}`` are skipped. The last
    ``:``-separated segment is the field name; the rest are filters."""
    refs: list[FieldRef] = []
    for m in _REF_RE.finditer(template):
        inner = m.group(1).strip()
        if not inner or inner[0] in "#^/!=":
            continue
        *filters, name = (part.strip() for part in inner.split(":"))
        if name == "FrontSide":
            continue
        refs.append(FieldRef(name, tuple(filters)))
    return refs


def split_answer_template(afmt: str) -> tuple[str, str]:
    """(before, after) ``<hr id=answer>``; without the rule, ``("", afmt)``."""
    m = _ANSWER_HR_RE.search(afmt)
    return (afmt[: m.start()], afmt[m.end() :]) if m else ("", afmt)


def answer_section(afmt: str) -> str:
    """The part of the answer template after ``<hr id=answer>``, or all of it."""
    return split_answer_template(afmt)[1]


def looks_like_media(field_name: str) -> bool:
    return _MEDIA_NAME_RE.search(field_name) is not None


def _field_key(name: str) -> str:
    return _FIELD_KEY_RE.sub("", name).casefold()


_REFERENCE_KEYS = frozenset(_field_key(n) for n in REFERENCE_FIELDS)


def is_reference_field(field_name: str) -> bool:
    """Extra, Notes, FullContext, Source, ... (case, spaces and ``_`` ignored)."""
    return _field_key(field_name) in _REFERENCE_KEYS


def field_names(model: Mapping[str, Any]) -> list[str]:
    return [str(f["name"]) for f in model["flds"]]


def type_in_field(model: Mapping[str, Any], tmpl: Mapping[str, Any]) -> str | None:
    """F from the front template's first ``{{type:F}}`` (not ``type:cloze``)."""
    names = set(field_names(model))
    for ref in field_refs(str(tmpl["qfmt"])):
        if ref.is_type and not ref.is_cloze and ref.field in names:
            return ref.field
    return None


def _candidates_in(section: str, names: set[str], front: set[str]) -> list[str]:
    out: list[str] = []
    for ref in field_refs(section):
        f = ref.field
        if (
            f not in names
            or f in front
            or f in out
            or ref.is_tts
            or looks_like_media(f)
            or is_reference_field(f)
        ):
            continue
        out.append(f)
    return out


def answer_candidates_in_section(
    model: Mapping[str, Any], tmpl: Mapping[str, Any]
) -> tuple[list[str], bool]:
    """(candidates, came from after ``<hr id=answer>``). See :func:`answer_candidates`."""
    names = set(field_names(model))
    front = {ref.field for ref in field_refs(str(tmpl["qfmt"]))}
    before, after = split_answer_template(str(tmpl["afmt"]))
    found = _candidates_in(after, names, front)
    if found:
        return found, True
    return _candidates_in(before, names, front), False


def answer_candidates(model: Mapping[str, Any], tmpl: Mapping[str, Any]) -> list[str]:
    """Fields the answer side shows and the front doesn't, in template order,
    minus reference fields, media-looking names and TTS-only references. After
    ``<hr id=answer>`` first; if nothing is left there, before it."""
    return answer_candidates_in_section(model, tmpl)[0]


def front_fields(model: Mapping[str, Any], tmpl: Mapping[str, Any], answer: str) -> list[str]:
    """Fields whose text the front shows, in template order: the prefix an
    answer field may repeat. ``{{type:}}`` and TTS references show no text."""
    names = set(field_names(model))
    out: list[str] = []
    for ref in field_refs(str(tmpl["qfmt"])):
        f = ref.field
        if f in names and f != answer and f not in out and not ref.is_type and not ref.is_tts:
            out.append(f)
    return out


def strip_front(answer: str, front: str) -> str:
    """``answer`` minus a leading copy of ``front`` (both grading text).

    An answer that repeats the question and adds the label grades as the label.
    A match that ends mid-word is not a copy ("pain" is not stripped from
    "painful")."""
    if not front or not answer.startswith(front):
        return answer
    rest = answer[len(front) :]
    if rest and front[-1].isalnum() and rest[0].isalnum():
        return answer
    return js_trim(rest)


def cloze_field(model: Mapping[str, Any]) -> str | None:
    """The field of the first ``{{cloze:F}}`` (or ``{{type:cloze:F}}``) on the
    front template, falling back to the back template."""
    names = set(field_names(model))
    tmpl = model["tmpls"][0]
    for side in ("qfmt", "afmt"):
        for ref in field_refs(str(tmpl[side])):
            if ref.is_cloze and ref.field in names:
                return ref.field
    return None


def first_named(names: Sequence[str], wanted: Iterable[str], exclude: str | None) -> str | None:
    """The first of ``wanted`` (case-insensitive) that is a field, other than ``exclude``."""
    by_fold = {n.casefold(): n for n in reversed(names)}
    for w in wanted:
        hit = by_fold.get(w.casefold())
        if hit is not None and hit != exclude:
            return hit
    return None


def kind_of(model: Mapping[str, Any]) -> NoteKind:
    """The note type's kind. The name plays no part."""
    if model.get("originalStockKind") == IO_ORIGINAL_STOCK_KIND:
        return "image_occlusion"
    if model.get("type") == MODEL_CLOZE:
        return "cloze"
    return "standard"


def has_content(html: str) -> bool:
    """Text or an image, for "does this field hold anything" checks."""
    return bool(grading_text(html)) or "<img" in html.lower()


# ---------------------------------------------------------------------------
# Overrides (mappings.json)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MappingOverride:
    """A stored mapping. ``answer_field`` None keeps the default answer field;
    ``extra_field`` None means no Extra."""

    answer_field: str | None
    extra_field: str | None
    ineligible: bool
    notetype_name: str = ""
    template_name: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "answer_field": self.answer_field,
            "extra_field": self.extra_field,
            "ineligible": self.ineligible,
            "notetype_name": self.notetype_name,
            "template_name": self.template_name,
        }


MappingKey = tuple[int, int]
"""(note type id, template ord)."""


def _opt_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def parse_overrides(data: object) -> dict[MappingKey, MappingOverride]:
    """mappings.json ``data`` -> overrides. Bad entries are skipped and logged."""
    out: dict[MappingKey, MappingOverride] = {}
    if not isinstance(data, dict):
        if data is not None:
            log.warning("Recall Drill: mappings.json data is not an object; ignored")
        return out
    for ntid_key, per_ord in cast(dict[object, object], data).items():
        if not isinstance(per_ord, dict):
            log.warning("Recall Drill: mappings.json entry %r ignored", ntid_key)
            continue
        for ord_key, raw in cast(dict[object, object], per_ord).items():
            try:
                key = (int(str(ntid_key)), int(str(ord_key)))
            except ValueError:
                log.warning("Recall Drill: mappings.json key %r/%r ignored", ntid_key, ord_key)
                continue
            if not isinstance(raw, dict):
                log.warning("Recall Drill: mappings.json entry %r/%r ignored", ntid_key, ord_key)
                continue
            entry = {str(k): v for k, v in cast(dict[object, object], raw).items()}
            out[key] = MappingOverride(
                answer_field=_opt_str(entry.get("answer_field")),
                extra_field=_opt_str(entry.get("extra_field")),
                ineligible=entry.get("ineligible") is True,
                notetype_name=str(entry.get("notetype_name") or ""),
                template_name=str(entry.get("template_name") or ""),
            )
    return out


def overrides_to_json(overrides: Mapping[MappingKey, MappingOverride]) -> dict[str, Any]:
    out: dict[str, dict[str, Any]] = {}
    for (ntid, ord_), o in sorted(overrides.items()):
        out.setdefault(str(ntid), {})[str(ord_)] = o.to_json()
    return out


def load_overrides(storage: Storage) -> dict[MappingKey, MappingOverride]:
    return parse_overrides(storage.read_json(MAPPINGS, {}))


def save_override(storage: Storage, ntid: int, template_ord: int, o: MappingOverride) -> None:
    overrides = load_overrides(storage)
    overrides[(ntid, template_ord)] = o
    storage.write_json(MAPPINGS, overrides_to_json(overrides))


# ---------------------------------------------------------------------------
# Resolved mappings (need the collection for sampling)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NoteMapping:
    """Where one (note type, template)'s answer and Extra come from."""

    ntid: int
    template_ord: int
    kind: NoteKind
    notetype_name: str
    template_name: str
    answer_field: str | None
    """The answer field; for a cloze kind, the cloze field. None = unmapped."""
    extra_field: str | None
    ineligible: bool
    """Image Occlusion, or marked ineligible by an override."""
    overridden: bool
    why: str
    """One line for the preview / settings panel."""
    candidates: tuple[str, ...] = ()
    front_fields: tuple[str, ...] = ()
    """Standard kind: the fields the front shows, whose text is stripped from
    the start of the answer (:func:`strip_front`)."""


def template_ord_for(model: Mapping[str, Any], card_ord: int) -> int:
    """The template a card comes from: ``card.ord``, or 0 for cloze-type note types."""
    return 0 if model.get("type") == MODEL_CLOZE else card_ord


def sample_nids[T: int](nids: Sequence[T], limit: int = SAMPLE_SIZE) -> list[T]:
    """Up to ``limit`` note ids, evenly spread over the sorted list (deterministic)."""
    ordered = sorted(nids)
    if len(ordered) <= limit:
        return ordered
    step = len(ordered) / limit
    return [ordered[int(i * step)] for i in range(limit)]


class MappingTable:
    """Resolves (note type, template) mappings: stored override, else default.

    Caches per note type, so one instance should live for one selection/build.
    """

    def __init__(
        self, col: Collection, overrides: Mapping[MappingKey, MappingOverride] | None = None
    ) -> None:
        self.col = col
        self.overrides: dict[MappingKey, MappingOverride] = dict(overrides or {})
        self._models: dict[int, NotetypeDict] = {}
        self._samples: dict[int, list[Note]] = {}
        self._kinds: dict[int, NoteKind] = {}
        self._resolved: dict[MappingKey, NoteMapping] = {}
        self._defaults: dict[MappingKey, NoteMapping] = {}

    def model(self, ntid: int) -> NotetypeDict:
        m = self._models.get(ntid)
        if m is None:
            m = self.col.models.get(NotetypeId(ntid))
            if m is None:
                raise KeyError(f"note type {ntid} not found")
            self._models[ntid] = m
        return m

    def samples(self, ntid: int) -> list[Note]:
        s = self._samples.get(ntid)
        if s is None:
            nids = sample_nids(self.col.models.nids(NotetypeId(ntid)))
            s = [self.col.get_note(nid) for nid in nids]
            self._samples[ntid] = s
        return s

    def default_kind(self, ntid: int) -> NoteKind:
        k = self._kinds.get(ntid)
        if k is None:
            k = kind_of(self.model(ntid))
            self._kinds[ntid] = k
        return k

    def for_card(self, ntid: int, card_ord: int) -> NoteMapping:
        return self.get(ntid, template_ord_for(self.model(ntid), card_ord))

    def get(self, ntid: int, template_ord: int) -> NoteMapping:
        key = (ntid, template_ord)
        hit = self._resolved.get(key)
        if hit is None:
            hit = self._resolve(ntid, template_ord)
            self._resolved[key] = hit
        return hit

    def default(self, ntid: int, template_ord: int) -> NoteMapping:
        key = (ntid, template_ord)
        hit = self._defaults.get(key)
        if hit is None:
            hit = self._default(ntid, template_ord, self.default_kind(ntid))
            self._defaults[key] = hit
        return hit

    # -- internals --

    def _names(self, ntid: int, template_ord: int) -> tuple[str, str]:
        model = self.model(ntid)
        tmpls = model["tmpls"]
        tname = str(tmpls[template_ord]["name"]) if template_ord < len(tmpls) else "?"
        return str(model["name"]), tname

    def _default(self, ntid: int, template_ord: int, kind: NoteKind) -> NoteMapping:
        model = self.model(ntid)
        nt_name, t_name = self._names(ntid, template_ord)
        names = field_names(model)

        def make(
            answer: str | None,
            extra: str | None,
            why: str,
            ineligible: bool = False,
            candidates: Sequence[str] = (),
            front: Sequence[str] = (),
        ) -> NoteMapping:
            return NoteMapping(
                ntid=ntid,
                template_ord=template_ord,
                kind=kind,
                notetype_name=nt_name,
                template_name=t_name,
                answer_field=answer,
                extra_field=extra,
                ineligible=ineligible,
                overridden=False,
                why=why,
                candidates=tuple(candidates),
                front_fields=tuple(front),
            )

        if kind == "image_occlusion":
            return make(None, None, "Image Occlusion: nothing to type", ineligible=True)
        if kind == "cloze":
            cf = cloze_field(model)
            extra = first_named(names, CLOZE_EXTRA_NAMES, cf)
            if cf is None:
                return make(None, extra, "no {{cloze:F}} field in the template")
            return make(cf, extra, f"cloze field {cf}")

        tmpls = model["tmpls"]
        if template_ord >= len(tmpls):
            return make(None, None, f"template {template_ord} not found")
        tmpl = tmpls[template_ord]
        typed = type_in_field(model, tmpl)
        samples = self.samples(ntid)
        answer: str | None
        candidates: list[str] = []
        if typed is not None:
            answer, why = typed, f"{{{{type:{typed}}}}} on the front"
        else:
            candidates, after_rule = answer_candidates_in_section(model, tmpl)
            where = "answer-side field" if after_rule else "field before <hr id=answer>"
            answer, why = None, "no field shown only on the answer side"
            if candidates:
                why = f"no candidate filled in {FILLED_SHARE:.0%} of {len(samples)} sampled notes"
            for cand in candidates:
                front = front_fields(model, tmpl, cand)
                filled = sum(1 for n in samples if standard_answer(n, cand, front))
                if not samples or filled >= FILLED_SHARE * len(samples):
                    answer = cand
                    why = f"first {where} filled in {filled}/{len(samples)} sampled notes"
                    break
        extra = None
        for name in STANDARD_EXTRA_NAMES:
            f = first_named(names, (name,), answer)
            if f is not None and any(has_content(n[f]) for n in samples):
                extra = f
                break
        front = front_fields(model, tmpl, answer) if answer else []
        return make(answer, extra, why, candidates=candidates, front=front)

    def _resolve(self, ntid: int, template_ord: int) -> NoteMapping:
        o = self.overrides.get((ntid, template_ord))
        if o is None:
            return self.default(ntid, template_ord)
        model = self.model(ntid)
        nt_name, t_name = self._names(ntid, template_ord)
        names = set(field_names(model))
        kind = self.default_kind(ntid)
        if o.ineligible:
            return NoteMapping(
                ntid=ntid,
                template_ord=template_ord,
                kind=kind,
                notetype_name=nt_name,
                template_name=t_name,
                answer_field=None,
                extra_field=None,
                ineligible=True,
                overridden=True,
                why="marked ineligible in mappings.json",
            )
        if kind == "image_occlusion":
            # Stock IO holds shapes, not text: no override makes it typeable.
            return self.default(ntid, template_ord)
        base = self.default(ntid, template_ord)
        answer = o.answer_field or base.answer_field
        why = "mappings.json"
        if answer is not None and answer not in names:
            why = f"mappings.json names a missing field {answer!r}"
            answer = None
        extra = o.extra_field if o.extra_field in names else None
        tmpls = model["tmpls"]
        front: tuple[str, ...] = ()
        if kind == "standard" and answer is not None and template_ord < len(tmpls):
            front = tuple(front_fields(model, tmpls[template_ord], answer))
        return NoteMapping(
            ntid=ntid,
            template_ord=template_ord,
            kind=kind,
            notetype_name=nt_name,
            template_name=t_name,
            answer_field=answer,
            extra_field=extra,
            ineligible=False,
            overridden=True,
            why=why,
            candidates=base.candidates,
            front_fields=front,
        )


# ---------------------------------------------------------------------------
# Per-note values
# ---------------------------------------------------------------------------


def front_text(note: Note, fields: Sequence[str]) -> str:
    """Grading text of the front's fields, joined the way the render joins
    blocks (one space)."""
    return tidy(" ".join(grading_text(note[f]) for f in fields))


def standard_answer(note: Note, answer_field: str, front: Sequence[str]) -> str:
    """Grading text of the answer field, minus a leading copy of the front."""
    return strip_front(grading_text(note[answer_field]), front_text(note, front))


def answer_text(col: Collection, note: Note, mapping: NoteMapping, card_ord: int) -> str:
    """The graded answer for one card: the answer field's grading text minus a
    repeated front (standard), or the card's cloze deletion(s) (``card.ord + 1``
    is the cloze number)."""
    if mapping.answer_field is None or mapping.ineligible:
        return ""
    if mapping.kind == "cloze":
        raw = col.extract_cloze_for_typing(note[mapping.answer_field], card_ord + 1)
        return grading_text(raw)
    return standard_answer(note, mapping.answer_field, mapping.front_fields)


def is_io_note(note: Note, mapping: NoteMapping) -> bool:
    """A cloze-kind note whose cloze field holds Image Occlusion shapes."""
    return (
        mapping.kind == "cloze"
        and mapping.answer_field is not None
        and IO_MARKER in note[mapping.answer_field]
    )


def extra_html(note: Note, mapping: NoteMapping) -> str:
    return note[mapping.extra_field] if mapping.extra_field else ""
