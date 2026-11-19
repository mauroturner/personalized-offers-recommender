"""What the recommenders of one round share (plan section 9).

``prepare`` takes the history cut for the Monday and the customers of the base (sorted, each once) and builds, once: the catalogue of the round, what each customer bought (``seen``) and the
repeat scores, the popularity counts (global, the ``fallback_days`` of the list and the ``blend_trend_days`` of the mix), the place of every product in the order that breaks the ties and the
fallback order. The two heavy parts, the matrix of the customers by products (for ALS and the cosine) and the co-occurrence counts (for the rules), are built the first time they are asked for and
then kept, so the candidates of a choice share them. It refuses a history that is not the cut of its round (M01).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from personaloffers.base import check_no_leak
from personaloffers.recommend import factor, popularity, repeats, rules


class RoundData:
    """The shared data of a round; see the module. Everything is read-only by use."""

    def __init__(self, history: pd.DataFrame, monday: date, customers: np.ndarray, view: Any) -> None:
        people = np.asarray(customers, dtype="int64")
        if len(people) > 1 and not (np.diff(people) > 0).all():
            raise ValueError("los clientes de la base deben venir en orden ascendente y sin repetidos")
        self._history = history
        self.monday = monday
        self.customers = people
        self.codes = popularity.catalogue(history, monday)
        self.repeat, self.seen = repeats.score_matrix(history, monday, people, self.codes, view)
        self.popularity = popularity.counts(history, monday, self.codes)
        self.recent = popularity.counts(history, monday, self.codes, days=view.recommend.fallback_days)
        same_window = view.grid.blend_trend_days == view.recommend.fallback_days
        self.trend = self.recent if same_window else popularity.counts(history, monday, self.codes, days=view.grid.blend_trend_days)
        self.tie_rank = popularity.tie_rank(self.popularity)
        self.fallback = popularity.fallback_order(self.recent, self.tie_rank)
        self._cache: dict[str, Any] = {}

    def user_item(self) -> factor.UserItem:
        """The customers by products matrix of the history (every customer with a purchase), built the first time."""
        if "user_item" not in self._cache:
            self._cache["user_item"] = factor.user_item(self._history, self.monday, self.codes)
        return self._cache["user_item"]

    def pair_counts(self) -> rules.PairCounts:
        """The co-occurrence counts of the baskets of the history, built the first time."""
        if "pair_counts" not in self._cache:
            self._cache["pair_counts"] = rules.pair_counts(self._history, self.monday, self.codes)
        return self._cache["pair_counts"]


def prepare(history: pd.DataFrame, monday: date, customers: np.ndarray, view: Any) -> RoundData:
    """The shared data of the round of `monday` for the base `customers` (see the module)."""
    check_no_leak(history, monday)       # the one check of the cut: ``RoundData`` is built here only (the static test of the guard names this function)
    return RoundData(history, monday, customers, view)
