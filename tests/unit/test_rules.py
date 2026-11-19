"""Association rules of pairs (U09; RF10, AC08, AC11; decision D09): support in invoices, confidence and the lift of the rule (``rule_lift``, a different thing from an offer's effect, D16),
the guest baskets that enter them, the minimum support and the strict minimum lift, the score of a product for a customer (the highest confidence from a product the customer bought) and
the confidences against mlxtend's on the fixture."""

from __future__ import annotations

from datetime import datetime
from fractions import Fraction

import numpy as np
import pandas as pd
import pytest

from personaloffers import base
from personaloffers.base import LeakageError
from personaloffers.recommend import rules
from tests.fixtures import hand_cases as hc
from tests.fixtures.hand_lines import hand_frame

CODES = np.array(["A", "B", "C", "D"])
MONDAY = hc.POPULARITY_MONDAY


def basket_history(guest_basket: int | None = None):
    """The five baskets of the hand case, one invoice each, on customers 1 to 5; the basket numbered `guest_basket` (from 0) is a guest's."""
    rows = []
    for n, basket in enumerate(hc.RULE_BASKETS):
        guest = n == guest_basket
        rows += [{"invoice": f"R{n}", "customer_id": None if guest else n + 1, "stock_code": code, "invoice_date": datetime(2011, 7, 1 + n),
                  "role": "guest_purchase" if guest else "purchase"} for code in basket]
    return hand_frame(*rows)


def rules_of(ruleset, codes=CODES):
    return {(codes[a], codes[c]): (int(s), float(k), float(lift)) for a, c, s, k, lift in zip(
        ruleset.antecedent, ruleset.consequent, ruleset.support, ruleset.confidence, ruleset.rule_lift, strict=True)}


def test_the_support_the_confidence_and_the_lift_are_the_ones_worked_out_by_hand():
    counts = rules.pair_counts(basket_history(), MONDAY, CODES)
    assert counts.item_counts.tolist() == [hc.RULE_ITEM_COUNTS[c] for c in CODES] and counts.baskets == 5
    found = rules_of(rules.select(counts, min_invoices=1, min_lift=0.0))
    assert set(found) == set(hc.RULES), "every ordered pair that appears together at least once"
    for key, (support, confidence, lift) in hc.RULES.items():
        assert found[key][0] == support, key
        assert found[key][1] == pytest.approx(float(confidence), abs=1e-12), key
        assert found[key][2] == pytest.approx(float(lift), abs=1e-12), key


@pytest.mark.parametrize(("min_invoices", "min_lift"), sorted(hc.RULES_KEPT, key=lambda k: (k[0], float(k[1]))))
def test_the_rules_that_pass_are_the_ones_of_the_hand_case(min_invoices, min_lift):
    kept = rules.select(rules.pair_counts(basket_history(), MONDAY, CODES), min_invoices=min_invoices, min_lift=float(min_lift))
    assert set(rules_of(kept)) == hc.RULES_KEPT[(min_invoices, min_lift)]


def test_the_support_is_at_least_and_the_lift_strictly_greater():
    counts = rules.pair_counts(basket_history(), MONDAY, CODES)
    assert set(rules_of(rules.select(counts, 2, 0.0))) >= {("B", "D")}, "a support exactly at the minimum passes"
    assert ("A", "C") not in rules_of(rules.select(counts, 3, 0.0)), "a support under it does not"
    assert set(rules_of(rules.select(counts, 2, 1.25))) == set(), "the lift of B -> D is exactly 1.25: it is not greater"
    assert set(rules_of(rules.select(counts, 2, 1.2499))) == {("B", "D"), ("D", "B")}


def test_a_product_never_recommends_itself_and_a_rule_needs_both_products_in_the_catalogue():
    found = rules_of(rules.select(rules.pair_counts(basket_history(), MONDAY, CODES), 1, 0.0))
    assert all(a != c for a, c in found)
    narrower = rules.pair_counts(basket_history(), MONDAY, np.array(["C", "D"]))
    assert rules_of(rules.select(narrower, 1, 0.0), np.array(["C", "D"])) == {("C", "D"): (1, pytest.approx(1 / 3), pytest.approx(5 / 6)), ("D", "C"): (1, 0.5, pytest.approx(5 / 6))}
    assert narrower.baskets == 5, "an invoice counts as a basket whatever its products: the lift is the one of the five baskets even though two of them hold neither C nor D"


def test_guest_baskets_enter_the_rules():
    """AC08: the guest's basket is a basket for the pairs, the counts and the lift; take it out (make it a service code) and the numbers move."""
    with_guest = rules.pair_counts(basket_history(guest_basket=3), MONDAY, CODES)
    assert with_guest.baskets == 5 and with_guest.item_counts.tolist() == [4, 4, 3, 2]
    assert rules_of(rules.select(with_guest, 2, 1.0)) == {("B", "D"): (2, 0.5, 1.25), ("D", "B"): (2, 1.0, 1.25)}
    history = basket_history(guest_basket=3)
    history.loc[history["invoice"] == "R3", "role"] = "non_product"
    without = rules.pair_counts(history, MONDAY, CODES)
    assert without.baskets == 4 and without.item_counts.tolist() == [4, 3, 2, 1]


def test_only_the_lines_of_a_basket_count_not_a_cancellation_or_a_bad_price():
    history = basket_history()
    extra = hand_frame(*({"invoice": f"X{n}", "customer_id": 9, "stock_code": code, "invoice_date": datetime(2011, 7, 10), "role": role}
                         for n, (code, role) in enumerate((("A", "cancellation"), ("B", "cancellation"), ("C", "bad_price"), ("D", "adjustment")))))
    both = pd.concat([history, extra], ignore_index=True)
    assert rules.pair_counts(both, MONDAY, CODES).item_counts.tolist() == [4, 4, 3, 2]
    assert rules.pair_counts(both, MONDAY, CODES).baskets == 5


def test_an_invoice_that_repeats_a_product_counts_the_pair_once():
    history = hand_frame(*({"invoice": "T1", "customer_id": 1, "stock_code": code, "invoice_date": datetime(2011, 7, 1)} for code in ("A", "A", "B")),
                         {"invoice": "T2", "customer_id": 2, "stock_code": "A", "invoice_date": datetime(2011, 7, 2)})
    counts = rules.pair_counts(history, MONDAY, np.array(["A", "B"]))
    assert counts.item_counts.tolist() == [2, 1] and counts.baskets == 2
    assert rules_of(rules.select(counts, 1, 0.0), np.array(["A", "B"])) == {("A", "B"): (1, 0.5, 1.0), ("B", "A"): (1, 1.0, 1.0)}


def test_the_score_of_a_product_is_the_highest_confidence_from_a_product_the_customer_bought():
    ruleset = rules.select(rules.pair_counts(basket_history(), MONDAY, CODES), min_invoices=2, min_lift=0.0)
    seen = np.array([[1, 0, 0, 0], [0, 1, 0, 0], [1, 0, 0, 1]], dtype=bool)
    scores = rules.score_matrix(ruleset, seen)
    assert scores.shape == (3, 4) and scores.dtype == np.float32
    for row, key in enumerate((("A",), ("B",), ("A", "D"))):
        for j, code in enumerate(CODES):
            expected = float(hc.RULE_SCORES[key].get(code, Fraction(0)))
            if code in key:
                continue            # a bought product has a score of its own that nothing uses
            assert scores[row, j] == pytest.approx(expected, abs=1e-7), (key, code)
    assert scores[0].tolist()[0] == 0.0, "a product does not score from itself"


def test_a_customer_with_nothing_bought_scores_zero_everywhere():
    ruleset = rules.select(rules.pair_counts(basket_history(), MONDAY, CODES), 1, 0.0)
    assert not rules.score_matrix(ruleset, np.zeros((2, 4), dtype=bool)).any()


def test_a_history_with_a_line_of_the_round_or_later_is_refused():
    late = pd.concat([basket_history(), hand_frame({"invoice": "L", "customer_id": 1, "stock_code": "A", "invoice_date": datetime(2011, 8, 1)})], ignore_index=True)
    with pytest.raises(LeakageError, match="2011-08-01"):
        rules.pair_counts(late, MONDAY, CODES)


def test_the_arrays_of_a_rule_set_round_trip():
    ruleset = rules.select(rules.pair_counts(basket_history(), MONDAY, CODES), 1, 0.0)
    again = rules.from_arrays(rules.to_arrays(ruleset))
    assert rules_of(again) == rules_of(ruleset) and set(rules.to_arrays(ruleset)) == {"antecedent", "consequent", "support", "confidence", "rule_lift", "shape"}
    assert all(not array.dtype.hasobject for array in rules.to_arrays(ruleset).values())


def test_confidences_match_mlxtend_on_the_fixture(fixture_lines, quick_cfg, quick_view):
    """AC11: the confidence and the lift of every pair rule that passes the thresholds are mlxtend's (fpgrowth and association_rules) at 1e-9, on the guests' baskets too."""
    from mlxtend.frequent_patterns import association_rules, fpgrowth

    monday = quick_cfg.calendar.test_first_round
    history = base.history_before(fixture_lines, monday)
    basket = history[history["role"].isin(["purchase", "guest_purchase"])]
    codes = np.array(sorted(basket["stock_code"].unique()))
    min_invoices = quick_view.grid.rules_min_invoices[0]
    mine = rules_of(rules.select(rules.pair_counts(history, monday, codes), min_invoices, 0.0), codes)
    invoices = basket.groupby("invoice")["stock_code"].apply(set)
    onehot = pd.DataFrame([[code in items for code in codes] for items in invoices], columns=codes)
    itemsets = fpgrowth(onehot, min_support=(min_invoices - 0.5) / len(onehot), use_colnames=True, max_len=2)
    theirs_table = association_rules(itemsets, num_itemsets=len(onehot), metric="confidence", min_threshold=0.0)
    theirs = {(next(iter(a)), next(iter(c))): (conf, lift) for a, c, conf, lift in zip(
        theirs_table["antecedents"], theirs_table["consequents"], theirs_table["confidence"], theirs_table["lift"], strict=True)}
    assert len(mine) > 30 and set(mine) == set(theirs), "the same pairs"
    for key, (support, confidence, lift) in mine.items():
        assert support >= min_invoices
        assert confidence == pytest.approx(theirs[key][0], abs=1e-9), key
        assert lift == pytest.approx(theirs[key][1], abs=1e-9), key


def test_the_minimum_support_comes_from_the_call_and_changes_the_rules(fixture_lines, quick_cfg):
    monday = quick_cfg.calendar.test_first_round
    history = base.history_before(fixture_lines, monday)
    codes = np.array(sorted(history.loc[history["role"].isin(["purchase", "guest_purchase"]), "stock_code"].unique()))
    counts = rules.pair_counts(history, monday, codes)
    sizes = [len(rules.select(counts, n, 1.0).support) for n in (2, 3, 5)]
    assert sizes[0] > sizes[1] > sizes[2] > 0
