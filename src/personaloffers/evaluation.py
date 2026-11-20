"""The evaluation of the test, once, from what was emitted (RF18, AC21, AC22, AC23, AC25; risk item 1: the test is evaluated once; decisions D08, D15, D16, D18, D19, D20; plan sections 16 and 17).

**What is evaluated is what was issued.** The figures come from ``offer_lists`` and ``baseline_lists`` (the lists of each round, the control group's included, which is as valid as the other to measure an order),
``round_outcomes`` and ``contact_base`` (who was in the base of each round and who bought in its week), the lines of the warehouse (what they bought) and ``holdout_assignments``: nothing is recomputed with a model
at the close (the lesson B2 of project 07). A pair is a round of the test and a customer of its base with a purchase line in its week; ``eval_pairs`` keeps each pair's four metrics for every method (customer numbers:
it never leaves ``data/``).

* ``evaluate_rankings``: hit@10, recall@10, precision@10 and NDCG@10 of the list, B0-B6 and the chosen discovery, each unrestricted and (but the list) new only, by round and in all the test; the 95 % interval of each hit
  rate and the paired differences of C01-C04 by resampling **customers** (``metrics``), Wilson's interval beside them, the cuts by segment and the coverage (the distinct products in **all** the lists of the round, the
  control group's included, over the products with a basket line in the 365 days before it; the validation's coverage in ``choose`` is over the lists of the evaluated pairs, a different denominator);
* ``run_experiment`` / ``evaluate_experiment``: the sealed A/A of the control group (the preregistered test: CUPED and a permutation inside the strata; the two normal tests beside it), its calibration on new
  draws, the minimum detectable effect and the balance (``experiment``, ``holdout``);
* ``crm_evidence``: what C09 needs from the CRM and the e-mail files;
* ``criteria_of``: C01-C10 from the figures and the sealed limits, **and nothing else**: each criterion tests the one quantity that requirements 8.1 says, in its unit (``tested_value`` and ``tested_value_es``), and
  ``criteria_from_seal`` rebuilds them from the seal's own figures, each compared with its entry to six decimals (the lesson A1 and the rebuild of project 07).

A criterion that cannot be computed is ``passed = False`` with its reason, never approved; a tie never beats. The archive has no offers: no figure, field or sentence here is the effect of an offer (D16).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import NormalDist
from typing import Any

import numpy as np
import pandas as pd

from personaloffers import base, baselines, experiment, holdout, metrics, texts, warehouse
from personaloffers import calendar as cal
from personaloffers.lines import PRODUCT_ROLES
from personaloffers.registry import SealError, rounded

LIST_METHOD = "offer_list"
CATALOGUE_DAYS = 365
METHOD_KEYS = (("offer_list", "unrestricted"), *((m, v) for m in baselines.METHODS for v in baselines.VARIANTS))     # the 17 that are measured
AA_SEED = experiment.PERMUTATION_SEED_BASE        # the generator of the permutations of the sealed A/A; the calibration draws use this + 1 to + seeds
INSERT_CHUNK = 20_000


class EvaluationError(RuntimeError):
    """The evaluation cannot be made as it is: a round of the test has no follow-up, a figure of the follow-up is not the one that is recomputed, or a list does not have its products."""


def _key(method: str, variant: str) -> str:
    return f"{method}:{variant}"


# --- the pairs and the lists -------------------------------------------------------------------------------------------------------------------------------------------


def _read_lists(conn: Any, table: str, round_id: str, k: int, index: pd.Index) -> dict[tuple[str, str], tuple[np.ndarray, np.ndarray]]:
    """``{(method, variant): (customers, positions)}`` of a round: the customers in order and, for each, the ``k`` products of its list as positions in the catalogue `index`."""
    if table == "offer_lists":
        frame = pd.read_sql_query("SELECT customer_id, rank, stock_code FROM offer_lists WHERE round_id = ? ORDER BY customer_id, rank", conn, params=(round_id,))
        frame["method"], frame["variant"] = LIST_METHOD, "unrestricted"
    else:
        frame = pd.read_sql_query("SELECT method, variant, customer_id, rank, stock_code FROM baseline_lists WHERE round_id = ? ORDER BY method, variant, customer_id, rank", conn, params=(round_id,))
    frame["position"] = index.get_indexer(frame["stock_code"])
    if (frame["position"] < 0).any():
        raise EvaluationError(f"las listas de {round_id} tienen productos que el almacén no conoce")
    found: dict[tuple[str, str], tuple[np.ndarray, np.ndarray]] = {}
    for (method, variant), part in frame.groupby(["method", "variant"], sort=True):
        if len(part) % k or not (part["rank"].to_numpy().reshape(-1, k) == np.arange(1, k + 1)).all():
            raise EvaluationError(f"las listas {method}/{variant} de {round_id} no tienen sus {k} lugares por cliente")
        found[(method, variant)] = (part["customer_id"].to_numpy()[::k].astype("int64"), part["position"].to_numpy().reshape(-1, k).astype("int64"))
    return found


def _of_pairs(lists: tuple[np.ndarray, np.ndarray], customers: np.ndarray, label: str) -> np.ndarray:
    """The lists of the customers `customers` (all of them must have one), in their order."""
    ids, positions = lists
    place = np.searchsorted(ids, customers)
    if (place >= len(ids)).any() or (ids[np.minimum(place, len(ids) - 1)] != customers).any():
        raise EvaluationError(f"hay clientes de la ronda que compraron y no tienen lista en {label}")
    return positions[place]


@dataclass
class _Round:
    round_id: str
    period: str
    customers: np.ndarray
    segments: np.ndarray
    test_products: np.ndarray
    metrics: dict[tuple[str, str], metrics.PairMetrics]
    distinct: dict[tuple[str, str], int]
    catalogue: int


def _evaluate_round(conn: Any, view: Any, monday: date, lines: pd.DataFrame, index: pd.Index) -> _Round:
    k = view.recommend.k
    round_id = cal.round_id(monday)
    frame = pd.read_sql_query(
        "SELECT c.customer_id AS customer_id, c.segment AS segment, o.products AS products FROM contact_base c JOIN round_outcomes o ON o.round_id = c.round_id AND o.customer_id = c.customer_id "
        "WHERE c.round_id = ? AND o.bought = 1 ORDER BY c.customer_id", conn, params=(round_id,))
    customers = frame["customer_id"].to_numpy().astype("int64")
    start, end = cal.window(monday, view)
    week = lines[(lines["role"] == "purchase") & lines["customer_id"].notna() & (lines["invoice_date"] >= start) & (lines["invoice_date"] < end)]
    week = week[week["customer_id"].isin(customers)][["customer_id", "stock_code"]].drop_duplicates()
    pair = pd.Index(customers).get_indexer(week["customer_id"].astype("int64"))
    product = index.get_indexer(week["stock_code"])
    bought, _ = metrics.bought_matrix(pair, product, len(customers), len(index))
    test_products = np.bincount(pair, minlength=len(customers)).astype("int64")
    if not np.array_equal(test_products, frame["products"].to_numpy().astype("int64")):
        raise EvaluationError(f"el seguimiento de {round_id} no es el que se recalcula con las líneas: lo evaluado es lo emitido y lo comprado, y no se evalúa si no coinciden")
    history = base.history_before(lines, monday)
    recent = history[history["role"].isin(PRODUCT_ROLES) & (history["invoice_date"] >= pd.Timestamp(monday) - pd.Timedelta(days=CATALOGUE_DAYS))]
    catalogue = int(recent["stock_code"].nunique())
    every = {**_read_lists(conn, "offer_lists", round_id, k, index), **_read_lists(conn, "baseline_lists", round_id, k, index)}
    if set(every) != set(METHOD_KEYS):
        raise EvaluationError(f"las listas de {round_id} no tienen los métodos que se evalúan: faltan {sorted(set(METHOD_KEYS) - set(every))}, sobran {sorted(set(every) - set(METHOD_KEYS))}")
    found, distinct = {}, {}
    for key in METHOD_KEYS:
        distinct[key] = int(len(np.unique(every[key][1])))
        if len(customers):
            found[key] = metrics.pair_metrics(_of_pairs(every[key], customers, f"{key[0]}/{key[1]} de {round_id}"), bought, test_products, k)
    return _Round(round_id, cal.period_of(monday, view), customers, frame["segment"].to_numpy().astype(str), test_products, found, distinct, catalogue)


# --- the rankings ------------------------------------------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RankingResult:
    rounds: tuple[str, ...]            # the rounds of the test, in order
    censored: tuple[str, ...]          # the censored round, when its follow-up is there
    pairs: pd.DataFrame                # round_id, customer_id, segment, method, variant, hit, recall, precision, ndcg, test_products (customer numbers: stays in the warehouse)
    methods: list[dict[str, Any]]      # the rows of ``eval_methods``: each method and variant by round and ``all``
    segments: list[dict[str, Any]]     # the rows of ``eval_segments``
    figures: dict[str, Any]            # what the criteria and the seal read


def _rate(values: np.ndarray) -> float:
    return float(np.mean(values)) if len(values) else float("nan")


def evaluate_rankings(conn: Any, view: Any, *, lines: pd.DataFrame | None = None) -> RankingResult:
    """The lists, B0-B6 and the chosen discovery over the test (see the module). ``EvaluationError`` when a round of the test has no follow-up."""
    mondays = cal.rounds(view, "test")
    followed = {row[0] for row in conn.execute("SELECT DISTINCT round_id FROM round_outcomes")}
    missing = [cal.round_id(m) for m in mondays if cal.round_id(m) not in followed]
    if missing:
        raise EvaluationError(f"las rondas {', '.join(missing)} de la prueba no tienen seguimiento: la prueba se evalúa con el cierre, cuando todas las semanas llegaron")
    censored = [m for m in cal.rounds(view, "censored") if cal.round_id(m) in followed]
    lines = warehouse.read_lines(conn) if lines is None else lines
    index = pd.Index(sorted(row[0] for row in conn.execute("SELECT stock_code FROM products")))
    rounds = [_evaluate_round(conn, view, monday, lines, index) for monday in [*mondays, *censored]]
    in_test = [r for r in rounds if r.period == "test"]

    customers = np.concatenate([r.customers for r in in_test]) if in_test else np.zeros(0, dtype="int64")
    if not len(customers):
        raise EvaluationError("ninguna ronda de la prueba tiene pares evaluados (clientes de la base que compraron en la semana)")
    segments = np.concatenate([r.segments for r in in_test])
    series = {key: {name: np.concatenate([getattr(r.metrics[key], name) for r in in_test]) for name in ("hit", "recall", "precision", "ndcg")} for key in METHOD_KEYS}

    groups = metrics.clusters(customers)
    draws = metrics.configured_draws(groups, view)
    method_rows, figures_methods = [], {}
    for key in METHOD_KEYS:
        s = series[key]
        coverage_by_round = [r.distinct[key] / r.catalogue if r.catalogue else 0.0 for r in in_test]
        interval = metrics.percentile_interval(metrics.resampled_means(groups, s["hit"], draws))
        hits = int(s["hit"].sum())
        wilson = metrics.wilson(hits, len(customers))
        row = {"method": key[0], "variant": key[1], "round_id": "all", "pairs": int(len(customers)), "hit_rate": _rate(s["hit"]), "ci_low": interval[0], "ci_high": interval[1], "wilson_low": wilson[0],
               "wilson_high": wilson[1], "recall": _rate(s["recall"]), "precision": _rate(s["precision"]), "ndcg": _rate(s["ndcg"]), "coverage": float(np.mean(coverage_by_round))}
        method_rows.append(row)
        figures_methods[_key(*key)] = {name: row[name] for name in ("pairs", "hit_rate", "ci_low", "ci_high", "recall", "precision", "ndcg", "coverage")}
        for r in rounds:
            if key not in r.metrics:
                method_rows.append({"method": key[0], "variant": key[1], "round_id": r.round_id, "pairs": 0, "hit_rate": None, "ci_low": None, "ci_high": None, "wilson_low": None, "wilson_high": None,
                                    "recall": None, "precision": None, "ndcg": None, "coverage": r.distinct[key] / r.catalogue if r.catalogue else 0.0})
                continue
            m = r.metrics[key]
            method_rows.append({"method": key[0], "variant": key[1], "round_id": r.round_id, "pairs": int(len(r.customers)), "hit_rate": _rate(m.hit), "ci_low": None, "ci_high": None, "wilson_low": None,
                                "wilson_high": None, "recall": _rate(m.recall), "precision": _rate(m.precision), "ndcg": _rate(m.ndcg), "coverage": r.distinct[key] / r.catalogue if r.catalogue else 0.0})

    def difference(a: tuple[str, str], b: tuple[str, str]) -> dict[str, Any]:
        spread = metrics.paired_difference(groups, series[a]["hit"], series[b]["hit"], draws)
        low, high = metrics.percentile_interval(spread)
        return {"a_rate": _rate(series[a]["hit"]), "b_rate": _rate(series[b]["hit"]), "value": _rate(series[a]["hit"]) - _rate(series[b]["hit"]), "ci_low": low, "ci_high": high, "pairs": int(len(customers))}

    diffs = {"list_vs_b2": difference((LIST_METHOD, "unrestricted"), ("b2", "unrestricted")), "list_vs_b3": difference((LIST_METHOD, "unrestricted"), ("b3", "unrestricted")),
             "chosen_vs_b2_new": difference(("chosen_discovery", "new_only"), ("b2", "new_only"))}

    segment_rows = []
    for name in base.SEGMENTS:
        inside = segments == name
        if not inside.any():
            continue
        sub = metrics.clusters(customers[inside])
        sub_draws = metrics.configured_draws(sub, view)
        for key in METHOD_KEYS:
            values = series[key]["hit"][inside]
            low, high = metrics.percentile_interval(metrics.resampled_means(sub, values, sub_draws))
            segment_rows.append({"method": key[0], "variant": key[1], "segment": name, "pairs": int(inside.sum()), "customers": int(len(sub.ids)), "hit_rate": _rate(values), "ci_low": low, "ci_high": high})

    frame = pd.DataFrame({"round_id": np.concatenate([np.full(len(r.customers), r.round_id, dtype=object) for r in rounds]), "customer_id": np.concatenate([r.customers for r in rounds]),
                          "segment": np.concatenate([r.segments for r in rounds])})
    chunks = []
    for key in METHOD_KEYS:
        part = frame.copy()
        part["method"], part["variant"] = key
        for name in ("hit", "recall", "precision", "ndcg"):
            part[name] = np.concatenate([getattr(r.metrics[key], name) for r in rounds])
        part["test_products"] = np.concatenate([r.test_products for r in rounds])
        chunks.append(part)
    figures = {"rounds": len(in_test), "pairs": int(len(customers)), "customers": int(len(groups.ids)), "variants": len(METHOD_KEYS), "censored_round": cal.round_id(censored[0]) if censored else None,
               "methods": figures_methods, "diffs": diffs, "coverage_list": figures_methods[_key(LIST_METHOD, "unrestricted")]["coverage"],
               "by_round": {r.round_id: {"pairs": int(len(r.customers)), "hit_rate_list": _rate(r.metrics[(LIST_METHOD, "unrestricted")].hit) if len(r.customers) else None, "period": r.period} for r in rounds}}
    return RankingResult(tuple(r.round_id for r in in_test), tuple(r.round_id for r in rounds if r.period == "censored"), pd.concat(chunks, ignore_index=True), method_rows, segment_rows, figures)


# --- C05 after the seal (B5 of the evaluation, D49) --------------------------------------------------------------------------------------------------------------------


COVERAGE_DEFINITIONS_ES = {
    "sealed": "Lo sellado: los productos distintos de todas las listas de la ronda sobre los productos con alguna línea de canasta (compras de clientes e invitados) en los 365 días anteriores.",
    "preregistered": "Lo preregistrado (requerimientos, 8.1): los productos distintos de todas las listas de la ronda sobre los productos con alguna línea de compra (`purchase`) en los 365 días anteriores.",
    "p01_denominator": "Solo el denominador de `p01`: los productos distintos de todas las listas de la ronda sobre todos los productos con alguna línea de canasta antes de la ronda.",
    "p01_definition": "La definición de la validación del plan (`p01`): los productos distintos de las listas de los clientes evaluados (los que compraron en la semana) sobre todos los productos con alguna "
                      "línea de canasta antes de la ronda.",
}


def coverage_definitions(conn: Any, view: Any, *, lines: pd.DataFrame | None = None) -> dict[str, Any]:
    """C05's coverage in the test rounds, mean over the rounds, with four definitions (``COVERAGE_DEFINITIONS_ES``), from what was issued and the lines, and nothing refitted: ``sealed`` is the one the seal
    holds (``coverage_list``), ``preregistered`` the one requirements 8.1 fix (a purchase line is ``purchase``, RF04), ``p01_definition`` the one of the plan's validation figure (0.158) and
    ``p01_denominator`` the sealed numerator over ``p01``'s denominator, which splits the distance between the sealed figure and the validation's into its two parts. Each with its rounds."""
    lines = warehouse.read_lines(conn) if lines is None else lines
    by_round, shares = {}, {key: [] for key in COVERAGE_DEFINITIONS_ES}
    for monday in cal.rounds(view, "test"):
        round_id = cal.round_id(monday)
        history = base.history_before(lines, monday)
        basket = history[history["role"].isin(PRODUCT_ROLES)]
        year = basket[basket["invoice_date"] >= pd.Timestamp(monday) - pd.Timedelta(days=CATALOGUE_DAYS)]
        listed = pd.read_sql_query("SELECT customer_id, stock_code FROM offer_lists WHERE round_id = ?", conn, params=(round_id,))
        evaluated = pd.read_sql_query("SELECT c.customer_id FROM contact_base c JOIN round_outcomes o ON o.round_id = c.round_id AND o.customer_id = c.customer_id WHERE c.round_id = ? AND o.bought = 1",
                                      conn, params=(round_id,))["customer_id"]
        row = {"distinct": int(listed["stock_code"].nunique()), "distinct_evaluated": int(listed.loc[listed["customer_id"].isin(evaluated), "stock_code"].nunique()),
               "basket_365": int(year["stock_code"].nunique()), "purchase_365": int(year.loc[year["role"] == "purchase", "stock_code"].nunique()), "basket_before": int(basket["stock_code"].nunique())}
        if not (row["basket_365"] and row["purchase_365"] and row["basket_before"]):
            raise EvaluationError(f"la ronda {round_id} no tiene productos en el catálogo de la cobertura")
        by_round[round_id] = row
        shares["sealed"].append(row["distinct"] / row["basket_365"])
        shares["preregistered"].append(row["distinct"] / row["purchase_365"])
        shares["p01_denominator"].append(row["distinct"] / row["basket_before"])
        shares["p01_definition"].append(row["distinct_evaluated"] / row["basket_before"])
    if not by_round:
        raise EvaluationError("la prueba no tiene rondas: no hay cobertura")
    return {"rounds": len(by_round), "by_round": by_round, **{key: {"value": float(np.mean(values)), "definition_es": COVERAGE_DEFINITIONS_ES[key]} for key, values in shares.items()}}


# --- the experiment ----------------------------------------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ExperimentResult:
    figures: dict[str, Any]


def _test_of(y: np.ndarray, control: np.ndarray, alpha: float, p: float | None = None) -> dict[str, float]:
    diff, error = experiment.welch(y, control)
    z = NormalDist().inv_cdf(1 - alpha / 2)
    return {"diff": diff, "p": experiment.normal_p(diff, error) if p is None else p, "ci_low": diff - z * error, "ci_high": diff + z * error}


def run_experiment(cov: pd.DataFrame, assignment: pd.DataFrame, lines: pd.DataFrame, test_weeks: Sequence[date], earlier_weeks: Sequence[date], view: Any) -> dict[str, Any]:
    """The A/A of a cohort: `cov` (its covariates, one row per customer in ascending order of number) and `assignment` (its group and stratum), the outcomes M1 and M2 of the `test_weeks` and the same of the
    `earlier_weeks` for CUPED, the preregistered test and the two normal ones beside it, the calibration on new draws, the minimum detectable effect and the balance. Pure: it reads nothing but its arguments."""
    ids = cov["customer_id"].to_numpy().astype("int64")
    ordered = assignment.set_index("customer_id").loc[ids]
    control = (ordered["grp"] == "control").to_numpy()
    strata = ordered["stratum"].to_numpy(dtype="int64")
    m1, m2 = experiment.outcomes(lines, ids, test_weeks)
    x1, x2 = experiment.outcomes(lines, ids, earlier_weeks)
    outcomes = {"m1": experiment.make_outcome(m1, x1), "m2": experiment.make_outcome(m2, x2)}
    x = view.experiment
    draws = experiment.draw_assignments(strata, control, x.permutations, np.random.default_rng(AA_SEED))
    aa = {}
    for name, outcome in outcomes.items():
        permuted = experiment.stratified_permutation(outcome.adjusted, control, strata, x.permutations, None, assignments=draws)
        aa[name] = {"preregistered": _test_of(outcome.adjusted, control, x.alpha, p=permuted.p), "normal_raw": _test_of(outcome.y, control, x.alpha), "normal_cuped": _test_of(outcome.adjusted, control, x.alpha)}
        aa[name]["preregistered"]["diff"] = permuted.diff
    calibration = experiment.calibrate(outcomes, cov, view)
    spread = {name: float(outcome.adjusted.std(ddof=1)) for name, outcome in outcomes.items()}
    mde = experiment.mde_table(sd_m1=spread["m1"], sd_m2=spread["m2"], customers=len(ids), shares=x.mde_shares, alpha=x.alpha, power=x.mde_power)
    balance = holdout.balance(cov, assignment[assignment["customer_id"].isin(ids)])
    per = {}
    for column in base.COVARIATE_COLUMNS:
        values = cov[column].to_numpy("float64")
        per[column] = {"smd": balance[column], "offer_mean": float(values[~control].mean()), "control_mean": float(values[control].mean())}
    worst = max(base.COVARIATE_COLUMNS, key=lambda column: abs(balance[column]))
    return {"customers": int(len(ids)), "control": int(control.sum()), "balance": {"max_abs_smd": abs(balance[worst]), "covariate": worst, "customers": int(len(ids)), "per_covariate": per}, "aa": aa,
            "outcomes": {name: {"mean": float(o.y.mean()), "sd": float(o.y.std(ddof=1)), "sd_adjusted": spread[name], "theta": o.theta} for name, o in outcomes.items()},
            "calibration": {"seeds": calibration.seeds, "permutations": calibration.permutations, "alpha": calibration.alpha, "rejection": dict(sorted(calibration.rejection.items()))},
            "mde": [{"holdout_share": row["holdout_share"], "holdout_size": int(row["holdout_size"]), "mde_m1": row["mde_m1"], "mde_m2": row["mde_m2"]} for row in mde]}


def evaluate_experiment(conn: Any, view: Any, *, lines: pd.DataFrame | None = None) -> ExperimentResult:
    """The A/A of the launch cohort of the warehouse (see ``run_experiment``): the customers that the launch drew, their covariates of the first round of the test, the 18 weeks of the test and the 18 weeks before it."""
    first = cal.round_id(view.calendar.test_first_round)
    assignment = holdout.read_assignments(conn)
    cohort = assignment[(assignment["assigned_round"] == first) & (assignment["method"] == "stratified")].sort_values("customer_id").reset_index(drop=True)
    cov = pd.read_sql_query("SELECT customer_id, recency_days, invoices_365, spend_365, tenure_days, bulk, invoices_before FROM contact_base WHERE round_id = ? ORDER BY customer_id", conn, params=(first,))
    if not len(cov) or not np.array_equal(cov["customer_id"].to_numpy(), cohort["customer_id"].to_numpy()):
        raise EvaluationError(f"la cohorte del lanzamiento ({first}) no es la base de esa ronda: no hay con qué armar el A/A")
    lines = warehouse.read_lines(conn) if lines is None else lines
    test_weeks = cal.rounds(view, "test")
    earlier = experiment.week_mondays(view.calendar.test_first_round, view.experiment.cuped_weeks)
    return ExperimentResult(run_experiment(cov, cohort, lines, test_weeks, earlier, view))


# --- what the CRM and the e-mail files say (C09) ------------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CrmEvidence:
    rounds: int                # the rounds that were delivered, so the e-mail files there should be
    lists: int                 # the lists of the offer group that were issued for them
    read_back_equal: int       # of those, the ones whose batch was delivered and read back equal
    control_in_crm: int        # customers of the control group that the CRM holds in any of those rounds
    control_in_csv: int        # and that the e-mail files hold
    csv_files: int             # e-mail files that are there
    repeat_round: str
    repeat_created: int
    repeat_contacts: int

    def figures(self) -> dict[str, Any]:
        return {"rounds": self.rounds, "lists": self.lists, "read_back_equal": self.read_back_equal, "control_in_crm": self.control_in_crm, "control_in_csv": self.control_in_csv,
                "csv_files": self.csv_files, "repeat_round": self.repeat_round, "repeat_created": self.repeat_created, "repeat_contacts": self.repeat_contacts}


def crm_evidence(conn: Any, client: Any, *, private_dir: Path, batch_size: int) -> CrmEvidence:
    """What C09 reads: for every round that was delivered (the test and the censored one), the lists issued for the offer group against the batches that were delivered and read back equal, the customers of the
    control group that the CRM and the e-mail files hold, and what sending the last round's batches again creates (``crm.client.repeat_round``: nothing is written in the warehouse)."""
    from personaloffers.crm.client import repeat_round
    from personaloffers.email_export import email_path

    delivered = [row[0] for row in conn.execute("SELECT DISTINCT d.round_id FROM crm_deliveries d JOIN rounds r ON r.round_id = d.round_id WHERE r.period IN ('test', 'censored') ORDER BY d.round_id")]
    if not delivered:
        return CrmEvidence(0, 0, 0, 0, 0, 0, "", 0, 0)
    control = {row[0] for row in conn.execute("SELECT customer_id FROM holdout_assignments WHERE grp = 'control'")}
    lists = sum(row[0] for row in conn.execute("SELECT offer_size FROM rounds WHERE round_id IN (%s)" % ", ".join("?" * len(delivered)), delivered))
    equal = conn.execute("SELECT COALESCE(SUM(contacts), 0) FROM (SELECT DISTINCT round_id, batch, contacts FROM crm_deliveries WHERE status = 'ok' AND readback_equal = 1 AND round_id IN (%s))"
                         % ", ".join("?" * len(delivered)), delivered).fetchone()[0]
    in_crm, in_csv, files = 0, 0, 0
    for round_id in delivered:
        in_crm += sum(1 for contact in client.read_round(round_id) if contact.contact_id in control)
        path = email_path(private_dir, round_id)
        if path.is_file():
            files += 1
            ids = {int(line.split(",", 1)[0]) for line in path.read_bytes().decode("utf-8").splitlines()[1:] if line}
            in_csv += len(ids & control)
    last = delivered[-1]
    repeated = repeat_round(conn, client, last, batch_size=batch_size)
    contacts = conn.execute("SELECT offer_size FROM rounds WHERE round_id = ?", (last,)).fetchone()[0]
    return CrmEvidence(len(delivered), int(lists), int(equal), in_crm, in_csv, files, last, repeated.created, int(contacts))


# --- the criteria ------------------------------------------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Criterion:
    criterion_id: str
    name_es: str
    tested_value: float | None      # the one number that the threshold compares (None when it compares two or more: then ``tested_value_es`` says them)
    tested_value_es: str            # what the threshold tests, with its unit
    point_value: float | None       # the point estimate beside it (the difference itself, for C01-C04)
    ci_low: float | None
    ci_high: float | None
    threshold_es: str
    passed: bool | None
    seen_by_research: str
    seen_by_planner: str
    verdict_es: str

    def seal_entry(self) -> dict[str, Any]:
        return {"id": self.criterion_id, "tested_value": self.tested_value, "point_value": self.point_value, "ci_low": self.ci_low, "ci_high": self.ci_high, "passed": self.passed, "verdict_es": self.verdict_es}


def _num(value: Any) -> float | None:
    """A figure as a number, or None when it is missing, not a number or not finite."""
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def _all(*values: Any) -> bool:
    return all(v is not None for v in values)


def criteria_of(figs: Mapping[str, Any], limits: Mapping[str, Any]) -> list[Criterion]:
    """C01 to C10 from the figures of the test and the sealed limits of ``[criteria]``: nothing else (see the module)."""
    thresholds = texts.thresholds_from(limits)
    out: list[Criterion] = []

    def add(cid: str, tested: float | None, tested_es: str, point: float | None, low: float | None, high: float | None, passed: bool | None, verdict: str) -> None:
        t = texts.CRITERIA[cid]
        out.append(Criterion(cid, t.name_es, tested, tested_es, point, low, high, thresholds[cid], passed, t.seen_by_research, t.seen_by_planner, verdict))

    def cannot(cid: str, why: str) -> None:
        add(cid, None, "sin dato", None, None, None, False, texts.cannot(why))

    rounds = figs.get("rounds")
    diffs = figs.get("diffs") or {}
    for cid, key, limit_key in (("C01", "list_vs_b2", "c01_min_diff_low"), ("C02", "list_vs_b3", "c02_min_diff_low"), ("C03", "list_vs_b3", "c03_min_diff_low"), ("C04", "chosen_vs_b2_new", "c04_min_diff_low")):
        d = diffs.get(key) or {}
        low, high, value, a, b = (_num(d.get(name)) for name in ("ci_low", "ci_high", "value", "a_rate", "b_rate"))
        if not _all(low, high, value, a, b):
            cannot(cid, "la prueba no tiene pares evaluados para esa comparación")
            continue
        ok = low > limits[limit_key]
        add(cid, low, texts.tested_value_es(cid, low=low), value, low, high, ok, texts.verdict(cid, ok, rounds=rounds, a=a, b=b, low=low, limit=limits[limit_key]))
    coverage = _num(figs.get("coverage_list"))
    if coverage is None:
        cannot("C05", "no hay listas de la ronda con qué medir la cobertura")
    else:
        ok = coverage >= limits["c05_min_coverage"]
        add("C05", coverage, texts.tested_value_es("C05", coverage=coverage), coverage, None, None, ok, texts.verdict("C05", ok, rounds=rounds, coverage=coverage, limit=limits["c05_min_coverage"]))
    balance = figs.get("balance") or {}
    smd = _num(balance.get("max_abs_smd"))
    if smd is None:
        cannot("C06", "el grupo de control no tiene covariables que comparar")
    else:
        ok = smd <= limits["c06_max_abs_smd"]
        add("C06", smd, texts.tested_value_es("C06", smd=smd), smd, None, None, ok, texts.verdict("C06", ok, smd=smd, covariate=balance.get("covariate", ""), customers=balance.get("customers", 0), limit=limits["c06_max_abs_smd"]))
    rejection = (figs.get("calibration") or {}).get("rejection") or {}
    m1, m2 = _num(rejection.get("m1_preregistered")), _num(rejection.get("m2_preregistered"))
    if not _all(m1, m2):
        cannot("C07", "no hay sorteos nuevos del grupo de control que calibren la prueba")
    else:
        low, high = limits["c07_rejection_band"]
        ok = low <= m1 <= high and low <= m2 <= high
        add("C07", None, texts.tested_value_es("C07", m1=m1, m2=m2), None, None, None, ok, texts.verdict("C07", ok, seeds=figs["calibration"]["seeds"], m1=m1, m2=m2, low=low, high=high))
    aa = figs.get("aa") or {}
    p1, p2 = _num(((aa.get("m1") or {}).get("preregistered") or {}).get("p")), _num(((aa.get("m2") or {}).get("preregistered") or {}).get("p"))
    if not _all(p1, p2):
        cannot("C08", "el A/A no tiene la prueba preregistrada de M1 y de M2")
    else:
        ok = p1 >= limits["c08_min_p"] and p2 >= limits["c08_min_p"]
        add("C08", None, texts.tested_value_es("C08", p1=p1, p2=p2), None, None, None, ok, texts.verdict("C08", ok, p1=p1, p2=p2, limit=limits["c08_min_p"]))
    crm = figs.get("crm") or {}
    if not crm.get("lists"):
        cannot("C09", "no hay listas entregadas al CRM")
    elif crm.get("csv_files") != crm.get("rounds"):
        cannot("C09", f"faltan los archivos de correo de algunas rondas (hay {crm.get('csv_files')} de {crm.get('rounds')})")
    else:
        control = crm["control_in_crm"] + crm["control_in_csv"]
        ok = crm["read_back_equal"] == crm["lists"] and control == 0 and crm["repeat_created"] == 0
        add("C09", None, texts.tested_value_es("C09", equal=crm["read_back_equal"], lists=crm["lists"], control=control, repeat=crm["repeat_created"]), None, None, None, ok,
            texts.verdict("C09", ok, equal=crm["read_back_equal"], lists=crm["lists"], control_crm=crm["control_in_crm"], control_csv=crm["control_in_csv"], round=crm["repeat_round"],
                          contacts=crm["repeat_contacts"], repeat=crm["repeat_created"]))
    t = texts.CRITERIA["C10"]
    out.append(Criterion("C10", t.name_es, None, texts.tested_value_es("C10"), None, None, None, thresholds["C10"], None, t.seen_by_research, t.seen_by_planner, texts.informative_verdict(int(figs.get("variants", 0)))))
    return out


def evaluate_criteria(figures: Mapping[str, Any], view: Any) -> list[Criterion]:
    """The criteria of an evaluation: ``criteria_of`` its figures and the sealed ``[criteria]`` of `view`."""
    import dataclasses

    limits = dataclasses.asdict(view.criteria)
    return criteria_of(figures, limits)


def criteria_from_seal(seal: Mapping[str, Any]) -> list[Criterion]:
    """C01 to C10 rebuilt from the test part of the seal with ``criteria_of``; each must give back its own entry of the seal to 6 decimals, or the seal is not taken (``SealError``): a seal that the code no
    longer knows how to rebuild is never published (D21)."""
    test, launch = seal.get("test"), seal.get("launch")
    if not test or not launch:
        raise SealError("el sello no tiene la parte de la prueba: no hay criterios sellados")
    rebuilt = criteria_of(test["metrics"], launch["config"]["criteria"])
    sealed = {entry["id"]: entry for entry in test["criteria"]}
    if set(sealed) != {c.criterion_id for c in rebuilt}:
        raise SealError("los criterios del sello no son C01 a C10: lo sellado no se toma (runbook R7)")
    for criterion in rebuilt:
        if rounded(criterion.seal_entry()) != rounded(sealed[criterion.criterion_id]):
            raise SealError(f"el criterio {criterion.criterion_id} del sello no se reconstruye desde sus cifras: lo sellado no se toma (runbook R7)")
    return rebuilt


def figures_of(ranking: RankingResult, result: ExperimentResult, crm: CrmEvidence) -> dict[str, Any]:
    """Everything the criteria and the seal read, in one dictionary of plain numbers (no customer number and no cell of a customer in it)."""
    f = result.figures
    return {**ranking.figures, "balance": f["balance"], "aa": f["aa"], "outcomes": f["outcomes"], "calibration": f["calibration"], "mde": f["mde"], "crm": crm.figures()}
