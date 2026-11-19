"""The list that is delivered (U09, risk item 6: a badly built order gives worse lists and no other test sees it; RF11, AC12, M06; decisions D10, D11): up to seven products of the
customer's own repeats, then products never bought from the discovery model, then the 28-day fallback, always ten different ones with their source, and a fixed order for every tie."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from personaloffers import offers
from personaloffers.offers import ListError
from personaloffers.recommend import popularity
from tests.fixtures import hand_cases as hc

PRODUCTS = 12
SOURCE = {"repeat": 0, "discovery": 1, "fallback": 2}
NAME = {code: name for name, code in SOURCE.items()}


def with_recommend(view, **keys):
    return dataclasses.replace(view, recommend=dataclasses.replace(view.recommend, **keys))


def matrices(case: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The repeat scores, the discovery scores and the bought mask of a hand case (a score missing from the dictionary is zero; a repeat score is in the bought products only)."""
    repeat = np.zeros((1, PRODUCTS), dtype=np.float32)
    discovery = np.zeros((1, PRODUCTS), dtype=np.float32)
    seen = np.zeros((1, PRODUCTS), dtype=bool)
    for product, score in case["repeat"].items():
        repeat[0, product], seen[0, product] = score, True
    for product, score in case["discovery"].items():
        discovery[0, product] = score
    return repeat, discovery, seen


def listed(products: np.ndarray, origins: np.ndarray, row: int = 0) -> list[tuple[int, str]]:
    return [(int(p), NAME[int(o)]) for p, o in zip(products[row], origins[row], strict=True)]


@pytest.mark.parametrize("name", sorted(hc.LIST_CASES))
def test_the_list_of_each_hand_case_is_the_one_worked_out_by_hand(name, quick_view):
    """AC12: the rich customer, the customer of one invoice, the model with two candidates and the model with none."""
    case = hc.LIST_CASES[name]
    repeat, discovery, seen = matrices(case)
    products, origins = offers.build_list(repeat, discovery, seen, np.array(hc.LIST_FALLBACK), quick_view)
    assert products.shape == origins.shape == (1, 10) and products.dtype == np.int64 and origins.dtype == np.int8
    assert listed(products, origins) == case["expected"]


def test_a_list_has_ten_different_products_with_at_most_seven_of_repeat_and_discovery_only_of_what_was_never_bought(quick_view):
    rng = np.random.default_rng(3)
    n, m = 200, 40
    seen = rng.random((n, m)) < rng.uniform(0.0, 0.5, (n, 1))
    seen[0], seen[1] = False, True            # a customer with no purchase at all and one that bought everything
    repeat = np.where(seen, rng.random((n, m)) * 5, 0).astype(np.float32)
    discovery = (rng.random((n, m)) * (rng.random((n, m)) < 0.4)).astype(np.float32)
    fallback = rng.permutation(m)
    products, origins = offers.build_list(repeat, discovery, seen, fallback, quick_view)
    offers.check_lists(products, origins, 10, m)
    for i in range(n):
        assert len(set(products[i].tolist())) == 10
        mine = {NAME[int(o)]: [int(p) for p, o2 in zip(products[i], origins[i], strict=True) if o2 == o] for o in set(origins[i].tolist())}
        assert len(mine.get("repeat", [])) == min(7, int(seen[i].sum()))
        assert all(seen[i, p] for p in mine.get("repeat", [])) and not any(seen[i, p] for p in mine.get("discovery", []))
        assert all(discovery[i, p] > 0 for p in mine.get("discovery", []))
        assert list(origins[i]) == sorted(origins[i]), "repeat first, then discovery, then fallback"
        wanted = [int(p) for p in fallback if int(p) not in set(products[i][origins[i] < 2].tolist())][: int((origins[i] == 2).sum())]
        assert mine.get("fallback", []) == wanted, "the fallback is its own order, skipping what the list holds"
        if len(mine.get("repeat", [])) == 7 and (discovery[i] * ~seen[i] > 0).sum() >= 3:
            assert len(mine.get("discovery", [])) == 3


def test_repeats_are_taken_in_the_order_of_their_score_and_seven_is_the_most(quick_view):
    repeat = np.zeros((1, 12), dtype=np.float32)
    seen = np.zeros((1, 12), dtype=bool)
    for product, score in zip(range(9), (1.5, 4.0, 3.0, 2.0, 9.0, 8.0, 7.0, 6.0, 5.0), strict=True):
        repeat[0, product], seen[0, product] = score, True
    products, origins = offers.build_list(repeat, np.zeros_like(repeat), seen, np.arange(12), quick_view)
    assert products[0, :7].tolist() == [4, 5, 6, 7, 8, 1, 2] and (origins[0, :7] == 0).all()
    assert products[0, 7:].tolist() == [0, 3, 9] and (origins[0, 7:] == 2).all(), "no discovery candidate: the fallback, which may hold a product the customer bought"


def test_the_slots_and_the_length_come_from_the_configuration(quick_view):
    case = hc.LIST_CASES["rich"]
    repeat, discovery, seen = matrices(case)
    fallback = np.array(hc.LIST_FALLBACK)
    five = with_recommend(quick_view, repeat_slots=5, discovery_slots=5)
    products, origins = offers.build_list(repeat, discovery, seen, fallback, five)
    assert listed(products, origins) == [(0, "repeat"), (1, "repeat"), (2, "repeat"), (3, "repeat"), (4, "repeat"), (9, "discovery"), (11, "discovery"), (10, "discovery"),
                                         (5, "fallback"), (8, "fallback")], "five of repeat, the three candidates of the model (it has no more) and the fallback"
    short = with_recommend(quick_view, k=4, repeat_slots=3, discovery_slots=1)
    products, origins = offers.build_list(repeat, discovery, seen, fallback, short)
    assert products.shape == (1, 4) and listed(products, origins) == [(0, "repeat"), (1, "repeat"), (2, "repeat"), (9, "discovery")]
    none = with_recommend(quick_view, repeat_slots=0, discovery_slots=10)
    products, origins = offers.build_list(repeat, discovery, seen, fallback, none)
    assert (origins[0] != 0).all() and products[0, :3].tolist() == [9, 11, 10]


def test_ties_follow_the_fixed_order_and_the_same_input_gives_the_same_list(quick_view):
    """D11 (AC21): the same score goes to the more popular product and then to the lower code; the same call twice gives the same bytes, and the order of the columns of the scores is not
    what decides a tie."""
    scores = np.zeros((1, 8), dtype=np.float32)
    counts = np.zeros(8, dtype=np.int64)
    for product, score in hc.TIE_SCORES.items():
        scores[0, product] = score
    for product, count in hc.TIE_POPULARITY.items():
        counts[product] = count
    rank = popularity.tie_rank(counts)
    top = offers.top_k(scores, rank, 3)
    assert top.tolist() == [list(hc.TIE_ORDER)], "the hand case: 6 (the most popular), then 4 and 5 (the lower code first)"
    assert offers.top_k(scores, rank, 3).tobytes() == top.tobytes()
    # the same through the list: ties in the discovery scores are broken the same way
    seen = np.zeros((1, 8), dtype=bool)
    products, origins = offers.build_list(np.zeros((1, 8), dtype=np.float32), scores, seen, np.arange(8), with_recommend(quick_view, k=3, repeat_slots=0, discovery_slots=3), tie_rank=rank)
    assert products[0].tolist() == list(hc.TIE_ORDER) and (origins[0] == 1).all()
    again = offers.build_list(np.zeros((1, 8), dtype=np.float32), scores, seen, np.arange(8), with_recommend(quick_view, k=3, repeat_slots=0, discovery_slots=3), tie_rank=rank)
    assert again[0].tobytes() == products.tobytes() and again[1].tobytes() == origins.tobytes()


def test_the_order_of_a_score_with_a_negative_zero_a_negative_value_and_a_tiny_difference_is_exact():
    """The keys that decide the order compare the float32 scores exactly: -0.0 equals 0.0 (a tie), and two scores one unit of the last place apart are two scores."""
    rank = np.arange(5, dtype=np.int64)
    tiny = np.nextafter(np.float32(1.0), np.float32(2.0))
    scores = np.array([[-0.0, 0.0, -2.0, 1.0, tiny]], dtype=np.float32)
    assert offers.top_k(scores, rank, 5).tolist() == [[4, 3, 0, 1, 2]], "the tiny excess wins, then 1.0, then the tie of -0 and +0 by rank (-0 first), then the negative"


def test_top_k_can_be_restricted_to_an_eligible_set_and_pads_with_minus_one():
    scores = np.array([[5.0, 4.0, 3.0, 2.0], [1.0, 9.0, 8.0, 7.0]], dtype=np.float32)
    eligible = np.array([[False, True, False, True], [False, False, False, False]])
    found = offers.top_k(scores, np.arange(4, dtype=np.int64), 3, eligible=eligible)
    assert found.tolist() == [[1, 3, -1], [-1, -1, -1]]
    assert offers.top_k(scores, np.arange(4, dtype=np.int64), 9).shape == (2, 4), "never more columns than products"


def test_a_catalogue_that_cannot_make_a_list_of_ten_is_refused(quick_view):
    small = np.zeros((1, 6), dtype=np.float32)
    with pytest.raises(ValueError, match="10"):
        offers.build_list(small, small, np.zeros((1, 6), dtype=bool), np.arange(6), quick_view)


def test_the_check_of_a_list_refuses_a_repeated_product_a_short_list_an_unknown_source_and_a_product_out_of_the_catalogue():
    good = np.arange(10, dtype=np.int64)[None, :]
    origins = np.array([[0, 0, 1, 1, 1, 2, 2, 2, 2, 2]], dtype=np.int8)
    offers.check_lists(good, origins, 10, 12)
    for bad_products, bad_origins, message in (
        (np.array([[0, 1, 2, 3, 4, 5, 6, 7, 8, 8]]), origins, "repet"),
        (np.array([[0, 1, 2, 3, 4, 5, 6, 7, 8, -1]]), origins, "catálogo"),
        (np.array([[0, 1, 2, 3, 4, 5, 6, 7, 8, 12]]), origins, "catálogo"),
        (good, np.array([[0, 0, 1, 1, 1, 2, 2, 2, 2, 3]], dtype=np.int8), "origen"),
        (good[:, :9], origins[:, :9], "10"),
    ):
        with pytest.raises(ListError, match=message):
            offers.check_lists(bad_products, bad_origins, 10, 12)


def test_the_error_of_a_bad_list_counts_the_lists_and_never_names_a_customer():
    products = np.tile(np.arange(10), (3, 1))
    products[1, 9] = 0
    origins = np.zeros((3, 10), dtype=np.int8)
    with pytest.raises(ListError) as caught:
        offers.check_lists(products, origins, 10, 12)
    assert "1 " in str(caught.value) and "90" not in str(caught.value)


def test_the_reserve_is_enough_when_the_customer_holds_the_first_products_of_it(quick_view):
    """The reserve is read only to its first k products: a list holds at most k, so even when the customer's own products are the first of the reserve there are enough left."""
    products = 30
    seen = np.zeros((1, products), dtype=bool)
    seen[0, :7] = True
    repeat = np.zeros((1, products), dtype=np.float32)
    repeat[0, :7] = np.arange(7, 0, -1)
    fallback = np.arange(products)           # the reserve starts with the seven products that the customer holds
    chosen, origins = offers.build_list(repeat, np.zeros((1, products), dtype=np.float32), seen, fallback, quick_view)
    assert chosen[0].tolist() == [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] and origins[0].tolist() == [0] * 7 + [2] * 3
    # and when it holds the first ten and none of them are among the seven of its list
    seen[0, :10] = True
    repeat[0, :10] = 1.0
    chosen, origins = offers.build_list(repeat, np.zeros((1, products), dtype=np.float32), seen, fallback, quick_view)
    assert sorted(chosen[0].tolist()) == list(range(10)) and (origins[0, :7] == 0).all() and (origins[0, 7:] == 2).all()


# --- U11: the lists of a round, their scores and their fingerprint -----------------------------------------------------------------------------------


def round_data_of(fixture_lines, quick_view, quick_cfg):
    from personaloffers import base
    from personaloffers.recommend import context

    monday = quick_cfg.calendar.test_first_round
    history = base.history_before(fixture_lines, monday)
    return context.prepare(history, monday, base.contact_base(history, monday, quick_view)["customer_id"].to_numpy(), quick_view)


def test_the_lists_of_a_round_are_the_list_built_from_the_repeats_the_discovery_of_the_recipe_and_the_fallback(fixture_lines, quick_view, quick_cfg):
    from personaloffers.recommend import blend

    data = round_data_of(fixture_lines, quick_view, quick_cfg)
    recipe = blend.Recipe("cosine", 20, 1.0)
    found = offers.round_lists(data, recipe, quick_view)
    discovery = blend.discovery_scores(data, recipe, quick_view)
    products, sources = offers.build_list(data.repeat, discovery, data.seen, data.fallback, quick_view, tie_rank=data.tie_rank)
    assert np.array_equal(found.customers, data.customers) and np.array_equal(found.products, products) and np.array_equal(found.sources, sources)
    assert found.products.shape == (len(data.customers), 10) and found.scores.shape == found.products.shape and found.scores.dtype == np.float64


def test_the_score_of_a_listed_product_is_the_one_of_its_source(fixture_lines, quick_view, quick_cfg):
    from personaloffers.recommend import blend

    data = round_data_of(fixture_lines, quick_view, quick_cfg)
    recipe = blend.Recipe("rules", 12, 0.0)
    found = offers.round_lists(data, recipe, quick_view)
    discovery = blend.discovery_scores(data, recipe, quick_view)
    seen_sources = set()
    for i in range(0, len(data.customers), 7):
        for rank in range(10):
            product, source, score = int(found.products[i, rank]), int(found.sources[i, rank]), found.scores[i, rank]
            seen_sources.add(source)
            expected = (data.repeat[i, product], discovery[i, product], data.recent[product])[source]
            assert score == pytest.approx(float(expected)), (i, rank, SOURCE and NAME[source])
    assert seen_sources == {0, 1, 2}, "the fixture has lists with the three sources"


def test_the_fingerprint_of_the_lists_is_the_hash_of_customer_rank_code_and_source_in_order(fixture_lines, quick_view, quick_cfg):
    import hashlib

    from personaloffers.recommend import blend

    data = round_data_of(fixture_lines, quick_view, quick_cfg)
    found = offers.round_lists(data, blend.Recipe("rules", 3, 1.0), quick_view)
    lines = ["customer_id,rank,stock_code,source"]
    for i, customer in enumerate(found.customers):
        for rank in range(10):
            lines.append(f"{int(customer)},{rank + 1},{data.codes[found.products[i, rank]]},{offers.SOURCES[int(found.sources[i, rank])]}")
    expected = hashlib.sha256(("\n".join(lines) + "\n").encode("utf-8")).hexdigest()
    assert offers.lists_fingerprint(found, data.codes) == expected
    swapped = dataclasses.replace(found, products=found.products.copy())
    swapped.products[0, [0, 1]] = swapped.products[0, [1, 0]]
    assert offers.lists_fingerprint(swapped, data.codes) != expected, "the order of a list is part of it"
    other = dataclasses.replace(found, sources=found.sources.copy())
    other.sources[3, 9] = (other.sources[3, 9] + 1) % 3
    assert offers.lists_fingerprint(other, data.codes) != expected, "and so is the source"
    assert offers.lists_fingerprint(offers.round_lists(data, blend.Recipe("rules", 3, 1.0), quick_view), data.codes) == expected, "the same lists again, the same fingerprint"
