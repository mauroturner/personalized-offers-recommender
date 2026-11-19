"""The rounds and their windows (RF05, RF14, AC18; decisions D05, D17, D23, D42).

A round is a Monday: its list is built with every line before that Monday and measured with the purchases of its window, ``[Monday, Monday + window_days)``. The
windows of consecutive rounds are consecutive weeks, so a purchase line is in the window of one round at most (no line is counted thirteen times, as it would be with
a window of ninety days that moves by the week). There are three periods: the **validation** rounds (every Monday from ``validation_first_round`` to
``validation_last_round``), the **test** rounds (from ``test_first_round`` to ``test_last_round``) and the **censored** one, the Monday of the close, whose window stops
at the last day of the archive (``close_last_day``) and so has five days, not seven (D42).

Every function reads only ``view.calendar`` (``[calendar]`` of the configuration or of its sealed view).
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from typing import Any

PERIODS = ("validation", "test", "censored")
ROUND_PREFIX = "R"
_ROUND_ID = re.compile(r"R(\d{4})-(\d{2})-(\d{2})", re.ASCII)


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time.min)


def _mondays(first: date, last: date) -> list[date]:
    return [first + timedelta(days=7 * n) for n in range((last - first).days // 7 + 1)]


def rounds(view: Any, period: str) -> list[date]:
    """The Mondays of a period (``PERIODS``), in order: 13 validation rounds, 18 test rounds and the one censored round of the real calendar."""
    c = view.calendar
    if period == "validation":
        return _mondays(c.validation_first_round, c.validation_last_round)
    if period == "test":
        return _mondays(c.test_first_round, c.test_last_round)
    if period == "censored":
        return [c.close_first_day]
    raise ValueError(f"periodo desconocido: {period!r}; se esperaba uno de {', '.join(PERIODS)} (validation, test, censored)")


def period_of(monday: date, view: Any) -> str:
    """The period a round belongs to; a day that is not the Monday of a round is a ``ValueError`` that says the day."""
    for period in PERIODS:
        if monday in rounds(view, period):
            return period
    raise ValueError(f"{monday.isoformat()} no es el lunes de ninguna ronda del calendario")


def window(monday: date, view: Any) -> tuple[datetime, datetime]:
    """``[start, end)`` of the purchases that measure the round of `monday`: from its midnight to ``window_days`` days later; the censored round stops at the midnight after
    the last day of the archive. A day that is not a Monday is refused (a round starts on a Monday)."""
    if monday.weekday() != 0:
        raise ValueError(f"{monday.isoformat()} no es un lunes: una ronda empieza el lunes")
    c = view.calendar
    end = _midnight(monday + timedelta(days=c.window_days))
    if monday == c.close_first_day:
        end = min(end, _midnight(c.close_last_day + timedelta(days=1)))
    return _midnight(monday), end


def days_observed(monday: date, view: Any) -> int:
    """The days of the window of a round (7, and 5 for the censored one of the real calendar)."""
    start, end = window(monday, view)
    return (end - start).days


def round_id(monday: date) -> str:
    """``R2011-08-01``: how a round is named in every table and file."""
    return f"{ROUND_PREFIX}{monday.isoformat()}"


def monday_of(text: str) -> date:
    """The Monday a round identifier names (the exact text ``R<AAAA-MM-DD>``, nothing around it)."""
    found = _ROUND_ID.fullmatch(text) if isinstance(text, str) else None
    if found is None:
        raise ValueError(f"{text!r} no es el identificador de una ronda (R<AAAA-MM-DD>)")
    try:
        return date(int(found[1]), int(found[2]), int(found[3]))
    except ValueError as error:
        raise ValueError(f"{text!r} no es el identificador de una ronda (R<AAAA-MM-DD>): {error}") from error
