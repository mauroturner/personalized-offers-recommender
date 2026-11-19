"""The mix of a model with the trend, and the recipe that names a discovery model (RF10; decision D12; plan sections 9.5 and 11).

``blend`` is the score of a model divided by the customer's own top score (clipped at zero) plus ``weight`` times the recent popularity over its maximum. With the weight 0 it is the model
alone. In the research's validation the models alone lose to the best sellers of four weeks on new products and only the mix with the trend wins, so the weight is part of what is chosen.

A ``Recipe`` is one candidate of the grid: the model (``als``, ``cosine`` or ``rules``), its size (the factors, the neighbours or the minimum invoices), the trend weight and, for ALS, the
regularization. ``discovery_scores`` fits what the recipe needs on the data of the round and returns the mixed score matrix; given a ``cache`` it fits each model once for all the weights.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from personaloffers.recommend import factor, rules

MODELS = ("als", "cosine", "rules")
TINY = np.float32(1e-9)


@dataclass(frozen=True)
class Recipe:
    model: str
    size: int                       # the factors of ALS, the neighbours of the cosine or the minimum invoices of the rules
    weight: float                   # of the trend
    regularization: float | None = None   # ALS only

    def __post_init__(self) -> None:
        if self.model not in MODELS:
            raise ValueError(f"modelo desconocido: {self.model!r}; se esperaba uno de {', '.join(MODELS)}")
        if self.size < 1 or not self.weight >= 0:
            raise ValueError(f"la receta necesita un tamaño de 1 o más y un peso desde 0, se recibió {self.size} y {self.weight}")
        if (self.model == "als") != (self.regularization is not None):
            raise ValueError("la regularización es de ALS y solo de ALS")

    @property
    def name(self) -> str:
        middle = f"_r{self.regularization:g}" if self.regularization is not None else ""
        return f"{self.model}_{self.size}{middle}_w{self.weight:g}"


def blend(model_scores: np.ndarray, trend_counts: np.ndarray, weight: float) -> np.ndarray:
    """``max(score / top score of the customer, 0) + weight * count / largest count``, ``float32``; the inputs are not changed."""
    scores = np.asarray(model_scores, dtype=np.float32)
    top = np.maximum(scores.max(axis=1, keepdims=True), TINY)
    normalized = np.clip(scores / top, 0, None)
    trend = np.asarray(trend_counts, dtype=np.float32) / np.float32(max(int(np.max(trend_counts, initial=0)), 1))
    return (normalized + np.float32(weight) * trend[None, :]).astype(np.float32)


def cache_key(recipe: Recipe) -> tuple:
    """What the fit of a recipe's model depends on: the model, its size and its regularization (not the trend weight)."""
    return (recipe.model, recipe.size, recipe.regularization)


def fit_model(data: Any, recipe: Recipe, view: Any) -> Any:
    """The fitted model of the recipe on the history of `data` (a ``RoundData``): an ``AlsModel``, a ``CosineModel`` or a ``RuleSet``."""
    if recipe.model == "als":
        return factor.fit_als(data.user_item(), view, factors=recipe.size, regularization=recipe.regularization)
    if recipe.model == "cosine":
        return factor.fit_cosine(data.user_item(), neighbours=recipe.size)
    return rules.select(data.pair_counts(), recipe.size, view.grid.rules_min_lift)


def model_scores(data: Any, recipe: Recipe, model: Any) -> np.ndarray:
    """The scores of a fitted model for the customers of `data`."""
    if recipe.model == "als":
        return factor.als_scores(model, data.customers)
    if recipe.model == "cosine":
        return factor.cosine_scores(model, data.user_item(), data.customers)
    return rules.score_matrix(model, data.seen)


def model_arrays(recipe: Recipe, model: Any) -> dict[str, np.ndarray]:
    """The flat arrays of a fitted model, as ``recommend.artifacts`` writes them."""
    return rules.to_arrays(model) if recipe.model == "rules" else model.to_arrays()


def raw_scores(data: Any, recipe: Recipe, view: Any, *, cache: dict | None = None) -> np.ndarray:
    """The scores of the recipe's model alone for the customers of `data`; with a `cache` a model is fitted once for every weight."""
    key = cache_key(recipe)
    if cache is not None and key in cache:
        return cache[key]
    found = model_scores(data, recipe, fit_model(data, recipe, view))
    if cache is not None:
        cache[key] = found
    return found


def discovery_scores(data: Any, recipe: Recipe, view: Any, *, cache: dict | None = None) -> np.ndarray:
    """The mixed discovery score of the recipe for every customer and product of `data`."""
    return blend(raw_scores(data, recipe, view, cache=cache), data.trend, recipe.weight)
