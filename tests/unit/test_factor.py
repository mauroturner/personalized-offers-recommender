"""The factorization and the similarity (U09; RF10, AC08, AC11, RNF01; decision D09): the customer by product matrix of the history (a guest is no row), implicit's ALS and cosine
neighbours on the hand matrix of 6 customers by 8 products and on the fixture, and the refits that give the same factors bit for bit with one thread and a fixed seed."""

from __future__ import annotations

import dataclasses
from datetime import datetime

import numpy as np
import pytest
import scipy.sparse as sp

from personaloffers import base
from personaloffers.base import LeakageError
from personaloffers.recommend import factor
from tests.fixtures import hand_cases as hc
from tests.fixtures.hand_lines import hand_frame

MONDAY = hc.POPULARITY_MONDAY


def hand_matrix() -> factor.UserItem:
    rows = [user for user, items in hc.MATRIX_PURCHASES.items() for _ in items]
    cols = [item for items in hc.MATRIX_PURCHASES.values() for item in items]
    matrix = sp.csr_matrix((np.ones(len(rows), dtype=np.float32), (rows, cols)), shape=(6, 8))
    return factor.UserItem(matrix, np.arange(6, dtype=np.int64) + 100)


def with_grid(view, **keys):
    return dataclasses.replace(view, grid=dataclasses.replace(view.grid, **keys))


def unbought_top(scores: np.ndarray, matrix: sp.csr_matrix) -> list[int]:
    bought = matrix.toarray() > 0
    return [int(np.argmax(np.where(bought[u], -np.inf, scores[u]))) for u in range(matrix.shape[0])]


def test_the_cosine_neighbours_put_the_missing_product_of_the_block_first_with_the_score_of_the_hand_case():
    """AC11: customer 0 bought 0, 1 and 2; the missing product of their block, 3, scores 1/2 + 2/sqrt(6) + 1/2 and every product of the other block scores exactly 0."""
    user_item = hand_matrix()
    model = factor.fit_cosine(user_item, neighbours=100)
    scores = factor.cosine_scores(model, user_item, user_item.user_ids)
    assert scores.shape == (6, 8) and scores.dtype == np.float32
    assert unbought_top(scores, user_item.matrix) == [hc.MATRIX_MISSING[u] for u in range(6)]
    assert scores[0, 3] == pytest.approx(hc.COSINE_TOP_SCORE, abs=1e-6)
    assert (scores[0, 4:] == 0).all() and (scores[3, :4] == 0).all(), "the two blocks never mix"


def test_the_als_puts_the_missing_product_of_the_block_first_for_every_customer(quick_view):
    user_item = hand_matrix()
    model = factor.fit_als(user_item, quick_view, factors=2, regularization=0.1)
    scores = factor.als_scores(model, user_item.user_ids)
    assert scores.shape == (6, 8) and scores.dtype == np.float32
    assert unbought_top(scores, user_item.matrix) == [hc.MATRIX_MISSING[u] for u in range(6)]
    own = [max(scores[u, j] for j in range(8) if j in hc.MATRIX_PURCHASES[u]) for u in range(6)]
    assert all(top > 0 for top in own), "what a customer bought is also high: the factors reconstruct the matrix"


def test_an_als_refit_with_one_thread_and_the_same_seed_gives_the_same_factors_bit_for_bit(quick_view):
    """RNF01 (research p01): the property that makes repeating a round give the same lists."""
    user_item = hand_matrix()
    first = factor.fit_als(user_item, quick_view, factors=4, regularization=0.1)
    again = factor.fit_als(user_item, quick_view, factors=4, regularization=0.1)
    assert np.array_equal(first.user_factors, again.user_factors) and np.array_equal(first.item_factors, again.item_factors)
    assert first.user_factors.tobytes() == again.user_factors.tobytes()
    other = factor.fit_als(user_item, with_grid(quick_view, seed=1), factors=4, regularization=0.1)
    assert not np.array_equal(first.item_factors, other.item_factors), "the seed is the one of [grid]"


def test_the_settings_of_the_fit_come_from_the_call_and_from_the_configuration(quick_view):
    user_item = hand_matrix()
    model = factor.fit_als(user_item, quick_view, factors=3, regularization=0.1)
    assert model.user_factors.shape == (6, 3) and model.item_factors.shape == (8, 3) and model.user_ids.tolist() == list(range(100, 106))
    assert model.user_factors.dtype == model.item_factors.dtype == np.float32
    assert not np.array_equal(model.item_factors, factor.fit_als(user_item, quick_view, factors=3, regularization=1.0).item_factors)
    assert not np.array_equal(model.item_factors, factor.fit_als(user_item, with_grid(quick_view, als_iterations=2), factors=3, regularization=0.1).item_factors)
    assert not np.array_equal(model.item_factors, factor.fit_als(user_item, with_grid(quick_view, als_alpha=1.0), factors=3, regularization=0.1).item_factors)


def test_the_number_of_neighbours_bounds_the_similarities_each_product_keeps():
    user_item = hand_matrix()
    wide = factor.fit_cosine(user_item, neighbours=100).similarity
    narrow = factor.fit_cosine(user_item, neighbours=1).similarity
    assert wide.shape == narrow.shape == (8, 8)
    assert narrow.nnz < wide.nnz and (np.diff(narrow.indptr) <= 2).all(), "one neighbour besides the product itself"


def test_the_matrix_of_the_history_has_a_row_for_each_customer_with_a_purchase_and_none_for_a_guest(quick_view):
    """AC08: a guest's line, a cancellation and a product outside the catalogue are not a row or an entry; a product bought on two invoices is one entry of 1."""
    history = hand_frame(
        {"customer_id": 7, "invoice": "I1", "stock_code": "A", "invoice_date": datetime(2011, 7, 1)},
        {"customer_id": 7, "invoice": "I2", "stock_code": "A", "invoice_date": datetime(2011, 7, 2)},
        {"customer_id": 7, "invoice": "I2", "stock_code": "B", "invoice_date": datetime(2011, 7, 2)},
        {"customer_id": 3, "invoice": "I3", "stock_code": "B", "invoice_date": datetime(2011, 7, 3)},
        {"customer_id": 3, "invoice": "I3", "stock_code": "Z", "invoice_date": datetime(2011, 7, 3)},
        {"customer_id": None, "invoice": "I4", "stock_code": "A", "invoice_date": datetime(2011, 7, 4), "role": "guest_purchase"},
        {"customer_id": 9, "invoice": "CI5", "stock_code": "A", "invoice_date": datetime(2011, 7, 5), "role": "cancellation"},
    )
    user_item = factor.user_item(history, MONDAY, np.array(["A", "B"]))
    assert user_item.user_ids.tolist() == [3, 7], "sorted by customer number; the guest and the customer of a cancellation are not rows"
    assert user_item.matrix.toarray().tolist() == [[0, 1], [1, 1]] and user_item.matrix.dtype == np.float32 and sp.isspmatrix_csr(user_item.matrix)


def test_a_history_with_a_line_of_the_round_or_later_is_refused():
    late = hand_frame({"customer_id": 7, "invoice": "I1", "stock_code": "A", "invoice_date": datetime(2011, 8, 1, 9)})
    with pytest.raises(LeakageError, match="2011-08-01"):
        factor.user_item(late, MONDAY, np.array(["A"]))


def test_a_customer_the_model_has_never_seen_scores_zero_everywhere(quick_view):
    user_item = hand_matrix()
    scores = factor.als_scores(factor.fit_als(user_item, quick_view, factors=2, regularization=0.1), np.array([100, 999]))
    assert scores[0].any() and not scores[1].any()
    similar = factor.cosine_scores(factor.fit_cosine(user_item, neighbours=5), user_item, np.array([100, 999]))
    assert similar[0].any() and not similar[1].any()


def test_the_arrays_of_the_models_round_trip_and_hold_no_object(quick_view):
    user_item = hand_matrix()
    als = factor.fit_als(user_item, quick_view, factors=2, regularization=0.1)
    cosine = factor.fit_cosine(user_item, neighbours=3)
    again_als = factor.AlsModel.from_arrays(als.to_arrays())
    again_cosine = factor.CosineModel.from_arrays(cosine.to_arrays())
    assert np.array_equal(again_als.user_factors, als.user_factors) and np.array_equal(again_als.item_factors, als.item_factors) and np.array_equal(again_als.user_ids, als.user_ids)
    assert (again_cosine.similarity != cosine.similarity).nnz == 0 and again_cosine.similarity.shape == cosine.similarity.shape
    for arrays in (als.to_arrays(), cosine.to_arrays()):
        assert arrays and all(isinstance(a, np.ndarray) and not a.dtype.hasobject for a in arrays.values())


def fixture_user_item(fixture_lines, quick_view, quick_cfg):
    monday = quick_cfg.calendar.test_first_round
    history = base.history_before(fixture_lines, monday)
    codes = np.array(sorted(history.loc[history["role"].isin(["purchase", "guest_purchase"]), "stock_code"].unique()))
    return history, monday, codes, factor.user_item(history, monday, codes)


def test_the_cosine_scores_equal_a_second_computation_on_the_fixture(fixture_lines, quick_view, quick_cfg):
    """With more neighbours than products nothing is cut: the similarity is the cosine of the columns, and the score of a customer is its row times it."""
    history, monday, codes, user_item = fixture_user_item(fixture_lines, quick_view, quick_cfg)
    dense = user_item.matrix.toarray().astype(np.float64)
    assert dense.shape[1] == len(codes) > 100 and set(np.unique(dense)) == {0.0, 1.0}
    norms = np.linalg.norm(dense, axis=0)
    similarity = (dense.T @ dense) / np.outer(np.where(norms == 0, 1, norms), np.where(norms == 0, 1, norms))
    customers = base.contact_base(history, monday, quick_view)["customer_id"].to_numpy()
    rows = np.searchsorted(user_item.user_ids, customers)
    expected = dense[rows] @ similarity
    scores = factor.cosine_scores(factor.fit_cosine(user_item, neighbours=len(codes) + 5), user_item, customers)
    assert np.allclose(scores, expected, atol=2e-5)


def test_the_als_of_the_fixture_is_deterministic_and_scores_what_a_customer_bought_above_the_rest(fixture_lines, quick_view, quick_cfg):
    history, monday, codes, user_item = fixture_user_item(fixture_lines, quick_view, quick_cfg)
    first = factor.fit_als(user_item, quick_view, factors=8, regularization=0.1)
    again = factor.fit_als(user_item, quick_view, factors=8, regularization=0.1)
    assert first.user_factors.tobytes() == again.user_factors.tobytes() and first.item_factors.tobytes() == again.item_factors.tobytes()
    scores = factor.als_scores(first, user_item.user_ids[:50])
    bought = user_item.matrix[:50].toarray() > 0
    assert scores[bought].mean() > scores[~bought].mean() + 0.1


def test_implicit_is_always_asked_for_one_thread_and_no_gpu(quick_view, monkeypatch):
    """RNF01, RNF04: the one-thread fit is what makes a refit give the same factors; the constructors of implicit are given those settings, whatever the machine has."""
    import implicit.als
    import implicit.nearest_neighbours

    seen = {}
    for module, name in ((implicit.als, "AlternatingLeastSquares"), (implicit.nearest_neighbours, "CosineRecommender")):
        original = getattr(module, name)

        def spy(*args, _original=original, _name=name, **kwargs):
            seen[_name] = kwargs
            return _original(*args, **kwargs)

        monkeypatch.setattr(module, name, spy)
    user_item = hand_matrix()
    factor.fit_als(user_item, quick_view, factors=2, regularization=0.1)
    factor.fit_cosine(user_item, neighbours=3)
    assert seen["AlternatingLeastSquares"]["num_threads"] == 1 and seen["AlternatingLeastSquares"]["use_gpu"] is False
    assert seen["CosineRecommender"]["num_threads"] == 1 and seen["CosineRecommender"]["K"] == 3
