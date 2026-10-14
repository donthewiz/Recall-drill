"""The unrated-cards warning (v0.3), pure: the count, the earliest deadline across
the rollover hour, the filtered-deck note, hidden after the deadline and at 0."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from recalldrill.unrated import (
    PendingCard,
    hour_text,
    unrated_warning,
    warning_line,
    window_last_day,
)

TZ = timezone(timedelta(hours=-5))
ROLLOVER = 4


def ms(y: int, mo: int, d: int, h: int, mi: int = 0) -> int:
    return int(datetime(y, mo, d, h, mi, tzinfo=TZ).timestamp() * 1000)


def test_the_window_ends_with_anki_day_two() -> None:
    # Handed off Tue Oct 13 at 20:00 (Anki day Oct 13): day 2 is Oct 15, which
    # ends Fri Oct 16 at 4 AM.
    w = unrated_warning([PendingCard(1, ms(2026, 10, 13, 20))], ms(2026, 10, 14, 9), ROLLOVER, TZ)
    assert w is not None
    assert (w.count, w.last_day, w.ends) == (1, date(2026, 10, 15), date(2026, 10, 16))
    assert w.rollover == 4
    assert warning_line(w) == (
        "1 drilled card is waiting for its first Anki rating. "
        "Rate it by Fri Oct 16 (before 4 AM) to keep it in the comparison."
    )


def test_several_cards_use_the_plural_line() -> None:
    cards = [PendingCard(i, ms(2026, 10, 13, 20)) for i in range(5)]
    w = unrated_warning(cards, ms(2026, 10, 13, 21), ROLLOVER, TZ)
    assert w is not None and w.line() == (
        "5 drilled cards are waiting for their first Anki rating. "
        "Rate them by Fri Oct 16 (before 4 AM) to keep them in the comparison."
    )


def test_the_rollover_hour_moves_the_deadline() -> None:
    # 2 AM Oct 14 still belongs to Anki day Oct 13; 5 AM Oct 14 is Oct 14.
    early = PendingCard(1, ms(2026, 10, 14, 2))
    late = PendingCard(2, ms(2026, 10, 14, 5))
    assert window_last_day(early.t0_ms, ROLLOVER, TZ) == date(2026, 10, 15)
    assert window_last_day(late.t0_ms, ROLLOVER, TZ) == date(2026, 10, 16)
    now = ms(2026, 10, 14, 12)
    w = unrated_warning([late, early], now, ROLLOVER, TZ)
    assert w is not None and w.count == 2 and w.ends == date(2026, 10, 16)  # the earlier one
    only_late = unrated_warning([late], now, ROLLOVER, TZ)
    assert only_late is not None and only_late.ends == date(2026, 10, 17)


def test_earliest_deadline_across_pending_handoffs() -> None:
    old = [PendingCard(1, ms(2026, 10, 11, 20)), PendingCard(2, ms(2026, 10, 11, 21))]
    new = [PendingCard(3, ms(2026, 10, 13, 20))]
    w = unrated_warning(old + new, ms(2026, 10, 13, 22), ROLLOVER, TZ)
    assert w is not None and w.count == 3
    assert w.last_day == date(2026, 10, 13) and w.ends == date(2026, 10, 14)  # the Oct 11 handoff
    # Once the older window has closed, only the newer card is left.
    after = unrated_warning(old + new, ms(2026, 10, 14, 4, 1), ROLLOVER, TZ)
    assert after is not None and after.count == 1 and after.ends == date(2026, 10, 16)


def test_hidden_after_the_deadline_and_at_zero() -> None:
    card = PendingCard(1, ms(2026, 10, 13, 20))
    # The last minute before 4 AM on Oct 16 still shows; 4:00 hides it.
    assert unrated_warning([card], ms(2026, 10, 16, 3, 59), ROLLOVER, TZ) is not None
    assert unrated_warning([card], ms(2026, 10, 16, 4, 0), ROLLOVER, TZ) is None
    assert unrated_warning([], ms(2026, 10, 13, 21), ROLLOVER, TZ) is None


def test_the_filtered_deck_note() -> None:
    cards = [
        PendingCard(1, ms(2026, 10, 13, 20), "Cram"),
        PendingCard(2, ms(2026, 10, 13, 20), "Cram"),
        PendingCard(3, ms(2026, 10, 13, 20)),
    ]
    w = unrated_warning(cards, ms(2026, 10, 13, 21), ROLLOVER, TZ)
    assert w is not None
    assert warning_line(w).endswith(
        "to keep them in the comparison. (2 are in the filtered deck 'Cram')"
    )
    one = unrated_warning(cards[:1] + cards[2:], ms(2026, 10, 13, 21), ROLLOVER, TZ)
    assert one is not None and one.line().endswith("(1 is in the filtered deck 'Cram')")
    more = [*cards, PendingCard(4, ms(2026, 10, 13, 20), "Exam prep")]
    two = unrated_warning(more, ms(2026, 10, 13, 21), ROLLOVER, TZ)
    assert two is not None and two.line().endswith("(in filtered decks: 'Cram' 2, 'Exam prep' 1)")


def test_hour_text() -> None:
    assert [hour_text(h) for h in (0, 4, 12, 13, 23)] == ["12 AM", "4 AM", "12 PM", "1 PM", "11 PM"]


def test_the_config_key() -> None:
    from recalldrill.addon_config import parse_config

    assert parse_config({}).unrated_warning is True
    assert parse_config({"unrated_warning": False}).unrated_warning is False
    assert parse_config({"unrated_warning": "no"}).unrated_warning is True  # mistyped: default
