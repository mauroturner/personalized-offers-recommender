"""The base of contacts of a round, its covariates and its segments (RF08, AC07, AC08; decisions D06, D07, D23).

**The clock is the round** (D23). ``history_before`` is the only function that cuts: it keeps the lines dated before the midnight of the Monday of the round. Everything here
receives its result and nothing else, and ``check_no_leak`` (M01) makes it a ``LeakageError`` to give a function a line from the round or after it, so a missing cut is a failure
and not a number that is a little too good. These modules never read the lines themselves (a static test checks it).

**Who is in the base** (D06): the customers with at least one *purchase* line in the ``[base] lookback_days`` (365) days before the Monday. Only the ``purchase`` role makes a buyer:
a guest's lines (no customer), a cancellation, an adjustment, a service code or a line of bad price never do (AC08). A customer who never bought does not exist for the CRM.

**What is known of each one** (RF08, plan section 7), always from the lines before the Monday:

* ``recency_days``: days from the last purchase (any time in the history) to the midnight of the Monday, with the fraction of the day;
* ``invoices_365`` and ``spend_365``: the distinct invoices of the customer in the year, and the sum of ``quantity * price`` of its lines of the year;
* ``tenure_days``: days from the first purchase to the Monday; ``invoices_before``: the distinct invoices of the whole history;
* ``bulk`` (D07): the median of the units of the lines of the year is at least ``[base] bulk_min_median_qty`` (24) in at least ``bulk_min_lines`` (3) lines. It is the rule of
  project 02 and it is used as the stratum of the control group and as a cut of the reports, never as a variable of a model (D39).

``segment`` crosses the bulk flag with whether the customer had bought before (``bulk|repeat``, ``retail|one_invoice``...). The functions take the configuration or its sealed view
(only ``view.base`` is read).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from typing import Any

import numpy as np
import pandas as pd

COVARIATE_COLUMNS = ("recency_days", "invoices_365", "spend_365", "tenure_days", "bulk")    # the five that the balance of the control group compares
TABLE_COLUMNS = ("customer_id", "recency_days", "invoices_365", "spend_365", "tenure_days", "bulk", "invoices_before")
SEGMENTS = ("bulk|repeat", "bulk|one_invoice", "retail|repeat", "retail|one_invoice")
SECONDS_PER_DAY = 86400.0


class LeakageError(RuntimeError):
    """A function that computes something for a round was given a line from the round or after it (M01, D23)."""


def _midnight(monday: date) -> datetime:
    return datetime.combine(monday, time.min)


def history_before(lines: pd.DataFrame, monday: date) -> pd.DataFrame:
    """The lines dated before the midnight of the Monday of a round, with their order and their index: the only cut. The result is what every calculation of the round receives."""
    if monday.weekday() != 0:
        raise ValueError(f"{monday.isoformat()} no es un lunes: una ronda empieza el lunes")
    return lines[lines["invoice_date"] < _midnight(monday)]


def check_no_leak(history: pd.DataFrame, monday: date) -> None:
    """M01: ``LeakageError`` if `history` holds a line dated at or after the midnight of `monday`."""
    if len(history) and history["invoice_date"].max() >= _midnight(monday):
        raise LeakageError(f"se le dieron a la ronda del {monday.isoformat()} líneas con fecha de esa ronda o posterior: el historial debe salir de history_before (D23)")


def _purchases(history: pd.DataFrame) -> pd.DataFrame:
    """The lines of a customer that are purchases (the role says it and the customer is there), with the integer number of the customer."""
    rows = history[(history["role"] == "purchase") & history["customer_id"].notna()]
    return rows.assign(customer_id=rows["customer_id"].astype("int64"))


def contact_base(history: pd.DataFrame, monday: date, view: Any) -> pd.DataFrame:
    """The base of the round of `monday`: one row per customer with a purchase in the ``lookback_days`` before it, sorted by customer number (column ``customer_id``)."""
    check_no_leak(history, monday)
    start = _midnight(monday) - timedelta(days=view.base.lookback_days)
    rows = _purchases(history)
    ids = np.sort(rows.loc[rows["invoice_date"] >= start, "customer_id"].unique())
    return pd.DataFrame({"customer_id": ids.astype("int64")})


def covariates(history: pd.DataFrame, base_ids: Any, monday: date, view: Any) -> pd.DataFrame:
    """The covariates of the customers `base_ids` (each once, in the order of their number): ``TABLE_COLUMNS``. A customer that is not in the base of the round is a ``ValueError`` that
    counts them and does not name them."""
    check_no_leak(history, monday)
    ids = np.unique(np.asarray(base_ids, dtype="int64"))
    cut = _midnight(monday)
    start = cut - timedelta(days=view.base.lookback_days)
    rows = _purchases(history)
    rows = rows[rows["customer_id"].isin(ids)].sort_values("line_key", kind="stable")
    rows = rows.assign(value=rows["quantity"].astype("float64") * rows["price"].astype("float64"))
    ever = rows.groupby("customer_id")
    year_rows = rows[rows["invoice_date"] >= start]
    year = year_rows.groupby("customer_id")
    missing = int((~pd.Index(ids).isin(year.size().index)).sum())
    if missing:
        raise ValueError(f"{missing} clientes de los que se pidieron no están en la base de la ronda del {monday.isoformat()} (sin compras en sus {view.base.lookback_days} días anteriores)")
    median, lines = year["quantity"].median(), year.size()
    found = pd.DataFrame({
        "customer_id": ids,
        "recency_days": ((cut - ever["invoice_date"].max().reindex(ids)).dt.total_seconds() / SECONDS_PER_DAY).to_numpy("float64"),
        "invoices_365": year["invoice"].nunique().reindex(ids).to_numpy("int64"),
        "spend_365": year["value"].sum().reindex(ids).to_numpy("float64"),
        "tenure_days": ((cut - ever["invoice_date"].min().reindex(ids)).dt.total_seconds() / SECONDS_PER_DAY).to_numpy("float64"),
        "bulk": ((median.reindex(ids) >= view.base.bulk_min_median_qty) & (lines.reindex(ids) >= view.base.bulk_min_lines)).to_numpy("int64"),
        "invoices_before": ever["invoice"].nunique().reindex(ids).to_numpy("int64"),
    })
    return found[list(TABLE_COLUMNS)]


def segment(row: Mapping[str, Any] | pd.Series) -> str:
    """``bulk|repeat``, ``bulk|one_invoice``, ``retail|repeat`` or ``retail|one_invoice``: the bulk flag and whether the customer had more than one invoice before the round."""
    return f"{'bulk' if row['bulk'] else 'retail'}|{'repeat' if row['invoices_before'] >= 2 else 'one_invoice'}"


def base_table(history: pd.DataFrame, monday: date, view: Any) -> pd.DataFrame:
    """The rows of ``contact_base`` for the round of `monday`: the customers of the base with their covariates and their segment."""
    found = covariates(history, contact_base(history, monday, view)["customer_id"].to_numpy(), monday, view)
    found["segment"] = np.where(found["bulk"] == 1, "bulk", "retail").astype(object) + "|" + np.where(found["invoices_before"] >= 2, "repeat", "one_invoice").astype(object)
    return found
