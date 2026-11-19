"""Own repeats: the products a customer already buys (RF10, decision D09).

The score of a product the customer bought is the number of distinct invoices of the customer that hold it, plus ``[recommend] repeat_recency_weight`` (0.5) times how recent the last purchase
is: the days from ``Monday - repeat_recency_days`` (90) to the last purchase, over those 90 days. The term is not clamped: a purchase older than the window lowers the score under the number of
invoices. It is the research's score. Only the lines with the role ``purchase`` and a customer count (a guest, a cancellation, a service code or a bad price make no product of a customer, AC08),
and only the products of the catalogue are scored; what the customer did not buy has no score and ``seen`` says so.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

import numpy as np
import pandas as pd

from personaloffers.base import check_no_leak


def score_matrix(history: pd.DataFrame, monday: date, customers: np.ndarray, codes: np.ndarray, view: Any) -> tuple[np.ndarray, np.ndarray]:
    """``(scores, seen)``: ``float32`` scores and a boolean mask, both customers by products in the order of `customers` and `codes`; the score of a product that was not bought is 0."""
    check_no_leak(history, monday)
    people = np.asarray(customers, dtype="int64")
    scores = np.zeros((len(people), len(codes)), dtype=np.float32)
    seen = np.zeros(scores.shape, dtype=bool)
    rows = history[(history["role"] == "purchase") & history["customer_id"].notna()]
    rows = rows[rows["customer_id"].isin(people) & rows["stock_code"].isin(codes)]
    if rows.empty:
        return scores, seen
    rows = rows.assign(customer_id=rows["customer_id"].astype("int64"))
    per_pair = rows.groupby(["customer_id", "stock_code"]).agg(invoices=("invoice", "nunique"), last=("invoice_date", "max")).reset_index()
    window_start = datetime.combine(monday, time.min) - timedelta(days=view.recommend.repeat_recency_days)
    recency = (per_pair["last"] - window_start).dt.total_seconds() / (view.recommend.repeat_recency_days * 86400)
    value = per_pair["invoices"].to_numpy("float64") + view.recommend.repeat_recency_weight * recency.to_numpy("float64")
    i = pd.Index(people).get_indexer(per_pair["customer_id"])
    j = pd.Index(codes).get_indexer(per_pair["stock_code"])
    scores[i, j] = value.astype(np.float32)
    seen[i, j] = True
    return scores, seen
