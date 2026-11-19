"""The metrics of a ranking (U10, risk item 6: a wrong denominator moves every criterion and no other test would see it; RF18, AC21; decisions D08, D20): hit, recall, precision and NDCG at k
of each (round, customer) pair, the coverage of the lists, the Wilson interval and the resampling by customer that moves all the pairs of a customer together and gives a paired difference
the same draws."""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest

from personaloffers import metrics
from tests.fixtures import hand_cases as hc

PRODUCTS = "abcdefghijklmnopqrstuvwxyz"


def hand_pairs() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The three lists of the hand cases as arrays: the lists (positions of the letters), the sets bought (a product bought twice is one) and the distinct products bought."""
    users = sorted(hc.METRIC_LISTS)
    lists = np.array([[PRODUCTS.index(p) for p in hc.METRIC_LISTS[u]] for u in users])
    pair = np.array([i for i, u in enumerate(users) for _ in hc.METRIC_BOUGHT[u]])
    product = np.array([PRODUCTS.index(p) for u in users for p in hc.METRIC_BOUGHT[u]])
    return lists, pair, product


def test_hit_and_recall_use_sets_and_ndcg_uses_the_list_order_only():
    """AC21: the hand cases of the plan; u1 bought b twice and the recall counts it once; the same products in another order keep hit, recall and precision and move the NDCG."""
    lists, pair, product = hand_pairs()
    bought, counts = metrics.bought_matrix(pair, product, pairs=3, products=26)
    assert counts.tolist() == [3, 2, 1] and bought.sum(axis=1).tolist() == [3, 2, 1]
    found = metrics.pair_metrics(lists, bought, counts)
    expected = np.array([hc.METRIC_EXPECTED[u] for u in sorted(hc.METRIC_LISTS)])
    assert np.allclose(np.column_stack([found.hit, found.recall, found.precision, found.ndcg]), expected, atol=1e-15)
    assert np.allclose([found.hit.mean(), found.recall.mean(), found.precision.mean(), found.ndcg.mean()], hc.METRIC_MEANS, atol=1e-15)
    reordered = metrics.pair_metrics(lists[:, ::-1].copy(), bought, counts)
    assert np.array_equal(reordered.hit, found.hit) and np.array_equal(reordered.recall, found.recall) and np.array_equal(reordered.precision, found.precision)
    assert reordered.ndcg[0] != pytest.approx(found.ndcg[0]), "the order of the list is what NDCG measures"
    assert np.allclose(metrics.pair_metrics(lists, bought[:, :], counts).ndcg, found.ndcg), "and the order of what was bought is not"


def test_a_product_bought_in_two_invoices_of_the_week_counts_once_and_one_outside_the_catalogue_still_counts_in_the_recall_denominator():
    """The distinct products the customer bought in the week are the denominator of the recall, also those that no list could hold; only those inside the catalogue can be hit."""
    lists = np.array([[0, 1, 2]])
    bought, inside = metrics.bought_matrix(np.array([0, 0, 0]), np.array([1, 1, 5]), pairs=1, products=6)
    assert inside.tolist() == [2]
    found = metrics.pair_metrics(lists, bought, np.array([4]))      # four distinct products were bought, one of them is not in the catalogue
    assert found.hit.tolist() == [1.0] and found.recall.tolist() == [0.25] and found.precision.tolist() == [pytest.approx(1 / 3)]
    ideal = 1 + 1 / math.log2(3) + 1 / math.log2(4)
    assert found.ndcg.tolist() == [pytest.approx((1 / math.log2(3)) / ideal)], "the ideal list holds min(4, 3) hits"


def test_the_ideal_is_cut_at_k_when_more_products_were_bought_than_the_list_holds():
    lists = np.array([[0, 1]])
    bought, counts = metrics.bought_matrix(np.zeros(5, dtype=int), np.arange(5), pairs=1, products=5)
    found = metrics.pair_metrics(lists, bought, counts)
    assert found.ndcg.tolist() == [pytest.approx(1.0)] and found.recall.tolist() == [0.4] and found.precision.tolist() == [1.0]


def test_a_pair_with_nothing_bought_is_refused_not_scored():
    with pytest.raises(ValueError, match="compras"):
        metrics.pair_metrics(np.array([[0, 1]]), np.zeros((1, 3), dtype=bool), np.array([0]))


def test_k_cuts_the_list_and_is_the_denominator_of_the_precision():
    lists = np.array([[3, 1, 0, 2]])
    bought, counts = metrics.bought_matrix(np.array([0]), np.array([1]), pairs=1, products=4)
    full = metrics.pair_metrics(lists, bought, counts)
    cut = metrics.pair_metrics(lists, bought, counts, k=2)
    assert full.precision.tolist() == [0.25] and cut.precision.tolist() == [0.5]
    assert full.ndcg.tolist() == [pytest.approx(1 / math.log2(3))] and cut.ndcg.tolist() == [pytest.approx(1 / math.log2(3))]
    assert metrics.pair_metrics(lists, bought, counts, k=1).hit.tolist() == [0.0], "the product bought is the second of the list"


def test_the_coverage_is_the_distinct_products_of_the_lists_over_the_catalogue():
    lists, *_ = hand_pairs()
    assert metrics.coverage(lists, hc.METRIC_CATALOGUE) == hc.METRIC_COVERAGE
    assert metrics.coverage(np.array([[0, 1], [1, 0]]), 4) == 0.5
    assert metrics.coverage(np.zeros((0, 3), dtype=int), 4) == 0.0


@pytest.mark.parametrize(("hits", "pairs", "interval"), hc.WILSON_CASES)
def test_the_wilson_interval_of_the_hand_cases(hits, pairs, interval):
    assert metrics.wilson(hits, pairs) == pytest.approx(interval, abs=1e-12)


def test_the_wilson_interval_stays_inside_zero_and_one_and_refuses_no_pairs():
    for hits, pairs in ((0, 1), (1, 1), (3, 7), (5000, 5000)):
        low, high = metrics.wilson(hits, pairs)
        assert 0.0 <= low <= hits / pairs <= high <= 1.0
    with pytest.raises(ValueError):
        metrics.wilson(0, 0)


def test_the_resample_of_the_hand_case_moves_every_pair_of_a_customer_together():
    """RESAMPLE: the draw c1, c1, c3 of four pairs of three customers gives 5/5 for the list, 2/5 for the baseline and 3/5 for the difference."""
    customers = np.array([c for c, _a, _b in hc.RESAMPLE_PAIRS])
    listed = np.array([a for _c, a, _b in hc.RESAMPLE_PAIRS], dtype=float)
    baseline = np.array([b for _c, _a, b in hc.RESAMPLE_PAIRS], dtype=float)
    groups = metrics.clusters(customers)
    assert groups.ids.tolist() == ["c1", "c2", "c3"] and groups.sizes.tolist() == [2, 1, 1]
    counts = np.array([[2, 0, 1]])      # c1 twice, c3 once
    assert metrics.resampled_means(groups, listed, counts).tolist() == [hc.RESAMPLE_EXPECTED[0]]
    assert metrics.resampled_means(groups, baseline, counts).tolist() == [hc.RESAMPLE_EXPECTED[1]]
    assert metrics.paired_difference(groups, listed, baseline, counts).tolist() == [pytest.approx(hc.RESAMPLE_EXPECTED[2])]


def test_the_resampled_mean_equals_an_explicit_resample_of_the_customers_with_all_their_pairs():
    rng = np.random.default_rng(5)
    customers = rng.integers(0, 40, 300)
    values = (rng.random(300) < 0.4).astype(float)
    groups = metrics.clusters(customers)
    counts = metrics.draw_counts(len(groups.ids), 25, seed=3)
    found = metrics.resampled_means(groups, values, counts)
    for row in range(25):
        chosen = np.repeat(np.arange(len(groups.ids)), counts[row])
        pairs = np.concatenate([np.flatnonzero(groups.index == c) for c in chosen])
        assert found[row] == pytest.approx(values[pairs].mean(), abs=1e-12), row


def test_the_draws_are_n_customers_with_replacement_the_same_for_the_same_seed_and_other_for_another():
    counts = metrics.draw_counts(50, 200, seed=0)
    assert counts.shape == (200, 50) and (counts.sum(axis=1) == 50).all() and counts.min() >= 0
    assert np.array_equal(counts, metrics.draw_counts(50, 200, seed=0)) and not np.array_equal(counts, metrics.draw_counts(50, 200, seed=1))
    assert abs(counts.mean() - 1.0) < 1e-12 and 0.9 < counts.var(axis=0).mean() < 1.1, "a customer is drawn about once, with the variance of a draw with replacement"
    assert np.abs(counts.mean(axis=0) - 1.0).max() < 0.4, "every customer has the same chance, not only the same total"


def test_a_paired_difference_uses_the_same_draws_for_both_so_it_is_less_spread_than_two_separate_ones():
    rng = np.random.default_rng(1)
    customers = np.repeat(np.arange(200), 3)
    common = rng.random(600) < 0.5
    first = (common | (rng.random(600) < 0.1)).astype(float)
    second = (common & (rng.random(600) < 0.9)).astype(float)
    groups = metrics.clusters(customers)
    counts = metrics.draw_counts(200, 1000, seed=0)
    paired = metrics.paired_difference(groups, first, second, counts)
    separate = metrics.resampled_means(groups, first, counts) - metrics.resampled_means(groups, second, metrics.draw_counts(200, 1000, seed=9))
    assert np.array_equal(paired, metrics.resampled_means(groups, first, counts) - metrics.resampled_means(groups, second, counts))
    assert paired.std() < separate.std() * 0.8


def test_the_interval_is_the_percentiles_2_5_and_97_5_of_the_resampled_statistics():
    statistics = np.arange(1, 2001, dtype=float)
    low, high = metrics.percentile_interval(statistics)
    assert (low, high) == (np.percentile(statistics, 2.5), np.percentile(statistics, 97.5)) == (pytest.approx(50.975), pytest.approx(1950.025))
    assert metrics.percentile_interval(statistics, level=0.9) == (np.percentile(statistics, 5), np.percentile(statistics, 95))


def test_the_number_and_the_seed_of_the_resamples_come_from_the_evaluation_section_of_the_configuration(quick_view):
    groups = metrics.clusters(np.arange(30))
    counts = metrics.configured_draws(groups, quick_view)
    assert counts.shape == (quick_view.evaluation.resamples, 30)
    assert np.array_equal(counts, metrics.draw_counts(30, quick_view.evaluation.resamples, seed=quick_view.evaluation.seed))
    other = dataclasses.replace(quick_view, evaluation=dataclasses.replace(quick_view.evaluation, seed=5, resamples=17))
    assert np.array_equal(metrics.configured_draws(groups, other), metrics.draw_counts(30, 17, seed=5)) and not np.array_equal(metrics.configured_draws(groups, other)[:1], counts[:1])
