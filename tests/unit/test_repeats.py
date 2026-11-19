"""Own repeats (U09; RF10, AC08, AC11; decision D09): the score of a product the customer bought is the invoices that hold it plus half of how recent the last purchase is, relative to
90 days; nothing else is scored; a guest, a cancellation or a service code never makes a customer's product."""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta

import numpy as np
import pytest

from personaloffers import base
from personaloffers.base import LeakageError
from personaloffers.recommend import repeats
from tests.fixtures import hand_cases as hc
from tests.fixtures.hand_lines import hand_frame
from tests.unit.test_popularity import CODES, cut, hand_history

CUSTOMERS = np.array([1, 2, 3, 4], dtype=np.int64)


def with_recommend(view, **keys):
    return dataclasses.replace(view, recommend=dataclasses.replace(view.recommend, **keys))


def scored(history, view, customers=CUSTOMERS, codes=CODES):
    return repeats.score_matrix(history, hc.POPULARITY_MONDAY, customers, codes, view)


def test_the_scores_of_the_hand_case_are_the_ones_worked_out_by_hand(quick_view):
    """AC11: the invoices of the customer with the product plus 0.5 x (last purchase - (Monday - 90 days)) / 90 days; a negative recency term is not clamped (customer 4)."""
    scores, seen = scored(cut(hand_history()), quick_view)
    assert scores.shape == seen.shape == (4, 4) and scores.dtype == np.float32 and seen.dtype == bool
    index = {code: j for j, code in enumerate(CODES)}
    expected = {(customer, index[code]): float(value) for (customer, code), value in hc.REPEAT_SCORES.items()}
    found = {(int(CUSTOMERS[i]), int(j)): float(scores[i, j]) for i, j in zip(*np.nonzero(seen), strict=True)}
    assert set(found) == set(expected), "exactly the products each customer bought are scored"
    for key, value in expected.items():
        assert found[key] == pytest.approx(value, abs=1e-6), key
    assert (scores[~seen] == 0).all(), "what the customer did not buy has no repeat score"


def test_the_order_of_the_repeats_of_a_customer_is_the_one_of_the_hand_case_and_a_tie_goes_to_the_popular_product(quick_view):
    scores, seen = scored(cut(hand_history()), quick_view)
    popularity_rank = np.array([0, 1, 2, 3])      # A, B, C, D: from the global counts A 4, B 3 and C 1 = D 1 (the lower code first)
    for i, customer in enumerate(CUSTOMERS):
        mine = np.flatnonzero(seen[i])
        ordered = sorted(mine, key=lambda j: (-scores[i, j], popularity_rank[j]))
        assert tuple(CODES[j] for j in ordered) == hc.REPEAT_ORDER[int(customer)], customer


def test_an_invoice_counts_once_for_a_product_however_many_lines_it_has(quick_view):
    """Customer 1 buys A on two lines of I5 and once on I1: two invoices, not three lines."""
    scores, _ = scored(cut(hand_history()), quick_view)
    assert scores[0, 0] == pytest.approx(2 + 0.5 * 88 / 90, abs=1e-6)


def test_a_guest_a_cancellation_and_a_service_code_make_no_product_of_a_customer(quick_view):
    extra = ({"invoice": "G1", "customer_id": None, "invoice_date": datetime(2011, 7, 29), "stock_code": "D", "role": "guest_purchase"},
             {"invoice": "C1", "customer_id": 3, "invoice_date": datetime(2011, 7, 29), "stock_code": "D", "role": "cancellation"},
             {"invoice": "N1", "customer_id": 3, "invoice_date": datetime(2011, 7, 29), "stock_code": "D", "role": "non_product"},
             {"invoice": "B1", "customer_id": 3, "invoice_date": datetime(2011, 7, 29), "stock_code": "D", "role": "bad_price"})
    plain = scored(cut(hand_history()), quick_view)
    more = scored(cut(hand_history(extra)), quick_view)
    assert (more[0] == plain[0]).all() and (more[1] == plain[1]).all(), "nothing of them is a repeat"
    assert more[1][2, 3] == False and more[0][2, 3] == 0   # noqa: E712 - customer 3 never bought D


def test_the_weight_and_the_days_of_the_recency_term_come_from_the_configuration(quick_view):
    history = cut(hand_history())
    base_scores, _ = scored(history, quick_view)
    no_recency, _ = scored(history, with_recommend(quick_view, repeat_recency_weight=0.0))
    assert no_recency[0, 0] == 2.0 and no_recency[3, 3] == 1.0, "with a zero weight the score is the number of invoices"
    longer, _ = scored(history, with_recommend(quick_view, repeat_recency_days=180))
    assert longer[0, 0] == pytest.approx(2 + 0.5 * (datetime(2011, 7, 30) - (datetime(2011, 8, 1) - timedelta(days=180))).days / 180, abs=1e-6)
    assert not np.array_equal(base_scores, longer)


def test_a_product_outside_the_catalogue_and_a_customer_without_lines_have_nothing(quick_view):
    scores, seen = scored(cut(hand_history()), quick_view, customers=np.array([1, 99]), codes=np.array(["A", "Z"]))
    assert seen.tolist() == [[True, False], [False, False]]
    assert scores[1].tolist() == [0, 0]


def test_a_history_with_a_line_of_the_round_or_later_is_refused(quick_view):
    with pytest.raises(LeakageError, match="2011-08-01"):
        scored(hand_history(), quick_view)


def test_the_scores_equal_a_second_computation_on_the_fixture(fixture_lines, quick_view, quick_cfg):
    """A plain loop over the purchase lines of each customer against the matrix, in a round of the calendar, with the fractions of a day of the real timestamps."""
    monday = quick_cfg.calendar.test_first_round
    history = base.history_before(fixture_lines, monday)
    customers = base.contact_base(history, monday, quick_view)["customer_id"].to_numpy()
    codes = np.array(sorted(history.loc[history["role"].isin(["purchase", "guest_purchase"]), "stock_code"].unique()))
    scores, seen = repeats.score_matrix(history, monday, customers, codes, quick_view)
    midnight = datetime.combine(monday, datetime.min.time())
    start = midnight - timedelta(days=quick_view.recommend.repeat_recency_days)
    mine: dict[tuple[int, str], tuple[set, datetime]] = {}
    for row in history[history["role"] == "purchase"].itertuples():
        invoices, last = mine.get((int(row.customer_id), row.stock_code), (set(), datetime.min))
        mine[(int(row.customer_id), row.stock_code)] = (invoices | {row.invoice}, max(last, row.invoice_date.to_pydatetime()))
    column = {code: j for j, code in enumerate(codes)}
    row_of = {int(c): i for i, c in enumerate(customers)}
    expected = np.zeros(scores.shape, dtype=np.float64)
    for (customer, code), (invoices, last) in mine.items():
        if customer in row_of:
            term = quick_view.recommend.repeat_recency_weight * (last - start).total_seconds() / (quick_view.recommend.repeat_recency_days * 86400)
            expected[row_of[customer], column[code]] = len(invoices) + term
    assert seen.sum() == sum(1 for (customer, _), _v in mine.items() if customer in row_of) > 200
    assert np.allclose(scores, expected, atol=2e-5)


def test_a_one_line_history_is_one_scored_product(quick_view):
    history = hand_frame({"customer_id": 5, "invoice": "Z", "stock_code": "A", "invoice_date": datetime(2011, 7, 31, 12)})
    scores, seen = repeats.score_matrix(history, hc.POPULARITY_MONDAY, np.array([5]), np.array(["A", "B"]), quick_view)
    assert seen.tolist() == [[True, False]]
    assert scores[0, 0] == pytest.approx(1 + 0.5 * ((datetime(2011, 7, 31, 12) - datetime(2011, 5, 3)).total_seconds() / (90 * 86400)), abs=1e-6)
