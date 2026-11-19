"""The baselines of the evaluation, built like the list (RF18, AC25; decision D18; plan section 15).

Every method is made from the same ``RoundData`` (the history before the Monday of the round, the fallback of its 28-day popularity and the fixed order of the ties) for the same customers, and has the two
variants of the criteria: **unrestricted** (the ten best products, whatever the customer bought) and **new only** (the ten best among the products the customer never bought). So the only difference between
two baselines is the method:

* **B0**: random scores, from a generator seeded with ``[evaluation] seed`` and the round (each round draws its own);
* **B1**: the global popularity; **B2**: the popularity of the last ``fallback_days`` days, the reserve of the list (``data.fallback`` is its order);
* **B3**: the customer's own products by their repeat score, completed with B2 (so the new-only variant is B2 restricted to what was never bought);
* **B4, B5, B6**: the rules, ALS and the cosine neighbours with the best parameter of the choice and no trend (their recipes are given);
* **chosen_discovery**: the mixed score of the chosen recipe, for C04.

What is emitted each round is these lists (``baseline_lists``), not a calculation made at the close that could read something the operation would not have seen (the 07's defect B2).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from datetime import date
from typing import Any

import numpy as np

from personaloffers import offers
from personaloffers.recommend import blend, popularity

METHODS = ("b0", "b1", "b2", "b3", "b4", "b5", "b6", "chosen_discovery")
VARIANTS = ("unrestricted", "new_only")
MODEL_BASELINES = ("b4", "b5", "b6")


def build(data: Any, chosen: blend.Recipe, recipes: Mapping[str, blend.Recipe], view: Any, *, monday: date | None = None, cache: dict | None = None) -> dict[tuple[str, str], np.ndarray]:
    """``{(method, variant): products}`` for the customers of `data` (a ``RoundData``): ``int64`` positions in the catalogue, customers by ``[recommend] k``. `recipes` has the recipes of the models
    (``b4``, ``b5``, ``b6``; one that is missing leaves its baseline out); `chosen` is the recipe of the list. A `cache` shares the fitted models with the list of the round."""
    k = view.recommend.k
    customers, products = len(data.customers), len(data.codes)
    day = monday or data.monday
    never_bought = ~data.seen
    found: dict[tuple[str, str], np.ndarray] = {}

    def ranked(method: str, scores: np.ndarray) -> None:
        found[(method, "unrestricted")] = offers.top_k(scores, data.tie_rank, k)
        found[(method, "new_only")] = offers.top_k(scores, data.tie_rank, k, eligible=never_bought)

    ranked("b0", np.random.default_rng([view.evaluation.seed, day.toordinal()]).random((customers, products), dtype=np.float32))
    for method, counts in (("b1", data.popularity), ("b2", data.recent)):
        scores = popularity.scores(counts, customers)
        found[(method, "unrestricted")] = np.tile(offers.top_k(scores[:1], data.tie_rank, k), (customers, 1))
        found[(method, "new_only")] = offers.top_k(scores, data.tie_rank, k, eligible=never_bought)
    only_repeats = dataclasses.replace(view, recommend=dataclasses.replace(view.recommend, repeat_slots=k, discovery_slots=0))
    found[("b3", "unrestricted")] = offers.build_list(data.repeat, np.zeros_like(data.repeat), data.seen, data.fallback, only_repeats, tie_rank=data.tie_rank)[0]
    found[("b3", "new_only")] = found[("b2", "new_only")]
    for method in MODEL_BASELINES:
        if method in recipes:
            ranked(method, blend.discovery_scores(data, recipes[method], view, cache=cache))
    ranked("chosen_discovery", blend.discovery_scores(data, chosen, view, cache=cache))
    for products_found in found.values():
        offers.check_lists(products_found, np.zeros(products_found.shape, dtype=np.int8), k, products)
    return found
