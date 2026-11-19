"""The control group (U08, risk item 1: the assignment is the experiment and is not redone; RF09, AC09, C06; decision D14): who is in the control group is drawn once from the sealed
seed, inside strata, and does not move when anything later happens; whoever enters after the launch is assigned by a hash that depends on nobody else; and the balance of the covariates
is measured with the standardized difference."""

from __future__ import annotations

import dataclasses
import hashlib
import math
from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from personaloffers import base, holdout
from personaloffers import calendar as cal

BAND_COLUMNS = ("customer_id", "recency_days", "invoices_365", "spend_365", "tenure_days", "bulk", "invoices_before")


def view_with(view, **holdout_keys):
    return dataclasses.replace(view, holdout=dataclasses.replace(view.holdout, **holdout_keys))


def synthetic(n: int, seed: int = 0, bulk_share: float = 0.12) -> pd.DataFrame:
    """A base of n customers with ties in recency and in invoices (the ranks must not depend on them) and a few bulk buyers."""
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "customer_id": np.arange(91001, 91001 + n, dtype="int64"), "recency_days": np.round(rng.uniform(1, 365, n), 0),
        "invoices_365": rng.integers(1, 10, n), "spend_365": np.round(rng.gamma(2.0, 300.0, n), 2), "tenure_days": np.round(rng.uniform(1, 700, n), 1),
        "bulk": (rng.random(n) < bulk_share).astype("int64"), "invoices_before": rng.integers(1, 15, n),
    })


def band_of(values: pd.Series, bands: int) -> np.ndarray:
    """The band of each value by its rank (ties broken by the order of the rows, which is the customer number): the rank, cut at the quantiles of the ranks, right-closed."""
    ranks = values.rank(method="first").to_numpy()
    edges = np.quantile(ranks, np.linspace(0, 1, bands + 1))
    return np.searchsorted(edges[1:-1], ranks, side="left")


def p02_assignment(cov: pd.DataFrame, share: float, seed: int, recency_bands: int, frequency_bands: int) -> np.ndarray:
    """The draw of the research's ``p02_control_preperiod.py``, written again here: the control mask of the customers in the order of their number."""
    cov = cov.sort_values("customer_id").reset_index(drop=True)
    rec = pd.qcut(cov["recency_days"].rank(method="first"), recency_bands, labels=False).to_numpy()
    frq = pd.qcut(cov["invoices_365"].rank(method="first"), frequency_bands, labels=False).to_numpy()
    strata = rec * (frequency_bands * 2) + frq * 2 + cov["bulk"].to_numpy().astype(int)
    control = np.zeros(len(strata), dtype=bool)
    rng = np.random.default_rng(seed)
    for stratum in np.unique(strata):
        index = np.flatnonzero(strata == stratum)
        control[rng.permutation(index)[: int(round(share * len(index)))]] = True
    return control


# --- the strata -----------------------------------------------------------------------------------------------------------------------------------------


def test_a_stratum_is_the_recency_band_the_invoice_band_and_the_bulk_flag(quick_view):
    cov = synthetic(500, seed=1)
    found = holdout.strata(cov, quick_view)
    rec, frq = band_of(cov["recency_days"], 3), band_of(cov["invoices_365"], 3)
    assert found.dtype == np.int64 and found.tolist() == (rec * 6 + frq * 2 + cov["bulk"].to_numpy()).tolist()
    assert set(found) <= set(range(18)) and len(set(found)) == 18, "up to eighteen strata, and with 500 customers all of them"
    assert sorted(np.bincount(rec).tolist()) == [166, 167, 167], "the recency terciles are as even as ranks can make them"


def test_the_bands_come_from_the_configuration(quick_view):
    cov = synthetic(300, seed=2)
    for recency_bands, frequency_bands in ((1, 1), (2, 2), (4, 3), (3, 1)):
        view = view_with(quick_view, recency_bands=recency_bands, frequency_bands=frequency_bands)
        found = holdout.strata(cov, view)
        expected = band_of(cov["recency_days"], recency_bands) * (frequency_bands * 2) + band_of(cov["invoices_365"], frequency_bands) * 2 + cov["bulk"].to_numpy()
        assert found.tolist() == expected.tolist() and len(set(found)) <= recency_bands * frequency_bands * 2
    assert set(holdout.strata(cov, view_with(quick_view, recency_bands=1, frequency_bands=1))) == {0, 1}, "only the bulk flag is left"


def test_ties_are_broken_by_the_customer_number_and_not_by_the_order_of_the_rows(quick_view):
    cov = synthetic(120, seed=3)
    cov["recency_days"] = 50.0                      # every recency is the same: the band depends on the order of the customers alone
    cov["invoices_365"] = 4
    cov["bulk"] = 0
    in_order = holdout.strata(cov, quick_view)
    assert in_order.tolist() == [0] * 40 + [8] * 40 + [16] * 40, "the first 40 customers by number are the first band of both, and so on: ties are broken by the customer number"
    shuffled = cov.sample(frac=1, random_state=5)
    assert holdout.strata(shuffled, quick_view).tolist() == pd.Series(in_order, index=cov.index).loc[shuffled.index].tolist(), "the same customer, the same stratum, in whatever order the rows come"


def test_there_is_a_stratum_for_a_base_of_one_or_none(quick_view):
    assert holdout.strata(synthetic(0), quick_view).tolist() == []
    one = holdout.strata(synthetic(1), quick_view)
    assert one.tolist() == [0 * 6 + 0 * 2 + int(synthetic(1)["bulk"].iloc[0])]
    assert len(holdout.strata(synthetic(2), quick_view)) == 2


# --- the draw of the launch ---------------------------------------------------------------------------------------------------------------------


def test_same_seed_same_assignment_and_later_lines_do_not_change_it(fixture_lines, quick_view, quick_cfg):
    monday = quick_cfg.calendar.test_first_round
    cov = base.base_table(base.history_before(fixture_lines, monday), monday, quick_view)
    first = holdout.assign_cohort(cov, quick_view)
    again = holdout.assign_cohort(cov, quick_view)
    pd.testing.assert_frame_equal(first, again)
    assert holdout.fingerprint(first) == holdout.fingerprint(again) and len(first) == len(cov) > 100
    # nothing that happens after the launch moves it: the lines from the Monday on are removed or changed, and the draw is the same
    later = fixture_lines["invoice_date"] >= pd.Timestamp(monday)
    for edited in (fixture_lines[~later], fixture_lines.assign(quantity=np.where(later, fixture_lines["quantity"] * 9, fixture_lines["quantity"]))):
        cov_again = base.base_table(base.history_before(edited, monday), monday, quick_view)
        pd.testing.assert_frame_equal(holdout.assign_cohort(cov_again, quick_view), first)
    # the seed is what decides it
    other = holdout.assign_cohort(cov, view_with(quick_view, seed=quick_view.holdout.seed + 1))
    assert holdout.fingerprint(other) != holdout.fingerprint(first)
    assert other["stratum"].tolist() == first["stratum"].tolist() and (other["grp"] == "control").sum() == (first["grp"] == "control").sum(), "the strata and their sizes do not depend on it"
    # and the draw is the one of the research, written again with its own code
    control = p02_assignment(cov, 0.2, quick_view.holdout.seed, 3, 3)
    assert (first["grp"] == "control").tolist() == control.tolist()


def test_the_rows_in_another_order_give_the_same_assignment(quick_view):
    cov = synthetic(400, seed=4)
    ordered = holdout.assign_cohort(cov, quick_view)
    shuffled = holdout.assign_cohort(cov.sample(frac=1, random_state=11), quick_view)
    pd.testing.assert_frame_equal(ordered, shuffled)
    assert ordered["customer_id"].is_monotonic_increasing, "sorted by customer number"


def test_the_assignment_is_the_numpy_stream_of_the_sealed_seed_pinned_by_hand(quick_view):
    """Twelve customers in one stratum, a quarter in control, seed 123: ``numpy.random.default_rng(123).permutation(12)[:3]`` is positions 2, 8 and 0 (numpy 2.4.6, the pinned one).
    If another version of numpy changes the stream, this test says so before a seal does."""
    cov = synthetic(12)
    cov["bulk"] = 0
    view = view_with(quick_view, share=0.25, seed=123, recency_bands=1, frequency_bands=1)
    found = holdout.assign_cohort(cov, view)
    assert found.loc[found["grp"] == "control", "customer_id"].tolist() == [91001, 91003, 91009]
    assert (found["method"] == "stratified").all() and set(found["stratum"]) == {0}


def test_the_assignment_has_its_columns_its_types_and_leaves_the_base_alone(quick_view):
    cov = synthetic(100, seed=5)
    before = cov.copy()
    found = holdout.assign_cohort(cov, quick_view)
    pd.testing.assert_frame_equal(cov, before)
    assert list(found.columns) == ["customer_id", "grp", "method", "stratum", "assigned_round"]
    assert found["customer_id"].dtype == np.int64 and found["stratum"].dtype == np.int64 and set(found["grp"]) == {"offer", "control"}
    assert set(found["method"]) == {"stratified"} and set(found["assigned_round"]) == {"R2011-03-28"}, "the round of the launch: the first one of the test"
    assert holdout.assign_cohort(synthetic(0), quick_view).empty


@pytest.mark.parametrize("share", [0.1, 0.2, 0.3, 0.5])
def test_each_stratum_puts_round_share_of_its_customers_in_control(share, quick_view):
    cov = synthetic(500, seed=6)
    view = view_with(quick_view, share=share)
    found = holdout.assign_cohort(cov, view)
    strata = holdout.strata(cov, view)
    assert found["stratum"].tolist() == strata.tolist()
    sizes = pd.Series(strata).value_counts().sort_index()
    for stratum, size in sizes.items():
        in_control = int(((found["stratum"] == stratum) & (found["grp"] == "control")).sum())
        assert in_control == int(round(share * size)), (share, stratum, size)
    assert (found["grp"] == "control").sum() == sum(int(round(share * size)) for size in sizes)
    assert (found["grp"] == "control").to_numpy().tolist() == p02_assignment(cov, share, view.holdout.seed, 3, 3).tolist()


def test_the_count_of_a_small_stratum_is_the_rounding_of_python_and_a_stratum_of_one_has_no_control(quick_view):
    cov = synthetic(5)
    cov["bulk"] = 0
    view = view_with(quick_view, share=0.5, recency_bands=1, frequency_bands=1)
    assert (holdout.assign_cohort(cov, view)["grp"] == "control").sum() == 2, "round(2.5) is 2: the rounding is Python's, to the even number"
    assert (holdout.assign_cohort(synthetic(1), quick_view)["grp"] == "control").sum() == 0
    cov7 = synthetic(7)
    cov7["bulk"] = 0
    assert (holdout.assign_cohort(cov7, view_with(quick_view, share=0.5, recency_bands=1, frequency_bands=1))["grp"] == "control").sum() == 4, "round(3.5) is 4"


def test_two_customers_never_share_a_customer_number_in_a_cohort(quick_view):
    cov = synthetic(10)
    cov.loc[3, "customer_id"] = cov.loc[2, "customer_id"]
    with pytest.raises(ValueError, match="repet"):
        holdout.assign_cohort(cov, quick_view)


# --- the customers that enter later (D14) ----------------------------------------------------------------------------------------------------------------


def expected_group(customer: int, salt: str, share: float) -> str:
    digest = hashlib.sha256(f"{salt}:{customer}".encode("utf-8")).digest()
    return "control" if int.from_bytes(digest[:8], "big") / 2**64 < share else "offer"


def test_a_newcomer_is_assigned_by_the_hash_of_the_salt_and_its_number(quick_view):
    controls = [12355, 12359, 12360, 12361, 12367, 12369, 12373, 12378, 12381]
    got = {customer: holdout.assign_newcomer(customer, quick_view) for customer in range(12346, 12386)}
    assert [c for c, g in got.items() if g == "control"] == controls, "pinned for the salt of the configuration and 20 %"
    assert all(holdout.assign_newcomer(c, quick_view) == expected_group(c, quick_view.holdout.salt, quick_view.holdout.share) for c in range(11000, 12000))
    assert holdout.assign_newcomer(np.int64(12355), quick_view) == "control" and holdout.assign_newcomer(12346, quick_view) == "offer"


def test_a_newcomer_depends_on_nobody_else_and_on_nothing_but_its_number_the_salt_and_the_share(quick_view):
    alone = [holdout.assign_newcomer(c, quick_view) for c in range(20000, 20300)]
    assert [holdout.assign_newcomer(c, quick_view) for c in reversed(range(20000, 20300))][::-1] == alone, "no order, no state"
    assert [holdout.assign_newcomer(c, quick_view) for c in range(20000, 20300)] == alone
    rate = sum(holdout.assign_newcomer(c, quick_view) == "control" for c in range(10_000, 30_000)) / 20_000
    assert abs(rate - 0.2) < 0.01, "a fifth of the numbers go to control"
    salted = view_with(quick_view, salt="other-salt")
    assert [c for c in range(12346, 12386) if holdout.assign_newcomer(c, salted) == "control"] == [12348, 12350, 12352, 12355, 12363, 12367, 12368, 12369, 12371, 12380, 12381, 12382, 12383]
    narrow, wide = view_with(quick_view, share=0.1), view_with(quick_view, share=0.3)
    in_narrow = {c for c in range(10_000, 12_000) if holdout.assign_newcomer(c, narrow) == "control"}
    in_default = {c for c in range(10_000, 12_000) if holdout.assign_newcomer(c, quick_view) == "control"}
    in_wide = {c for c in range(10_000, 12_000) if holdout.assign_newcomer(c, wide) == "control"}
    assert in_narrow < in_default < in_wide, "a larger share only adds customers to the control group"


def test_the_newcomers_of_a_round_are_a_table_with_their_hash_group_and_no_stratum(quick_view):
    found = holdout.assign_newcomers(np.array([12361, 12346, 12355]), cal.monday_of("R2011-04-04"), quick_view)
    assert list(found.columns) == ["customer_id", "grp", "method", "stratum", "assigned_round"]
    assert found["customer_id"].tolist() == [12346, 12355, 12361] and found["grp"].tolist() == ["offer", "control", "control"]
    assert set(found["method"]) == {"hash"} and found["stratum"].isna().all() and set(found["assigned_round"]) == {"R2011-04-04"}
    assert holdout.assign_newcomers(np.array([], dtype="int64"), cal.monday_of("R2011-04-04"), quick_view).empty
    with pytest.raises(ValueError, match="lunes"):
        holdout.assign_newcomers(np.array([1]), cal.monday_of("R2011-04-04") + timedelta(days=1), quick_view)


# --- the balance (C06) -----------------------------------------------------------------------------------------------------------------------------------


def test_the_standardized_difference_is_the_offer_mean_less_the_control_mean_over_the_pooled_deviation():
    from tests.fixtures import hand_cases as hc

    x = np.array(list(hc.SMD_CONTROL) + list(hc.SMD_OFFER))
    control = np.array([True] * 4 + [False] * 4)
    assert holdout.smd(x, control) == pytest.approx(hc.SMD_EXPECTED, rel=1e-12)
    assert holdout.smd(x, ~control) == pytest.approx(-hc.SMD_EXPECTED, rel=1e-12), "swap the groups and the sign changes"
    assert holdout.smd(x[::-1], control[::-1]) == pytest.approx(hc.SMD_EXPECTED, rel=1e-12), "the order of the customers does not matter"
    assert holdout.smd(np.full(8, 3.0), control) == 0.0, "no variation: no difference"
    with pytest.raises(ValueError, match="2"):
        holdout.smd(x, np.array([True] + [False] * 7))
    with pytest.raises(ValueError, match="2"):
        holdout.smd(x, np.zeros(8, dtype=bool))


def test_the_balance_is_the_difference_of_each_of_the_five_covariates(quick_view):
    cov = synthetic(400, seed=7)
    assignment = holdout.assign_cohort(cov, quick_view)
    found = holdout.balance(cov, assignment)
    assert list(found) == list(base.COVARIATE_COLUMNS) == ["recency_days", "invoices_365", "spend_365", "tenure_days", "bulk"]
    control = (assignment["grp"] == "control").to_numpy()
    for column in found:
        values = cov.sort_values("customer_id")[column].to_numpy(dtype="float64")
        a, b = values[~control], values[control]
        expected = (a.mean() - b.mean()) / math.sqrt((a.var(ddof=1) + b.var(ddof=1)) / 2)
        assert found[column] == pytest.approx(expected, rel=1e-10), column
    assert all(math.isfinite(v) for v in found.values())


def test_the_balance_finds_a_customer_without_an_assignment_and_reads_the_rows_in_any_order(quick_view):
    cov = synthetic(100, seed=8)
    assignment = holdout.assign_cohort(cov, quick_view)
    pd.testing.assert_series_equal(pd.Series(holdout.balance(cov.sample(frac=1, random_state=1), assignment.sample(frac=1, random_state=2))), pd.Series(holdout.balance(cov, assignment)))
    with pytest.raises(ValueError, match="1 clientes"):
        holdout.balance(cov, assignment.iloc[1:])


def test_the_stratified_draw_balances_better_than_a_simple_one_on_the_covariates_it_stratifies_by(quick_view):
    """The reason for D14: over many seeds the largest difference, among the three covariates that the strata are made of, is smaller with the stratified draw than with a simple draw of the same size."""
    cov = synthetic(300, seed=9)
    stratified, simple = [], []
    for seed in range(40):
        view = view_with(quick_view, seed=seed)
        balanced = holdout.balance(cov, holdout.assign_cohort(cov, view))
        stratified.append(max(abs(balanced[c]) for c in ("recency_days", "invoices_365", "bulk")))
        rng = np.random.default_rng(seed)
        mask = np.zeros(len(cov), dtype=bool)
        mask[rng.choice(len(cov), size=round(0.2 * len(cov)), replace=False)] = True
        simple.append(max(abs(holdout.smd(cov[c].to_numpy(dtype="float64"), mask)) for c in ("recency_days", "invoices_365", "bulk")))
    assert np.mean(stratified) < np.mean(simple)


# --- what the seal keeps -------------------------------------------------------------------------------------------------------------------------------


def test_the_fingerprint_and_the_sizes_of_an_assignment(quick_view):
    found = holdout.assign_cohort(synthetic(200, seed=10), quick_view)
    lines = "".join(f"{c},{g}\n" for c, g in zip(found["customer_id"], found["grp"], strict=True))
    assert holdout.fingerprint(found) == hashlib.sha256(("customer_id,grp\n" + lines).encode("utf-8")).hexdigest()
    swapped = found.copy()
    swapped.loc[swapped.index[0], "grp"] = "control" if swapped.loc[swapped.index[0], "grp"] == "offer" else "offer"
    assert holdout.fingerprint(swapped) != holdout.fingerprint(found)
    assert holdout.fingerprint(found.sample(frac=1, random_state=3)) == holdout.fingerprint(found), "the order of the rows is not part of it"
    sizes = holdout.sizes(found)
    assert sizes["groups"] == {"offer": int((found["grp"] == "offer").sum()), "control": int((found["grp"] == "control").sum())}
    assert sum(sum(counts.values()) for counts in sizes["strata"].values()) == 200 and list(sizes["strata"]) == sorted(sizes["strata"])
    assert all(set(counts) == {"offer", "control"} for counts in sizes["strata"].values())
