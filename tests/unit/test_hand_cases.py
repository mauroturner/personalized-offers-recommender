"""The cases worked out by hand (U03): each one is checked here against a second, independent computation (the standard library, Fractions, closed forms, an
enumeration, a small ALS in numpy), so a typo in a case is found before a unit trusts it. The code under test is never used."""

from __future__ import annotations

import itertools
import math
from datetime import timedelta
from fractions import Fraction
from statistics import NormalDist

import numpy as np
import pytest

from tests.fixtures import hand_cases as h

# --- popularity and own repeats -------------------------------------------------------------------------------------------


def test_the_popularity_cases_count_invoices_before_the_monday_and_an_invoice_once():
    before = [line for line in h.POPULARITY_HISTORY if line[2] < h.POPULARITY_MONDAY]
    assert len(before) == len(h.POPULARITY_HISTORY) - 1, "only the line after the Monday is left out"
    whole: dict[str, set] = {}
    recent: dict[str, set] = {}
    for invoice, _customer, day, product in before:
        whole.setdefault(product, set()).add(invoice)
        if day >= h.POPULARITY_MONDAY - timedelta(days=28):
            recent.setdefault(product, set()).add(invoice)
    assert {product: len(invoices) for product, invoices in whole.items()} == h.GLOBAL_POPULARITY
    assert {product: len(invoices) for product, invoices in recent.items()} == h.RECENT_POPULARITY_28_DAYS
    assert h.POPULARITY_HISTORY.count(("I2", 2, h.POPULARITY_HISTORY[2][2], "A")) == 2, "a line twice in an invoice is there to be counted once"


def test_the_repeat_scores_are_the_invoices_plus_half_the_relative_recency_and_the_order_breaks_ties_by_popularity():
    reference = h.POPULARITY_MONDAY - timedelta(days=90)
    assert reference.isoformat() == "2011-05-03"
    purchases: dict[tuple, dict[str, object]] = {}
    for invoice, customer, day, product in h.POPULARITY_HISTORY:
        if customer is None or day >= h.POPULARITY_MONDAY:
            continue
        entry = purchases.setdefault((customer, product), {"invoices": set(), "last": day})
        entry["invoices"].add(invoice)
        entry["last"] = max(entry["last"], day)
    scores = {key: len(entry["invoices"]) + Fraction(1, 2) * Fraction((entry["last"] - reference).days, 90) for key, entry in purchases.items()}
    assert scores == h.REPEAT_SCORES
    assert float(scores[(4, "D")]) == 0.65 and scores[(4, "D")] < 1, "the recency term is not clamped: an old purchase scores below one invoice"
    for customer, order in h.REPEAT_ORDER.items():
        ranked = sorted((product for (who, product) in scores if who == customer), key=lambda p: (-scores[(customer, p)], -h.GLOBAL_POPULARITY[p], p))
        assert tuple(ranked) == order, customer


# --- association rules ------------------------------------------------------------------------------------------------------


def test_the_rule_cases_are_the_counts_confidences_and_lifts_of_five_baskets():
    baskets = [set(basket) for basket in h.RULE_BASKETS]
    items = {item: sum(item in basket for basket in baskets) for item in "ABCD"}
    pairs = {(a, b): sum(a in basket and b in basket for basket in baskets) for a, b in itertools.combinations("ABCD", 2)}
    assert items == h.RULE_ITEM_COUNTS and pairs == h.RULE_PAIR_COUNTS
    rules = {}
    for (a, b), together in pairs.items():
        for x, y in ((a, b), (b, a)):
            rules[(x, y)] = (together, Fraction(together, items[x]), Fraction(together * len(baskets), items[x] * items[y]))
    assert rules == h.RULES and len(rules) == 12
    for (minimum, lift), kept in h.RULES_KEPT.items():
        assert kept == {pair for pair, (support, _confidence, value) in rules.items() if support >= minimum and value > lift}, (minimum, lift)
    assert {pair for pair, (_s, _c, value) in rules.items() if value > 1} == {("B", "D"), ("D", "B")}


def test_the_rule_scores_are_the_highest_confidence_from_a_product_the_customer_bought():
    kept = {pair: rules[1] for pair, rules in h.RULES.items() if pair in h.RULES_KEPT[(2, Fraction(0))]}
    for bought, expected in h.RULE_SCORES.items():
        scores: dict[str, Fraction] = {}
        for (antecedent, consequent), confidence in kept.items():
            if antecedent in bought and consequent not in bought:
                scores[consequent] = max(scores.get(consequent, Fraction(0)), confidence)
        assert scores == expected, bought


# --- the factorization and the similarity -----------------------------------------------------------------------------------------


def matrix() -> np.ndarray:
    x = np.zeros((6, 8))
    for customer, products in h.MATRIX_PURCHASES.items():
        x[customer, list(products)] = 1.0
    return x


def als(x: np.ndarray, factors: int = 2, regularization: float = 0.1, alpha: float = 20.0, iterations: int = 20, seed: int = 0) -> np.ndarray:
    """Hu, Koren and Volinsky's implicit ALS, written out: confidence 1 + alpha x purchase, preference 1 for a purchase."""
    rng = np.random.default_rng(seed)
    n, m = x.shape
    users, items = rng.normal(0, 0.1, (n, factors)), rng.normal(0, 0.1, (m, factors))
    confidence = 1 + alpha * x
    for _ in range(iterations):
        for u in range(n):
            users[u] = np.linalg.solve((items.T * confidence[u]) @ items + regularization * np.eye(factors), (items.T * confidence[u]) @ x[u])
        for i in range(m):
            items[i] = np.linalg.solve((users.T * confidence[:, i]) @ users + regularization * np.eye(factors), (users.T * confidence[:, i]) @ x[:, i])
    return users @ items.T


def test_the_matrix_cases_cosine_scores_the_missing_product_and_zero_across_the_blocks():
    x = matrix()
    norms = np.linalg.norm(x, axis=0)
    similarity = (x.T @ x) / np.outer(norms, norms)
    np.fill_diagonal(similarity, 0.0)
    assert similarity[3, 1] == pytest.approx(2 / math.sqrt(6)) and similarity[3, 0] == pytest.approx(0.5) and similarity[3, 2] == pytest.approx(0.5)
    scores = x @ similarity
    for customer, missing in h.MATRIX_MISSING.items():
        block = range(0, 4) if customer < 3 else range(4, 8)
        unseen = [j for j in range(8) if x[customer, j] == 0]
        assert missing in block and sorted(set(block) - set(h.MATRIX_PURCHASES[customer])) == [missing]
        assert max(unseen, key=lambda j: scores[customer, j]) == missing
        assert scores[customer, missing] == pytest.approx(h.COSINE_TOP_SCORE) and h.COSINE_TOP_SCORE == pytest.approx(1 + 2 / math.sqrt(6))
        assert all(scores[customer, j] == 0.0 for j in unseen if j != missing), "the other block never mixes"


@pytest.mark.parametrize("seed", range(4))
def test_the_matrix_cases_als_puts_the_missing_product_of_its_block_first_whatever_the_start(seed):
    x = matrix()
    scores = als(x, seed=seed)
    for customer, missing in h.MATRIX_MISSING.items():
        unseen = [j for j in range(8) if x[customer, j] == 0]
        assert max(unseen, key=lambda j: scores[customer, j]) == missing


# --- the list ---------------------------------------------------------------------------------------------------------------------


def build_list(repeat: dict[int, float], discovery: dict[int, float], fallback: tuple[int, ...], k: int = 10, slots: int = 7) -> list[tuple[int, str]]:
    """D10 written again: up to seven own products by repeat score, then products never bought with a discovery score above 0 (the best first) up to k, then the
    fallback in its order without repeating."""
    own = sorted(repeat, key=lambda p: -repeat[p])[:slots]
    chosen = [(p, "repeat") for p in own]
    taken = set(own)
    for product in sorted((p for p in discovery if p not in repeat and discovery[p] > 0), key=lambda p: -discovery[p]):
        if len(chosen) < k:
            chosen.append((product, "discovery"))
            taken.add(product)
    for product in fallback:
        if len(chosen) < k and product not in taken:
            chosen.append((product, "fallback"))
            taken.add(product)
    return chosen


@pytest.mark.parametrize("name", sorted(h.LIST_CASES))
def test_each_list_case_is_the_rule_of_the_decision_and_has_ten_distinct_products(name):
    case = h.LIST_CASES[name]
    expected = build_list(case["repeat"], case["discovery"], h.LIST_FALLBACK)
    assert expected == case["expected"]
    assert len(expected) == 10 and len({product for product, _source in expected}) == 10
    assert sum(source == "repeat" for _p, source in expected) == min(7, len(case["repeat"]))
    assert all(product not in case["repeat"] for product, source in expected if source == "discovery"), "a discovery product is never one the customer bought"
    assert sorted(h.LIST_FALLBACK) == list(range(12)), "the fallback holds every product once"


def test_the_ties_go_to_the_popular_product_and_then_to_the_lower_code():
    ranked = sorted(h.TIE_SCORES, key=lambda p: (-h.TIE_SCORES[p], -h.TIE_POPULARITY[p], p))
    assert tuple(ranked) == h.TIE_ORDER == (6, 4, 5)


# --- the metrics ------------------------------------------------------------------------------------------------------------------


def metrics(listed: tuple[str, ...], bought: tuple[str, ...], k: int) -> tuple[float, float, float, float]:
    wanted = set(bought)
    hits = [product in wanted for product in listed[:k]]
    dcg = sum(1 / math.log2(rank + 1) for rank, hit in enumerate(hits, start=1) if hit)
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(len(wanted), k) + 1))
    return (float(any(hits)), sum(hits) / len(wanted), sum(hits) / k, dcg / ideal)


def test_the_metric_cases_use_sets_for_hit_and_recall_and_the_order_only_for_ndcg():
    results = {customer: metrics(h.METRIC_LISTS[customer], h.METRIC_BOUGHT[customer], h.METRIC_K) for customer in h.METRIC_LISTS}
    for customer, expected in h.METRIC_EXPECTED.items():
        assert results[customer] == pytest.approx(expected, abs=1e-15), customer
    assert tuple(np.mean(list(results.values()), axis=0)) == pytest.approx(h.METRIC_MEANS, abs=1e-15)
    assert len(h.METRIC_BOUGHT["u1"]) == 4 and len(set(h.METRIC_BOUGHT["u1"])) == 3, "one product is bought twice: the recall counts it once"
    # the same products in another order: hit and recall do not change, NDCG does
    reordered = metrics(("e", "d", "c", "b", "a"), h.METRIC_BOUGHT["u1"], h.METRIC_K)
    assert reordered[:3] == pytest.approx(results["u1"][:3]) and reordered[3] != pytest.approx(results["u1"][3])
    listed = {product for products in h.METRIC_LISTS.values() for product in products}
    assert len(listed) == 12 and len(listed) / h.METRIC_CATALOGUE == h.METRIC_COVERAGE


@pytest.mark.parametrize(("hits", "pairs", "interval"), h.WILSON_CASES)
def test_the_wilson_cases(hits, pairs, interval):
    z = NormalDist().inv_cdf(0.975)
    p = hits / pairs
    centre, spread = p + z * z / (2 * pairs), z * math.sqrt(p * (1 - p) / pairs + z * z / (4 * pairs * pairs))
    low, high = (centre - spread) / (1 + z * z / pairs), (centre + spread) / (1 + z * z / pairs)
    assert (low, high) == pytest.approx(interval, abs=1e-12)


def test_the_resampling_case_moves_every_pair_of_a_customer_together():
    by_customer: dict[str, list[tuple[int, int]]] = {}
    for customer, hit_list, hit_baseline in h.RESAMPLE_PAIRS:
        by_customer.setdefault(customer, []).append((hit_list, hit_baseline))
    drawn = [pair for customer in h.RESAMPLE_DRAW for pair in by_customer[customer]]
    assert len(drawn) == 5
    mean_list, mean_baseline = sum(a for a, _b in drawn) / len(drawn), sum(b for _a, b in drawn) / len(drawn)
    assert (mean_list, mean_baseline, mean_list - mean_baseline) == pytest.approx(h.RESAMPLE_EXPECTED)


# --- the experiment ---------------------------------------------------------------------------------------------------------------


def test_the_smd_case_uses_the_sample_variances():
    control, offer = np.array(h.SMD_CONTROL), np.array(h.SMD_OFFER)
    assert (offer.var(ddof=1), control.var(ddof=1)) == pytest.approx((35 / 3, 20 / 3))
    assert (offer.mean() - control.mean()) / math.sqrt((offer.var(ddof=1) + control.var(ddof=1)) / 2) == pytest.approx(h.SMD_EXPECTED, abs=1e-15)


def test_the_cuped_case_adjusts_by_the_slope_of_the_earlier_period_and_cuts_the_variance():
    x, y = np.array(h.CUPED_X), np.array(h.CUPED_Y)
    theta = float(np.sum((x - x.mean()) * (y - y.mean())) / np.sum((x - x.mean()) ** 2))
    assert theta == pytest.approx(33.5 / 17.5)
    assert theta == pytest.approx(h.CUPED_THETA, abs=1e-15)
    adjusted = y - theta * (x - x.mean())
    assert tuple(adjusted) == pytest.approx(h.CUPED_ADJUSTED, abs=1e-12)
    assert adjusted.mean() == pytest.approx(y.mean()) and y.var(ddof=1) == pytest.approx(13.1) and adjusted.var(ddof=1) < 0.3


def test_the_permutation_case_enumerates_the_assignments_that_keep_each_stratum_s_control_count():
    customers = sorted(h.PERMUTATION_STRATA)

    def difference(control: set[int]) -> float:
        offer = [h.PERMUTATION_Y[c] for c in customers if c not in control]
        return float(np.mean(offer) - np.mean([h.PERMUTATION_Y[c] for c in control]))

    assert difference(set(h.PERMUTATION_CONTROL)) == h.PERMUTATION_DIFFERENCE == -3.0
    strata = {s: [c for c in customers if h.PERMUTATION_STRATA[c] == s] for s in set(h.PERMUTATION_STRATA.values())}
    assignments = [set(a) | set(b) for a in itertools.combinations(strata[1], 2) for b in itertools.combinations(strata[2], 2)]
    assert len(assignments) == h.PERMUTATION_ASSIGNMENTS == 36
    as_far = sum(abs(difference(control)) >= abs(h.PERMUTATION_DIFFERENCE) - 1e-12 for control in assignments)
    assert as_far == h.PERMUTATION_AS_EXTREME and Fraction(as_far, len(assignments)) == h.PERMUTATION_P == Fraction(5, 18)
    assert {frozenset(a) for a in assignments} >= {frozenset(h.PERMUTATION_CONTROL)}


def test_the_minimum_detectable_effect_cases_are_the_researchs_figures():
    normal = NormalDist()
    z = (normal.inv_cdf(1 - 0.05 / 2), normal.inv_cdf(0.80))
    assert z == pytest.approx(h.MDE_Z, abs=1e-12)
    for sd, offered, control, expected in h.MDE_CASES:
        assert sum(z) * sd * math.sqrt(1 / offered + 1 / control) == pytest.approx(expected, rel=1e-12)
    assert offered + control == 4320 and control / 4320 == 0.2
    assert round(h.MDE_CASES[0][3] * 100, 2) == 0.71 and round(h.MDE_CASES[1][3], 2) == 164.22


# --- the choice -------------------------------------------------------------------------------------------------------------------


def choose(candidates, tolerance: float) -> str:
    """D12 written again: those within the tolerance of the best hit, the highest coverage, the lowest weight, the simplest base, the smallest size."""
    best = max(candidate[4] for candidate in candidates)
    kept = [c for c in candidates if best - c[4] < tolerance]
    simplicity = {"rules": 0, "cosine": 1, "als": 2}
    return min(kept, key=lambda c: (-c[5], c[3], simplicity[c[1]], c[2]))[0]


@pytest.mark.parametrize(("candidates", "expected"), h.CHOICE_CASES)
def test_each_choice_case_follows_the_rule_of_the_decision(candidates, expected):
    assert choose(candidates, h.CHOICE_TOLERANCE) == expected
    assert len({candidate[0] for candidate in candidates}) == len(candidates)


def test_the_first_choice_case_keeps_the_candidate_that_covers_more_and_leaves_out_the_one_over_the_tolerance():
    candidates = h.CHOICE_CASES[0][0]
    by_hit = max(candidates, key=lambda c: c[4])
    assert by_hit[0] == "als_64_w1" and choose(candidates, h.CHOICE_TOLERANCE) != by_hit[0]
    assert choose(candidates, 0.002) == by_hit[0], "with a tolerance under the 0.4 points between them, the best hit wins"
    assert choose(candidates, 0.02) == "rules_10_w0", "and with a wide one the one that covers most does"
