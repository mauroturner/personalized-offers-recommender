"""The control group (RF09, AC09, AC10, C06; decision D14). Risk item 1: the assignment *is* the experiment, and an experiment is not redone.

**The launch.** The cohort is the base of the first round of the test. It is split into strata: ``[holdout] recency_bands`` bands of the recency (smallest recency first), crossed with
``frequency_bands`` bands of the invoices of the year and with the bulk flag, up to 18 with the bands of the plan (terciles). A band is cut by rank (``rank(method="first")``,
the customers taken in the order of their number), so ties never decide anything and the strata do not depend on the order of the rows. Inside each stratum, in the order of
the customer number, a permutation of ``numpy.random.default_rng(seed)`` (one generator for the whole cohort, the strata taken in order) puts the first ``round(share * n)`` customers
in the control group (Python's ``round``: to the even number on a tie). It is the draw of the research's ``p02``, which measured its balance.

**Who enters later** is assigned by a hash: ``sha256(salt + ":" + customer)``, its first eight bytes as a number over 2**64, below ``share`` is control. It depends on nobody else and
on no order, so nothing has to be drawn again and nobody who enters changes anyone's group.

**Persistence.** ``store_assignments`` writes only the customers that have no assignment yet. A customer that already has one is never written again, and offering a *different*
assignment for it (another seed, another stratum) is an ``AssignmentConflictError`` before anything is written: the table is also insert-only in the database itself. The control group
has its list (what it would have been offered) and the list is **never delivered**: ``check_deliverable`` (M05) is what every delivery asks before it sends a customer, and it fails
for a customer of the control group and for one that has no assignment at all.

Everything that is computed here receives the sealed view (``view.holdout``, ``view.calendar``) and the covariates of ``personaloffers.base``; none of it reads lines.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from personaloffers.base import COVARIATE_COLUMNS
from personaloffers.calendar import round_id

GROUPS = ("offer", "control")
COLUMNS = ["customer_id", "grp", "method", "stratum", "assigned_round"]
QUERY_CHUNK = 500


class AssignmentConflictError(RuntimeError):
    """An assignment was offered for a customer that already has another one: the draw is not redone (D14)."""


class ControlLeakError(RuntimeError):
    """A customer of the control group, or one without an assignment, was about to be delivered (M05, D14)."""


def _sorted_by_customer(cov: pd.DataFrame) -> pd.DataFrame:
    ordered = cov.sort_values("customer_id", kind="stable").reset_index(drop=True)
    if ordered["customer_id"].duplicated().any():
        raise ValueError(f"hay {int(ordered['customer_id'].duplicated().sum())} números de cliente repetidos en la base: cada cliente entra una vez")
    return ordered


def _bands(values: pd.Series, bands: int) -> np.ndarray:
    """The band of each value, by its rank (ties by the order of the rows) cut at the quantiles of the ranks: ``qcut`` of the research's p02."""
    if len(values) < 2 or bands == 1:
        return np.zeros(len(values), dtype="int64")
    return pd.qcut(values.rank(method="first"), bands, labels=False).to_numpy().astype("int64")


def _strata(ordered: pd.DataFrame, view: Any) -> np.ndarray:
    frequency_bands = view.holdout.frequency_bands
    return (_bands(ordered["recency_days"], view.holdout.recency_bands) * (frequency_bands * 2) + _bands(ordered["invoices_365"], frequency_bands) * 2
            + ordered["bulk"].to_numpy().astype("int64"))


def strata(cov: pd.DataFrame, view: Any) -> np.ndarray:
    """The stratum of each customer of `cov` (in the order of its rows): ``recency band * (frequency_bands * 2) + invoices band * 2 + bulk``, from 0 to 17 with terciles."""
    if cov.empty:
        return np.zeros(0, dtype="int64")
    order = np.argsort(cov["customer_id"].to_numpy(), kind="stable")
    found = np.empty(len(cov), dtype="int64")
    found[order] = _strata(cov.iloc[order].reset_index(drop=True), view)
    return found


def assign_cohort(cov: pd.DataFrame, view: Any) -> pd.DataFrame:
    """The draw of the launch for the customers of `cov` (their covariates, one row each): ``COLUMNS``, sorted by customer number, ``method`` ``stratified``, the stratum of each
    and ``assigned_round`` the first round of the test. The same seed gives the same assignment whatever the order of the rows."""
    ordered = _sorted_by_customer(cov)
    labels = _strata(ordered, view)
    control = np.zeros(len(ordered), dtype=bool)
    rng = np.random.default_rng(view.holdout.seed)
    for stratum in np.unique(labels):
        members = np.flatnonzero(labels == stratum)
        control[rng.permutation(members)[: int(round(view.holdout.share * len(members)))]] = True
    return pd.DataFrame({
        "customer_id": ordered["customer_id"].to_numpy().astype("int64"), "grp": np.where(control, "control", "offer").astype(object), "method": "stratified",
        "stratum": labels, "assigned_round": round_id(view.calendar.test_first_round),
    })[COLUMNS]


def assign_newcomer(customer_id: int, view: Any) -> str:
    """``control`` or ``offer`` for a customer that enters the base after the launch: ``sha256(salt + ":" + customer)``, its first 8 bytes over 2**64, below ``share``."""
    digest = hashlib.sha256(f"{view.holdout.salt}:{int(customer_id)}".encode("utf-8")).digest()
    return "control" if int.from_bytes(digest[:8], "big") / 2**64 < view.holdout.share else "offer"


def assign_newcomers(customer_ids: Any, monday: date, view: Any) -> pd.DataFrame:
    """The assignments of the customers that entered the base of the round of `monday`: ``COLUMNS`` with ``method`` ``hash`` and no stratum, sorted by customer number."""
    if monday.weekday() != 0:
        raise ValueError(f"{monday.isoformat()} no es un lunes: una ronda empieza el lunes")
    ids = np.unique(np.asarray(customer_ids, dtype="int64"))
    return pd.DataFrame({
        "customer_id": ids, "grp": pd.Series([assign_newcomer(c, view) for c in ids], dtype=object), "method": "hash", "stratum": pd.array([pd.NA] * len(ids), dtype="Int64"),
        "assigned_round": round_id(monday),
    })[COLUMNS]


def smd(x: Any, control: Any) -> float:
    """The standardized mean difference of `x` between the offer group and the control group (the mask `control`): offer mean less control mean over the pooled deviation, the
    square root of the mean of the two sample variances. Zero when `x` does not vary; at least two customers are needed in each group."""
    values, mask = np.asarray(x, dtype="float64"), np.asarray(control, dtype=bool)
    offer, held = values[~mask], values[mask]
    if len(offer) < 2 or len(held) < 2:
        raise ValueError("para comparar los dos grupos hacen falta al menos 2 clientes en cada uno")
    pooled = float(np.sqrt((offer.var(ddof=1) + held.var(ddof=1)) / 2))
    return 0.0 if pooled == 0.0 else float((offer.mean() - held.mean()) / pooled)


def balance(cov: pd.DataFrame, assignment: pd.DataFrame) -> dict[str, float]:
    """The standardized difference of each of the five covariates (``COVARIATE_COLUMNS``) between the groups (C06 asks for the largest in absolute value)."""
    ordered = _sorted_by_customer(cov)
    groups = assignment.set_index("customer_id")["grp"]
    missing = int((~ordered["customer_id"].isin(groups.index)).sum())
    if missing:
        raise ValueError(f"{missing} clientes de la base no tienen asignación")
    control = (groups.reindex(ordered["customer_id"]).to_numpy() == "control")
    return {column: smd(ordered[column].to_numpy("float64"), control) for column in COVARIATE_COLUMNS}


def fingerprint(assignment: pd.DataFrame) -> str:
    """The SHA-256 of ``customer_id,grp`` lines in order of customer number (what the seal keeps): the order of the rows and the other columns are not part of it."""
    ordered = assignment.sort_values("customer_id")
    text = "customer_id,grp\n" + "".join(f"{int(c)},{g}\n" for c, g in zip(ordered["customer_id"], ordered["grp"], strict=True))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sizes(assignment: pd.DataFrame) -> dict[str, Any]:
    """The customers of each group and of each stratum with each group, as counts (what the seal keeps): ``{"groups": {...}, "strata": {stratum: {group: n}}}``."""
    groups = {group: int((assignment["grp"] == group).sum()) for group in GROUPS}
    drawn = assignment[assignment["stratum"].notna()]
    per = {int(stratum): {group: int(((drawn["stratum"] == stratum) & (drawn["grp"] == group)).sum()) for group in GROUPS} for stratum in sorted(drawn["stratum"].unique())}
    return {"groups": groups, "strata": per}


# --- persistence (the table is insert-only: plan section 5) -----------------------------------------------------------------------------------------


def read_assignments(conn: sqlite3.Connection) -> pd.DataFrame:
    """Every stored assignment (``COLUMNS``), sorted by customer number."""
    rows = conn.execute("SELECT customer_id, grp, method, stratum, assigned_round FROM holdout_assignments ORDER BY customer_id").fetchall()
    found = pd.DataFrame(rows, columns=COLUMNS)
    return found.astype({"customer_id": "int64", "stratum": "Int64"})


def store_assignments(conn: sqlite3.Connection, assignment: pd.DataFrame, run_key: str) -> int:
    """Write the assignments of the customers that have none yet and return how many. One that has the same assignment is skipped (repeating the launch or a week writes nothing);
    one that has *another* is an ``AssignmentConflictError`` and nothing is written. All or nothing; joins the transaction of the caller if there is one."""
    ids = assignment["customer_id"].astype("int64").tolist()
    if len(set(ids)) != len(ids):
        raise ValueError("una asignación no puede repetir un cliente")
    own = not conn.in_transaction
    if own:
        conn.execute("BEGIN IMMEDIATE")
    try:
        stored = {row[0]: row[1:] for row in conn.execute("SELECT customer_id, grp, method, stratum, assigned_round FROM holdout_assignments")}
        rows = [(int(c), g, m, None if pd.isna(s) else int(s), r) for c, g, m, s, r in zip(*(assignment[column] for column in COLUMNS), strict=True)]
        different = sum(1 for row in rows if row[0] in stored and stored[row[0]] != row[1:])
        if different:
            raise AssignmentConflictError(f"{different} clientes ya tienen guardada otra asignación: una asignación no se rehace (D14)")
        fresh = [(*row, run_key) for row in rows if row[0] not in stored]
        conn.executemany("INSERT INTO holdout_assignments (customer_id, grp, method, stratum, assigned_round, run_key) VALUES (?, ?, ?, ?, ?, ?)", fresh)
        if own:
            conn.execute("COMMIT")
        return len(fresh)
    except BaseException:
        if own and conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def check_deliverable(conn: sqlite3.Connection, customer_ids: Any) -> None:
    """M05: ``ControlLeakError`` unless every customer of `customer_ids` is assigned to the offer group. Run before any batch goes to the CRM or any row to the e-mail file; the
    error counts the customers and never names one."""
    ids = sorted({int(c) for c in customer_ids})
    found: dict[int, str] = {}
    for start in range(0, len(ids), QUERY_CHUNK):
        chunk = ids[start:start + QUERY_CHUNK]
        marks = ", ".join("?" * len(chunk))
        found.update(dict(conn.execute(f"SELECT customer_id, grp FROM holdout_assignments WHERE customer_id IN ({marks})", chunk)))
    in_control = sum(1 for group in found.values() if group == "control")
    if in_control:
        raise ControlLeakError(f"{in_control} clientes del grupo de control iban en lo que se iba a entregar: ninguno se entrega (M05, D14)")
    if len(found) != len(ids):
        raise ControlLeakError(f"{len(ids) - len(found)} clientes que se iban a entregar no tienen asignación: sin saber su grupo no se entrega (M05, D14)")
