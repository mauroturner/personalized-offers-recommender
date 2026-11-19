"""The weekly round: follow-up, base, refit, lists and baselines (RF14, RF17, AC13, AC17, AC25; risk item 1: what was issued is not redone; decisions D11, D14, D18, D23; plan sections 3 and 14).

A weekly delivery ``W<Monday s>`` brings the lines of the week ``[s, s + 7)``. ``run_round`` does, for it, in this order and refusing first anything that is not its turn:

1. **the seal**: without the launch part of the seal (``registry.require_launch_seal``) nothing is done and nothing is written: the test never starts before the seal (RNF07e);
2. **follow-up** (``track_round``): for the round ``R<s>`` whose week just arrived, one row of ``round_outcomes`` for each customer of its base: whether it bought, how many distinct products, how many of them were in
   its list (the list of the control group too: the follow-up is by intention to treat) and the pounds it spent. The close delivery follows the censored round, which has five days;
3. **the next round** (``emit_round`` for ``s + 7``): its base and covariates from the history before that Monday, the hash assignment of whoever entered the base, the models refitted with the sealed recipe
   (the list's and the three baselines'), the lists of every customer of the base (the control group's included, never delivered) and the lists of the baselines, all in one transaction that reads inside it what
   is already issued and does not touch it. The last weekly delivery builds the censored round of the close.

Everything is a function of the lines the warehouse holds, which are only the deliveries that were loaded, and of the sealed recipe; the same delivery run again finds its round issued, recomputes it and checks
that it is the same (AC17) instead of writing it. ``write_round_ops`` is the last write of a round (the CRM delivery is ``U13``'s and its count goes in the same row).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from personaloffers import base, baselines, holdout, offers, registry, warehouse
from personaloffers import launch as launch_module
from personaloffers import calendar as cal
from personaloffers.deliveries import DeliverySpec
from personaloffers.recommend import artifacts, blend, context

PRODUCTS_CHUNK = 500
BASELINE_CHUNK = 100_000


class ScoringError(RuntimeError):
    """A round that is not the one of the delivery in hand was asked for, or what is issued is not what is recomputed (D14)."""


@dataclass(frozen=True)
class TrackResult:
    round_id: str
    rows: int
    buyers: int
    days_observed: int


@dataclass(frozen=True)
class RoundResult:
    round_id: str
    status: str                       # fresh: written now; done: it was issued and what is recomputed is the same
    base: int
    offer: int
    control: int
    new_assignments: int
    lists: int                        # rows of offer_lists
    baseline_rows: int
    fingerprint: str                  # of the lists of the round (``offers.lists_fingerprint``)
    seconds: dict[str, float]


@dataclass(frozen=True)
class WeeklyResult:
    track: TrackResult | None
    emitted: RoundResult | None


# --- the sealed recipe ------------------------------------------------------------------------------------------------------------------------------


def sealed_recipes(launch: dict[str, Any]) -> tuple[blend.Recipe, dict[str, blend.Recipe]]:
    """The recipe of the list and the recipes of the three model baselines, from the launch part of the seal."""
    def recipe_of(entry: dict[str, Any]) -> blend.Recipe:
        return blend.Recipe(entry["model"], int(entry["size"]), float(entry["weight"]), regularization=entry["regularization"])

    return recipe_of(launch["recipe"]), {key: recipe_of(entry) for key, entry in launch["baselines"].items()}


def _require_sealed(view: Any, seal_path: Path) -> dict[str, Any]:
    return registry.require_launch_seal(seal_path, registry.config_fingerprint(view))


# --- the follow-up ------------------------------------------------------------------------------------------------------------------------------------


def track_round(conn: Any, view: Any, run_key: str, monday: Any, *, lines: pd.DataFrame | None = None) -> TrackResult:
    """Write the follow-up of the round of `monday` (``round_outcomes``, insert-only): a row for each customer of its base. Written once: a round that was followed up is checked against what is recomputed
    and nothing is written (``ScoringError`` if it differs)."""
    round_id = cal.round_id(monday)
    if conn.execute("SELECT 1 FROM rounds WHERE round_id = ?", (round_id,)).fetchone() is None:
        raise ScoringError(f"la ronda {round_id} no se armó: no hay base que seguir")
    lines = warehouse.read_lines(conn) if lines is None else lines
    start, end = cal.window(monday, view)
    week = lines[(lines["role"] == "purchase") & lines["customer_id"].notna() & (lines["invoice_date"] >= start) & (lines["invoice_date"] < end)]
    customers = [row[0] for row in conn.execute("SELECT customer_id FROM contact_base WHERE round_id = ? ORDER BY customer_id", (round_id,))]
    listed: dict[int, set[str]] = {}
    for customer, code in conn.execute("SELECT customer_id, stock_code FROM offer_lists WHERE round_id = ?", (round_id,)):
        listed.setdefault(customer, set()).add(code)
    totals: dict[int, Decimal] = {}
    bought: dict[int, set[str]] = {}
    for row in week.itertuples(index=False):
        customer = int(row.customer_id)
        bought.setdefault(customer, set()).add(row.stock_code)
        totals[customer] = totals.get(customer, Decimal(0)) + Decimal(repr(float(row.price))) * int(row.quantity)
    days = cal.days_observed(monday, view)
    rows = []
    for customer in customers:
        mine = bought.get(customer, set())
        rows.append((round_id, customer, int(bool(mine)), len(mine), len(mine & listed.get(customer, set())), format(totals.get(customer, Decimal(0)), "f"), days, run_key))
    stored = conn.execute("SELECT COUNT(*) FROM round_outcomes WHERE round_id = ?", (round_id,)).fetchone()[0]
    if stored:
        again = conn.execute("SELECT round_id, customer_id, bought, products, products_in_offer, spend, days_observed, run_key FROM round_outcomes WHERE round_id = ? ORDER BY customer_id", (round_id,)).fetchall()
        if [row[:7] for row in again] != [row[:7] for row in rows]:
            raise ScoringError(f"el seguimiento de la ronda {round_id} ya está escrito y no es el que se recalcula con las líneas del almacén: lo emitido no se rehace")
        return TrackResult(round_id, 0, sum(r[2] for r in rows), days)
    own = not conn.in_transaction
    if own:
        conn.execute("BEGIN IMMEDIATE")
    try:
        conn.executemany("INSERT INTO round_outcomes (round_id, customer_id, bought, products, products_in_offer, spend, days_observed, run_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
        if own:
            conn.execute("COMMIT")
    except BaseException:
        if own and conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    return TrackResult(round_id, len(rows), sum(r[2] for r in rows), days)


# --- the next round -----------------------------------------------------------------------------------------------------------------------------------


def _list_rows(round_id: str, run_key: str, lists: offers.RoundLists, codes: np.ndarray, groups: np.ndarray) -> list[tuple]:
    rows = []
    for i, customer in enumerate(lists.customers.tolist()):
        for rank in range(lists.products.shape[1]):
            rows.append((round_id, customer, rank + 1, str(codes[lists.products[i, rank]]), offers.SOURCES[int(lists.sources[i, rank])], float(lists.scores[i, rank]), str(groups[i]), run_key))
    return rows


def _baseline_rows(round_id: str, run_key: str, built: dict[tuple[str, str], np.ndarray], customers: np.ndarray, codes: np.ndarray):
    for (method, variant), products in sorted(built.items()):
        for i, customer in enumerate(customers.tolist()):
            for rank in range(products.shape[1]):
                yield (round_id, method, variant, customer, rank + 1, str(codes[products[i, rank]]), run_key)


def _stored_lists(conn: Any, round_id: str) -> tuple[list[tuple], list[tuple]]:
    offer = conn.execute("SELECT round_id, customer_id, rank, stock_code, source, score, grp FROM offer_lists WHERE round_id = ? ORDER BY customer_id, rank", (round_id,)).fetchall()
    baseline = conn.execute("SELECT round_id, method, variant, customer_id, rank, stock_code FROM baseline_lists WHERE round_id = ? ORDER BY method, variant, customer_id, rank", (round_id,)).fetchall()
    return offer, baseline


def emit_round(conn: Any, view: Any, run_key: str, monday: Any, *, models_dir: Path, seal_path: Path, lines: pd.DataFrame | None = None) -> RoundResult:
    """Build and store the round of `monday` (see the module). Written once, in one transaction; a round that is already issued is recomputed and compared with what is stored, and nothing is written."""
    started = time.perf_counter()
    seconds: dict[str, float] = {}
    launch = _require_sealed(view, seal_path)
    chosen, recipes = sealed_recipes(launch)
    round_id = cal.round_id(monday)
    lines = warehouse.read_lines(conn) if lines is None else lines
    history = base.history_before(lines, monday)
    cov = base.base_table(history, monday, view)
    stored = holdout.read_assignments(conn)
    stored_ids = set(stored["customer_id"].astype("int64"))
    entering = cov.loc[~cov["customer_id"].isin(stored_ids), "customer_id"].to_numpy()
    newcomers = holdout.assign_newcomers(entering, monday, view)
    seconds["base"] = round(time.perf_counter() - started, 3)

    fitted = time.perf_counter()
    data = context.prepare(history, monday, cov["customer_id"].to_numpy(), view)
    cache: dict = {}
    model = blend.fit_model(data, chosen, view)
    cache[blend.cache_key(chosen)] = blend.model_scores(data, chosen, model)
    lists = offers.round_lists(data, chosen, view, cache=cache)
    built = baselines.build(data, chosen, recipes, view, monday=monday, cache=cache)
    seconds["fit"] = round(time.perf_counter() - fitted, 3)
    fingerprint = offers.lists_fingerprint(lists, data.codes)

    groups_by_customer = dict(zip(stored["customer_id"].astype("int64"), stored["grp"], strict=True))
    groups_by_customer.update(dict(zip(newcomers["customer_id"].astype("int64"), newcomers["grp"], strict=True)))
    groups = np.array([groups_by_customer[int(c)] for c in lists.customers])
    offer_rows = _list_rows(round_id, run_key, lists, data.codes, groups)
    stored_offer, stored_baseline = _stored_lists(conn, round_id)
    if stored_offer:
        expected_offer = sorted((r[0], r[1], r[2], r[3], r[4], r[5], r[6]) for r in offer_rows)
        expected_baseline = sorted((r[0], r[1], r[2], r[3], r[4], r[5]) for r in _baseline_rows(round_id, run_key, built, data.customers, data.codes))
        if stored_offer != expected_offer or stored_baseline != expected_baseline:
            raise ScoringError(f"la ronda {round_id} ya está emitida y no es la que se recalcula con las líneas del almacén: lo emitido no se rehace (D14)")
        control = int((groups == "control").sum())
        return RoundResult(round_id, "done", len(cov), len(cov) - control, control, 0, len(offer_rows), len(stored_baseline), fingerprint, seconds | {"total": round(time.perf_counter() - started, 3)})

    components = launch_module.round_components(data, chosen, model, view)
    registered = warehouse.registered_models(conn, round_id)
    written = {component: artifacts.write_component(Path(models_dir), round_id, component, arrays, params) for component, (arrays, params) in components.items()}
    for component, artifact in written.items():
        if component in registered and registered[component][1] != artifact.sha256:
            raise ScoringError(f"el artefacto {component} de la ronda {round_id} se registró con otra huella que la que se recalcula: lo registrado no se rehace (runbook R6)")
    writing = time.perf_counter()
    conn.execute("BEGIN IMMEDIATE")
    try:
        created = warehouse.store_round_base(conn, round_id, monday, cal.period_of(monday, view), run_key, cov, newcomers)
        conn.executemany("INSERT INTO offer_lists (round_id, customer_id, rank, stock_code, source, score, grp, run_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", offer_rows)
        rows = _baseline_rows(round_id, run_key, built, data.customers, data.codes)
        while chunk := list(_take(rows, BASELINE_CHUNK)):
            conn.executemany("INSERT INTO baseline_lists (round_id, method, variant, customer_id, rank, stock_code, run_key) VALUES (?, ?, ?, ?, ?, ?, ?)", chunk)
        missing = [(c, components[c][1], f"{round_id}/{c}", written[c].sha256, len(history), seconds["fit"]) for c in components if c not in registered]
        warehouse.register_models(conn, round_id, missing)
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    seconds["write"] = round(time.perf_counter() - writing, 3)
    seconds["total"] = round(time.perf_counter() - started, 3)
    control = int((groups == "control").sum())
    return RoundResult(round_id, "fresh", len(cov), len(cov) - control, control, len(entering) if created else 0, len(offer_rows), len(built) * len(lists.customers) * view.recommend.k, fingerprint, seconds)


def _take(iterator: Any, count: int):
    for _, item in zip(range(count), iterator, strict=False):
        yield item


# --- a delivery -----------------------------------------------------------------------------------------------------------------------------------


def run_round(conn: Any, view: Any, run_key: str, spec: DeliverySpec, *, models_dir: Path, seal_path: Path) -> WeeklyResult:
    """Follow up the round whose week the delivery `spec` brings and build the next one (see the module). `spec` must be a weekly or the close delivery and the last one loaded; anything else is a
    ``ScoringError`` before anything is written. Without the launch part of the seal nothing is done."""
    _require_sealed(view, seal_path)
    if spec.kind not in ("weekly", "close"):
        raise ScoringError(f"la entrega {spec.delivery_id} es {spec.kind}: una ronda semanal sigue y arma a partir de una semanal o del cierre")
    last = conn.execute("SELECT delivery_id FROM deliveries WHERE status = 'loaded' ORDER BY as_of DESC, delivery_id DESC LIMIT 1").fetchone()
    if last is None or last[0] != spec.delivery_id:
        raise ScoringError(f"la entrega {spec.delivery_id} no es la última cargada ({last[0] if last else 'ninguna'}): una ronda se emite solo con la entrega de su semana")
    lines = warehouse.read_lines(conn)
    tracked = track_round(conn, view, run_key, spec.first_day, lines=lines)
    emitted = None
    if spec.kind == "weekly":
        emitted = emit_round(conn, view, run_key, spec.first_day + timedelta(days=cal.DAYS_PER_ROUND), models_dir=models_dir, seal_path=seal_path, lines=lines)
    return WeeklyResult(tracked, emitted)


def write_round_ops(conn: Any, round_id: str, run_key: str, *, delivered: int, seconds: float) -> None:
    """The operation of a round (``round_ops``, insert-only), written at the end of its run: the base and the groups come from the round's own row, the lists from ``offer_lists`` and
    the share of the fallback from their sources."""
    row = conn.execute("SELECT base_size, offer_size, control_size FROM rounds WHERE round_id = ?", (round_id,)).fetchone()
    if row is None:
        raise ScoringError(f"la ronda {round_id} no existe")
    lists, fallback = conn.execute("SELECT COUNT(DISTINCT customer_id), COALESCE(SUM(source = 'fallback'), 0) FROM offer_lists WHERE round_id = ?", (round_id,)).fetchone()
    total = conn.execute("SELECT COUNT(*) FROM offer_lists WHERE round_id = ?", (round_id,)).fetchone()[0]
    new = conn.execute("SELECT COUNT(*) FROM holdout_assignments WHERE assigned_round = ? AND method = 'hash'", (round_id,)).fetchone()[0]
    conn.execute("INSERT INTO round_ops (round_id, base, offer, control, new_assignments, lists, delivered, fallback_share, seconds, run_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (round_id, row[0], row[1], row[2], new, lists, delivered, (fallback / total) if total else 0.0, seconds, run_key))
