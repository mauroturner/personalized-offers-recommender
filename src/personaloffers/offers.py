"""The list that is delivered to each customer (RF11, AC12, M06; risk item 6; decisions D10, D11; plan section 9.6).

A list has ``[recommend] k`` (10) different products, each with its **source**: up to ``repeat_slots`` (7) of the products the customer bought, by the repeat score; then, up to ``k``, products the
customer never bought, from the discovery model, by its score and only with a score above zero (at least ``discovery_slots`` of them when the model has candidates, and more when the repeats give
fewer than 7); then the fallback, the best sellers of the last 28 days in their order, skipping what the list already holds. It is the rule that the research measured (77.1 % against 79.1 % for the
repeats alone) with the 28-day fallback of D18.

**The order that breaks every tie is fixed** (D11): the score, then the global popularity, then the code. It is applied exactly, not by adding a tiny number to the scores: each score is turned into
an integer key that orders the float32 values exactly (``-0.0`` is ``0.0``, a unit of the last place is a difference) with the place of the product in the tie order below it, so a key is never equal to
another in its row and the ranking is the same whatever the order of the columns or the version of the sort. ``top_k`` is the one function that ranks; the baselines and the choice use it too.

``check_lists`` is M06: a list that does not have its ``k`` different products of the catalogue, each with a known source, is a ``ListError`` (it counts the lists and never names a customer).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import numpy as np

SOURCES = ("repeat", "discovery", "fallback")
RANK_LIMIT = 1 << 16          # the tie order has 16 bits under the score's 32: a catalogue of up to 65,535 products (the real one has about 4,600)


class ListError(RuntimeError):
    """A list does not have its products or their sources as the rule says (M06)."""


def order_keys(scores: np.ndarray, rank: np.ndarray) -> np.ndarray:
    """One ``int64`` per score, larger is better: the float32 score in the high bits (its bits turned to an order-preserving integer) and, below it, the place in the tie order."""
    scores32 = np.asarray(scores, dtype=np.float32)
    if scores32.shape[1] >= RANK_LIMIT:
        raise ValueError(f"un catálogo de {scores32.shape[1]} productos no cabe en el orden de desempate (hasta {RANK_LIMIT - 1})")
    if np.isnan(scores32).any():
        raise ValueError("un puntaje no es un número: no se puede ordenar")
    bits = (scores32 + np.float32(0)).view(np.uint32).astype(np.int64)       # adding +0.0 turns -0.0 into 0.0
    monotone = np.where(bits >> 31 == 1, (~bits) & 0xFFFFFFFF, bits | 0x80000000)
    return (monotone << 16) | (RANK_LIMIT - 1 - np.asarray(rank, dtype=np.int64))[None, :]


def top_k(scores: np.ndarray, rank: np.ndarray, k: int, eligible: np.ndarray | None = None) -> np.ndarray:
    """The `k` best products of each row, best first, by score and then the tie order `rank` (0 is the best place); with `eligible`, only the products where it is True. A row with fewer than
    `k` eligible products is padded with -1. ``int64``, rows by ``min(k, products)``."""
    keys = order_keys(scores, rank)
    if eligible is not None:
        keys = np.where(eligible, keys, -1)
    rows, products = keys.shape
    width = min(k, products)
    part = np.argpartition(keys, products - width, axis=1)[:, products - width:]
    values = np.take_along_axis(keys, part, axis=1)
    order = np.argsort(-values, axis=1, kind="stable")
    found = np.take_along_axis(part, order, axis=1).astype(np.int64)
    found[np.take_along_axis(values, order, axis=1) < 0] = -1
    return found


def build_list(repeat_scores: np.ndarray, discovery_scores: np.ndarray, seen: np.ndarray, fallback_order: np.ndarray, view: Any, *,
               tie_rank: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """The lists of the customers, one row each: ``(products, sources)``, ``int64`` positions in the catalogue and ``int8`` codes of ``SOURCES`` (0 repeat, 1 discovery, 2 fallback).

    `repeat_scores` is read only where `seen` says the customer bought the product, `discovery_scores` only where it did not and the score is above zero, and `fallback_order` is the products
    in the order of the reserve. `tie_rank` is the fixed order of the ties (``popularity.tie_rank``); without it the order of the catalogue decides them."""
    k, slots = view.recommend.k, min(view.recommend.repeat_slots, view.recommend.k)
    customers, products = repeat_scores.shape
    if products < k:
        raise ValueError(f"el catálogo tiene {products} productos y una lista necesita {k} distintos")
    rank = np.arange(products, dtype=np.int64) if tie_rank is None else tie_rank
    own = top_k(repeat_scores, rank, slots, eligible=seen) if slots > 0 else np.empty((customers, 0), dtype=np.int64)
    new = top_k(discovery_scores, rank, k, eligible=~seen & (discovery_scores > 0))
    reserve = np.tile(np.asarray(fallback_order, dtype=np.int64)[:k], (customers, 1))      # a list holds at most k products, so the first k of the reserve always have enough that it does not
    first = np.concatenate([own, new], axis=1)
    held = (reserve[:, :, None] == first[:, None, :]).any(axis=2)
    candidates = np.concatenate([first, reserve], axis=1)
    source = np.concatenate([np.zeros(own.shape, dtype=np.int8), np.ones(new.shape, dtype=np.int8), np.full(reserve.shape, 2, dtype=np.int8)], axis=1)
    valid = candidates >= 0
    valid[:, first.shape[1]:] &= ~held
    keep = valid & (np.cumsum(valid, axis=1) <= k)
    order = np.argsort(~keep, axis=1, kind="stable")[:, :k]
    chosen, origins = np.take_along_axis(candidates, order, axis=1), np.take_along_axis(source, order, axis=1)
    check_lists(chosen, origins, k, products)
    return chosen, origins


def check_lists(products: np.ndarray, sources: np.ndarray, k: int, catalogue_size: int) -> None:
    """M06: every row has `k` different products of the catalogue (0 to `catalogue_size` - 1), each with a known source; a ``ListError`` that counts the lists and never names a customer."""
    if products.ndim != 2 or products.shape[1] != k or sources.shape != products.shape:
        raise ListError(f"las listas deben tener {k} productos y tienen {products.shape[1] if products.ndim == 2 else products.shape}")
    outside = int(((products < 0) | (products >= catalogue_size)).any(axis=1).sum())
    if outside:
        raise ListError(f"{outside} listas tienen un producto que no está en el catálogo de la ronda")
    ordered = np.sort(products, axis=1)
    repeated = int((ordered[:, 1:] == ordered[:, :-1]).any(axis=1).sum())
    if repeated:
        raise ListError(f"{repeated} listas tienen productos repetidos: cada lista lleva {k} distintos")
    unknown = int(((sources < 0) | (sources >= len(SOURCES))).any(axis=1).sum())
    if unknown:
        raise ListError(f"{unknown} listas tienen un producto sin un origen conocido ({', '.join(SOURCES)})")


@dataclass(frozen=True)
class RoundLists:
    """The lists of every customer of a round: the customers, and for each of them the ``k`` products (positions in the catalogue), their sources (codes of ``SOURCES``) and their scores."""

    customers: np.ndarray        # (n,) int64
    products: np.ndarray         # (n, k) int64
    sources: np.ndarray          # (n, k) int8
    scores: np.ndarray           # (n, k) float64: the repeat score, the discovery score or the recent popularity of the product, by its source


def list_scores(products: np.ndarray, sources: np.ndarray, repeat_scores: np.ndarray, discovery_scores: np.ndarray, recent_counts: np.ndarray) -> np.ndarray:
    """The score each listed product had: the repeat score of the customer, the mixed discovery score, or the 28-day count of the fallback."""
    rows = np.arange(len(products))[:, None]
    return np.choose(sources.astype(np.int64), [repeat_scores[rows, products], discovery_scores[rows, products], np.asarray(recent_counts)[products]]).astype(np.float64)


def round_lists(data: Any, recipe: Any, view: Any, *, cache: dict | None = None) -> RoundLists:
    """The lists of the customers of `data` (a ``RoundData``) with the discovery model of `recipe`: ``build_list`` over the repeat scores, the mixed discovery scores and the fallback of the round."""
    from personaloffers.recommend import blend

    discovery = blend.discovery_scores(data, recipe, view, cache=cache)
    products, sources = build_list(data.repeat, discovery, data.seen, data.fallback, view, tie_rank=data.tie_rank)
    return RoundLists(customers=data.customers, products=products, sources=sources, scores=list_scores(products, sources, data.repeat, discovery, data.recent))


def lists_fingerprint(lists: RoundLists, codes: np.ndarray) -> str:
    """The SHA-256 of the lists as ``customer_id,rank,stock_code,source`` lines (a header first, the customers in order and the ranks from 1): what the seal keeps of the first round."""
    parts = ["customer_id,rank,stock_code,source\n"]
    for customer, listed, origin in zip(lists.customers, lists.products, lists.sources, strict=True):
        parts.append("".join(f"{int(customer)},{rank},{codes[product]},{SOURCES[int(source)]}\n" for rank, (product, source) in enumerate(zip(listed, origin, strict=True), start=1)))
    return hashlib.sha256("".join(parts).encode("utf-8")).hexdigest()
