"""The marts that hide small cells (U15; AC26; decision D30; risk item 3), on tables written by hand: the primary rule (a cell with fewer customers than the minimum is empty), the secondary rule of project 04 (a group
that would hide only one cell hides its smallest shown one too, because a published total would give the hidden one back by subtraction) and the columns that go together. The fixture's cells are too few and too
alike to reach each branch."""

from __future__ import annotations

import sqlite3

import pytest

from personaloffers import warehouse

MARTS = warehouse.SQL_DIR / "marts" / "powerbi"
ROUND = "R2011-03-28"


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.execute("PRAGMA foreign_keys=OFF")
    warehouse.apply_schema(connection)
    connection.execute("CREATE TABLE ref_round (round_key TEXT PRIMARY KEY, monday TEXT, period TEXT, days_observed INTEGER, buyers_outside_base INTEGER, followed INTEGER)")
    connection.execute("CREATE TABLE ref_week_purchase (round_id TEXT, customer_id INTEGER, stock_code TEXT)")
    yield connection
    connection.close()


def run(conn, name, minimum):
    warehouse.run_sql_file(conn, MARTS / name, {"min_cell_customers": minimum})


def add_round(conn, round_id=ROUND, followed=1, outside=0):
    conn.execute("INSERT INTO ref_round VALUES (?, ?, 'test', 7, ?, ?)", (round_id, round_id[1:], outside, followed))


# --- the operation of a round: the parts of a total go together -------------------------------------------------------------------------------------------------------


def ops(conn, **row):
    values = {"base": 100, "offer": 80, "control": 20, "new_assignments": 15, "delivered": 80, "outside": 12, **row}
    add_round(conn, outside=values["outside"])
    conn.execute("INSERT INTO round_ops VALUES (?, ?, ?, ?, ?, ?, ?, 0.1, 1.5, 'run-1')", (ROUND, values["base"], values["offer"], values["control"], values["new_assignments"], values["base"], values["delivered"]))
    run(conn, "mart_12_fact_round_ops.sql", 10)
    return conn.execute("SELECT base, offer, control, new_assignments, delivered, buyers_outside_base, suppressed FROM star_fact_round_ops").fetchone()


def test_a_round_with_every_cell_big_enough_is_published_whole(conn):
    assert ops(conn) == (100, 80, 20, 15, 80, 12, 0)


def test_a_small_control_group_hides_both_parts_of_the_base_and_what_was_delivered_but_not_the_base(conn):
    assert ops(conn, offer=95, control=5, delivered=95) == (100, None, None, 15, None, 12, 1), "the control group is under 10: the base minus the offer would give it back"


def test_a_small_offer_group_hides_both_parts_too(conn):
    assert ops(conn, base=14, offer=7, control=7, delivered=7, new_assignments=11, outside=11) == (14, None, None, 11, None, 11, 1)


def test_a_small_base_hides_every_part_and_a_small_independent_count_hides_only_itself(conn):
    assert ops(conn, base=9, offer=5, control=4, delivered=5) == (None, None, None, 15, None, 12, 1)


def test_a_delivery_under_the_minimum_with_a_big_offer_is_hidden_alone(conn):
    assert ops(conn, delivered=3) == (100, 80, 20, 15, None, 12, 1)


def test_a_count_of_new_customers_or_of_buyers_outside_that_is_zero_is_hidden_as_any_cell_under_the_minimum(conn):
    assert ops(conn, new_assignments=0, outside=0) == (100, 80, 20, None, 80, None, 1)


# --- the follow-up of a round: a group never hides just one ---------------------------------------------------------------------------------------------------


def customers(conn, group, segment, count, buyers, listed, round_id=ROUND, start=1000):
    """`count` customers of a group and a segment in the base of the round; the first `buyers` bought, and the first `listed` of them bought a product of their list."""
    base = start + conn.execute("SELECT COUNT(*) FROM contact_base").fetchone()[0]
    for n in range(count):
        customer = base + n
        conn.execute("INSERT INTO contact_base VALUES (?, ?, 5.0, 2, 10.0, 30.0, 0, 2, ?)", (round_id, customer, segment))
        conn.execute("INSERT INTO holdout_assignments VALUES (?, ?, 'stratified', 0, ?, 'run-1')", (customer, group, round_id))
        if conn.execute("SELECT followed FROM ref_round WHERE round_key = ?", (round_id,)).fetchone()[0]:
            conn.execute("INSERT INTO round_outcomes VALUES (?, ?, ?, ?, ?, ?, 7, 'run-1')", (round_id, customer, int(n < buyers), 1 if n < buyers else 0, 1 if n < listed else 0, "12.50" if n < buyers else "0"))


def group_rows(conn, minimum):
    run(conn, "mart_13_fact_round_group.sql", minimum)
    return {(r[0], r[1], r[2]): r[3:] for r in conn.execute("SELECT round_key, group_key, segment_key, customers, buyers, buyers_of_listed, spend, suppressed FROM star_fact_round_group")}


def test_a_group_with_nothing_small_publishes_every_segment(conn):
    add_round(conn)
    customers(conn, "offer", "retail|repeat", 40, 20, 12)
    customers(conn, "offer", "bulk|repeat", 30, 15, 11)
    rows = group_rows(conn, 10)
    assert rows[(ROUND, "offer", "retail|repeat")] == (40, 20, 12, 250.0, 0) and rows[(ROUND, "offer", "bulk|repeat")] == (30, 15, 11, 187.5, 0)


def test_a_segment_with_few_customers_or_few_buyers_or_few_buyers_of_a_listed_product_is_hidden_whole(conn):
    add_round(conn)
    customers(conn, "offer", "retail|repeat", 40, 20, 12)
    customers(conn, "offer", "bulk|repeat", 8, 8, 8)             # too few customers
    customers(conn, "offer", "bulk|one_invoice", 30, 6, 6)       # too few buyers
    customers(conn, "offer", "retail|one_invoice", 30, 20, 4)    # too few buyers of a listed product
    rows = group_rows(conn, 10)
    hidden = (None, None, None, None, 1)
    assert rows[(ROUND, "offer", "bulk|repeat")] == hidden and rows[(ROUND, "offer", "bulk|one_invoice")] == hidden and rows[(ROUND, "offer", "retail|one_invoice")] == hidden
    assert rows[(ROUND, "offer", "retail|repeat")] == (40, 20, 12, 250.0, 0), "three cells are hidden: no one of them can be recovered, so the shown one stays"


def test_a_group_with_exactly_one_hidden_segment_hides_its_smallest_shown_one_too(conn):
    add_round(conn)
    customers(conn, "offer", "retail|repeat", 60, 30, 20)
    customers(conn, "offer", "bulk|repeat", 25, 12, 11)
    customers(conn, "offer", "bulk|one_invoice", 40, 15, 10)
    customers(conn, "offer", "retail|one_invoice", 6, 6, 6)       # the only one under the minimum
    rows = group_rows(conn, 10)
    shown = {k[2]: v for k, v in rows.items() if not v[4]}
    assert set(shown) == {"retail|repeat", "bulk|one_invoice"} and rows[(ROUND, "offer", "bulk|repeat")][4] == 1, "the smallest shown (25 customers) goes with the one that was small"
    assert rows[(ROUND, "offer", "bulk|repeat")][:4] == (None, None, None, None)


def test_the_groups_are_protected_one_at_a_time_and_a_group_with_two_hidden_hides_no_third(conn):
    add_round(conn)
    customers(conn, "offer", "retail|repeat", 60, 30, 20)
    customers(conn, "offer", "bulk|repeat", 25, 12, 11)
    customers(conn, "offer", "bulk|one_invoice", 5, 5, 5)
    customers(conn, "offer", "retail|one_invoice", 6, 6, 6)       # two hidden: no one is given back
    customers(conn, "control", "retail|repeat", 50, 25, 15)
    customers(conn, "control", "bulk|repeat", 20, 11, 10)         # the control group has nothing small
    rows = group_rows(conn, 10)
    assert [rows[(ROUND, "offer", s)][4] for s in ("bulk|one_invoice", "bulk|repeat", "retail|one_invoice", "retail|repeat")] == [1, 0, 1, 0]
    assert [rows[(ROUND, "control", s)][4] for s in ("bulk|repeat", "retail|repeat")] == [0, 0]


def test_a_tie_for_the_smallest_shown_cell_goes_to_the_lowest_key(conn):
    add_round(conn)
    customers(conn, "offer", "retail|repeat", 60, 30, 20)
    customers(conn, "offer", "bulk|repeat", 25, 12, 11)
    customers(conn, "offer", "bulk|one_invoice", 25, 12, 11)
    customers(conn, "offer", "retail|one_invoice", 3, 3, 3)
    rows = group_rows(conn, 10)
    assert rows[(ROUND, "offer", "bulk|one_invoice")][4] == 1 and rows[(ROUND, "offer", "bulk|repeat")][4] == 0, "of two shown cells with 25 customers, the lower key is hidden"


def test_a_round_whose_week_has_not_arrived_has_customers_and_no_buyers(conn):
    add_round(conn, followed=0)
    customers(conn, "offer", "retail|repeat", 40, 0, 0)
    assert group_rows(conn, 10)[(ROUND, "offer", "retail|repeat")] == (40, None, None, None, 0)


# --- the products offered: rows that are left out, and the second one --------------------------------------------------------------------------------------------


def products(conn, minimum, offered: dict[str, int], bought: dict[str, int], followed=1):
    """Each product offered to the customers of the offer group (the first `n` customers get it as rank 1... one product a rank) and bought by the first `bought` of them."""
    add_round(conn, followed=followed)
    for code, n in offered.items():
        for c in range(n):
            customer = 5000 + c
            rank = 1 + sorted(offered).index(code)
            conn.execute("INSERT INTO offer_lists VALUES (?, ?, ?, ?, 'repeat', 1.0, 'offer', 'run-1')", (ROUND, customer, rank, code))
            if c < bought.get(code, 0):
                conn.execute("INSERT INTO ref_week_purchase VALUES (?, ?, ?)", (ROUND, customer, code))
    conn.execute("INSERT INTO offer_lists VALUES (?, 9999, 1, 'CTRL', 'repeat', 1.0, 'control', 'run-1')", (ROUND,))
    run(conn, "mart_14_fact_offer_product.sql", minimum)
    return {r[0]: r[1:] for r in conn.execute("SELECT product_key, offered_to, bought_by, suppressed FROM star_fact_offer_product ORDER BY product_key")}


def test_a_product_offered_to_few_customers_has_no_row_and_the_control_group_is_not_offered_anything(conn):
    assert products(conn, 10, {"A": 30, "B": 20, "C": 4, "D": 3}, {"A": 15, "B": 12}) == {"A": (30, 15, 0), "B": (20, 12, 0)}, "two rows left out: nobody is given back"


def test_a_round_with_exactly_one_row_left_out_leaves_out_the_smallest_shown_row_too(conn):
    assert products(conn, 10, {"A": 30, "B": 20, "C": 14, "D": 3}, {"A": 15, "B": 12, "C": 11}) == {"A": (30, 15, 0), "B": (20, 12, 0)}, "D (3) is left out and C, the smallest shown, goes with it"


def test_the_purchases_of_a_product_are_hidden_when_they_are_few_and_for_a_round_whose_week_has_not_arrived(conn):
    assert products(conn, 10, {"A": 30, "B": 20, "C": 25}, {"A": 15, "B": 4, "C": 0}) == {"A": (30, 15, 0), "B": (20, None, 1), "C": (25, None, 1)}


def test_a_round_whose_week_has_not_arrived_has_offers_and_no_purchases(conn):
    assert products(conn, 10, {"A": 30, "B": 20}, {}, followed=0) == {"A": (30, None, 0), "B": (20, None, 0)}
