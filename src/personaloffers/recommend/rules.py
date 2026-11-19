"""Association rules of pairs of products (RF10, AC08, AC11; decision D09; plan section 9.3).

The baskets are the invoices of the history before the Monday that hold a line of a basket (a guest's basket enters, AC08; a cancellation, a service code and a bad price do not). For a pair
``X -> Y``: the **support** is the number of invoices that hold both, the **confidence** is that over the invoices that hold ``X``, and the **rule_lift** is the confidence over the share of the
invoices that hold ``Y`` (always called ``rule_lift``: it is not the lift of an offer, which this project never measures, D16). A rule passes when its support is at least ``min_invoices`` and its
lift is strictly greater than ``min_lift``. The score of a product for a customer is the highest confidence of a passing rule from a product the customer bought.

The counts come from a sparse co-occurrence matrix (``B.T @ B`` of the invoices by products), so nothing here is as large as the dense catalogue squared; a test compares every confidence and
lift with mlxtend's (``fpgrowth`` and ``association_rules``) on the fixture at 1e-9. The counts are made once for a round and ``select`` is cheap, so the grid of minimum supports shares them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
import scipy.sparse as sp

from personaloffers.base import check_no_leak
from personaloffers.lines import PRODUCT_ROLES


@dataclass(frozen=True)
class PairCounts:
    """What the rules are made from: how many invoices hold each product, how many baskets there are and, for each pair of products, how many invoices hold both (the diagonal is empty)."""

    item_counts: np.ndarray        # (m,) int64
    baskets: int
    pairs: sp.csr_matrix           # (m, m) int32, symmetric, no diagonal, no zeros


@dataclass(frozen=True)
class RuleSet:
    """The rules that passed, ordered by antecedent and then consequent (positions in the catalogue of the round)."""

    antecedent: np.ndarray         # (r,) int64
    consequent: np.ndarray         # (r,) int64
    support: np.ndarray            # (r,) int64, invoices that hold both
    confidence: np.ndarray         # (r,) float64
    rule_lift: np.ndarray          # (r,) float64
    shape: int                     # the products of the catalogue


def pair_counts(history: pd.DataFrame, monday: date, codes: np.ndarray) -> PairCounts:
    """The counts of the invoices of `history` over the products `codes` (an invoice that holds a product twice counts once for it and once for each pair)."""
    check_no_leak(history, monday)
    lines = history[history["role"].isin(PRODUCT_ROLES)][["invoice", "stock_code"]].drop_duplicates()
    baskets = int(lines["invoice"].nunique())
    lines = lines[lines["stock_code"].isin(codes)]
    invoice_index, _ = pd.factorize(lines["invoice"])
    product_index = pd.Index(codes).get_indexer(lines["stock_code"])
    m = len(codes)
    incidence = sp.csr_matrix((np.ones(len(lines), dtype=np.int32), (invoice_index, product_index)), shape=(int(invoice_index.max(initial=-1)) + 1, m))
    together = (incidence.T @ incidence).tocsr()
    item_counts = together.diagonal().astype(np.int64)
    together.setdiag(0)
    together.eliminate_zeros()
    return PairCounts(item_counts=item_counts, baskets=baskets, pairs=together)


def select(counts: PairCounts, min_invoices: int, min_lift: float) -> RuleSet:
    """The rules with a support of at least `min_invoices` invoices and a lift greater than `min_lift`."""
    together = counts.pairs.tocoo()
    keep = together.data >= min_invoices
    antecedent, consequent, support = together.row[keep].astype(np.int64), together.col[keep].astype(np.int64), together.data[keep].astype(np.int64)
    confidence = support / counts.item_counts[antecedent]
    rule_lift = confidence / (counts.item_counts[consequent] / counts.baskets)
    passing = rule_lift > min_lift
    order = np.lexsort((consequent[passing], antecedent[passing]))
    return RuleSet(antecedent=antecedent[passing][order], consequent=consequent[passing][order], support=support[passing][order],
                   confidence=confidence[passing][order], rule_lift=rule_lift[passing][order], shape=len(counts.item_counts))


def score_matrix(ruleset: RuleSet, seen: np.ndarray) -> np.ndarray:
    """The score of every product for every customer of `seen` (a boolean customers by products mask of what each bought): the highest confidence of a rule whose antecedent the customer
    bought, 0 when there is none. ``float32``."""
    scores = np.zeros(seen.shape, dtype=np.float32)
    confidence = ruleset.confidence.astype(np.float32)
    starts = np.searchsorted(ruleset.antecedent, np.arange(ruleset.shape + 1))
    for product in np.unique(ruleset.antecedent):
        customers = np.flatnonzero(seen[:, product])
        if not len(customers):
            continue
        span = slice(starts[product], starts[product + 1])
        targets, values = ruleset.consequent[span], confidence[span]
        block = np.ix_(customers, targets)
        scores[block] = np.maximum(scores[block], values)
    return scores


def to_arrays(ruleset: RuleSet) -> dict[str, np.ndarray]:
    """The rules as flat arrays (what ``artifacts`` writes)."""
    return {"antecedent": ruleset.antecedent, "consequent": ruleset.consequent, "support": ruleset.support, "confidence": ruleset.confidence,
            "rule_lift": ruleset.rule_lift, "shape": np.array([ruleset.shape], dtype=np.int64)}


def from_arrays(arrays: dict[str, np.ndarray]) -> RuleSet:
    return RuleSet(antecedent=arrays["antecedent"], consequent=arrays["consequent"], support=arrays["support"], confidence=arrays["confidence"],
                   rule_lift=arrays["rule_lift"], shape=int(arrays["shape"][0]))
