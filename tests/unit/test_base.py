"""The base of contacts, its covariates and its segments (U07; RF08, AC07, AC08; decisions D06, D07, D23): who is in the base of a round, what is known of each one before the
Monday, and that a line without a customer is never a customer."""

from __future__ import annotations

import dataclasses
import math
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from personaloffers import base
from personaloffers.base import LeakageError
from tests.fixtures.hand_lines import hand_frame

MONDAY = date(2011, 8, 1)
D = datetime


def when(*parts: int) -> datetime:
    return datetime(*parts)


# A history worked out by hand for the Monday 2011-08-01: the base is the customers with a purchase from 2010-08-01 00:00 (365 days before) on.
HAND = hand_frame(
    # customer 90001: one invoice before the year and two inside it; the 24 units of the last one do not make a bulk buyer (the median of 12, 6 and 24 is 12)
    {"customer_id": 90001, "invoice": "A1", "invoice_date": when(2010, 7, 15, 9, 0), "quantity": 1, "price": 5.0},
    {"customer_id": 90001, "invoice": "A2", "invoice_date": when(2011, 1, 10, 10, 0), "quantity": 12, "price": 2.5},
    {"customer_id": 90001, "invoice": "A2", "invoice_date": when(2011, 1, 10, 10, 0), "quantity": 6, "price": 10.0},
    {"customer_id": 90001, "invoice": "A3", "invoice_date": when(2011, 7, 30, 14, 30), "quantity": 24, "price": 1.0},
    {"customer_id": 90001, "invoice": "CA3", "invoice_date": when(2011, 7, 31, 10, 0), "quantity": -3, "price": 1.0, "role": "cancellation"},   # a cancellation is not a purchase
    # customer 90002: one invoice of three lines of 24, 48 and 30 units: a bulk buyer (median 30, three lines)
    {"customer_id": 90002, "invoice": "B1", "invoice_date": when(2011, 6, 1, 12, 0), "quantity": 24, "price": 1.0},
    {"customer_id": 90002, "invoice": "B1", "invoice_date": when(2011, 6, 1, 12, 0), "quantity": 48, "price": 0.5},
    {"customer_id": 90002, "invoice": "B1", "invoice_date": when(2011, 6, 1, 12, 0), "quantity": 30, "price": 2.0},
    # customer 90003: two lines of 100 units: not a bulk buyer, because the rule asks for three lines
    {"customer_id": 90003, "invoice": "C1", "invoice_date": when(2011, 5, 5, 10, 0), "quantity": 100, "price": 1.0},
    {"customer_id": 90003, "invoice": "C2", "invoice_date": when(2011, 5, 6, 11, 0), "quantity": 100, "price": 1.0},
    # customer 90004: the last purchase is one second before the year starts: not in the base
    {"customer_id": 90004, "invoice": "D1", "invoice_date": when(2010, 7, 31, 23, 59, 59), "quantity": 1, "price": 1.0},
    # customer 90005: the purchase at the very start of the year: in the base
    {"customer_id": 90005, "invoice": "E1", "invoice_date": when(2010, 8, 1, 0, 0, 0), "quantity": 1, "price": 1.0},
    # customers that are not buyers: a cancellation only, a bad price only, a service code only
    {"customer_id": 90007, "invoice": "CG1", "invoice_date": when(2011, 7, 20, 10, 0), "quantity": -5, "price": 3.0, "role": "cancellation"},
    {"customer_id": 90008, "invoice": "H1", "invoice_date": when(2011, 7, 20, 10, 0), "quantity": 1, "price": 0.0, "role": "bad_price"},
    {"customer_id": 90009, "invoice": "J1", "invoice_date": when(2011, 7, 20, 10, 0), "quantity": 1, "price": 18.0, "role": "non_product", "stock_code": "POST"},
    # guests: lines without a customer, a lot of them, are never a customer
    *({"customer_id": None, "invoice": f"G{n}", "invoice_date": when(2011, 7, 25, 10, 0), "quantity": 500, "price": 9.0, "role": "guest_purchase"} for n in range(6)),
    # after the Monday: customer 90006 buys at the very midnight, 90001 buys again two days later and 90010 is new
    {"customer_id": 90006, "invoice": "F1", "invoice_date": when(2011, 8, 1, 0, 0, 0), "quantity": 1, "price": 1.0},
    {"customer_id": 90001, "invoice": "A4", "invoice_date": when(2011, 8, 3, 10, 0), "quantity": 999, "price": 999.0},
    {"customer_id": 90010, "invoice": "K1", "invoice_date": when(2011, 8, 9, 10, 0), "quantity": 1, "price": 1.0},
)
EXPECTED = {   # customer: (recency_days, invoices_365, spend_365, tenure_days, bulk, invoices_before, segment)
    90001: (33.5 / 24, 2, 114.0, 381.625, 0, 3, "retail|repeat"),          # 30 + 60 + 24; the last purchase 1 day 9.5 hours before; the first one 381 days 15 hours before
    90002: (60.5, 1, 108.0, 60.5, 1, 1, "bulk|one_invoice"),               # 24 + 24 + 60
    90003: (86 + 13 / 24, 2, 200.0, 87 + 14 / 24, 0, 2, "retail|repeat"),
    90005: (365.0, 1, 1.0, 365.0, 0, 1, "retail|one_invoice"),
}
VIEW_COLUMNS = ["customer_id", "recency_days", "invoices_365", "spend_365", "tenure_days", "bulk", "invoices_before"]


@pytest.fixture(scope="module")
def history():
    return base.history_before(HAND, MONDAY)


# --- history_before: the only cutter (D23) ---------------------------------------------------------------------------------------------------------------


def test_history_before_keeps_what_is_before_the_midnight_of_the_monday_and_nothing_else():
    edge = hand_frame({"invoice_date": when(2011, 7, 31, 23, 59, 59, 999999)}, {"invoice_date": when(2011, 8, 1, 0, 0, 0)}, {"invoice_date": when(2011, 8, 1, 0, 0, 0, 1)},
                      {"invoice_date": when(2011, 7, 1, 0, 0, 0)})
    cut = base.history_before(edge, MONDAY)
    assert cut["line_key"].tolist() == [edge.loc[0, "line_key"], edge.loc[3, "line_key"]], "the order and the keys of what stays"
    assert cut["invoice_date"].max() < when(2011, 8, 1)
    assert len(edge) == 4, "the input is as it was"
    assert base.history_before(edge.iloc[0:0], MONDAY).empty


def test_history_before_takes_a_round_only(history):
    with pytest.raises(ValueError, match="lunes"):
        base.history_before(HAND, date(2011, 8, 2))
    assert history["invoice_date"].max() == when(2011, 7, 31, 10, 0)


# --- the base ------------------------------------------------------------------------------------------------------------------------------------------


def test_the_base_is_the_customers_with_a_purchase_in_the_365_days_before_the_monday(history, quick_view):
    cfg_view = dataclasses.replace(quick_view, base=dataclasses.replace(quick_view.base, lookback_days=365))
    found = base.contact_base(history, MONDAY, cfg_view)
    assert list(found.columns) == ["customer_id"] and found["customer_id"].dtype == np.int64
    assert found["customer_id"].tolist() == [90001, 90002, 90003, 90005], "90004 bought one second too soon, 90006 and 90010 after the Monday, and 90007 to 90009 never purchased"


def test_the_lookback_of_the_configuration_moves_the_start_of_the_year(history, quick_view):
    def ids(days):
        view = dataclasses.replace(quick_view, base=dataclasses.replace(quick_view.base, lookback_days=days))
        return base.contact_base(history, MONDAY, view)["customer_id"].tolist()

    assert ids(366) == [90001, 90002, 90003, 90004, 90005], "one more day takes in the purchase of 23:59:59 of the day before"
    assert ids(365) == [90001, 90002, 90003, 90005]
    assert ids(364) == [90001, 90002, 90003], "one day less leaves out the purchase at the midnight that started the year"
    assert ids(87) == [90001, 90002, 90003] and ids(86) == [90001, 90002], "90003 bought 2011-05-05 and 2011-05-06, 86.5 and 87.6 days before"
    assert ids(61) == [90001, 90002] and ids(60) == [90001], "90002 bought 60.5 days before"
    assert ids(2) == [90001] and ids(1) == [], "90001 bought 2011-07-30 14:30; its cancellation of the 31st is not a purchase"


def test_no_line_without_customer_becomes_a_customer_anywhere(history, quick_view):
    """AC08: the lines of guests are many and big, and none of them is a customer of the base, of its covariates or of its segments."""
    guests = history[history["role"] == "guest_purchase"]
    assert len(guests) == 6 and guests["customer_id"].isna().all()
    found = base.contact_base(history, MONDAY, quick_view)
    table = base.base_table(history, MONDAY, quick_view)
    assert found["customer_id"].notna().all() and table["customer_id"].notna().all() and len(table) == 4
    assert 500 not in table["customer_id"].tolist() and table["spend_365"].max() < 500 * 9.0, "the spend of a customer is never the guests' 4,500"
    only_guests = history[history["role"] == "guest_purchase"]
    assert base.contact_base(only_guests, MONDAY, quick_view).empty
    assert base.covariates(only_guests, np.array([], dtype="int64"), MONDAY, quick_view).empty
    assert base.base_table(only_guests, MONDAY, quick_view).empty
    # a line that says it is a purchase with no customer cannot make one either: the base reads the customers that have one
    forged = history.copy()
    forged.loc[forged["role"] == "guest_purchase", "role"] = "purchase"
    assert base.contact_base(forged, MONDAY, quick_view)["customer_id"].tolist() == [90001, 90002, 90003, 90005]
    assert base.base_table(forged, MONDAY, quick_view)["customer_id"].notna().all()


def test_only_purchases_make_a_buyer_not_a_cancellation_a_bad_price_or_a_service_code(history, quick_view):
    ids = base.contact_base(history, MONDAY, quick_view)["customer_id"].tolist()
    assert not {90007, 90008, 90009} & set(ids)
    table = base.base_table(history, MONDAY, quick_view).set_index("customer_id")
    assert table.loc[90001, "invoices_before"] == 3 and table.loc[90001, "recency_days"] == pytest.approx(33.5 / 24), "the cancellation of 2011-07-31 is not a purchase"


# --- the covariates ----------------------------------------------------------------------------------------------------------------------------------


def test_the_covariates_are_the_ones_worked_out_by_hand(history, quick_view):
    ids = base.contact_base(history, MONDAY, quick_view)["customer_id"].to_numpy()
    found = base.covariates(history, ids, MONDAY, quick_view)
    assert list(found.columns) == VIEW_COLUMNS and found["customer_id"].tolist() == sorted(EXPECTED)
    for row in found.itertuples(index=False):
        recency, invoices, spend, tenure, bulk, before, _segment = EXPECTED[row.customer_id]
        assert row.recency_days == pytest.approx(recency, rel=1e-12) and row.tenure_days == pytest.approx(tenure, rel=1e-12), row.customer_id
        assert (row.invoices_365, row.bulk, row.invoices_before) == (invoices, bulk, before), row.customer_id
        assert row.spend_365 == pytest.approx(spend, rel=1e-12), row.customer_id
    assert found["invoices_365"].dtype == np.int64 and found["bulk"].dtype == np.int64 and found["invoices_before"].dtype == np.int64
    assert found["recency_days"].dtype == np.float64 and found["spend_365"].dtype == np.float64 and found["tenure_days"].dtype == np.float64


def test_the_covariates_of_a_customer_do_not_depend_on_who_else_is_asked_for_or_in_what_order(history, quick_view):
    everyone = base.covariates(history, np.array([90005, 90001, 90003, 90002]), MONDAY, quick_view)
    assert everyone["customer_id"].tolist() == [90001, 90002, 90003, 90005], "always in the order of the customer number"
    alone = base.covariates(history, np.array([90003]), MONDAY, quick_view)
    pd.testing.assert_frame_equal(alone.reset_index(drop=True), everyone[everyone["customer_id"] == 90003].reset_index(drop=True))
    twice = base.covariates(history, np.array([90001, 90001]), MONDAY, quick_view)
    assert twice["customer_id"].tolist() == [90001], "a customer asked for twice is one row"


def test_a_customer_that_is_not_in_the_base_has_no_covariates_and_the_error_does_not_name_it(history, quick_view):
    with pytest.raises(ValueError, match="1 clientes") as caught:
        base.covariates(history, np.array([90001, 90004]), MONDAY, quick_view)
    assert "90004" not in str(caught.value) and "90001" not in str(caught.value)
    with pytest.raises(ValueError, match="2 clientes"):
        base.covariates(history, np.array([90007, 90008]), MONDAY, quick_view)


def test_the_year_is_365_days_in_the_covariates_too_and_the_history_before_it_still_counts_for_the_tenure_and_the_invoices(history, quick_view):
    found = base.covariates(history, np.array([90001]), MONDAY, quick_view).iloc[0]
    assert found["invoices_365"] == 2 and found["invoices_before"] == 3 and found["tenure_days"] == pytest.approx(381.625)
    shorter = dataclasses.replace(quick_view, base=dataclasses.replace(quick_view.base, lookback_days=30))
    month = base.covariates(history, np.array([90001]), MONDAY, shorter).iloc[0]
    assert (month["invoices_365"], month["spend_365"], month["invoices_before"]) == (1, 24.0, 3), "only the invoice of 2011-07-30 is in the last 30 days"


@pytest.mark.parametrize("quantities, bulk", [
    ([24, 24, 24], 1), ([23, 23, 23], 0), ([24, 24, 1], 1), ([23, 23, 100], 0), ([1, 24, 24], 1), ([100, 100], 0), ([100], 0),
    ([20, 28, 1, 100], 1), ([23, 25, 1, 100], 1), ([20, 20, 24, 24], 0), ([20, 26, 24, 24], 1), ([24, 24, 24, 1, 1], 1), ([1, 1, 24, 24, 24, 1], 0),
])
def test_a_bulk_buyer_has_a_median_of_at_least_24_units_in_at_least_three_lines(quantities, bulk, quick_view):
    lines = hand_frame(*({"customer_id": 90001, "invoice": f"X{n}", "quantity": q, "invoice_date": when(2011, 7, 1, 10, n)} for n, q in enumerate(quantities)))
    found = base.covariates(base.history_before(lines, MONDAY), np.array([90001]), MONDAY, quick_view).iloc[0]
    assert int(found["bulk"]) == bulk, quantities


def test_the_two_numbers_of_the_bulk_rule_come_from_the_configuration(quick_view):
    lines = hand_frame(*({"customer_id": 90001, "invoice": f"X{n}", "quantity": q, "invoice_date": when(2011, 7, 1, 10, n)} for n, q in enumerate([6, 6])))

    def bulk(median, count):
        view = dataclasses.replace(quick_view, base=dataclasses.replace(quick_view.base, bulk_min_median_qty=median, bulk_min_lines=count))
        return int(base.covariates(lines, np.array([90001]), MONDAY, view).iloc[0]["bulk"])

    assert (bulk(24, 3), bulk(6, 3), bulk(6, 2), bulk(7, 2), bulk(6, 1)) == (0, 0, 1, 0, 1)


def test_the_median_counts_the_lines_of_the_year_and_not_the_older_ones(quick_view):
    lines = hand_frame(
        *({"customer_id": 90001, "invoice": f"O{n}", "quantity": 1, "invoice_date": when(2010, 3, 1, 10, n)} for n in range(5)),     # older than the year: small lines
        *({"customer_id": 90001, "invoice": f"N{n}", "quantity": 30, "invoice_date": when(2011, 7, 1, 10, n)} for n in range(3)))
    found = base.covariates(base.history_before(lines, MONDAY), np.array([90001]), MONDAY, quick_view).iloc[0]
    assert int(found["bulk"]) == 1 and found["invoices_before"] == 8 and found["invoices_365"] == 3


# --- segments ------------------------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("bulk, invoices, segment", [(1, 1, "bulk|one_invoice"), (1, 2, "bulk|repeat"), (1, 40, "bulk|repeat"), (0, 1, "retail|one_invoice"),
                                                     (0, 2, "retail|repeat"), (0, 9, "retail|repeat")])
def test_a_segment_is_the_bulk_flag_and_whether_the_customer_has_bought_before(bulk, invoices, segment):
    assert base.segment({"bulk": bulk, "invoices_before": invoices}) == segment
    assert base.segment(pd.Series({"bulk": bulk, "invoices_before": invoices, "other": 3})) == segment


def test_the_table_of_the_base_carries_a_segment_that_is_the_one_of_each_row(history, quick_view):
    table = base.base_table(history, MONDAY, quick_view)
    assert list(table.columns) == [*VIEW_COLUMNS, "segment"]
    assert table["segment"].tolist() == [EXPECTED[customer][6] for customer in table["customer_id"]]
    assert [base.segment(row) for _, row in table.iterrows()] == table["segment"].tolist()
    assert set(table["segment"]) <= {"bulk|repeat", "bulk|one_invoice", "retail|repeat", "retail|one_invoice"}


def test_the_five_covariates_of_the_balance_are_named_and_in_the_table():
    assert base.COVARIATE_COLUMNS == ("recency_days", "invoices_365", "spend_365", "tenure_days", "bulk")
    assert set(base.COVARIATE_COLUMNS) < set(VIEW_COLUMNS)


# --- no line from the round or after it (M01, D23) -----------------------------------------------------------------------------------------


def test_the_base_and_the_covariates_given_a_line_of_their_round_raise_a_leakage_error(quick_view):
    for stamp in (when(2011, 8, 1, 0, 0, 0), when(2011, 8, 1, 0, 0, 1), when(2011, 8, 5, 10, 0), when(2012, 1, 1)):
        leaky = hand_frame({"invoice_date": when(2011, 7, 1, 10, 0)}, {"invoice_date": stamp})
        for call in (lambda: base.contact_base(leaky, MONDAY, quick_view), lambda: base.covariates(leaky, np.array([90001]), MONDAY, quick_view),
                     lambda: base.base_table(leaky, MONDAY, quick_view), lambda: base.check_no_leak(leaky, MONDAY)):
            with pytest.raises(LeakageError, match="2011-08-01") as caught:
                call()
            assert isinstance(caught.value, RuntimeError) and "90001" not in str(caught.value)
    fine = hand_frame({"invoice_date": when(2011, 7, 31, 23, 59, 59)})
    base.check_no_leak(fine, MONDAY)
    base.check_no_leak(fine.iloc[0:0], MONDAY)


def test_a_history_cut_for_a_round_is_the_same_whatever_follows_it(quick_view):
    """The calendar's own rounds: the table of a round is what its Monday's history gives, and the Monday of another round gives its own."""
    first = base.base_table(base.history_before(HAND, MONDAY), MONDAY, quick_view)
    later = base.base_table(base.history_before(HAND, date(2011, 8, 8)), date(2011, 8, 8), quick_view)
    assert 90006 in later["customer_id"].tolist() and 90006 not in first["customer_id"].tolist(), "90006 bought at midnight of the first Monday: for the next round, and not for this one"
    assert math.isclose(float(later.set_index("customer_id").loc[90001, "recency_days"]), (when(2011, 8, 8) - when(2011, 8, 3, 10, 0)).total_seconds() / 86400)


# --- the base of the fixture, against a second computation made with plain loops ---------------------------------------------------------------------------


def reference(lines: pd.DataFrame, monday: date, lookback: int, bulk_median: float, bulk_lines: int) -> dict[int, tuple]:
    """What the base must hold, with no pandas aggregation: a customer's purchases are read row by row, in a dictionary."""
    cut, start = datetime.combine(monday, datetime.min.time()), datetime.combine(monday, datetime.min.time()) - timedelta(days=lookback)
    rows: dict[int, list[tuple]] = {}
    for row in lines.itertuples(index=False):
        if row.role == "purchase" and not pd.isna(row.customer_id) and row.invoice_date < cut:
            rows.setdefault(int(row.customer_id), []).append((row.invoice_date, row.invoice, int(row.quantity), float(row.price)))
    found = {}
    for customer, mine in rows.items():
        year = [r for r in mine if r[0] >= start]
        if not year:
            continue
        quantities = sorted(r[2] for r in year)
        middle = len(quantities) // 2
        median = quantities[middle] if len(quantities) % 2 else (quantities[middle - 1] + quantities[middle]) / 2
        found[customer] = (
            (cut - max(r[0] for r in mine)).total_seconds() / 86400, len({r[1] for r in year}), math.fsum(r[2] * r[3] for r in year),
            (cut - min(r[0] for r in mine)).total_seconds() / 86400, int(median >= bulk_median and len(year) >= bulk_lines), len({r[1] for r in mine}))
    return found


@pytest.mark.parametrize("settings", [(365, 24, 3), (365, 6, 2), (30, 12, 3), (100, 4, 1)])
def test_the_base_of_every_round_of_the_fixture_is_what_a_second_computation_gives(settings, fixture_lines, quick_view, quick_cfg):
    from personaloffers import calendar as cal

    lookback, median, count = settings
    view = dataclasses.replace(quick_view, base=dataclasses.replace(quick_view.base, lookback_days=lookback, bulk_min_median_qty=median, bulk_min_lines=count))
    mondays = [monday for period in cal.PERIODS for monday in cal.rounds(quick_cfg, period)]
    sizes, bulks = [], 0
    for monday in mondays:
        table = base.base_table(base.history_before(fixture_lines, monday), monday, view)
        expected = reference(fixture_lines, monday, lookback, median, count)
        assert table["customer_id"].tolist() == sorted(expected), monday
        for row in table.itertuples(index=False):
            recency, invoices, spend, tenure, bulk, before = expected[row.customer_id]
            assert (row.invoices_365, row.bulk, row.invoices_before) == (invoices, bulk, before)
            assert row.recency_days == pytest.approx(recency, rel=1e-12) and row.tenure_days == pytest.approx(tenure, rel=1e-12) and row.spend_365 == pytest.approx(spend, rel=1e-12)
        sizes.append(len(table))
        bulks += int(table["bulk"].sum())
    assert min(sizes) > 20, "the base of each round has customers"
    assert sizes == sorted(sizes) or settings[0] < 365, "the base grows as the history does (with the whole year in reach)"
    if settings[1] <= 6:
        assert bulks > 0, "a looser rule finds bulk buyers in the fixture, so the comparison covers the flag"
