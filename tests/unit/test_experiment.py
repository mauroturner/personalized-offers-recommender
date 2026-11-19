"""The experiment that is prepared and never run with an offer (U10, risk item 6; RF18, AC22, C07, C08; decisions D15, D16): the outcomes of the cohort, the standardized difference, CUPED, the
permutation test inside the strata (with its exact p in a case of eight customers), the calibration of the test on new draws of the control group and the minimum detectable effect. Nothing
here is named after an effect of an offer: the differences it computes are those of an A/A."""

from __future__ import annotations

import dataclasses
import math
from datetime import date, datetime
from fractions import Fraction
from statistics import NormalDist

import numpy as np
import pandas as pd
import pytest

from personaloffers import experiment, holdout
from tests.fixtures import hand_cases as hc
from tests.fixtures.hand_lines import hand_frame

MONDAYS = [date(2011, 8, 1), date(2011, 8, 8), date(2011, 8, 15)]


def permutation_case() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    customers = sorted(hc.PERMUTATION_STRATA)
    y = np.array([hc.PERMUTATION_Y[c] for c in customers])
    strata = np.array([hc.PERMUTATION_STRATA[c] for c in customers])
    control = np.array([c in hc.PERMUTATION_CONTROL for c in customers])
    return y, control, strata


# --- the standardized difference and CUPED -------------------------------------------------------------------------------------------------------------


def test_the_standardized_difference_is_the_one_of_the_control_group_and_the_hand_case():
    assert experiment.smd is holdout.smd
    x = np.array(list(hc.SMD_CONTROL) + list(hc.SMD_OFFER))
    control = np.array([True] * 4 + [False] * 4)
    assert experiment.smd(x, control) == pytest.approx(hc.SMD_EXPECTED, rel=1e-12)


def test_cuped_adjusts_by_the_slope_of_the_earlier_period_and_keeps_the_mean():
    """AC22: theta = cov(y, x) / var(x); the adjusted outcome is y - theta (x - mean x), with the same mean and a smaller variance."""
    y, x = np.array(hc.CUPED_Y), np.array(hc.CUPED_X)
    adjusted, theta = experiment.cuped(y, x)
    assert theta == pytest.approx(hc.CUPED_THETA, abs=1e-15)
    assert adjusted == pytest.approx(np.array(hc.CUPED_ADJUSTED), abs=1e-12)
    assert adjusted.mean() == pytest.approx(y.mean()) and adjusted.var(ddof=1) < y.var(ddof=1) / 40
    assert not np.shares_memory(adjusted, y), "the outcome that comes in is not changed"


def test_cuped_with_a_constant_earlier_period_changes_nothing_and_a_mismatch_is_refused():
    y = np.array([1.0, 2.0, 5.0, 4.0])
    adjusted, theta = experiment.cuped(y, np.full(4, 3.0))
    assert theta == 0.0 and np.array_equal(adjusted, y)
    with pytest.raises(ValueError, match="mismo"):
        experiment.cuped(y, np.array([1.0, 2.0]))


# --- the permutation test ------------------------------------------------------------------------------------------------------------------------------


def test_the_exact_permutation_of_the_hand_case_has_the_p_worked_out_by_hand():
    """AC22: eight customers in two strata, two of each stratum in the control group: 36 assignments, 10 as far from zero as the observed -3, p = 10/36."""
    y, control, strata = permutation_case()
    found = experiment.exact_permutation(y, control, strata)
    assert found.diff == hc.PERMUTATION_DIFFERENCE and found.assignments == hc.PERMUTATION_ASSIGNMENTS
    assert Fraction(found.p).limit_denominator(100) == hc.PERMUTATION_P and found.p == pytest.approx(10 / 36, abs=1e-15)
    assert found.sd == pytest.approx(np.std(experiment.exact_differences(y, control, strata), ddof=1))
    flipped = experiment.exact_permutation(y, ~control, strata)
    assert flipped.diff == 3.0 and flipped.p == found.p and flipped.assignments == 36


def test_each_permutation_keeps_the_control_count_of_every_stratum():
    """The assignments are drawn inside the strata: every row has the observed number of control customers in each one, and the draws are not all the same."""
    rng = np.random.default_rng(0)
    strata = np.repeat(np.arange(5), [7, 11, 3, 20, 9])
    control = np.zeros(len(strata), dtype=bool)
    for stratum, count in zip(range(5), [2, 3, 1, 4, 2], strict=True):
        control[np.flatnonzero(strata == stratum)[:count]] = True
    assignments = experiment.draw_assignments(strata, control, 500, rng)
    assert assignments.shape == (500, len(strata)) and assignments.dtype == bool
    for stratum in range(5):
        assert (assignments[:, strata == stratum].sum(axis=1) == control[strata == stratum].sum()).all(), stratum
    assert (assignments.sum(axis=1) == control.sum()).all()
    assert len({row.tobytes() for row in assignments}) > 450, "the permutations are not repeated"
    again = experiment.draw_assignments(strata, control, 500, np.random.default_rng(0))
    assert np.array_equal(assignments, again), "the same generator, the same draws"


def test_the_p_value_counts_the_permutations_as_far_from_zero_plus_one_over_the_permutations_plus_one():
    y = np.array([10.0, 12.0, 4.0, 6.0])
    control, strata = np.array([True, True, False, False]), np.zeros(4, dtype=int)
    given = np.array([[True, True, False, False], [False, False, True, True], [True, False, True, False]])
    found = experiment.stratified_permutation(y, control, strata, 3, np.random.default_rng(0), assignments=given)
    assert found.diff == -6.0
    assert found.p == pytest.approx((2 + 1) / (3 + 1)), "the observed one and its mirror are as far as the observed; the third is not"
    assert found.sd == pytest.approx(np.std([-6.0, 6.0, 2.0], ddof=1)) and found.permutations == 3


def test_the_monte_carlo_p_is_the_exact_p_of_the_hand_case_within_the_noise():
    y, control, strata = permutation_case()
    found = experiment.stratified_permutation(y, control, strata, 20_000, np.random.default_rng(7))
    assert found.p == pytest.approx(10 / 36, abs=0.012) and found.diff == -3.0 and found.permutations == 20_000


def test_the_p_value_is_two_sided_and_never_zero():
    y = np.arange(20, dtype=float) * 100
    control = np.zeros(20, dtype=bool)
    control[:10] = True
    found = experiment.stratified_permutation(y, control, np.zeros(20, dtype=int), 200, np.random.default_rng(0))
    assert found.p >= 1 / 201, "even the most extreme observed difference has a p of at least 1 / (permutations + 1)"
    assert found.diff == 1000.0 and found.p < 0.05


def test_the_preregistered_test_is_the_stratified_permutation_on_cuped():
    """C07, C08: the outcome is adjusted with the earlier period (CUPED) and tested with the permutation inside the strata, not with a normal approximation on the raw outcome."""
    rng = np.random.default_rng(11)
    n = 240
    strata = np.repeat(np.arange(6), n // 6)
    x = rng.gamma(2.0, 100.0, n)
    y = 0.8 * x + rng.normal(0, 20, n)
    control = np.zeros(n, dtype=bool)
    for stratum in range(6):
        control[np.flatnonzero(strata == stratum)[:8]] = True
    found = experiment.preregistered(y, x, control, strata, 300, np.random.default_rng(3))
    adjusted, theta = experiment.cuped(y, x)
    manual = experiment.stratified_permutation(adjusted, control, strata, 300, np.random.default_rng(3))
    assert (found.diff, found.p, found.sd, found.theta) == (manual.diff, manual.p, manual.sd, theta)
    raw = experiment.stratified_permutation(y, control, strata, 300, np.random.default_rng(3))
    assert found.sd < raw.sd / 3, "the earlier period explains most of the spread, so the adjusted test sees far less noise"
    assert found.diff == pytest.approx(y[~control].mean() - y[control].mean() - theta * (x[~control].mean() - x[control].mean()))


def test_the_normal_p_is_two_sided_and_a_difference_without_any_spread_is_decisive():
    assert experiment._normal_p(1.959963984540054, 1.0) == pytest.approx(0.05, abs=1e-12)
    assert experiment._normal_p(-1.959963984540054, 1.0) == pytest.approx(0.05, abs=1e-12)
    assert experiment._normal_p(0.0, 0.0) == 1.0 and experiment._normal_p(2.0, 0.0) == 0.0 and experiment._normal_p(0.0, 1.0) == 1.0


def test_the_normal_test_gives_the_difference_of_the_means_and_its_standard_error():
    y, control, _ = permutation_case()
    diff, se = experiment.welch(y, control)
    offer, held = y[~control], y[control]
    assert diff == offer.mean() - held.mean() == -3.0
    assert se == pytest.approx(math.sqrt(offer.var(ddof=1) / 4 + held.var(ddof=1) / 4))


# --- the outcomes of the cohort ------------------------------------------------------------------------------------------------------------------------


def lines_of_the_hand_case() -> pd.DataFrame:
    at = lambda *parts: datetime(*parts)   # noqa: E731
    return hand_frame(
        {"customer_id": 1, "invoice": "A1", "invoice_date": at(2011, 8, 2, 10), "quantity": 2, "price": 3.5},     # week 1: 7.00
        {"customer_id": 1, "invoice": "A2", "invoice_date": at(2011, 8, 4, 10), "quantity": 1, "price": 1.25},    # week 1 again: 1.25
        {"customer_id": 1, "invoice": "A3", "invoice_date": at(2011, 8, 16, 9), "quantity": 10, "price": 0.5},    # week 3: 5.00
        {"customer_id": 1, "invoice": "A4", "invoice_date": at(2011, 8, 22, 0), "quantity": 99, "price": 9.0},    # after the last week: out
        {"customer_id": 1, "invoice": "A0", "invoice_date": at(2011, 7, 31, 23, 59), "quantity": 99, "price": 9.0},   # before the first: out
        {"customer_id": 2, "invoice": "B1", "invoice_date": at(2011, 8, 9, 12), "quantity": 4, "price": 2.0},     # week 2: 8.00
        {"customer_id": 3, "invoice": "C1", "invoice_date": at(2011, 8, 3, 12), "quantity": -2, "price": 2.0, "role": "cancellation"},
        {"customer_id": 3, "invoice": "C2", "invoice_date": at(2011, 8, 3, 13), "quantity": 1, "price": 2.0, "role": "bad_price"},
        {"customer_id": None, "invoice": "G1", "invoice_date": at(2011, 8, 3, 14), "quantity": 5, "price": 1.0, "role": "guest_purchase"},
        {"customer_id": 9, "invoice": "Z1", "invoice_date": at(2011, 8, 3, 15), "quantity": 5, "price": 1.0},       # not in the cohort
    )


def test_the_outcomes_are_the_share_of_weeks_with_a_purchase_and_the_spend_of_the_cohort():
    """M1: the weeks (of the three) in which the customer bought something, over three; M2: the pounds of the purchase lines of those weeks. Only the cohort, only purchases."""
    m1, m2 = experiment.outcomes(lines_of_the_hand_case(), np.array([1, 2, 3, 4]), MONDAYS)
    assert m1.tolist() == [pytest.approx(2 / 3), pytest.approx(1 / 3), 0.0, 0.0]
    assert m2.tolist() == [pytest.approx(13.25), 8.0, 0.0, 0.0]
    assert m1.dtype == m2.dtype == np.float64


def test_the_share_of_weeks_is_over_the_weeks_given_and_the_lines_of_the_others_do_not_count():
    lines = lines_of_the_hand_case()
    m1, m2 = experiment.outcomes(lines, np.array([1, 2]), MONDAYS[:2])
    assert m1.tolist() == [0.5, 0.5] and m2.tolist() == [pytest.approx(8.25), 8.0], "customer 1 bought in the first of the two weeks only: the purchase of the third week is out"
    m1, _ = experiment.outcomes(lines, np.array([1]), MONDAYS + [date(2011, 8, 22)])
    assert m1.tolist() == [pytest.approx(3 / 4)], "the line of 2011-08-22 is in the fourth week"


def test_the_outcomes_of_a_cohort_follow_the_order_of_the_cohort_and_need_consecutive_mondays():
    lines = lines_of_the_hand_case()
    m1, m2 = experiment.outcomes(lines, np.array([2, 1]), MONDAYS)
    assert m2.tolist() == [8.0, pytest.approx(13.25)]
    for bad in ([date(2011, 8, 2)], [MONDAYS[0], MONDAYS[2]], []):
        with pytest.raises(ValueError, match="lunes|semanas"):
            experiment.outcomes(lines, np.array([1]), bad)


def test_the_weeks_before_a_monday_are_the_consecutive_mondays_that_end_the_week_before_it():
    assert experiment.week_mondays(date(2011, 8, 22), 3) == MONDAYS
    assert experiment.week_mondays(date(2011, 8, 1), 18)[0] == date(2011, 3, 28) and experiment.week_mondays(date(2011, 8, 1), 18)[-1] == date(2011, 7, 25)


# --- the calibration and the minimum detectable effect ---------------------------------------------------------------------------------------------


def synthetic_cohort(n: int = 300, seed: int = 0):
    rng = np.random.default_rng(seed)
    cov = pd.DataFrame({"customer_id": np.arange(91001, 91001 + n, dtype="int64"), "recency_days": np.round(rng.uniform(1, 365, n)), "invoices_365": rng.integers(1, 10, n),
                        "spend_365": rng.gamma(2.0, 300.0, n), "tenure_days": rng.uniform(1, 700, n), "bulk": (rng.random(n) < 0.1).astype("int64"),
                        "invoices_before": rng.integers(1, 12, n)})
    earlier = rng.gamma(1.5, 40.0, n)
    now = 0.6 * earlier + rng.gamma(1.2, 30.0, n)
    return cov, earlier, now


def test_the_calibration_draws_the_control_group_again_with_the_seeds_one_to_n_and_reports_rates(quick_view, monkeypatch):
    cov, earlier, now = synthetic_cohort()
    outcomes = {"m1": experiment.make_outcome(now / 100, earlier / 100), "m2": experiment.make_outcome(now, earlier)}
    seeds = []
    original = holdout.assign_cohort
    monkeypatch.setattr(holdout, "assign_cohort", lambda c, v: seeds.append(v.holdout.seed) or original(c, v))
    found = experiment.calibrate(outcomes, cov, quick_view)
    assert seeds == list(range(1, quick_view.experiment.calibration_seeds + 1)) and quick_view.holdout.seed not in seeds
    assert found.seeds == quick_view.experiment.calibration_seeds and found.permutations == quick_view.experiment.calibration_permutations
    assert set(found.rejection) == {f"{m}_{test}" for m in ("m1", "m2") for test in ("preregistered", "normal_raw", "normal_cuped")}
    for rate in found.rejection.values():
        assert 0.0 <= rate <= 1.0 and rate * found.seeds == pytest.approx(round(rate * found.seeds))
    assert found.rejection["m1_preregistered"] <= 0.2 and found.rejection["m2_preregistered"] <= 0.2, "no effect was added: the test rejects about 5 % of the draws, never most of them"
    again = experiment.calibrate(outcomes, cov, quick_view)
    assert again == found, "the same inputs, the same rates"


def test_each_test_of_the_calibration_rejects_about_alpha_of_the_draws_when_nothing_was_added(quick_view):
    """With 200 draws of the control group and no effect in the data, the rate of each test is near 0.05 (the normal tests on a bounded outcome too); a test that rejected a third is not calibrated."""
    cov, earlier, now = synthetic_cohort(300, seed=4)
    outcomes = {"m1": experiment.make_outcome(now / 100, earlier / 100), "m2": experiment.make_outcome(now, earlier)}
    wide = dataclasses.replace(quick_view, experiment=dataclasses.replace(quick_view.experiment, calibration_seeds=200, calibration_permutations=60))
    found = experiment.calibrate(outcomes, cov, wide)
    assert found.alpha == 0.05 and found.seeds == 200
    for name, rate in found.rejection.items():
        assert rate <= 0.13, (name, rate)
    assert any(rate > 0 for rate in found.rejection.values()), "and the draws are not all the same"


def test_a_draw_of_the_calibration_is_the_sealed_procedure_with_its_seed_and_each_test_on_its_own_outcome(quick_view):
    """Written again with the pieces of the module: the draw of seed s is the sealed procedure with that seed; its permutations come from the generator seeded 100,000 + s and are the same for
    both metrics; the preregistered test is on the adjusted outcome and the two normal ones on the raw and on the adjusted."""
    cov, earlier, now = synthetic_cohort(200, seed=6)
    first, second = experiment.make_outcome(now / 50, earlier / 50), experiment.make_outcome(now, earlier * 0.5)
    config = dataclasses.replace(quick_view, experiment=dataclasses.replace(quick_view.experiment, calibration_permutations=40))
    for seed in (1, 2, 7):
        drawn = holdout.assign_cohort(cov, dataclasses.replace(config, holdout=dataclasses.replace(config.holdout, seed=seed)))
        control, strata = (drawn["grp"] == "control").to_numpy(), drawn["stratum"].to_numpy("int64")
        shared = experiment.draw_assignments(strata, control, 40, np.random.default_rng(100_000 + seed))
        expected = {}
        for metric, outcome in (("m1", first), ("m2", second)):
            expected[f"{metric}_preregistered"] = experiment.stratified_permutation(outcome.adjusted, control, strata, 40, None, assignments=shared).p
            for test, values in (("normal_raw", outcome.y), ("normal_cuped", outcome.adjusted)):
                diff = values[~control].mean() - values[control].mean()
                error = math.sqrt(values[~control].var(ddof=1) / (~control).sum() + values[control].var(ddof=1) / control.sum())
                expected[f"{metric}_{test}"] = 2 * (1 - NormalDist().cdf(abs(diff) / error))
        found = experiment.calibration_draw({"m1": first, "m2": second}, cov, config, seed)
        assert found.keys() == expected.keys() and all(found[name] == pytest.approx(expected[name], abs=1e-12) for name in expected), seed
    assert experiment.calibration_draw({"m1": first, "m2": second}, cov, config, 1) != experiment.calibration_draw({"m1": first, "m2": second}, cov, config, 2)


def test_the_rate_of_each_test_is_the_share_of_draws_with_a_p_under_alpha(quick_view):
    cov, earlier, now = synthetic_cohort(150, seed=8)
    outcome = experiment.make_outcome(now, earlier)
    config = dataclasses.replace(quick_view, experiment=dataclasses.replace(quick_view.experiment, calibration_seeds=30, calibration_permutations=40))
    draws = [experiment.calibration_draw({"m1": outcome, "m2": outcome}, cov, config, seed) for seed in range(1, 31)]
    found = experiment.calibrate({"m1": outcome, "m2": outcome}, cov, config)
    for name, rate in found.rejection.items():
        assert rate == sum(draw[name] < 0.05 for draw in draws) / 30, name


def test_the_calibration_of_a_constant_outcome_never_rejects(quick_view):
    """A constant outcome has no difference in any draw: the rate is zero for every test (the standard error is zero too, and zero is not above zero)."""
    cov, _earlier, _now = synthetic_cohort(120, seed=2)
    constant = experiment.make_outcome(np.full(120, 5.0), np.full(120, 2.0))
    found = experiment.calibrate({"m1": constant, "m2": constant}, cov, quick_view)
    assert all(rate == 0.0 for rate in found.rejection.values())


def test_the_calibration_needs_the_outcomes_in_the_order_of_the_cohort(quick_view):
    cov, earlier, now = synthetic_cohort(50)
    short = experiment.make_outcome(now[:40], earlier[:40])
    with pytest.raises(ValueError, match="cohorte"):
        experiment.calibrate({"m1": short, "m2": short}, cov, quick_view)
    shuffled = cov.sample(frac=1, random_state=0)
    with pytest.raises(ValueError, match="orden"):
        experiment.calibrate({"m1": experiment.make_outcome(now, earlier), "m2": experiment.make_outcome(now, earlier)}, shuffled, quick_view)


def test_the_number_of_seeds_and_of_permutations_come_from_the_experiment_section(quick_view):
    cov, earlier, now = synthetic_cohort(150)
    outcomes = {"m1": experiment.make_outcome(now, earlier), "m2": experiment.make_outcome(now, earlier)}
    smaller = dataclasses.replace(quick_view, experiment=dataclasses.replace(quick_view.experiment, calibration_seeds=8, calibration_permutations=30))
    found = experiment.calibrate(outcomes, cov, smaller)
    assert (found.seeds, found.permutations) == (8, 30) and all(rate * 8 == pytest.approx(round(rate * 8)) for rate in found.rejection.values())


def test_the_minimum_detectable_effect_of_the_hand_cases():
    """AC22: (z(0.975) + z(0.80)) x sd x sqrt(1 / n_offer + 1 / n_control), the research's figures."""
    for sd, offered, control, expected in hc.MDE_CASES:
        assert experiment.mde(sd, offered, control, 0.05, 0.80) == pytest.approx(expected, rel=1e-12)
    z = NormalDist()
    assert experiment.mde(1.0, 100, 100, 0.10, 0.90) == pytest.approx((z.inv_cdf(0.95) + z.inv_cdf(0.90)) * math.sqrt(0.02), rel=1e-12)


def test_the_table_of_effects_a_holdout_of_ten_twenty_and_thirty_per_cent_could_detect():
    table = experiment.mde_table(sd_m1=0.0669, sd_m2=1541.05, customers=4320, shares=(0.10, 0.20, 0.30), alpha=0.05, power=0.80)
    assert [row["holdout_share"] for row in table] == [0.10, 0.20, 0.30] and [row["holdout_size"] for row in table] == [432, 864, 1296]
    twenty = table[1]
    assert twenty["mde_m1"] == pytest.approx(hc.MDE_CASES[0][3], rel=1e-12) and twenty["mde_m2"] == pytest.approx(hc.MDE_CASES[1][3], rel=1e-12)
    assert table[0]["mde_m1"] > twenty["mde_m1"] > table[2]["mde_m1"], "a larger holdout detects smaller effects"
