"""What the recommenders of one round share (U09): the catalogue, the base customers, what each one bought and its repeat scores, the popularity counts and the fixed order that breaks
every tie, built once from the history before the Monday and refused when it is not that history."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from personaloffers import base
from personaloffers.base import LeakageError
from personaloffers.recommend import context, popularity, repeats


@pytest.fixture(scope="module")
def prepared(fixture_lines, quick_view, quick_cfg):
    monday = quick_cfg.calendar.test_first_round
    history = base.history_before(fixture_lines, monday)
    customers = base.contact_base(history, monday, quick_view)["customer_id"].to_numpy()
    return history, monday, customers, context.prepare(history, monday, customers, quick_view)


def test_the_round_data_is_what_each_recommender_computes_on_its_own(prepared, quick_view):
    history, monday, customers, data = prepared
    assert data.monday == monday and data.customers.tolist() == customers.tolist() and data.codes.tolist() == popularity.catalogue(history, monday).tolist()
    scores, seen = repeats.score_matrix(history, monday, customers, data.codes, quick_view)
    assert np.array_equal(data.repeat, scores) and np.array_equal(data.seen, seen)
    assert np.array_equal(data.popularity, popularity.counts(history, monday, data.codes))
    assert np.array_equal(data.recent, popularity.counts(history, monday, data.codes, days=quick_view.recommend.fallback_days))
    assert np.array_equal(data.trend, popularity.counts(history, monday, data.codes, days=quick_view.grid.blend_trend_days))
    assert np.array_equal(data.tie_rank, popularity.tie_rank(data.popularity))
    assert np.array_equal(data.fallback, popularity.fallback_order(data.recent, data.tie_rank))
    assert data.seen.shape == data.repeat.shape == (len(customers), len(data.codes)) and data.seen.any(axis=1).all(), "every customer of the base bought something"


def test_the_heavy_parts_are_built_once_and_only_when_asked_for(prepared):
    *_, data = prepared
    assert data.user_item() is data.user_item() and data.pair_counts() is data.pair_counts()
    assert data.user_item().matrix.shape[1] == len(data.codes) and set(data.customers) <= set(data.user_item().user_ids)


def test_the_fallback_window_and_the_trend_window_come_from_two_different_keys(fixture_lines, quick_view, quick_cfg):
    monday = quick_cfg.calendar.test_first_round
    history = base.history_before(fixture_lines, monday)
    customers = base.contact_base(history, monday, quick_view)["customer_id"].to_numpy()
    changed = dataclasses.replace(quick_view, recommend=dataclasses.replace(quick_view.recommend, fallback_days=7))
    data = context.prepare(history, monday, customers, changed)
    assert data.recent.sum() < popularity.counts(history, monday, data.codes, days=28).sum()
    assert np.array_equal(data.trend, popularity.counts(history, monday, data.codes, days=quick_view.grid.blend_trend_days))


def test_a_history_that_is_not_the_cut_of_its_round_is_refused(fixture_lines, quick_view, quick_cfg):
    monday = quick_cfg.calendar.test_first_round
    with pytest.raises(LeakageError, match=monday.isoformat()):
        context.prepare(fixture_lines, monday, np.array([90001]), quick_view)


def test_the_customers_must_be_sorted_and_without_repeats(fixture_lines, quick_view, quick_cfg):
    monday = quick_cfg.calendar.test_first_round
    history = base.history_before(fixture_lines, monday)
    for bad in ([90002, 90001], [90001, 90001]):
        with pytest.raises(ValueError, match="orden|repet"):
            context.prepare(history, monday, np.array(bad), quick_view)


def test_the_cut_of_the_history_is_checked_once_for_the_round(fixture_lines, quick_view, quick_cfg, monkeypatch):
    """``prepare`` and the data it builds both asked for the same check, which walks the whole history: once is enough, and a history that is not the cut is still refused."""
    monday = quick_cfg.calendar.test_first_round
    history = base.history_before(fixture_lines, monday)
    customers = base.contact_base(history, monday, quick_view)["customer_id"].to_numpy()
    calls = []
    original = context.check_no_leak
    monkeypatch.setattr(context, "check_no_leak", lambda *args: (calls.append(args), original(*args))[1])
    context.prepare(history, monday, customers, quick_view)
    assert len(calls) == 1
    with pytest.raises(LeakageError):
        context.prepare(fixture_lines, monday, customers, quick_view)
    assert len(calls) == 2, "a refused history is refused by the same one check"
