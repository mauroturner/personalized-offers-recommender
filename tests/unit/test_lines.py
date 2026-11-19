"""The role of every line (U05; RF04, AC04; decision D04): the six roles in the order of the requirements, decided by the first rule that a line meets, with the
catalogue's rule for what a product code is."""

from __future__ import annotations

import dataclasses

import pandas as pd
import pytest

from personaloffers import lines as ln

ORDER = ("cancellation", "adjustment", "non_product", "bad_price", "guest_purchase", "purchase")


def frame(*rows) -> pd.DataFrame:
    """Lines from ``(invoice, stock code, quantity, price, customer or None)`` tuples: the five columns the roles read."""
    return pd.DataFrame({
        "invoice": pd.array([r[0] for r in rows], dtype="string"), "stock_code": pd.array([r[1] for r in rows], dtype="string"),
        "quantity": [r[2] for r in rows], "price": [float(r[3]) for r in rows], "customer_id": pd.array([r[4] for r in rows], dtype="Int64"),
    })


# Each case is one line and the role the order of RF04 gives it: the first rule that fits.
HAND_CASES = (
    ("489434", "85123A", 12, 2.5, 90001, "purchase"),                       # an ordinary line
    ("489434", "85123a", 12, 2.5, 90001, "purchase"),                       # the letters may be lower case
    ("489434", "15056BL", 1, 0.01, 90001, "purchase"),                      # two letters, a price of a cent
    ("489434", "47591ABC", 1, 1.0, 90001, "purchase"),                      # three letters at most
    ("489434", "47591ABCD", 1, 1.0, 90001, "non_product"),                  # four are too many
    ("489434", "8512", 1, 1.0, 90001, "non_product"),                       # four digits
    ("489434", "851234", 1, 1.0, 90001, "non_product"),                     # six digits
    ("489434", "POST", 1, 18.0, 90001, "non_product"),                      # a service code
    ("489434", "BANK CHARGES", 1, 15.0, 90001, "non_product"),
    ("489434", "DCGS0076", 1, 20.0, 90001, "non_product"),                  # the codes of D04 that are left out
    ("489434", "gift_0001_20", 1, 20.0, 90001, "non_product"),              # a voucher
    ("489434", "85123A\n", 1, 1.0, 90001, "non_product"),                   # a trailing line break is not a product code
    ("489434", "١٢٣٤٥", 1, 1.0, 90001, "non_product"),   # five Arabic-Indic digits are not the digits of a code
    ("489434", "85123A", 1, 0.0, 90001, "bad_price"),                       # a price of zero
    ("489434", "85123A", 1, -1.0, 90001, "bad_price"),                      # a negative price
    ("489434", "85123A", 0, 2.5, 90001, "bad_price"),                       # a quantity of zero
    ("489434", "85123A", -3, 2.5, 90001, "bad_price"),                      # a negative quantity outside a cancellation: damaged goods
    ("489434", "85123A", 2, 2.5, None, "guest_purchase"),                   # no customer
    ("489434", "85123A", 2, 0.0, None, "bad_price"),                        # a bad price comes before a missing customer
    ("489434", "POST", 2, 18.0, None, "non_product"),                       # and a service code before a bad price or a guest
    ("489434", "POST", -2, 0.0, None, "non_product"),
    ("C489434", "85123A", -2, 2.5, 90001, "cancellation"),                  # a cancellation is first of all
    ("C489434", "POST", -1, 18.0, None, "cancellation"),                    # even with a service code and no customer
    ("C489434", "85123A", 2, 0.0, 90001, "cancellation"),
    ("A563185", "B", 1, 11062.06, None, "adjustment"),                      # an adjustment
    ("A563185", "85123A", 1, 0.0, 90001, "adjustment"),
    ("c489434", "85123A", 2, 2.5, 90001, "purchase"),                       # only the capital C and the capital A mark an invoice
    ("a563185", "85123A", 2, 2.5, 90001, "purchase"),
    ("489434C", "85123A", 2, 2.5, 90001, "purchase"),                       # and only at the start
)


def test_each_hand_case_gets_its_role_in_order(quick_cfg):
    lines = frame(*(case[:5] for case in HAND_CASES))
    roles = ln.assign_roles(lines, quick_cfg)
    assert list(roles) == [case[5] for case in HAND_CASES]
    assert set(roles) == set(ORDER), "the hand cases hold every role"
    assert tuple(ln.ROLES) == ORDER, "the roles, in the order of RF04"


def test_the_roles_come_back_in_the_order_of_the_lines_with_their_index_and_the_input_is_untouched(quick_cfg):
    lines = frame(("1", "85123A", 1, 1.0, 90001), ("C2", "85123A", -1, 1.0, 90001), ("3", "POST", 1, 1.0, None))
    lines.index = [10, 4, 7]
    before = lines.copy()
    roles = ln.assign_roles(lines, quick_cfg)
    assert roles.index.tolist() == [10, 4, 7] and roles.tolist() == ["purchase", "cancellation", "non_product"]
    pd.testing.assert_frame_equal(lines, before)


def test_no_lines_have_no_roles(quick_cfg):
    assert ln.assign_roles(frame(), quick_cfg).tolist() == []


def test_the_rule_of_a_product_code_is_the_catalogues_not_a_constant(quick_cfg):
    lines = frame(("1", "85123A", 1, 1.0, 90001), ("2", "AB", 1, 1.0, 90001), ("3", "12345", 1, 1.0, 90001))
    assert ln.assign_roles(lines, quick_cfg).tolist() == ["purchase", "non_product", "purchase"]
    only_letters = dataclasses.replace(quick_cfg, catalogue=dataclasses.replace(quick_cfg.catalogue, product_code_regex="[A-Z]{2}"))
    assert ln.assign_roles(lines, only_letters).tolist() == ["non_product", "purchase", "non_product"]


def test_the_sealed_view_gives_the_same_roles_as_the_configuration(quick_cfg, quick_view):
    lines = frame(*(case[:5] for case in HAND_CASES))
    assert ln.assign_roles(lines, quick_view).tolist() == ln.assign_roles(lines, quick_cfg).tolist()


def test_the_roles_of_the_fixture_are_the_counts_it_worked_out_with_its_own_rules(fixture_lines, workbook):
    counts = fixture_lines["role"].value_counts().to_dict()
    truth = workbook.truth.roles
    assert {role: counts.get(role, 0) for role in ORDER} == truth
    assert all(count > 0 for count in truth.values()), "the fixture has every role"
    assert set(counts) <= set(ORDER)


def test_a_line_without_a_customer_is_never_a_purchase_and_a_purchase_always_has_one(fixture_lines):
    purchases = fixture_lines[fixture_lines["role"] == "purchase"]
    assert purchases["customer_id"].notna().all()
    guests = fixture_lines[fixture_lines["customer_id"].isna()]
    assert not (guests["role"] == "purchase").any()
    assert set(guests["role"]) <= {"cancellation", "adjustment", "non_product", "bad_price", "guest_purchase"}


def test_the_product_roles_are_the_lines_of_a_basket():
    assert ln.PRODUCT_ROLES == ("purchase", "guest_purchase")



@pytest.mark.real_data
def test_the_roles_of_the_first_rows_of_each_real_sheet_follow_the_rule_with_the_codes_the_real_file_has(project_root, quick_cfg):
    """The first 3,000 rows of each sheet (December 2009 and December 2010: nothing from the test window is read) get their roles: every purchase has a code of five digits and up to
    three letters, a customer and an invoice that does not start with C or A; the lines of the other roles do not meet that. The counts of the whole file are U21's (AC04)."""
    import re

    import openpyxl

    from personaloffers import workbook as wb

    book = openpyxl.load_workbook(project_root / "data" / "raw" / "online_retail_II.xlsx", read_only=True, data_only=True)
    try:
        raw = {"sheet": [], "source_row": [], **{key: [] for key in wb.RAW_COLUMNS[2:]}}
        for number, name in enumerate(book.sheetnames, start=1):
            for row_number, row in enumerate(book[name].iter_rows(min_row=2, max_row=3001, values_only=True), start=1):
                converted, bad = wb.convert_row(tuple(row))
                assert not bad
                raw["sheet"].append(number)
                raw["source_row"].append(row_number)
                for key, value in zip(wb.RAW_COLUMNS[2:], converted, strict=True):
                    raw[key].append(value)
    finally:
        book.close()
    frame = pd.DataFrame({
        "sheet": raw["sheet"], "source_row": raw["source_row"], "invoice": pd.array(raw["invoice"], dtype="string"), "stock_code": pd.array(raw["stock_code"], dtype="string"),
        "description": pd.array(raw["description"], dtype="string"), "quantity": raw["quantity"], "invoice_date": pd.Series(raw["invoice_date"], dtype="datetime64[us]"),
        "price": raw["price"], "customer_id": pd.array(raw["customer_id"], dtype="Int64"), "country": pd.array(raw["country"], dtype="string"),
    })
    assert frame["invoice_date"].max() < pd.Timestamp("2011-08-01")
    roles = ln.assign_roles(frame, quick_cfg)
    rule = re.compile(quick_cfg.catalogue.product_code_regex)
    purchases = frame[roles == "purchase"]
    assert len(purchases) > 3000 and purchases["customer_id"].notna().all()
    assert all(rule.fullmatch(code) for code in purchases["stock_code"]) and not purchases["invoice"].str.startswith(("C", "A")).any()
    assert not any(rule.fullmatch(code) for code in frame.loc[roles == "non_product", "stock_code"])
    assert {"purchase", "cancellation", "non_product", "guest_purchase"} <= set(roles), "the first rows of the real file have each of these roles"
    assert frame.loc[roles == "cancellation", "invoice"].str.startswith("C").all()
