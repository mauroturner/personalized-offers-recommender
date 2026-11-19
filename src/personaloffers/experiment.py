"""The experiment that is prepared and never run with an offer (RF18, AC22, C06 to C08; risk item 6; decisions D15, D16; plan section 17).

The archive has no offers, so no difference between the offer group and the control group is an effect: what this module computes is the **A/A** of a control group that is ready for the day there
are real offers, and nothing in it, by name or by text, claims an effect of an offer (D16).

* The unit is the customer of the launch cohort. **M1** is the share of the test weeks in which the customer bought something and **M2** the pounds spent on purchase lines in them; the earlier period (the
  same number of weeks before the launch) gives the **CUPED** covariate: ``y - theta (x - mean x)`` with ``theta = cov(y, x) / var(x)``, which keeps the mean and removes the part of the spread that the customer's
  own past explains.
* The **preregistered test** is the difference of the means of the adjusted outcome (offer less control), tested with a **permutation inside the strata**: the control group of each stratum is drawn again at
  random with the count it has, so every permutation keeps the control count of every stratum, and the two-sided p is ``(permutations as far from zero as the observed + 1) / (permutations + 1)``. A normal
  approximation on the raw spend rejects far too often in this archive (7.8 % to 10.4 % when it should reject 5 %); that is why it is not the test (C07, research ``p02``).
* The **calibration** (C07) draws the control group again with ``holdout.assign_cohort`` (the same procedure that is sealed) for the seeds 1 to ``calibration_seeds`` and tests each draw; with no effect, the
  tests should reject about ``alpha`` of them.
* The **minimum detectable effect** is what an operation of this size could see: ``(z(1 - alpha / 2) + z(power)) * sd * sqrt(1 / n_offer + 1 / n_control)``.

``exact_permutation`` enumerates every assignment of a small case (the hand case of eight customers) and gives the exact p that the Monte Carlo one estimates.
"""

from __future__ import annotations

import dataclasses
import itertools
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from statistics import NormalDist
from typing import Any

import numpy as np
import pandas as pd

from personaloffers import holdout
from personaloffers.holdout import smd  # noqa: F401  (the standardized difference of the balance is also the experiment's)

TOLERANCE = 1e-12          # the difference of a permutation is "as far" when it is at least the observed one less this, so that equal values computed in another order count
PERMUTATION_SEED_BASE = 100_000   # the generator of the permutations of calibration draw s is seeded with this + s (the research's p02 did the same)
TESTS = ("preregistered", "normal_raw", "normal_cuped")
METRICS = ("m1", "m2")
DAYS_PER_WEEK = 7


@dataclass(frozen=True)
class PermResult:
    diff: float          # mean of the offer group less mean of the control group
    p: float             # two-sided
    sd: float            # standard deviation of the differences of the permutations
    permutations: int
    assignments: int = 0   # the assignments enumerated by ``exact_permutation`` (0 for the Monte Carlo test)


@dataclass(frozen=True)
class Preregistered:
    diff: float
    p: float
    sd: float
    theta: float
    permutations: int


@dataclass(frozen=True)
class Outcome:
    """One metric of the cohort: the outcome of the test period, the same quantity of the earlier period, the adjusted outcome and the slope that adjusted it."""

    y: np.ndarray
    x: np.ndarray
    adjusted: np.ndarray
    theta: float


@dataclass(frozen=True)
class Calibration:
    seeds: int
    permutations: int
    alpha: float
    rejection: dict[str, float]      # ``<metric>_<test>`` -> the share of the draws that the test rejected


# --- the outcomes and CUPED ---------------------------------------------------------------------------------------------------------------------------------


def week_mondays(end: date, weeks: int) -> list[date]:
    """The `weeks` consecutive Mondays that end the week before the Monday `end`: ``end - 7 * weeks`` to ``end - 7``."""
    if end.weekday() != 0 or weeks < 1:
        raise ValueError(f"{end.isoformat()} debe ser un lunes y las semanas, 1 o más")
    return [end - timedelta(days=DAYS_PER_WEEK * (weeks - n)) for n in range(weeks)]


def _check_weeks(weeks: Sequence[date]) -> None:
    if not weeks or any(day.weekday() != 0 for day in weeks) or any((b - a).days != DAYS_PER_WEEK for a, b in itertools.pairwise(weeks)):
        raise ValueError("las semanas deben ser lunes consecutivos, una lista no vacía")


def outcomes(lines: pd.DataFrame, cohort: np.ndarray, weeks: Sequence[date]) -> tuple[np.ndarray, np.ndarray]:
    """``(m1, m2)`` for the customers `cohort` (in its order) over the Mondays `weeks`: the share of those weeks in which the customer had a purchase line and the pounds (quantity times price) of its purchase
    lines in them. Only lines of role ``purchase`` of a customer of the cohort, dated from the first Monday to the end of the last week, count."""
    _check_weeks(weeks)
    people = np.asarray(cohort, dtype="int64")
    start = datetime.combine(weeks[0], time.min)
    end = datetime.combine(weeks[-1] + timedelta(days=DAYS_PER_WEEK), time.min)
    rows = lines[(lines["role"] == "purchase") & lines["customer_id"].notna() & (lines["invoice_date"] >= start) & (lines["invoice_date"] < end)]
    rows = rows[rows["customer_id"].isin(people)].sort_values("line_key", kind="stable")
    customer = rows["customer_id"].astype("int64").to_numpy()
    week = ((rows["invoice_date"] - pd.Timestamp(start)) // pd.Timedelta(days=DAYS_PER_WEEK)).to_numpy("int64")
    value = rows["quantity"].to_numpy("float64") * rows["price"].to_numpy("float64")
    index = pd.Index(people).get_indexer(customer)
    spend = np.bincount(index, weights=value, minlength=len(people))
    active = np.zeros((len(people), len(weeks)), dtype=bool)
    active[index, week] = True
    return active.sum(axis=1) / len(weeks), spend.astype(np.float64)


def cuped(y: np.ndarray, x: np.ndarray) -> tuple[np.ndarray, float]:
    """``(adjusted, theta)``: ``y - theta (x - mean x)`` with ``theta = cov(y, x) / var(x)`` (0 when `x` does not vary, which leaves `y` as it is)."""
    outcome, covariate = np.asarray(y, dtype=np.float64), np.asarray(x, dtype=np.float64)
    if outcome.shape != covariate.shape:
        raise ValueError(f"el resultado y el período anterior deben tener el mismo número de clientes ({outcome.shape} y {covariate.shape})")
    spread = covariate.var(ddof=1)
    theta = float(np.cov(outcome, covariate, ddof=1)[0, 1] / spread) if spread > 0 else 0.0
    return outcome - theta * (covariate - covariate.mean()), theta


def make_outcome(y: np.ndarray, x: np.ndarray) -> Outcome:
    adjusted, theta = cuped(y, x)
    return Outcome(y=np.asarray(y, dtype=np.float64), x=np.asarray(x, dtype=np.float64), adjusted=adjusted, theta=theta)


# --- the tests ---------------------------------------------------------------------------------------------------------------------------------------------


def welch(y: np.ndarray, control: np.ndarray) -> tuple[float, float]:
    """``(difference, standard error)`` of the normal test: the mean of the offer group less the mean of the control group, and ``sqrt(var_offer / n_offer + var_control / n_control)``."""
    values, mask = np.asarray(y, dtype=np.float64), np.asarray(control, dtype=bool)
    offer, held = values[~mask], values[mask]
    return float(offer.mean() - held.mean()), float(np.sqrt(offer.var(ddof=1) / len(offer) + held.var(ddof=1) / len(held)))


def draw_assignments(strata: np.ndarray, control: np.ndarray, permutations: int, rng: np.random.Generator) -> np.ndarray:
    """`permutations` assignments of the control group, drawn inside each stratum with the count that stratum has (a boolean permutations by customers matrix): the control customers of each stratum are
    chosen by ranking random numbers, the strata taken in order, so the same generator gives the same draws."""
    labels, mask = np.asarray(strata), np.asarray(control, dtype=bool)
    assignments = np.zeros((permutations, len(labels)), dtype=bool)
    for stratum in np.unique(labels):
        members = np.flatnonzero(labels == stratum)
        keep = int(mask[members].sum())
        if keep:
            ranks = rng.random((permutations, len(members))).argsort(axis=1).argsort(axis=1)
            assignments[:, members] = ranks < keep
    return assignments


def _differences(y: np.ndarray, assignments: np.ndarray) -> np.ndarray:
    held = assignments.sum(axis=1)
    in_control = assignments.astype(np.float64) @ y
    return (y.sum() - in_control) / (len(y) - held) - in_control / held


def stratified_permutation(y: np.ndarray, control: np.ndarray, strata: np.ndarray, permutations: int, rng: np.random.Generator | None, *,
                           assignments: np.ndarray | None = None) -> PermResult:
    """The test of the difference of means (offer less control) by permutation inside the strata, two-sided. `assignments` are given when two outcomes share the same draws."""
    values, mask = np.asarray(y, dtype=np.float64), np.asarray(control, dtype=bool)
    observed = float(values[~mask].mean() - values[mask].mean())
    drawn = draw_assignments(strata, mask, permutations, rng) if assignments is None else assignments
    differences = _differences(values, drawn)
    as_far = int(np.sum(np.abs(differences) >= abs(observed) - TOLERANCE))
    return PermResult(diff=observed, p=(as_far + 1) / (len(differences) + 1), sd=float(differences.std(ddof=1)), permutations=len(differences))


def exact_differences(y: np.ndarray, control: np.ndarray, strata: np.ndarray) -> np.ndarray:
    """The difference of means of every assignment that keeps the control count of each stratum (all of them: only for small cases)."""
    values, mask, labels = np.asarray(y, dtype=np.float64), np.asarray(control, dtype=bool), np.asarray(strata)
    groups = [(np.flatnonzero(labels == s), int(mask[labels == s].sum())) for s in np.unique(labels)]
    found = []
    for choice in itertools.product(*(itertools.combinations(members, keep) for members, keep in groups)):
        held = np.zeros(len(values), dtype=bool)
        for part in choice:
            held[list(part)] = True
        found.append(values[~held].mean() - values[held].mean())
    return np.array(found)


def exact_permutation(y: np.ndarray, control: np.ndarray, strata: np.ndarray, limit: int = 1_000_000) -> PermResult:
    """The same test with every assignment instead of a sample of them: the exact p of a small case (more than `limit` assignments is a ``ValueError``)."""
    mask, labels = np.asarray(control, dtype=bool), np.asarray(strata)
    total = math.prod(math.comb(int((labels == s).sum()), int(mask[labels == s].sum())) for s in np.unique(labels))
    if total > limit:
        raise ValueError(f"hay {total} asignaciones posibles, más que el límite de {limit}: para un caso grande se usa stratified_permutation")
    values = np.asarray(y, dtype=np.float64)
    observed = float(values[~mask].mean() - values[mask].mean())
    differences = exact_differences(values, mask, labels)
    as_far = int(np.sum(np.abs(differences) >= abs(observed) - TOLERANCE))
    return PermResult(diff=observed, p=as_far / len(differences), sd=float(differences.std(ddof=1)), permutations=len(differences), assignments=len(differences))


def preregistered(y: np.ndarray, x: np.ndarray, control: np.ndarray, strata: np.ndarray, permutations: int, rng: np.random.Generator) -> Preregistered:
    """The preregistered test of C07 and C08: the outcome adjusted with its earlier period, tested by permutation inside the strata."""
    adjusted, theta = cuped(y, x)
    result = stratified_permutation(adjusted, control, strata, permutations, rng)
    return Preregistered(diff=result.diff, p=result.p, sd=result.sd, theta=theta, permutations=result.permutations)


# --- the calibration and the minimum detectable effect ---------------------------------------------------------------------------------------------------


def _check_cohort(outcomes_by_metric: Mapping[str, Outcome], cov: pd.DataFrame) -> None:
    ids = cov["customer_id"].to_numpy()
    if not (np.diff(ids) > 0).all():
        raise ValueError("la cohorte debe venir en orden ascendente de cliente y sin repetidos")
    if any(len(outcome.y) != len(ids) for outcome in outcomes_by_metric.values()):
        raise ValueError(f"los resultados deben tener un valor por cliente de la cohorte ({len(ids)})")


def _normal_p(diff: float, error: float) -> float:
    """The two-sided p of the normal test: 1 when there is no difference and no spread, 0 when there is a difference and no spread."""
    if error == 0:
        return 1.0 if diff == 0 else 0.0
    return 2.0 * (1.0 - NormalDist().cdf(abs(diff) / error))


normal_p = _normal_p        # the name that ``evaluation`` uses for the p of the two normal tests that are shown beside the preregistered one


def calibration_draw(outcomes_by_metric: Mapping[str, Outcome], cov: pd.DataFrame, view: Any, seed: int) -> dict[str, float]:
    """The p-value of every test on the draw of the control group made with `seed` (``<metric>_<test>`` -> p): the draw is ``holdout.assign_cohort`` with that seed, the preregistered test uses
    ``calibration_permutations`` permutations of the generator seeded ``PERMUTATION_SEED_BASE + seed`` (shared by the metrics of the draw) and the two normal tests are the ones C10 shows beside it."""
    x = view.experiment
    drawn = holdout.assign_cohort(cov, dataclasses.replace(view, holdout=dataclasses.replace(view.holdout, seed=seed)))
    control = (drawn["grp"] == "control").to_numpy()
    strata = drawn["stratum"].to_numpy(dtype="int64")
    assignments = draw_assignments(strata, control, x.calibration_permutations, np.random.default_rng(PERMUTATION_SEED_BASE + seed))
    found: dict[str, float] = {}
    for metric, outcome in outcomes_by_metric.items():
        found[f"{metric}_preregistered"] = stratified_permutation(outcome.adjusted, control, strata, x.calibration_permutations, None, assignments=assignments).p
        for test, values in (("normal_raw", outcome.y), ("normal_cuped", outcome.adjusted)):
            found[f"{metric}_{test}"] = _normal_p(*welch(values, control))
    return found


def calibrate(outcomes_by_metric: Mapping[str, Outcome], cov: pd.DataFrame, view: Any) -> Calibration:
    """The rejection rate of each test over new draws of the control group (C07): the share of the seeds 1 to ``calibration_seeds`` whose ``calibration_draw`` has a p under ``alpha``. The cohort `cov`
    (its covariates, one row per customer, sorted by number) and the outcomes (in that order) are those of the launch."""
    _check_cohort(outcomes_by_metric, cov)
    x = view.experiment
    rejected = {f"{metric}_{test}": 0 for metric in outcomes_by_metric for test in TESTS}
    for seed in range(1, x.calibration_seeds + 1):
        for name, p in calibration_draw(outcomes_by_metric, cov, view, seed).items():
            rejected[name] += p < x.alpha
    return Calibration(seeds=x.calibration_seeds, permutations=x.calibration_permutations, alpha=x.alpha, rejection={name: count / x.calibration_seeds for name, count in rejected.items()})


def mde(sd: float, n_offer: int, n_control: int, alpha: float, power: float) -> float:
    """The smallest difference of means that a test of level `alpha` finds with probability `power`: ``(z(1 - alpha / 2) + z(power)) * sd * sqrt(1 / n_offer + 1 / n_control)``."""
    normal = NormalDist()
    return (normal.inv_cdf(1 - alpha / 2) + normal.inv_cdf(power)) * sd * math.sqrt(1 / n_offer + 1 / n_control)


def mde_table(*, sd_m1: float, sd_m2: float, customers: int, shares: Sequence[float], alpha: float, power: float) -> list[dict[str, float]]:
    """For each share of the cohort kept as control: its size and the smallest difference of M1 (a share of weeks) and of M2 (pounds) that the test could detect."""
    rows = []
    for share in shares:
        held = int(round(share * customers))
        rows.append({"holdout_share": share, "holdout_size": held, "mde_m1": mde(sd_m1, customers - held, held, alpha, power), "mde_m2": mde(sd_m2, customers - held, held, alpha, power)})
    return rows
