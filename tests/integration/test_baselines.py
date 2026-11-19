"""The baselines are built like the list (U12; RF18, AC25; decision D18; plan section 15): the same history before the Monday, the same fallback and the same order for every tie, for the same customers
and both variants, so that what is compared is the method and nothing else; the random one is seeded and the three models are the best of their kind with no trend."""

from __future__ import annotations

import dataclasses
from datetime import datetime

import numpy as np
import pytest

from personaloffers import base, baselines, offers
from personaloffers.recommend import blend, context
from tests.fixtures import hand_cases as hc
from tests.fixtures.hand_lines import hand_frame

MONDAY = hc.POPULARITY_MONDAY


def hand_data(quick_view):
    """The hand history of the popularity cases for the customers 1 to 4, with lists of two products: A 4 invoices, B 3, C 1, D 1; in the last 28 days A 3, B 2, C 1, D 0."""
    rows = [{"invoice": invoice, "customer_id": customer, "invoice_date": datetime(day.year, day.month, day.day), "stock_code": product,
             "role": "guest_purchase" if customer is None else "purchase"} for invoice, customer, day, product in hc.POPULARITY_HISTORY]
    history = base.history_before(hand_frame(*rows), MONDAY)
    view = dataclasses.replace(quick_view, recommend=dataclasses.replace(quick_view.recommend, k=2, repeat_slots=1, discovery_slots=1))
    return context.prepare(history, MONDAY, np.array([1, 2, 3, 4]), view), view


def lists(found, method, variant, data):
    return [[str(data.codes[p]) for p in row] for row in found[(method, variant)]]


def test_every_method_and_variant_has_a_list_of_k_different_products_for_every_customer(quick_view):
    data, view = hand_data(quick_view)
    found = baselines.build(data, blend.Recipe("cosine", 3, 1.0), {"b4": blend.Recipe("rules", 1, 0.0), "b5": blend.Recipe("als", 2, 0.0, regularization=0.1), "b6": blend.Recipe("cosine", 3, 0.0)}, view)
    assert set(found) == {(m, v) for m in baselines.METHODS for v in baselines.VARIANTS} and len(found) == 16
    for key, products in found.items():
        assert products.shape == (4, 2) and products.dtype == np.int64, key
        offers.check_lists(products, np.zeros(products.shape, dtype=np.int8), 2, len(data.codes))


def test_the_popularity_baselines_follow_the_global_and_the_28_day_counts_on_the_hand_case(quick_view):
    """AC25: B1 is the global popularity (A 4, B 3, C 1, D 1), B2 the last 28 days (A 3, B 2, C 1, D 0); the new-only variant leaves out what each customer bought, with the same order."""
    data, view = hand_data(quick_view)
    found = baselines.build(data, blend.Recipe("cosine", 3, 1.0), {}, view)
    assert lists(found, "b1", "unrestricted", data) == [["A", "B"]] * 4 and lists(found, "b2", "unrestricted", data) == [["A", "B"]] * 4
    # customers 1 and 3 bought A and B, customer 2 bought A and C, customer 4 bought D
    assert lists(found, "b1", "new_only", data) == [["C", "D"], ["B", "D"], ["C", "D"], ["A", "B"]]
    assert lists(found, "b2", "new_only", data) == [["C", "D"], ["B", "D"], ["C", "D"], ["A", "B"]]


def test_the_own_repeats_are_completed_with_the_same_reserve_as_the_list(quick_view):
    """B3: the customer's own products by their repeat score and then the 28-day reserve; customer 4 bought only D, and A completes the list. The new-only variant is the reserve alone, restricted to what was
    never bought."""
    data, view = hand_data(quick_view)
    found = baselines.build(data, blend.Recipe("cosine", 3, 1.0), {}, view)
    assert lists(found, "b3", "unrestricted", data) == [["A", "B"], ["A", "C"], ["A", "B"], ["D", "A"]]
    assert lists(found, "b3", "new_only", data) == [["C", "D"], ["B", "D"], ["C", "D"], ["A", "B"]]


def test_every_baseline_is_built_from_the_history_before_its_monday_with_the_same_fallback(fixture_lines, quick_view, quick_cfg):
    """AC25 (07 B2: a baseline that reads something the operation would not see): each list is the same bytes if every line from the Monday on is removed or changed, the completion of the
    repeats is the order of the fallback that the list of the round uses, and B2 is that fallback itself."""
    calendar = quick_cfg.calendar
    chosen = blend.Recipe("als", 8, 1.0, regularization=0.1)
    recipes = {"b4": blend.Recipe("rules", 3, 0.0), "b5": blend.Recipe("als", 8, 0.0, regularization=0.1), "b6": blend.Recipe("cosine", 20, 0.0)}

    def build_from(lines, monday):
        history = base.history_before(lines, monday)
        data = context.prepare(history, monday, base.contact_base(history, monday, quick_view)["customer_id"].to_numpy(), quick_view)
        return data, baselines.build(data, chosen, recipes, quick_view, monday=monday)

    for monday in (calendar.validation_last_round, calendar.test_first_round, calendar.test_last_round):
        midnight = datetime.combine(monday, datetime.min.time())
        data, whole = build_from(fixture_lines, monday)
        _, truncated = build_from(fixture_lines[fixture_lines["invoice_date"] < midnight], monday)
        changed = fixture_lines.copy()
        later = changed["invoice_date"] >= midnight
        changed.loc[later, "quantity"] = changed.loc[later, "quantity"] * 5 + 1
        _, altered = build_from(changed, monday)
        for key in whole:
            assert whole[key].tobytes() == truncated[key].tobytes() == altered[key].tobytes(), (monday, key)
        fallback = data.fallback
        assert (whole[("b2", "unrestricted")] == fallback[:10]).all(), "B2 is the reserve of the list"
        assert np.array_equal(whole[("b3", "new_only")], whole[("b2", "new_only")]), "the own repeats leave only the reserve for the new-only variant"
        assert not np.array_equal(whole[("b2", "new_only")], whole[("b1", "new_only")]), "and the reserve is the 28 days, not the whole history"
        own = data.seen.sum(axis=1)
        for row in np.flatnonzero(own < 10)[:25]:
            listed = whole[("b3", "unrestricted")][row]
            mine = int(own[row])
            completion = [int(p) for p in fallback if int(p) not in set(listed[:mine].tolist())][: 10 - mine]
            assert listed[mine:].tolist() == completion, (monday, row)
            assert set(listed[:mine].tolist()) == set(np.flatnonzero(data.seen[row]).tolist()), "the customer's own products come first"


def test_the_random_baseline_is_seeded_by_the_evaluation_seed_and_the_round(quick_view):
    data, view = hand_data(quick_view)
    first = baselines.build(data, blend.Recipe("cosine", 3, 1.0), {}, view, monday=MONDAY)
    again = baselines.build(data, blend.Recipe("cosine", 3, 1.0), {}, view, monday=MONDAY)
    other_seed = baselines.build(data, blend.Recipe("cosine", 3, 1.0), {}, dataclasses.replace(view, evaluation=dataclasses.replace(view.evaluation, seed=7)), monday=MONDAY)
    other_round = baselines.build(data, blend.Recipe("cosine", 3, 1.0), {}, view, monday=datetime(2011, 8, 8).date())
    assert first[("b0", "unrestricted")].tobytes() == again[("b0", "unrestricted")].tobytes()
    assert not all(np.array_equal(first[("b0", v)], other_seed[("b0", v)]) for v in baselines.VARIANTS), "the seed is the one of [evaluation]"
    assert not all(np.array_equal(first[("b0", v)], other_round[("b0", v)]) for v in baselines.VARIANTS), "and each round draws its own"
    rows = np.arange(4)[:, None]
    assert not data.seen[rows, first[("b0", "new_only")]].any(), "the new-only variant never holds what was bought"


def test_the_three_models_and_the_chosen_discovery_are_the_models_alone_and_the_mix_ranked_by_the_same_rule(fixture_lines, quick_view, quick_cfg):
    from personaloffers import base as base_module

    monday = quick_cfg.calendar.test_first_round
    history = base_module.history_before(fixture_lines, monday)
    data = context.prepare(history, monday, base_module.contact_base(history, monday, quick_view)["customer_id"].to_numpy(), quick_view)
    chosen = blend.Recipe("cosine", 20, 1.0)
    recipes = {"b4": blend.Recipe("rules", 3, 0.0), "b5": blend.Recipe("als", 8, 0.0, regularization=0.1), "b6": blend.Recipe("cosine", 20, 0.0)}
    found = baselines.build(data, chosen, recipes, quick_view, monday=monday)
    for key, recipe in (*recipes.items(), ("chosen_discovery", chosen)):
        scores = blend.discovery_scores(data, recipe, quick_view)
        assert np.array_equal(found[(key, "unrestricted")], offers.top_k(scores, data.tie_rank, 10)), key
        assert np.array_equal(found[(key, "new_only")], offers.top_k(scores, data.tie_rank, 10, eligible=~data.seen)), key
    assert not np.array_equal(found[("b6", "new_only")], found[("chosen_discovery", "new_only")]), "the trend moves the chosen model's list away from the model alone"


def test_a_baseline_that_is_missing_its_recipe_is_left_out_and_nothing_else_changes(quick_view):
    data, view = hand_data(quick_view)
    found = baselines.build(data, blend.Recipe("cosine", 3, 1.0), {"b5": blend.Recipe("als", 2, 0.0, regularization=0.1)}, view)
    assert {m for m, _ in found} == {"b0", "b1", "b2", "b3", "b5", "chosen_discovery"}
