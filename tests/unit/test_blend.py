"""The mix of a model with the trend (U09; RF10, decision D12) and the recipe that names a discovery model: the score of a model divided by the customer's own top score, clipped at
zero, plus a weight times the 28-day popularity over its maximum; a weight of zero is the model alone."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from personaloffers import base
from personaloffers.recommend import blend, context, factor, rules


def test_the_blend_is_the_normalized_model_plus_the_weighted_trend_worked_out_by_hand():
    model = np.array([[2.0, 1.0, 0.0, -1.0], [-1.0, -2.0, 0.0, 0.0], [0.0, 0.0, 4.0, 0.0]], dtype=np.float32)
    trend = np.array([0, 4, 2, 0])
    expected_trend = np.array([0.0, 1.0, 0.5, 0.0])
    # row 0: top score 2 -> [1, .5, 0, 0] (a negative score is clipped); row 1: nothing above zero, the model adds nothing; row 2: top score 4 -> [0, 0, 1, 0]
    norm = np.array([[1.0, 0.5, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0]])
    for weight in (0.0, 0.5, 1.0, 2.0):
        found = blend.blend(model, trend, weight)
        assert found.dtype == np.float32 and found.shape == (3, 4)
        assert np.allclose(found, norm + weight * expected_trend, atol=1e-7), weight
    assert np.array_equal(blend.blend(model, trend, 0.0), norm.astype(np.float32)), "a weight of zero is the model alone"


def test_a_history_without_any_sale_has_no_trend_to_divide_by_and_does_not_fail():
    found = blend.blend(np.ones((2, 3), dtype=np.float32), np.zeros(3, dtype=np.int64), 1.0)
    assert np.array_equal(found, np.ones((2, 3), dtype=np.float32))


def test_the_input_scores_are_not_changed():
    model = np.array([[2.0, -1.0]], dtype=np.float32)
    before = model.copy()
    blend.blend(model, np.array([1, 2]), 1.0)
    assert np.array_equal(model, before)


def test_a_recipe_has_a_name_from_its_parts_and_refuses_what_is_not_a_model_or_a_weight():
    assert blend.Recipe("als", 64, 1.0, regularization=0.1).name == "als_64_r0.1_w1"
    assert blend.Recipe("cosine", 100, 0.5).name == "cosine_100_w0.5"
    assert blend.Recipe("rules", 10, 0.0).name == "rules_10_w0"
    for bad in (("knn", 10, 1.0, None), ("als", 10, -1.0, 0.1), ("als", 0, 1.0, 0.1), ("als", 10, 1.0, None), ("cosine", 10, 1.0, 0.1)):
        with pytest.raises(ValueError):
            blend.Recipe(*bad)


def test_a_recipe_whose_weight_is_not_a_number_is_refused():
    """``weight < 0`` is false for NaN, so the check is written as ``not weight >= 0``: a NaN weight would give a NaN score to every product."""
    with pytest.raises(ValueError, match="peso"):
        blend.Recipe("rules", 10, float("nan"))


@pytest.fixture(scope="module")
def round_data(fixture_lines, quick_view, quick_cfg):
    monday = quick_cfg.calendar.test_first_round
    history = base.history_before(fixture_lines, monday)
    return context.prepare(history, monday, base.contact_base(history, monday, quick_view)["customer_id"].to_numpy(), quick_view)


def test_the_discovery_scores_of_a_recipe_are_its_model_blended_with_the_trend_of_the_round(round_data, quick_view):
    n, m = len(round_data.customers), len(round_data.codes)
    raw_als = factor.als_scores(factor.fit_als(round_data.user_item(), quick_view, factors=8, regularization=0.1), round_data.customers)
    for recipe in (blend.Recipe("als", 8, 1.0, regularization=0.1), blend.Recipe("als", 8, 0.0, regularization=0.1)):
        found = blend.discovery_scores(round_data, recipe, quick_view)
        assert found.shape == (n, m) and found.dtype == np.float32 and np.isfinite(found).all()
        assert np.array_equal(found, blend.blend(raw_als, round_data.trend, recipe.weight)), recipe.name
    cosine = blend.discovery_scores(round_data, blend.Recipe("cosine", 20, 1.0), quick_view)
    expected = blend.blend(factor.cosine_scores(factor.fit_cosine(round_data.user_item(), neighbours=20), round_data.user_item(), round_data.customers), round_data.trend, 1.0)
    assert np.array_equal(cosine, expected)
    counts = round_data.pair_counts()
    by_rules = blend.discovery_scores(round_data, blend.Recipe("rules", 3, 1.0), quick_view)
    expected = blend.blend(rules.score_matrix(rules.select(counts, 3, quick_view.grid.rules_min_lift), round_data.seen), round_data.trend, 1.0)
    assert np.array_equal(by_rules, expected)


def test_one_fit_serves_every_weight_of_its_model_when_a_cache_is_given(round_data, quick_view, monkeypatch):
    calls = []
    original = factor.fit_als
    monkeypatch.setattr(factor, "fit_als", lambda *a, **k: calls.append(1) or original(*a, **k))
    cache: dict = {}
    first = blend.discovery_scores(round_data, blend.Recipe("als", 8, 0.0, regularization=0.1), quick_view, cache=cache)
    second = blend.discovery_scores(round_data, blend.Recipe("als", 8, 1.0, regularization=0.1), quick_view, cache=cache)
    assert len(calls) == 1 and not np.array_equal(first, second)
    blend.discovery_scores(round_data, blend.Recipe("als", 8, 1.0, regularization=0.1), quick_view)
    assert len(calls) == 2, "without a cache each call fits"


def test_the_trend_window_is_the_one_of_the_configuration(round_data, quick_view, fixture_lines, quick_cfg):
    monday = quick_cfg.calendar.test_first_round
    history = base.history_before(fixture_lines, monday)
    customers = round_data.customers
    shorter = dataclasses.replace(quick_view, grid=dataclasses.replace(quick_view.grid, blend_trend_days=7))
    other = context.prepare(history, monday, customers, shorter)
    assert other.trend.sum() < round_data.trend.sum() and (other.trend <= round_data.trend).all()
