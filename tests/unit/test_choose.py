"""The choice of the recipe in the validation rounds (U11; RF12, AC14; decisions D12, D18, D23): 48 candidates measured on new products only in the rounds that end before the first day of the test,
picked by the rule of the decision, with the figures of every candidate in every round and the rounds it was fitted on."""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime

import numpy as np
import pytest

from personaloffers import base, choose
from personaloffers import calendar as cal
from personaloffers.choose import ChoiceError, ValidationLeakError
from personaloffers.recommend import blend, context, popularity
from tests.fixtures import hand_cases as hc

TOLERANCE = hc.CHOICE_TOLERANCE


def with_grid(view, **keys):
    return dataclasses.replace(view, grid=dataclasses.replace(view.grid, **keys))


# --- the rule ----------------------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("candidates", "expected"), hc.CHOICE_CASES)
def test_each_choice_case_follows_the_rule_of_the_decision(candidates, expected):
    """AC14: those within the tolerance of the best hit, then the highest coverage, then the lowest weight, then the simplest base (rules, cosine, ALS), then the smallest size."""
    assert choose.pick(candidates, TOLERANCE) == expected


def test_the_candidate_at_exactly_the_tolerance_is_out_and_the_one_just_inside_is_in():
    inside = (("best", "als", 64, 1.0, 0.300, 0.05), ("near", "als", 32, 1.0, 0.2951, 0.50))
    assert choose.pick(inside, 0.005) == "near"
    edge = (("best", "als", 64, 1.0, 0.300, 0.05), ("far", "als", 32, 1.0, 0.250, 0.50))
    assert choose.pick(edge, 0.05) == "best", "the difference is not under the tolerance: it is the tolerance"
    assert choose.pick(edge, 0.0) == "best" and choose.pick(edge, 0.06) == "far"


def test_a_regularization_and_then_the_name_break_what_the_rule_leaves_tied():
    tied = (("als_64_r0.1_w1", "als", 64, 1.0, 0.3, 0.1, 0.1), ("als_64_r0.01_w1", "als", 64, 1.0, 0.3, 0.1, 0.01))
    assert choose.pick(tied, TOLERANCE) == "als_64_r0.01_w1", "the smaller regularization"
    assert choose.pick(tuple(reversed(tied)), TOLERANCE) == "als_64_r0.01_w1"
    same = (("b", "rules", 5, 0.0, 0.3, 0.1), ("a", "rules", 5, 0.0, 0.3, 0.1))
    assert choose.pick(same, TOLERANCE) == "a"
    with pytest.raises(ValueError, match="candidatas"):
        choose.pick((), TOLERANCE)


def test_the_grid_of_the_plan_has_forty_eight_candidates_and_the_quick_one_six(cfg, quick_view):
    from personaloffers.config import SealedConfig

    full = choose.candidates_of(SealedConfig.of(cfg, "a" * 64, "b" * 64, "c" * 64))
    assert len(full) == 48 and len({recipe.name for recipe in full}) == 48
    assert {m: sum(r.model == m for r in full) for m in ("als", "cosine", "rules")} == {"als": 24, "cosine": 12, "rules": 12}
    assert {r.weight for r in full} == {0.0, 0.5, 1.0, 2.0} and {r.size for r in full if r.model == "als"} == {32, 64, 128} and {r.regularization for r in full if r.model == "als"} == {0.01, 0.1}
    quick = choose.candidates_of(quick_view)
    assert [r.name for r in quick] == ["als_8_r0.1_w0", "als_8_r0.1_w1", "cosine_20_w0", "cosine_20_w1", "rules_3_w0", "rules_3_w1"]
    narrower = choose.candidates_of(with_grid(quick_view, cosine_k=[20, 50], blend_trend_weights=(0.0, 0.5, 1.0)))
    assert len(narrower) == 3 * (1 + 2 + 1)


# --- the figures, with the scores made up so that only the plumbing is under test ---------------------------------------------------------------------


def fixed_scores(data, recipe, view, *, cache=None):
    """A score for each (customer, product) that depends only on the numbers and the weight: the same matrix whatever the model, which the test recomputes by hand."""
    n, m = len(data.customers), len(data.codes)
    rng = np.random.default_rng(int(data.customers[0]) % 1000 + len(data.codes))
    return (rng.random((n, m)) + recipe.weight * data.trend / max(data.trend.max(), 1)).astype(np.float32)


def test_the_figures_of_a_round_are_what_a_plain_loop_over_the_lines_gives(fixture_lines, quick_view, quick_cfg, monkeypatch):
    """pairs: customers of the base of the round with a purchase in its week; hits: those whose list of ten new products holds a product bought; distinct: the products in those lists; catalogue:
    the products with a line of a basket in the 365 days before the round. Every number recomputed from the lines with loops."""
    monkeypatch.setattr(blend, "discovery_scores", fixed_scores)
    monday = quick_cfg.calendar.validation_last_round
    lines = fixture_lines[fixture_lines["invoice_date"] < datetime.combine(quick_cfg.calendar.test_first_round, datetime.min.time())]
    figures = choose.round_figures(lines, monday, choose.candidates_of(quick_view)[:2], quick_view)
    history = base.history_before(lines, monday)
    midnight = datetime.combine(monday, datetime.min.time())
    base_ids = set(base.contact_base(history, monday, quick_view)["customer_id"])
    bought: dict[int, set[str]] = {}
    for row in lines[(lines["invoice_date"] >= midnight) & (lines["invoice_date"] < midnight + (datetime(2011, 1, 8) - datetime(2011, 1, 1))) & (lines["role"] == "purchase")].itertuples():
        if row.customer_id in base_ids:
            bought.setdefault(int(row.customer_id), set()).add(row.stock_code)
    customers = np.array(sorted(bought))
    data = context.prepare(history, monday, customers, quick_view)
    active = {row.stock_code for row in history.itertuples() if row.role in ("purchase", "guest_purchase") and (midnight - row.invoice_date).total_seconds() <= 365 * 86400}
    for recipe in choose.candidates_of(quick_view)[:2]:
        scores = fixed_scores(data, recipe, quick_view)
        tie = popularity.tie_rank(data.popularity)
        hits, listed = 0, set()
        for i in range(len(customers)):
            candidates = [j for j in range(len(data.codes)) if not data.seen[i, j]]
            top = sorted(candidates, key=lambda j: (-float(scores[i, j]), tie[j]))[:10]
            listed |= set(top)
            hits += any(data.codes[j] in bought[int(customers[i])] for j in top)
        figure = figures[recipe.name]
        assert (figure.pairs, figure.hits, figure.distinct, figure.catalogue) == (len(customers), hits, len(listed), len(active)), recipe.name
    assert len(customers) > 15, "the round has pairs"


def test_a_round_with_no_pair_has_zero_figures_and_the_choice_needs_pairs_somewhere(fixture_lines, quick_view, quick_cfg, monkeypatch):
    monkeypatch.setattr(blend, "discovery_scores", fixed_scores)
    lines = fixture_lines[fixture_lines["invoice_date"] < datetime(2011, 3, 28)]
    empty = choose.round_figures(lines[lines["invoice_date"] < datetime(2011, 3, 14)], quick_cfg.calendar.validation_first_round, choose.candidates_of(quick_view)[:1], quick_view)
    assert [(f.pairs, f.hits, f.distinct) for f in empty.values()] == [(0, 0, 0)]
    no_buyers = lines[lines["invoice_date"] < datetime(2011, 3, 14)]
    with pytest.raises(ChoiceError, match="pares"):
        choose.choose(no_buyers, quick_view)


# --- the choice --------------------------------------------------------------------------------------------------------------------------------


def validation_lines(lines, cfg):
    return lines[lines["invoice_date"] < datetime.combine(cfg.calendar.test_first_round, datetime.min.time())]


@pytest.fixture(scope="module")
def chosen(fixture_lines, quick_view, quick_cfg):
    return choose.choose(validation_lines(fixture_lines, quick_cfg), quick_view)


def test_every_candidate_names_the_validation_rounds_it_was_fitted_on(chosen, quick_cfg, quick_view):
    expected = tuple(cal.round_id(m) for m in cal.rounds(quick_view, "validation"))
    assert expected == ("R2011-03-14", "R2011-03-21") and chosen.rounds == expected
    assert len(chosen.candidates) == 6
    for candidate in chosen.candidates:
        assert candidate.fit_rounds == expected and tuple(candidate.per_round) == expected, candidate.name
        assert candidate.pairs == sum(f.pairs for f in candidate.per_round.values()) > 30 and candidate.hits == sum(f.hits for f in candidate.per_round.values())
        assert candidate.hit_new == candidate.hits / candidate.pairs and 0 < candidate.coverage <= 1


def test_the_pairs_of_a_round_are_the_same_for_every_candidate(chosen):
    for round_id in chosen.rounds:
        assert len({c.per_round[round_id].pairs for c in chosen.candidates}) == 1 and len({c.per_round[round_id].catalogue for c in chosen.candidates}) == 1


def test_the_recipe_chosen_is_the_one_the_rule_picks_among_the_figures(chosen, quick_view):
    rows = [(c.name, c.recipe.model, c.recipe.size, c.recipe.weight, c.hit_new, c.coverage, c.recipe.regularization or 0.0) for c in chosen.candidates]
    assert chosen.chosen.name == choose.pick(rows, quick_view.grid.choice_tolerance)
    best = max(c.hit_new for c in chosen.candidates)
    assert {c.name for c in chosen.candidates if c.kept} == {c.name for c in chosen.candidates if best - c.hit_new < quick_view.grid.choice_tolerance}
    assert [c.name for c in chosen.candidates if c.chosen] == [chosen.chosen.name] and chosen.chosen.kept


def test_the_tolerance_of_the_configuration_moves_the_set_that_is_kept(fixture_lines, quick_view, quick_cfg, chosen):
    lines = validation_lines(fixture_lines, quick_cfg)
    strict = choose.choose(lines, with_grid(quick_view, choice_tolerance=0.0))
    top = max(c.hit_new for c in strict.candidates)
    assert {c.name for c in strict.candidates if c.kept} == {c.name for c in strict.candidates if c.hit_new == top}, "with no tolerance only those that tie with the best are kept"
    wide = choose.choose(lines, with_grid(quick_view, choice_tolerance=0.99))
    assert all(c.kept for c in wide.candidates) and wide.chosen.coverage == max(c.coverage for c in wide.candidates)
    assert len([c for c in chosen.candidates if c.kept]) >= 1


def test_the_baselines_take_their_best_parameter_with_no_trend_by_the_same_rule(chosen, quick_view):
    assert set(chosen.baselines) == {"b4", "b5", "b6"}
    for key, model in (("b4", "rules"), ("b5", "als"), ("b6", "cosine")):
        mine = [c for c in chosen.candidates if c.recipe.model == model and c.recipe.weight == 0.0]
        rows = [(c.name, c.recipe.model, c.recipe.size, c.recipe.weight, c.hit_new, c.coverage, c.recipe.regularization or 0.0) for c in mine]
        assert chosen.baselines[key].name == choose.pick(rows, quick_view.grid.choice_tolerance) and chosen.baselines[key].recipe.weight == 0.0


def test_the_choice_is_the_same_whatever_the_order_of_the_lines(fixture_lines, quick_view, quick_cfg, chosen):
    shuffled = validation_lines(fixture_lines, quick_cfg).sample(frac=1, random_state=3)
    again = choose.choose(shuffled, quick_view)
    assert choose.to_dict(again) == choose.to_dict(chosen) and choose.digest(again) == choose.digest(chosen)


def test_the_digest_covers_every_figure_and_the_choice_and_the_dictionary_round_trips(chosen):
    document = choose.to_dict(chosen)
    assert json.loads(json.dumps(document)) == document and document["recipe"] == chosen.chosen.name and set(document["baselines"]) == {"b4", "b5", "b6"}
    first = document["candidates"][0]
    assert set(first) == {"name", "model", "size", "regularization", "weight", "hit_new", "coverage", "pairs", "hits", "fit_rounds", "per_round", "kept", "chosen"}
    assert first["per_round"]["R2011-03-14"] == [chosen.candidates[0].per_round["R2011-03-14"].pairs, chosen.candidates[0].per_round["R2011-03-14"].hits,
                                                 chosen.candidates[0].per_round["R2011-03-14"].distinct, chosen.candidates[0].per_round["R2011-03-14"].catalogue]
    again = choose.from_dict(document)
    assert choose.to_dict(again) == document and choose.digest(again) == choose.digest(chosen) == document["digest"] and len(document["digest"]) == 64
    figure = chosen.candidates[0].per_round["R2011-03-14"]
    tweaked_round = {**chosen.candidates[0].per_round, "R2011-03-14": dataclasses.replace(figure, hits=figure.hits + 1)}
    tweaked = dataclasses.replace(chosen, candidates=(dataclasses.replace(chosen.candidates[0], per_round=tweaked_round), *chosen.candidates[1:]))
    assert choose.digest(tweaked) != choose.digest(chosen)


# --- no line from the first day of the test (M04, D23) -----------------------------------------------------------------------------------------------


def test_a_line_from_the_first_day_of_the_test_is_refused_before_anything_is_computed(fixture_lines, quick_view, quick_cfg, monkeypatch):
    monkeypatch.setattr(context, "prepare", lambda *a, **k: pytest.fail("nothing is computed"))
    first_day = datetime.combine(quick_cfg.calendar.test_first_round, datetime.min.time())
    with pytest.raises(ValidationLeakError, match=quick_cfg.calendar.test_first_round.isoformat()) as caught:
        choose.choose(fixture_lines[fixture_lines["invoice_date"] <= first_day + (datetime(2011, 1, 2) - datetime(2011, 1, 1))], quick_view)
    assert "R5" in str(caught.value) and issubclass(ValidationLeakError, base.LeakageError)
    choose.check_validation_lines(fixture_lines[fixture_lines["invoice_date"] < first_day], quick_view)
    choose.check_validation_lines(fixture_lines.iloc[:0], quick_view)


def test_no_history_a_candidate_is_fitted_on_holds_a_line_of_the_test(fixture_lines, quick_view, quick_cfg, monkeypatch):
    """Every round gets its own cut (the lines before its Monday), so the ends of the histories are the Mondays of the validation rounds, the last one a week before the first test day."""
    seen = []
    original = context.prepare
    monkeypatch.setattr(context, "prepare", lambda history, monday, customers, view: seen.append((monday, history["invoice_date"].max())) or original(history, monday, customers, view))
    choose.choose(validation_lines(fixture_lines, quick_cfg), quick_view)
    first_day = datetime.combine(quick_cfg.calendar.test_first_round, datetime.min.time())
    assert [monday for monday, _ in seen] == cal.rounds(quick_view, "validation")
    for monday, last in seen:
        assert last < datetime.combine(monday, datetime.min.time()) < first_day


def test_the_lowest_weight_comes_before_the_simplest_base_and_both_after_the_coverage():
    """A rules candidate with a weight of 1 and an ALS one with a weight of 0.5 tie in hit and coverage: the lower weight wins, whatever the base; a higher coverage beats both."""
    tied = (("rules_5_w1", "rules", 5, 1.0, 0.3, 0.1), ("als_32_r0.1_w0.5", "als", 32, 0.5, 0.3, 0.1))
    assert choose.pick(tied, TOLERANCE) == "als_32_r0.1_w0.5"
    assert choose.pick((*tied, ("cosine_20_w2", "cosine", 20, 2.0, 0.3, 0.2)), TOLERANCE) == "cosine_20_w2"


def old_and_recent_lines():
    """Customers 1 to 20 bought product A in January 2010 and product B in June 2011 and bought B again in the week of 2011-08-01; customer 21 bought C in June 2011 and E only in the week after
    it; customers 22 to 24 bought product D in June 2011 and D again in the week; a guest bought Z in 2011-06."""
    from tests.fixtures.hand_lines import hand_frame

    at = lambda m, d: datetime(2011, m, d, 10)   # noqa: E731
    rows = []
    for c in range(1, 21):
        rows += [{"customer_id": c, "invoice": f"O{c}", "stock_code": "A", "invoice_date": datetime(2010, 1, 5, 10)}, {"customer_id": c, "invoice": f"P{c}", "stock_code": "B", "invoice_date": at(6, 1)},
                 {"customer_id": c, "invoice": f"Q{c}", "stock_code": "B", "invoice_date": at(8, 2)}]
    rows += [{"customer_id": 21, "invoice": "R21", "stock_code": "C", "invoice_date": at(6, 1)}, {"customer_id": 21, "invoice": "S21", "stock_code": "E", "invoice_date": at(8, 9)}]
    for c in range(22, 25):
        rows += [{"customer_id": c, "invoice": f"T{c}", "stock_code": "D", "invoice_date": at(6, 2)}, {"customer_id": c, "invoice": f"U{c}", "stock_code": "D", "invoice_date": at(8, 3)}]
    rows += [{"customer_id": None, "invoice": "G1", "stock_code": "Z", "invoice_date": at(6, 3), "role": "guest_purchase"}]
    return hand_frame(*rows)


def test_the_catalogue_of_the_coverage_is_the_products_with_a_basket_line_in_the_year_before_the_round_and_the_pairs_are_those_of_its_week(quick_view, monkeypatch):
    from datetime import date

    from personaloffers.recommend import blend as blend_module

    lines = old_and_recent_lines()
    monkeypatch.setattr(blend_module, "discovery_scores", lambda data, recipe, view, cache=None: np.tile(np.arange(len(data.codes), dtype=np.float32), (len(data.customers), 1)))
    wide = dataclasses.replace(quick_view, recommend=dataclasses.replace(quick_view.recommend, k=1, repeat_slots=1, discovery_slots=0))
    figures = choose.round_figures(lines, date(2011, 8, 1), choose.candidates_of(quick_view)[:1], wide)
    figure = next(iter(figures.values()))
    # products with a line in the year before 2011-08-01: B, C, D and the guest's Z; A (January 2010) is out; E is of the week after
    assert figure.catalogue == 4
    # pairs: customers 1-20 and 22-24 bought in the week; customer 21 bought only in the next week; the guest is no customer
    assert figure.pairs == 23
