"""Popularity (U09; RF10, AC08, AC13; decisions D11, D18, D23): the invoices that hold a product, counted in the history before the Monday only (a guest's basket included, the lines of
a cancellation, a service code and a bad price never), over all of it or over the last days; and the fixed order that breaks every tie (the score, then the global popularity, then the
code)."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from personaloffers import base
from personaloffers.base import LeakageError
from personaloffers.recommend import popularity
from tests.fixtures import hand_cases as hc
from tests.fixtures.hand_lines import hand_frame

CODES = np.array(["A", "B", "C", "D"])


def hand_history(extra: tuple[dict, ...] = ()) -> pd.DataFrame:
    """The history of the hand case: one line per row of POPULARITY_HISTORY (a line without a customer is a guest's), the cut for the Monday 2011-08-01 applied by the test."""
    rows = [{"invoice": invoice, "customer_id": customer, "invoice_date": datetime(day.year, day.month, day.day), "stock_code": product,
             "role": "guest_purchase" if customer is None else "purchase"} for invoice, customer, day, product in hc.POPULARITY_HISTORY]
    return hand_frame(*rows, *extra)


def cut(frame: pd.DataFrame) -> pd.DataFrame:
    return base.history_before(frame, hc.POPULARITY_MONDAY)


def test_popularity_counts_only_lines_before_the_monday():
    """AC13: the invoice of the Monday's own week (I6, product C, 2011-08-02) is not in any count; the same hand case, counted for the global and the 28-day popularity."""
    history = cut(hand_history())
    assert len(history) == len(hand_history()) - 1
    assert dict(zip(CODES, popularity.counts(history, hc.POPULARITY_MONDAY, CODES), strict=True)) == hc.GLOBAL_POPULARITY
    recent = dict(zip(CODES, popularity.counts(history, hc.POPULARITY_MONDAY, CODES, days=28), strict=True))
    assert recent == {**{code: 0 for code in CODES}, **hc.RECENT_POPULARITY_28_DAYS}
    assert popularity.counts(history, hc.POPULARITY_MONDAY, CODES).dtype == np.int64


def test_an_invoice_counts_once_for_a_product_whatever_its_lines_and_a_guest_basket_counts():
    history = cut(hand_history())
    counts = dict(zip(CODES, popularity.counts(history, hc.POPULARITY_MONDAY, CODES), strict=True))
    assert counts["A"] == 4, "I2 and I5 hold A on two lines each and count once"
    assert counts["B"] == 3, "I4 is a guest's basket and counts for the popularity (it never makes a customer)"


def test_only_the_lines_of_a_basket_count_not_a_cancellation_a_service_code_or_a_bad_price():
    extra = tuple({"invoice": f"X{n}", "customer_id": 9, "invoice_date": datetime(2011, 7, 28), "stock_code": "A", "role": role}
                  for n, role in enumerate(("cancellation", "adjustment", "non_product", "bad_price")))
    history = cut(hand_history(extra))
    assert dict(zip(CODES, popularity.counts(history, hc.POPULARITY_MONDAY, CODES), strict=True)) == hc.GLOBAL_POPULARITY


def test_the_window_starts_at_the_midnight_that_many_days_before_the_monday():
    """From 2011-07-04 00:00 (28 days before the Monday) the line counts, and one a second earlier does not."""
    extra = ({"invoice": "E1", "customer_id": 7, "invoice_date": datetime(2011, 7, 4, 0, 0, 0), "stock_code": "D"},
             {"invoice": "E2", "customer_id": 7, "invoice_date": datetime(2011, 7, 3, 23, 59, 59), "stock_code": "D"})
    history = cut(hand_history(extra))
    assert popularity.counts(history, hc.POPULARITY_MONDAY, CODES, days=28)[3] == 1
    assert popularity.counts(history, hc.POPULARITY_MONDAY, CODES, days=29)[3] == 2


def test_a_product_that_is_not_in_the_catalogue_is_ignored_and_a_catalogue_product_without_a_line_counts_zero():
    history = cut(hand_history())
    counts = popularity.counts(history, hc.POPULARITY_MONDAY, np.array(["A", "Z"]))
    assert counts.tolist() == [4, 0]


def test_a_history_with_a_line_of_the_round_or_later_is_refused():
    """M01: the guard of the round, here for the one function of this module that reads the lines."""
    with pytest.raises(LeakageError, match="2011-08-01"):
        popularity.counts(hand_history(), hc.POPULARITY_MONDAY, CODES)
    with pytest.raises(LeakageError):
        popularity.catalogue(hand_history(), hc.POPULARITY_MONDAY)


def test_the_catalogue_is_the_sorted_products_with_a_line_of_a_basket_in_the_history():
    extra = ({"invoice": "S1", "customer_id": 9, "invoice_date": datetime(2011, 7, 1), "stock_code": "Z", "role": "non_product"},
             {"invoice": "S2", "customer_id": 9, "invoice_date": datetime(2011, 7, 1), "stock_code": "0", "role": "guest_purchase"})
    codes = popularity.catalogue(cut(hand_history(extra)), hc.POPULARITY_MONDAY)
    assert codes.tolist() == ["0", "A", "B", "C", "D"], "the guest's product is in, the service code is out, and the order is the order of the codes"
    assert popularity.catalogue(cut(hand_history()), hc.POPULARITY_MONDAY).tolist() == ["A", "B", "C", "D"]


def test_ties_follow_the_fixed_order_the_more_popular_product_and_then_the_lower_code():
    """D11: the same score goes to the more popular product, and the same popularity to the lower code: TIE_ORDER of the hand cases (product 6 is the most popular; 4 and 5 tie)."""
    global_counts = np.zeros(8, dtype=np.int64)
    for product, count in hc.TIE_POPULARITY.items():
        global_counts[product] = count
    rank = popularity.tie_rank(global_counts)
    assert rank.dtype == np.int64 and sorted(rank.tolist()) == list(range(8)), "a rank is a permutation: no two products share a place"
    in_order = sorted(hc.TIE_SCORES, key=lambda product: (-hc.TIE_SCORES[product], rank[product]))
    assert tuple(in_order) == hc.TIE_ORDER


def test_the_fallback_is_the_recent_popularity_with_the_global_popularity_and_the_code_breaking_its_ties():
    recent = np.array([5, 9, 9, 0, 9, 5])
    global_counts = np.array([10, 3, 7, 1, 7, 10])
    order = popularity.fallback_order(recent, popularity.tie_rank(global_counts))
    # 9 recent: products 2 and 4 (global 7 each, so the lower index first) before product 1 (global 3); then 5 recent: products 0 and 5 (global 10 each); then 3
    assert order.tolist() == [2, 4, 1, 0, 5, 3]
    assert sorted(order.tolist()) == list(range(6))


def test_the_scores_of_a_popularity_are_one_row_for_every_customer():
    counts = np.array([4, 3, 1, 1])
    matrix = popularity.scores(counts, 3)
    assert matrix.shape == (3, 4) and matrix.dtype == np.float32
    assert (matrix == counts.astype(np.float32)).all()


def test_popularity_equals_a_second_computation_on_the_fixture(fixture_lines, quick_cfg):
    """Every round of the calendar, the whole fixture: a plain loop over the lines of a basket against the vectorized counts."""
    for monday in (quick_cfg.calendar.validation_first_round, quick_cfg.calendar.test_first_round, quick_cfg.calendar.test_last_round):
        history = base.history_before(fixture_lines, monday)
        codes = popularity.catalogue(history, monday)
        midnight = datetime.combine(monday, datetime.min.time())
        for days in (None, 28):
            expected: dict[str, set[str]] = {}
            for row in history.itertuples():
                if row.role not in ("purchase", "guest_purchase"):
                    continue
                if days is not None and (midnight - row.invoice_date).total_seconds() > days * 86400:
                    continue
                expected.setdefault(row.stock_code, set()).add(row.invoice)
            counts = popularity.counts(history, monday, codes, days=days)
            assert dict(zip(codes, counts.tolist(), strict=True)) == {code: len(expected.get(code, ())) for code in codes}, (monday, days)
