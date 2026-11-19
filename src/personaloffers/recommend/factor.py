"""The factorization and the similarity of the products (RF10, AC08, AC11, RNF01; decision D09; plan section 9.4), with implicit.

The matrix is every customer of the history (a row for each customer with a ``purchase`` line, sorted by number: a guest is no row, AC08) by the products of the catalogue, with a 1 where the
customer bought the product. ALS is implicit's ``AlternatingLeastSquares`` with ``[grid] als_alpha`` as the weight of the 1s, ``als_iterations`` and the seed of ``[grid]``, one thread and no GPU:
with that, refitting on the same matrix gives the same factors bit for bit (research p01), which is what makes repeating a round give the same lists. The cosine neighbours are implicit's
``CosineRecommender``. The score of a customer for a product is the row of its factors by the factors of the products (ALS) or the row of its purchases by the similarities (cosine).

implicit is imported inside the functions that fit: ``import implicit`` costs about a second and nothing else in the package needs it.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
import scipy.sparse as sp

from personaloffers.base import check_no_leak


@dataclass(frozen=True)
class UserItem:
    """The customers by products matrix of a history: ``float32`` CSR of 0s and 1s, and the customer numbers of its rows."""

    matrix: sp.csr_matrix
    user_ids: np.ndarray           # (rows,) int64, sorted


@dataclass(frozen=True)
class AlsModel:
    user_ids: np.ndarray
    user_factors: np.ndarray       # (customers, factors) float32
    item_factors: np.ndarray       # (products, factors) float32

    def to_arrays(self) -> dict[str, np.ndarray]:
        return {"user_ids": self.user_ids, "user_factors": self.user_factors, "item_factors": self.item_factors}

    @classmethod
    def from_arrays(cls, arrays: dict[str, np.ndarray]) -> AlsModel:
        return cls(user_ids=arrays["user_ids"], user_factors=arrays["user_factors"], item_factors=arrays["item_factors"])


@dataclass(frozen=True)
class CosineModel:
    similarity: sp.csr_matrix      # (products, products) float32

    def to_arrays(self) -> dict[str, np.ndarray]:
        s = self.similarity
        return {"data": s.data, "indices": s.indices, "indptr": s.indptr, "shape": np.array(s.shape, dtype=np.int64)}

    @classmethod
    def from_arrays(cls, arrays: dict[str, np.ndarray]) -> CosineModel:
        shape = tuple(int(side) for side in arrays["shape"])
        return cls(sp.csr_matrix((arrays["data"], arrays["indices"], arrays["indptr"]), shape=shape))


def user_item(history: pd.DataFrame, monday: date, codes: np.ndarray) -> UserItem:
    """The matrix of the history for the products `codes`."""
    check_no_leak(history, monday)
    rows = history[(history["role"] == "purchase") & history["customer_id"].notna() & history["stock_code"].isin(codes)][["customer_id", "stock_code"]].drop_duplicates()
    customers = rows["customer_id"].astype("int64").to_numpy()
    user_ids = np.unique(customers)
    i = np.searchsorted(user_ids, customers)
    j = pd.Index(codes).get_indexer(rows["stock_code"])
    matrix = sp.csr_matrix((np.ones(len(rows), dtype=np.float32), (i, j)), shape=(len(user_ids), len(codes)))
    return UserItem(matrix=matrix, user_ids=user_ids)


def _fit(model: Any, data: UserItem) -> None:
    """``model.fit`` without implicit's ``ParameterWarning``: it says, with the path of its own file, that it converted a matrix it was given to CSR, which changes no value and would put a path of
    this machine in every log."""
    from implicit.utils import ParameterWarning

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ParameterWarning)
        model.fit(data.matrix, show_progress=False)


def fit_als(data: UserItem, view: Any, *, factors: int, regularization: float) -> AlsModel:
    """ALS on `data` with the settings of ``[grid]`` of `view` and the given number of factors and regularization."""
    from implicit.als import AlternatingLeastSquares

    model = AlternatingLeastSquares(factors=factors, regularization=regularization, alpha=view.grid.als_alpha, iterations=view.grid.als_iterations,
                                    random_state=view.grid.seed, num_threads=1, use_gpu=False)
    _fit(model, data)
    return AlsModel(user_ids=data.user_ids.copy(), user_factors=np.array(model.user_factors, dtype=np.float32), item_factors=np.array(model.item_factors, dtype=np.float32))


def _rows_of(user_ids: np.ndarray, customers: np.ndarray) -> np.ndarray:
    return pd.Index(user_ids).get_indexer(np.asarray(customers, dtype="int64"))


def als_scores(model: AlsModel, customers: np.ndarray) -> np.ndarray:
    """The score of every product for each of `customers` (a customer the model has no row for scores 0 everywhere). ``float32``, customers by products."""
    rows = _rows_of(model.user_ids, customers)
    scores = np.zeros((len(rows), model.item_factors.shape[0]), dtype=np.float32)
    known = rows >= 0
    scores[known] = model.user_factors[rows[known]] @ model.item_factors.T
    return scores


def fit_cosine(data: UserItem, *, neighbours: int) -> CosineModel:
    """The cosine similarity between products, keeping the `neighbours` nearest of each."""
    from implicit.nearest_neighbours import CosineRecommender

    model = CosineRecommender(K=neighbours, num_threads=1)
    _fit(model, data)
    similarity = sp.csr_matrix(model.similarity, dtype=np.float32)
    similarity.sort_indices()
    return CosineModel(similarity=similarity)


def cosine_scores(model: CosineModel, data: UserItem, customers: np.ndarray) -> np.ndarray:
    """The score of every product for each of `customers`: their row of purchases times the similarities (0 for a customer that is not a row of `data`). ``float32``."""
    rows = _rows_of(data.user_ids, customers)
    scores = np.zeros((len(rows), model.similarity.shape[1]), dtype=np.float32)
    known = rows >= 0
    if known.any():
        scores[known] = (data.matrix[rows[known]] @ model.similarity).toarray()
    return scores
