"""Popularity: the invoices that hold a product (RF10; decisions D11, D18; AC13).

A count is the number of **distinct invoices** with a line of a basket (``purchase`` or ``guest_purchase``: a guest's basket counts for the popularity and is never a customer, AC08) that
holds the product, over the whole history before the Monday (B1, the global popularity that breaks ties) or over the last ``days`` days before it (B2 with the ``fallback_days`` of the
list, 28, and the trend of the mix). Nothing from the Monday on is counted: ``check_no_leak`` refuses such a history (the leak that took the research's hit@10 from 56.3 % to 58.9 %).

The order that breaks every tie is fixed (D11): the score, then the global popularity, then the code. The catalogue is sorted by code, so the code is the position; ``tie_rank`` is the
place of each product in that order (0 is the best) and ``fallback_order`` is the products by recent popularity with the same tie-break.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd

from personaloffers.base import check_no_leak
from personaloffers.lines import PRODUCT_ROLES


def _basket_lines(history: pd.DataFrame) -> pd.DataFrame:
    return history[history["role"].isin(PRODUCT_ROLES)]


def catalogue(history: pd.DataFrame, monday: date) -> np.ndarray:
    """The products of the round: the codes with a line of a basket in the history, sorted (a text array)."""
    check_no_leak(history, monday)
    codes = _basket_lines(history)["stock_code"].dropna().unique()
    return np.array(sorted(str(code) for code in codes), dtype=str)


def counts(history: pd.DataFrame, monday: date, codes: np.ndarray, *, days: int | None = None) -> np.ndarray:
    """For each of `codes` (in its order) the distinct invoices of the history that hold it; with `days`, only those from the midnight that many days before `monday` on. A code with no
    invoice counts 0 and an invoice with a product outside `codes` counts for none of them. ``int64``."""
    check_no_leak(history, monday)
    rows = _basket_lines(history)
    if days is not None:
        rows = rows[rows["invoice_date"] >= datetime.combine(monday, time.min) - timedelta(days=days)]
    per_product = rows[["invoice", "stock_code"]].drop_duplicates().groupby("stock_code").size()
    return per_product.reindex(pd.Index(codes)).fillna(0).to_numpy(dtype="int64")


def tie_rank(global_counts: np.ndarray) -> np.ndarray:
    """The place of each product (0 is the best) in the fixed order of the ties: the more popular first and, among equals, the lower code (the lower position of the sorted catalogue)."""
    popularity = np.asarray(global_counts)
    order = np.lexsort((np.arange(len(popularity)), -popularity))
    rank = np.empty(len(popularity), dtype=np.int64)
    rank[order] = np.arange(len(popularity), dtype=np.int64)
    return rank


def fallback_order(recent_counts: np.ndarray, rank: np.ndarray) -> np.ndarray:
    """The products by recent popularity, the most sold first, and with the fixed order for the ties: what completes a list when the models have nothing more (D10)."""
    return np.lexsort((np.asarray(rank), -np.asarray(recent_counts))).astype(np.int64)


def scores(product_counts: np.ndarray, customers: int) -> np.ndarray:
    """The count of each product as the score of every one of `customers` customers: a read-only ``float32`` view of one row, which takes no memory per customer."""
    row = np.asarray(product_counts, dtype=np.float32)
    return np.broadcast_to(row, (customers, len(row)))
