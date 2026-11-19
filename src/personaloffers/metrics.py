"""The metrics of a ranking and the intervals around them (RF18, AC21; risk item 6; decisions D08, D20; plan section 16).

For each evaluated pair (a round and a customer of its base who bought something in its week), a list of ``k`` products is compared with the distinct products that the customer bought in that week:

* **hit@k**: 1 if any product of the list was bought. The rate of a method is the mean over the pairs (D08's primary metric);
* **recall@k**: the products of the list that were bought over the distinct products bought (also those that no list could hold: they are in the denominator);
* **precision@k**: the products of the list that were bought over ``k``;
* **NDCG@k**: the discounted gain of the hits (``1 / log2(rank + 1)``) over the ideal one, the hits of ``min(bought, k)`` products at the top. It is the only one that reads the order of the list.

What was bought is a set: a product bought twice, or on two invoices, counts once (``bought_matrix``). The **coverage** of the lists of a round is the distinct products in them over the products of the
catalogue. The **Wilson** interval is informative (C10). The intervals of the criteria are **resampled by customer** (D20): a customer's pairs of all the rounds move together, a draw is ``n``
customers with replacement (their number of times is the multinomial draw ``draw_counts``), the statistic of a draw is the mean over the pairs of the drawn customers, and a paired difference of two
methods uses the same draws for both, which is what makes it narrower than two separate intervals.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist
from typing import Any

import numpy as np

Z_95 = NormalDist().inv_cdf(0.975)


@dataclass(frozen=True)
class PairMetrics:
    hit: np.ndarray
    recall: np.ndarray
    precision: np.ndarray
    ndcg: np.ndarray


@dataclass(frozen=True)
class Clusters:
    """The customers of the pairs: the sorted distinct ``ids``, the ``index`` of each pair's customer in them and the pairs of each customer (``sizes``)."""

    ids: np.ndarray
    index: np.ndarray
    sizes: np.ndarray


def bought_matrix(pair_index: np.ndarray, product_index: np.ndarray, pairs: int, products: int) -> tuple[np.ndarray, np.ndarray]:
    """``(bought, inside)``: a boolean pairs by products matrix with a True where the pair bought the product (repeated lines of one pair and product are one), and how many distinct products
    of the catalogue each pair bought. The products outside the catalogue are counted by the caller (``pair_metrics`` takes the distinct products bought, all of them)."""
    bought = np.zeros((pairs, products), dtype=bool)
    bought[np.asarray(pair_index, dtype=np.int64), np.asarray(product_index, dtype=np.int64)] = True
    return bought, bought.sum(axis=1).astype(np.int64)


def pair_metrics(lists: np.ndarray, bought: np.ndarray, test_products: np.ndarray, k: int | None = None) -> PairMetrics:
    """The four metrics of every pair. `lists` is pairs by at least `k` positions of products, best first; `bought` is the boolean matrix of ``bought_matrix``; `test_products` is the number of
    distinct products each pair bought (the recall's denominator). `k` defaults to the width of the lists. A pair that bought nothing is a ``ValueError``: it is not an evaluated pair."""
    width = lists.shape[1] if k is None else k
    shown = np.asarray(lists)[:, :width]
    wanted = np.asarray(test_products, dtype=np.int64)
    if len(wanted) and wanted.min() < 1:
        raise ValueError(f"{int((wanted < 1).sum())} pares no tienen compras en su semana: un par evaluado compró al menos un producto")
    relevant = np.take_along_axis(np.asarray(bought, dtype=bool), shown, axis=1)
    hits = relevant.sum(axis=1)
    discount = 1.0 / np.log2(np.arange(2, width + 2))
    ideal = np.cumsum(discount)[np.minimum(wanted, width) - 1] if len(wanted) else np.zeros(0)
    return PairMetrics(hit=(hits > 0).astype(np.float64), recall=hits / wanted, precision=hits / width, ndcg=(relevant * discount).sum(axis=1) / ideal)


def coverage(lists: np.ndarray, catalogue_size: int) -> float:
    """The distinct products in `lists` over the products of the catalogue."""
    return float(len(np.unique(lists)) / catalogue_size) if lists.size else 0.0


def wilson(hits: int, pairs: int, z: float = Z_95) -> tuple[float, float]:
    """The Wilson score interval of `hits` out of `pairs` (95 % by default)."""
    if pairs < 1:
        raise ValueError("el intervalo de Wilson necesita al menos un par")
    p = hits / pairs
    centre = p + z * z / (2 * pairs)
    spread = z * math.sqrt(p * (1 - p) / pairs + z * z / (4 * pairs * pairs))
    scale = 1 + z * z / pairs
    return max(0.0, (centre - spread) / scale), min(1.0, (centre + spread) / scale)


def clusters(customers: np.ndarray) -> Clusters:
    ids, index, sizes = np.unique(np.asarray(customers), return_inverse=True, return_counts=True)
    return Clusters(ids=ids, index=index, sizes=sizes)


def draw_counts(n_clusters: int, resamples: int, seed: int) -> np.ndarray:
    """``resamples`` draws of `n_clusters` customers with replacement, each as the number of times every customer was drawn (resamples by customers, ``int64``): the multinomial draw, from the
    generator of `seed`."""
    rng = np.random.default_rng(seed)
    return rng.multinomial(n_clusters, np.full(n_clusters, 1.0 / n_clusters), size=resamples).astype(np.int64)


def configured_draws(groups: Clusters, view: Any) -> np.ndarray:
    """The draws of ``[evaluation]``: its number of resamples and its seed, for these customers."""
    return draw_counts(len(groups.ids), view.evaluation.resamples, seed=view.evaluation.seed)


def resampled_means(groups: Clusters, values: np.ndarray, counts: np.ndarray) -> np.ndarray:
    """The mean of `values` over the pairs of the customers of each draw (a customer's pairs all enter as many times as it was drawn): the pairs' sum over the pairs' count."""
    totals = np.bincount(groups.index, weights=np.asarray(values, dtype=np.float64), minlength=len(groups.ids))
    return (counts @ totals) / (counts @ groups.sizes)


def paired_difference(groups: Clusters, first: np.ndarray, second: np.ndarray, counts: np.ndarray) -> np.ndarray:
    """``first - second`` of the resampled means with the same draws for both."""
    return resampled_means(groups, first, counts) - resampled_means(groups, second, counts)


def percentile_interval(statistics: np.ndarray, level: float = 0.95) -> tuple[float, float]:
    """The percentiles 2.5 and 97.5 (for the default level) of the resampled statistics."""
    tail = round(100 * (1 - level) / 2, 9)
    return float(np.percentile(statistics, tail)), float(np.percentile(statistics, 100 - tail))
