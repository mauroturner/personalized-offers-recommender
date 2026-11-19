"""The choice of the recipe in the validation rounds (RF12, AC14; M04; decisions D12, D18, D23; plan section 11).

**Candidates** (D12): each combination of a model and a trend weight: ALS with ``als_factors`` x ``als_regularization``, the cosine neighbours with ``cosine_k`` and the rules with
``rules_min_invoices``, each with every weight of ``blend_trend_weights`` (48 with the grid of the plan; the weight 0 is the model alone).

**Figures.** For each validation round (every Monday from ``validation_first_round`` to ``validation_last_round``; 13 in the plan), the history is the lines before its Monday and nothing else
(``history_before``), the evaluated pairs are the customers of the base of the round who bought something in its week, and each candidate's list is the ten best products the customer **never
bought** by its mixed score (``offers.top_k`` with the fixed tie order). A pair is a hit when the list holds a product bought in the week. A figure is four whole numbers (``RoundFigure``: the pairs,
the hits, the distinct products in the lists and the products with a basket line in the 365 days before the round), so that no sum of floats ever decides a choice and the seal reproduces to the digit:
the hit rate of a candidate is its hits over its pairs in all the rounds, and its coverage the mean of the rounds' distinct over catalogue. Every candidate carries ``fit_rounds``, the rounds its
figures come from.

**The rule** (``pick``): those whose hit rate is less than ``choice_tolerance`` under the best (the best itself is always kept), then the highest coverage, then the lowest trend weight, then the
simplest base (rules, then cosine, then ALS), then the smallest size, then the smallest regularization, then the name. ``baselines`` are the best ALS, cosine and rules with no trend (B5, B6, B4) by the
same rule among the candidates of weight 0.

**M04**: ``choose`` refuses lines dated on or after the first day of the test (``ValidationLeakError``, runbook R5) before it computes anything; each round is cut by ``history_before`` for its own Monday
and the last validation week ends the day before the first test day.
"""

from __future__ import annotations

import hashlib
import itertools
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any

import numpy as np
import pandas as pd

from personaloffers import base, metrics, offers
from personaloffers import calendar as cal
from personaloffers.base import LeakageError
from personaloffers.recommend import blend, context, popularity
from personaloffers.recommend.blend import Recipe

SIMPLICITY = {"rules": 0, "cosine": 1, "als": 2}
BASELINES = {"b4": "rules", "b5": "als", "b6": "cosine"}
EPSILON = 1e-12            # "less than the tolerance" is judged with this much room, so that a difference that is the tolerance in decimal and one unit under it in binary stays out
ACTIVE_DAYS = 365          # the catalogue of the coverage: the products with a basket line in this many days before the round


class ValidationLeakError(LeakageError):
    """A line dated on or after the first day of the test reached the choice (M04, runbook R5)."""


class ChoiceError(RuntimeError):
    """The choice cannot be made (no evaluated pair in any validation round)."""


@dataclass(frozen=True)
class RoundFigure:
    pairs: int            # customers of the base of the round that bought something in its week
    hits: int             # of them, those whose list of ten new products holds a product they bought
    distinct: int         # products in the lists of those customers
    catalogue: int        # products with a basket line in the 365 days before the round


@dataclass(frozen=True)
class Candidate:
    recipe: Recipe
    per_round: dict[str, RoundFigure]
    fit_rounds: tuple[str, ...]
    kept: bool = False
    chosen: bool = False

    @property
    def name(self) -> str:
        return self.recipe.name

    @property
    def pairs(self) -> int:
        return sum(f.pairs for f in self.per_round.values())

    @property
    def hits(self) -> int:
        return sum(f.hits for f in self.per_round.values())

    @property
    def hit_new(self) -> float:
        return self.hits / self.pairs if self.pairs else 0.0

    @property
    def coverage(self) -> float:
        shares = [f.distinct / f.catalogue for f in self.per_round.values() if f.catalogue]
        return sum(shares) / len(shares) if shares else 0.0


@dataclass(frozen=True)
class Choice:
    candidates: tuple[Candidate, ...]
    chosen: Candidate
    baselines: dict[str, Candidate]
    rounds: tuple[str, ...]


# --- the grid and the rule -----------------------------------------------------------------------------------------------------------------------------


def candidates_of(view: Any) -> list[Recipe]:
    """Every candidate of ``[grid]``, in a fixed order: ALS (factors, then regularization), cosine, rules; each with every trend weight."""
    g = view.grid
    models = [("als", size, reg) for size, reg in itertools.product(g.als_factors, g.als_regularization)]
    models += [("cosine", k, None) for k in g.cosine_k] + [("rules", n, None) for n in g.rules_min_invoices]
    return [Recipe(model, int(size), float(weight), regularization=None if reg is None else float(reg)) for (model, size, reg) in models for weight in g.blend_trend_weights]


def _key(row: Sequence[Any]) -> tuple:
    name, model, size, weight, _hit, coverage, *rest = row
    return (-coverage, weight, SIMPLICITY[model], size, rest[0] if rest else 0.0, name)


def pick(rows: Sequence[Sequence[Any]], tolerance: float) -> str:
    """The name of the chosen candidate among ``(name, model, size, weight, hit, coverage[, regularization])`` rows, by the rule of D12 (see the module)."""
    if not rows:
        raise ValueError("no hay candidatas entre las que elegir")
    best = max(row[4] for row in rows)
    kept = [row for row in rows if row[4] == best or best - row[4] < tolerance - EPSILON]
    return min(kept, key=_key)[0]


def _rows(candidates: Sequence[Candidate]) -> list[tuple]:
    return [(c.name, c.recipe.model, c.recipe.size, c.recipe.weight, c.hit_new, c.coverage, c.recipe.regularization or 0.0) for c in candidates]


# --- the figures ------------------------------------------------------------------------------------------------------------------------------------------


def check_validation_lines(lines: pd.DataFrame, view: Any) -> None:
    """M04: a ``ValidationLeakError`` if `lines` holds a line dated on or after the first day of the test."""
    first_day = datetime.combine(view.calendar.test_first_round, time.min)
    if len(lines) and lines["invoice_date"].max() >= first_day:
        late = int((lines["invoice_date"] >= first_day).sum())
        raise ValidationLeakError(f"{late} líneas son del {view.calendar.test_first_round.isoformat()} o posteriores: la elección solo ve lo anterior al primer día de la prueba (M04, runbook R5)")


def round_figures(lines: pd.DataFrame, monday: Any, recipes: Sequence[Recipe], view: Any) -> dict[str, RoundFigure]:
    """The ``RoundFigure`` of each recipe in the validation round of `monday`, from `lines` (which hold the history and the week of the round)."""
    history = base.history_before(lines, monday)
    start, end = cal.window(monday, view)
    in_base = set(base.contact_base(history, monday, view)["customer_id"].tolist())
    week = lines[(lines["role"] == "purchase") & lines["customer_id"].notna() & (lines["invoice_date"] >= start) & (lines["invoice_date"] < end)]
    week = week[week["customer_id"].isin(in_base)][["customer_id", "stock_code"]].drop_duplicates()
    customers = np.sort(week["customer_id"].astype("int64").unique())
    if not len(customers):
        return {recipe.name: RoundFigure(0, 0, 0, 0) for recipe in recipes}
    data = context.prepare(history, monday, customers, view)
    catalogue = int((popularity.counts(history, monday, data.codes, days=ACTIVE_DAYS) > 0).sum())
    pair = pd.Index(customers).get_indexer(week["customer_id"].astype("int64"))
    product = pd.Index(data.codes).get_indexer(week["stock_code"])
    inside = product >= 0
    bought, _ = metrics.bought_matrix(pair[inside], product[inside], len(customers), len(data.codes))
    test_products = np.bincount(pair, minlength=len(customers))
    cache: dict = {}
    figures = {}
    for recipe in recipes:
        scores = blend.discovery_scores(data, recipe, view, cache=cache)
        lists = offers.top_k(scores, data.tie_rank, view.recommend.k, eligible=~data.seen)
        if (lists < 0).any():
            raise ChoiceError("hay clientes con menos de k productos que nunca compraron: el catálogo de la ronda es demasiado chico para esta elección")
        found = metrics.pair_metrics(lists, bought, test_products, k=view.recommend.k)
        figures[recipe.name] = RoundFigure(pairs=len(customers), hits=int(found.hit.sum()), distinct=int(len(np.unique(lists))), catalogue=catalogue)
    return figures


def choose(lines: pd.DataFrame, view: Any) -> Choice:
    """Measure every candidate in every validation round and choose (see the module). `lines` must be the lines before the first day of the test (``ValidationLeakError`` otherwise)."""
    check_validation_lines(lines, view)
    recipes = candidates_of(view)
    mondays = cal.rounds(view, "validation")
    rounds = tuple(cal.round_id(monday) for monday in mondays)
    per_candidate: dict[str, dict[str, RoundFigure]] = {recipe.name: {} for recipe in recipes}
    for monday in mondays:
        for name, figure in round_figures(lines, monday, recipes, view).items():
            per_candidate[name][cal.round_id(monday)] = figure
    built = [Candidate(recipe=recipe, per_round=per_candidate[recipe.name], fit_rounds=rounds) for recipe in recipes]
    if not sum(c.pairs for c in built[:1]):
        raise ChoiceError("ninguna ronda de validación tiene pares evaluados (clientes de la base que compraron en la semana): no hay con qué elegir")
    return _decided(built, rounds, view.grid.choice_tolerance)


def _decided(built: Sequence[Candidate], rounds: tuple[str, ...], tolerance: float) -> Choice:
    best = max(c.hit_new for c in built)
    chosen_name = pick(_rows(built), tolerance)
    flagged = tuple(Candidate(c.recipe, c.per_round, c.fit_rounds, kept=c.hit_new == best or best - c.hit_new < tolerance - EPSILON, chosen=c.name == chosen_name) for c in built)
    chosen = next(c for c in flagged if c.chosen)
    baselines = {}
    for key, model in BASELINES.items():
        mine = [c for c in flagged if c.recipe.model == model and c.recipe.weight == 0.0]
        if mine:
            baselines[key] = next(c for c in mine if c.name == pick(_rows(mine), tolerance))
    return Choice(candidates=flagged, chosen=chosen, baselines=baselines, rounds=rounds)


# --- the dictionary of the seal ---------------------------------------------------------------------------------------------------------------------------------


def _candidate_dict(c: Candidate) -> dict[str, Any]:
    r = c.recipe
    return {"name": c.name, "model": r.model, "size": r.size, "regularization": r.regularization, "weight": r.weight, "hit_new": c.hit_new, "coverage": c.coverage, "pairs": c.pairs, "hits": c.hits,
            "fit_rounds": list(c.fit_rounds), "per_round": {rid: [f.pairs, f.hits, f.distinct, f.catalogue] for rid, f in c.per_round.items()}, "kept": c.kept, "chosen": c.chosen}


def digest(choice: Choice) -> str:
    """The SHA-256 of what the choice rests on: for every candidate, its rounds and its four whole numbers in each, and the names of what was chosen. It is the ``validation_digest`` of the seal."""
    from personaloffers.registry import canonical_json

    document = {"rounds": list(choice.rounds), "chosen": choice.chosen.name, "baselines": {key: c.name for key, c in sorted(choice.baselines.items())},
                "candidates": [{"name": c.name, "per_round": {rid: [f.pairs, f.hits, f.distinct, f.catalogue] for rid, f in c.per_round.items()}} for c in choice.candidates]}
    return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


def to_dict(choice: Choice) -> dict[str, Any]:
    """The choice as the plain dictionary the seal keeps (the validation part of the launch)."""
    return {"rounds": list(choice.rounds), "recipe": choice.chosen.name, "baselines": {key: c.name for key, c in sorted(choice.baselines.items())},
            "candidates": [_candidate_dict(c) for c in choice.candidates], "digest": digest(choice)}


def from_dict(document: dict[str, Any]) -> Choice:
    """The choice of a seal's validation part (what a launch adopts instead of measuring again)."""
    built = []
    for entry in document["candidates"]:
        recipe = Recipe(entry["model"], int(entry["size"]), float(entry["weight"]), regularization=entry["regularization"])
        built.append(Candidate(recipe=recipe, per_round={rid: RoundFigure(*numbers) for rid, numbers in entry["per_round"].items()}, fit_rounds=tuple(entry["fit_rounds"]),
                               kept=bool(entry["kept"]), chosen=bool(entry["chosen"])))
    by_name = {c.name: c for c in built}
    return Choice(candidates=tuple(built), chosen=by_name[document["recipe"]], baselines={key: by_name[name] for key, name in document["baselines"].items()}, rounds=tuple(document["rounds"]))


